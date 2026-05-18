"""SonosController — all business logic, MCP-agnostic.

The FastMCP tool layer is a thin wrapper that validates inputs and
calls these methods. Keeping things here means we can unit-test the
behavior without the MCP transport.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from soco import SoCo

from . import speakers as sp
from ._urls import validate_http_url
from .audio_host import AudioHost
from .playlists import PlaylistManager
from .tts import synthesize


# How long a single TTS clip is allowed to play before we give up
# polling. Piper at the default rate is ~150 wpm, so even long messages
# finish well within this.
TTS_TIMEOUT_SECONDS = 30


def _track_state(speaker: SoCo) -> dict:
    """Return a JSON-safe snapshot of a speaker's playback state."""
    info = speaker.get_current_transport_info()
    track = speaker.get_current_track_info()
    return {
        "state": info.get("current_transport_state"),
        "title": track.get("title"),
        "artist": track.get("artist"),
        "album": track.get("album"),
        "position": track.get("position"),
        "duration": track.get("duration"),
        "uri": track.get("uri"),
    }


def _coordinator_of(speaker: SoCo) -> SoCo:
    """Return the coordinator for `speaker`, or `speaker` itself.

    SoCo briefly returns `group.coordinator = None` after rapid topology
    changes. In that state the speaker is effectively a coordinator-of-
    one, so we report it as such. This makes every downstream call
    (transport, now-playing, group lookups) robust against the lull.
    """
    try:
        if speaker.group:
            c = speaker.group.coordinator
            if c is not None:
                return c
    except Exception:
        pass
    return speaker


def _group_members_of(speaker: SoCo) -> list[str]:
    try:
        if speaker.group and speaker.group.members:
            return sorted(m.player_name for m in speaker.group.members)
    except Exception:
        pass
    return [speaker.player_name]


def _speaker_dict(speaker: SoCo) -> dict:
    coord = _coordinator_of(speaker)
    return {
        "name": speaker.player_name,
        "ip": speaker.ip_address,
        "uid": speaker.uid,
        "is_coordinator": coord.uid == speaker.uid,
        "coordinator_name": coord.player_name,
        "volume": speaker.volume,
        "muted": speaker.mute,
    }


class SonosController:
    """Stateful controller: speakers cache + audio host + lock."""

    def __init__(self, cache_dir: Path | None = None, audio_port: int | None = None):
        self.cache_dir = Path(cache_dir or tempfile.gettempdir()) / "mcp-sonos-audio"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._host_ip = sp.lan_host_ip()
        self.audio = AudioHost(self.cache_dir, host_ip=self._host_ip, port=audio_port)
        self.audio.start()
        _mr = os.environ.get("AUDIO_MEDIA_ROOT", "").strip()
        self.media_root: Path | None = Path(_mr).expanduser().resolve() if _mr else None
        self._speakers: list[SoCo] = []
        self._speakers_ts: float = 0.0
        self.playlists = PlaylistManager(resolve_coordinator=self._resolve_coordinator)

    # ---- discovery / lookup -------------------------------------------------

    def _speakers_fresh(self, max_age: float = 30.0) -> list[SoCo]:
        if not self._speakers or (time.monotonic() - self._speakers_ts) > max_age:
            self._speakers = sp.discover_speakers()
            self._speakers_ts = time.monotonic()
        return self._speakers

    def refresh(self) -> list[dict]:
        self._speakers = sp.discover_speakers()
        self._speakers_ts = time.monotonic()
        return [_speaker_dict(s) for s in self._speakers]

    def list_speakers(self) -> list[dict]:
        return [_speaker_dict(s) for s in self._speakers_fresh()]

    def _resolve(self, name: str) -> SoCo:
        return sp.resolve_name(self._speakers_fresh(), name)

    def _resolve_coordinator(self, name: str) -> tuple[SoCo, SoCo]:
        """Return (named_speaker, its_coordinator).

        Transport commands (play_uri, pause, etc.) must run on the
        coordinator. Falls back to the speaker itself when SoCo
        reports `coordinator=None` (transient post-dissolve state).
        """
        s = self._resolve(name)
        return s, _coordinator_of(s)

    # ---- queries ------------------------------------------------------------

    def now_playing(self, name: str) -> dict:
        s, coord = self._resolve_coordinator(name)
        return {
            "speaker": s.player_name,
            "coordinator": coord.player_name,
            "group_members": _group_members_of(coord),
            **_track_state(coord),
        }

    def list_groups(self) -> list[dict]:
        out: dict[str, dict] = {}
        for s in self._speakers_fresh():
            coord = _coordinator_of(s)
            if coord.uid not in out:
                out[coord.uid] = {
                    "coordinator": coord.player_name,
                    "members": [],
                }
            out[coord.uid]["members"].append(s.player_name)
        for g in out.values():
            g["members"].sort()
        return sorted(out.values(), key=lambda g: g["coordinator"])

    # ---- transport ----------------------------------------------------------

    def play_url(self, name: str, url: str, title: str | None = None) -> dict:
        """Play any HTTP URL on the speaker's group coordinator."""
        # Defence in depth: the MCP tool surface already validates, but
        # direct/test callers reach this method without that gate.
        validate_http_url(url)
        s, coord = self._resolve_coordinator(name)
        coord.play_uri(url, title=title or "MCP playback")
        return {
            "requested": s.player_name,
            "played_on_coordinator": coord.player_name,
            "group_members": _group_members_of(coord),
            "url": url,
            **_track_state(coord),
        }

    def play_file(self, name: str, path: str, title: str | None = None) -> dict:
        """Play a local file (path on the MCP host) by staging it to audio host."""
        if self.media_root is None:
            raise ValueError("play_file is disabled; set AUDIO_MEDIA_ROOT to enable")
        if not self.media_root.is_dir():
            raise ValueError(f"AUDIO_MEDIA_ROOT={self.media_root} does not exist or is not a directory")
        target = Path(path).expanduser().resolve()
        if not target.is_relative_to(self.media_root):
            raise ValueError(f"path {target} is outside AUDIO_MEDIA_ROOT={self.media_root}")
        if not target.is_file():
            raise FileNotFoundError(target)
        if target.suffix.lower() not in {".mp3", ".wav", ".flac", ".m4a", ".ogg"}:
            raise ValueError(f"unsupported extension {target.suffix!r}; allowed: mp3/wav/flac/m4a/ogg")
        url = self.audio.stage(target)
        result = self.play_url(name, url, title=title or target.name)
        result["staged_file"] = str(target)
        return result

    def pause(self, name: str) -> dict:
        _, coord = self._resolve_coordinator(name)
        try:
            coord.pause()
        except Exception:
            # Already paused/stopped; idempotent for the agent.
            pass
        return {"coordinator": coord.player_name, **_track_state(coord)}

    def resume(self, name: str) -> dict:
        _, coord = self._resolve_coordinator(name)
        coord.play()
        return {"coordinator": coord.player_name, **_track_state(coord)}

    def stop(self, name: str) -> dict:
        _, coord = self._resolve_coordinator(name)
        try:
            coord.stop()
        except Exception:
            pass
        return {"coordinator": coord.player_name, **_track_state(coord)}

    def next_track(self, name: str) -> dict:
        _, coord = self._resolve_coordinator(name)
        coord.next()
        return {"coordinator": coord.player_name, **_track_state(coord)}

    def previous_track(self, name: str) -> dict:
        _, coord = self._resolve_coordinator(name)
        coord.previous()
        return {"coordinator": coord.player_name, **_track_state(coord)}

    # ---- volume -------------------------------------------------------------

    def set_volume(self, name: str, level: int) -> dict:
        if not 0 <= level <= 100:
            raise ValueError("volume must be 0..100")
        s = self._resolve(name)
        s.volume = level
        return {"speaker": s.player_name, "volume": s.volume, "muted": s.mute}

    def mute(self, name: str) -> dict:
        s = self._resolve(name)
        s.mute = True
        return {"speaker": s.player_name, "muted": s.mute}

    def unmute(self, name: str) -> dict:
        s = self._resolve(name)
        s.mute = False
        return {"speaker": s.player_name, "muted": s.mute}

    # ---- grouping -----------------------------------------------------------

    def group(self, coordinator: str, members: list[str]) -> dict:
        coord = self._resolve(coordinator)
        # Coordinator must be a coordinator-of-one or already a coordinator.
        if _coordinator_of(coord).uid != coord.uid:
            coord.unjoin()
            time.sleep(0.3)
        joined: list[str] = []
        for m_name in members:
            if m_name.casefold() == coord.player_name.casefold():
                continue
            m = self._resolve(m_name)
            m.join(coord)
            joined.append(m.player_name)
        time.sleep(0.5)  # let topology broadcast settle
        return {
            "coordinator": coord.player_name,
            "joined": joined,
            "group_members": _group_members_of(coord),
        }

    def ungroup(self, name: str) -> dict:
        s = self._resolve(name)
        try:
            s.unjoin()
        except Exception:
            pass
        return {"speaker": s.player_name, "is_coordinator": True}

    def partymode(self, coordinator: str) -> dict:
        coord = self._resolve(coordinator)
        # Dissolve everything first so partymode has a clean slate.
        for s in self._speakers_fresh():
            if s.uid != coord.uid:
                try:
                    s.unjoin()
                except Exception:
                    pass
        time.sleep(0.5)
        coord.partymode()
        time.sleep(0.7)
        return {
            "coordinator": coord.player_name,
            "group_members": _group_members_of(coord),
        }

    def dissolve_all_groups(self) -> dict:
        for s in self._speakers_fresh():
            try:
                s.unjoin()
            except Exception:
                pass
        time.sleep(0.5)
        return {"dissolved": True, "count": len(self._speakers)}

    # ---- TTS ----------------------------------------------------------------

    def say(
        self,
        target: str,
        text: str,
        *,
        volume: int | None = None,
        lang: str = "en",
    ) -> dict:
        """Speak `text` on a speaker or on "all" (synced across all speakers).

        Blocks until playback finishes (or hits TTS_TIMEOUT_SECONDS).
        """
        if not text.strip():
            raise ValueError("text is empty")

        mp3 = synthesize(text, self.cache_dir, lang=lang)
        url = self.audio.url_for(mp3.name)

        if target.strip().casefold() == "all":
            return self._say_all(text, url, volume=volume)

        s, coord = self._resolve_coordinator(target)
        if volume is not None:
            member_names = _group_members_of(coord)
            members = [self._resolve(n) for n in member_names]
            for m in members:
                m.volume = volume
        coord.play_uri(url, title=f"Say: {text[:40]}")
        self._wait_until_stopped(coord)
        return {
            "spoken_on": coord.player_name,
            "group_members": _group_members_of(coord),
            "text": text,
        }

    def _say_all(self, text: str, url: str, volume: int | None) -> dict:
        # Dissolve, partymode, play, dissolve.
        speakers = self._speakers_fresh()
        if not speakers:
            raise RuntimeError("No speakers available")
        for s in speakers:
            try:
                s.unjoin()
            except Exception:
                pass
        time.sleep(0.5)
        if volume is not None:
            for s in speakers:
                s.volume = volume
        coord = sorted(speakers, key=lambda s: s.player_name)[0]
        coord.partymode()
        time.sleep(1.0)
        coord.play_uri(url, title=f"Say-all: {text[:40]}")
        self._wait_until_stopped(coord)
        # Leave them ungrouped after the announcement.
        for s in speakers:
            try:
                s.unjoin()
            except Exception:
                pass
        return {
            "spoken_on": "all",
            "coordinator_used": coord.player_name,
            "speakers": [s.player_name for s in speakers],
            "text": text,
        }

    @staticmethod
    def _wait_until_stopped(speaker: SoCo, timeout: float = TTS_TIMEOUT_SECONDS) -> None:
        deadline = time.monotonic() + timeout
        time.sleep(0.4)  # let playback actually start
        while time.monotonic() < deadline:
            state = speaker.get_current_transport_info().get("current_transport_state")
            if state in ("STOPPED", "PAUSED_PLAYBACK"):
                return
            time.sleep(0.25)
