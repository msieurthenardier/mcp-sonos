"""In-memory named playlists with continuous background playback.

Each playlist is a named list of `PlaylistItem`s. Calling `play()` spawns
a worker thread keyed by the originally-named *speaker's UID* (not the
group coordinator's UID). The worker re-resolves the group coordinator on
every iteration so the playlist follows the speaker through grouping
changes. Keying by coordinator UID breaks the moment someone groups the
speaker — see CLAUDE.md for the design history. External playback events
(e.g., a `say()` call, a `play_url()`, a manual stop) cleanly terminate
the session.

Per-process state. Nothing persists across server restarts. That's
deliberate — playlists are scratch space for the agent, not a library.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from soco import SoCo

from ._urls import validate_http_url


log = logging.getLogger("mcp_sonos.playlists")


# How often the worker polls transport state. 500 ms is responsive
# enough for skip/stop without hammering UPnP.
POLL_INTERVAL = 0.5

# Tolerance for "did the track finish naturally vs get interrupted":
# Sonos briefly reports STOPPED at the boundary between two play_uri
# calls, so we require N consecutive STOPPED reads before advancing.
STOPPED_CONFIRMATIONS = 2


@dataclass
class PlaylistItem:
    url: str
    title: Optional[str] = None

    def to_dict(self) -> dict:
        return {"url": self.url, "title": self.title}


@dataclass
class Playlist:
    name: str
    items: list[PlaylistItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "count": len(self.items),
            "items": [it.to_dict() for it in self.items],
        }


@dataclass
class PlaybackSession:
    playlist_name: str
    speaker_uid: str         # UID of the speaker the agent asked us to play on
    speaker_name: str        # human-readable for status reporting
    current_index: int = 0
    shuffle: bool = False
    started_at: float = field(default_factory=time.monotonic)

    # Signaling. Worker checks each on every poll cycle.
    stop_event: threading.Event = field(default_factory=threading.Event)
    skip_event: threading.Event = field(default_factory=threading.Event)
    back_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None

    def to_dict(self) -> dict:
        return {
            "playlist": self.playlist_name,
            "speaker": self.speaker_name,
            "current_index": self.current_index,
            "shuffle": self.shuffle,
            "uptime_seconds": round(time.monotonic() - self.started_at, 1),
            "running": self.thread is not None and self.thread.is_alive(),
        }


class PlaylistError(ValueError):
    pass


class PlaylistManager:
    """Owns named playlists and at-most-one playback session per coordinator."""

    def __init__(self, resolve_coordinator: Callable[[str], tuple[SoCo, SoCo]]):
        """`resolve_coordinator(name) -> (named_speaker, coordinator)` is
        injected so tests / future refactors don't pull in the whole
        SonosController."""
        self._resolve_coordinator = resolve_coordinator
        self._playlists: dict[str, Playlist] = {}
        self._sessions: dict[str, PlaybackSession] = {}  # speaker_uid -> session
        self._lock = threading.Lock()
        # Test-observability hook — production code never waits on this.
        self._iteration_event = threading.Event()

    # ---- playlist CRUD -----------------------------------------------------

    def create(self, name: str) -> Playlist:
        name = self._validate_name(name)
        with self._lock:
            if name in self._playlists:
                raise PlaylistError(f"Playlist {name!r} already exists")
            pl = Playlist(name=name)
            self._playlists[name] = pl
            return pl

    def delete(self, name: str) -> None:
        name = self._validate_name(name)
        with self._lock:
            if name not in self._playlists:
                raise PlaylistError(f"No playlist named {name!r}")
            # If any session is playing this playlist, stop it first.
            for sess in list(self._sessions.values()):
                if sess.playlist_name == name:
                    self._signal_stop(sess)
            del self._playlists[name]

    def clear(self, name: str) -> Playlist:
        name = self._validate_name(name)
        pl = self._get_playlist(name)
        with self._lock:
            pl.items.clear()
            return pl

    def add(self, name: str, url: str, title: Optional[str] = None) -> Playlist:
        pl = self._get_playlist(self._validate_name(name))
        url = url.strip()
        if not url:
            raise PlaylistError("url is empty")
        try:
            validate_http_url(url)
        except ValueError as e:
            raise PlaylistError(str(e))
        with self._lock:
            pl.items.append(PlaylistItem(url=url, title=title))
            return pl

    def add_many(self, name: str, items: list[dict]) -> Playlist:
        """Bulk-add. Each dict must have `url`; `title` is optional."""
        pl = self._get_playlist(self._validate_name(name))
        normalized: list[PlaylistItem] = []
        for i, raw in enumerate(items):
            if not isinstance(raw, dict) or "url" not in raw:
                raise PlaylistError(f"items[{i}] missing 'url'")
            url = str(raw["url"]).strip()
            if not url:
                raise PlaylistError(f"items[{i}] has empty url")
            try:
                validate_http_url(url)
            except ValueError as e:
                raise PlaylistError(f"items[{i}]: {e}")
            normalized.append(PlaylistItem(url=url, title=raw.get("title")))
        with self._lock:
            pl.items.extend(normalized)
            return pl

    def remove(self, name: str, index: int) -> Playlist:
        pl = self._get_playlist(self._validate_name(name))
        with self._lock:
            if not 0 <= index < len(pl.items):
                raise PlaylistError(
                    f"index {index} out of range (playlist has {len(pl.items)} items)"
                )
            pl.items.pop(index)
            return pl

    def get(self, name: str) -> Playlist:
        return self._get_playlist(self._validate_name(name))

    def list_all(self) -> list[dict]:
        with self._lock:
            return [
                {"name": pl.name, "count": len(pl.items)}
                for pl in sorted(self._playlists.values(), key=lambda p: p.name)
            ]

    # ---- playback ----------------------------------------------------------

    def play(
        self,
        speaker_name: str,
        playlist_name: str,
        shuffle: bool = False,
        start_index: int = 0,
    ) -> dict:
        playlist_name = self._validate_name(playlist_name)
        pl = self._get_playlist(playlist_name)
        if not pl.items:
            raise PlaylistError(f"Playlist {playlist_name!r} is empty")

        speaker, _ = self._resolve_coordinator(speaker_name)
        if not 0 <= start_index < len(pl.items):
            raise PlaylistError(
                f"start_index {start_index} out of range (0..{len(pl.items) - 1})"
            )

        with self._lock:
            # Stop any pre-existing session on this speaker.
            prev = self._sessions.get(speaker.uid)
            if prev:
                self._signal_stop(prev)

            session = PlaybackSession(
                playlist_name=playlist_name,
                speaker_uid=speaker.uid,
                speaker_name=speaker.player_name,
                current_index=start_index,
                shuffle=shuffle,
            )
            self._sessions[speaker.uid] = session

        # Build the play order. For shuffle, generate a permutation now
        # so skip/back behave intuitively.
        order = list(range(len(pl.items)))
        if shuffle:
            head = order[start_index]
            rest = order[:start_index] + order[start_index + 1:]
            random.shuffle(rest)
            order = [head] + rest
            session.current_index = 0  # index into `order`, not the playlist

        if prev and prev.thread:
            prev.thread.join(timeout=2.0)

        t = threading.Thread(
            target=self._worker,
            args=(session, pl, order, speaker),
            name=f"playlist-{playlist_name}@{speaker.player_name}",
            daemon=True,
        )
        session.thread = t
        t.start()

        first_item = pl.items[order[0] if shuffle else start_index]
        return {
            "started": True,
            "playlist": playlist_name,
            "speaker": speaker.player_name,
            "total_items": len(pl.items),
            "start_index": start_index,
            "shuffle": shuffle,
            "first_item": first_item.to_dict(),
        }

    def next_track(self, speaker_name: str) -> dict:
        sess = self._session_for(speaker_name)
        sess.skip_event.set()
        return {"signaled": "next", **sess.to_dict()}

    def previous_track(self, speaker_name: str) -> dict:
        sess = self._session_for(speaker_name)
        sess.back_event.set()
        return {"signaled": "previous", **sess.to_dict()}

    def stop(self, speaker_name: str) -> dict:
        speaker, coord = self._resolve_coordinator(speaker_name)
        with self._lock:
            sess = self._sessions.get(speaker.uid)
        if not sess:
            return {"running": False, "speaker": speaker.player_name}
        self._signal_stop(sess)
        try:
            coord.stop()
        except Exception:
            pass
        return {"stopped": True, **sess.to_dict()}

    def status(self, speaker_name: str) -> dict:
        speaker, _ = self._resolve_coordinator(speaker_name)
        with self._lock:
            sess = self._sessions.get(speaker.uid)
        if not sess:
            return {"running": False, "speaker": speaker.player_name}
        info = sess.to_dict()
        with self._lock:
            pl = self._playlists.get(sess.playlist_name)
        if pl and 0 <= sess.current_index < len(pl.items):
            info["current_item"] = pl.items[sess.current_index].to_dict()
        return info

    # ---- worker ------------------------------------------------------------

    def _worker(
        self,
        session: PlaybackSession,
        playlist: Playlist,
        order: list[int],
        speaker: SoCo,
    ) -> None:
        """Background thread: play items in `order` until done or interrupted.

        Resolves the speaker's current group coordinator on every track so
        the playlist follows the speaker even if grouping changes
        mid-playback.
        """
        log.info(
            "playlist worker started: %s on %s (%d items)",
            session.playlist_name,
            session.speaker_name,
            len(order),
        )
        try:
            while not session.stop_event.is_set():
                if session.current_index < 0:
                    session.current_index = 0
                if session.current_index >= len(order):
                    log.info(
                        "playlist %r finished on %s",
                        session.playlist_name,
                        session.speaker_name,
                    )
                    break

                playlist_idx = order[session.current_index]
                item = playlist.items[playlist_idx]
                title = item.title or f"{session.playlist_name} #{playlist_idx + 1}"

                # Re-resolve coord each iteration in case grouping changed.
                try:
                    _, coord = self._resolve_coordinator(session.speaker_name)
                except Exception as e:
                    log.warning(
                        "playlist %r: cannot resolve %s — stopping (%s)",
                        session.playlist_name,
                        session.speaker_name,
                        e,
                    )
                    break

                try:
                    coord.play_uri(item.url, title=title)
                except Exception as e:
                    log.warning(
                        "playlist %r: failed to play %s — skipping (%s)",
                        session.playlist_name,
                        item.url,
                        e,
                    )
                    session.current_index += 1
                    continue

                # Wait for natural end, skip, back, stop, or takeover.
                stopped_reads = 0
                advance = True
                while not session.stop_event.is_set():
                    self._iteration_event.set()
                    if session.skip_event.is_set():
                        session.skip_event.clear()
                        try:
                            coord.stop()
                        except Exception:
                            pass
                        break
                    if session.back_event.is_set():
                        session.back_event.clear()
                        try:
                            coord.stop()
                        except Exception:
                            pass
                        session.current_index = max(0, session.current_index - 2)
                        # We'll do +1 below; net -1 lands us on previous track.
                        # Edge: at index 0, back stays at 0.
                        if session.current_index < 0:
                            session.current_index = -1
                        break

                    try:
                        ti = coord.get_current_transport_info()
                        state = ti.get("current_transport_state")
                        tr = coord.get_current_track_info()
                        current_uri = tr.get("uri") or ""
                    except Exception as e:
                        log.warning("playlist worker poll failed: %s", e)
                        time.sleep(POLL_INTERVAL)
                        continue

                    # External takeover: a different URI is playing →
                    # someone else (say(), play_url()) has hijacked. Bow out.
                    if state == "PLAYING" and current_uri and current_uri != item.url:
                        log.info(
                            "playlist %r preempted on %s by %s — stopping",
                            session.playlist_name,
                            session.speaker_name,
                            current_uri,
                        )
                        advance = False
                        session.stop_event.set()
                        break

                    if state == "STOPPED":
                        stopped_reads += 1
                        if stopped_reads >= STOPPED_CONFIRMATIONS:
                            break  # natural end
                    else:
                        stopped_reads = 0

                    time.sleep(POLL_INTERVAL)

                if advance:
                    session.current_index += 1
        except Exception:
            log.exception("playlist worker crashed")
        finally:
            log.info(
                "playlist worker exited: %s on %s",
                session.playlist_name,
                session.speaker_name,
            )
            with self._lock:
                # Only clear if this session is still the registered one
                # — a fresh play() may have replaced us already.
                cur = self._sessions.get(session.speaker_uid)
                if cur is session:
                    self._sessions.pop(session.speaker_uid, None)

    # ---- internal ----------------------------------------------------------

    def _validate_name(self, name: str) -> str:
        n = (name or "").strip()
        if not n:
            raise PlaylistError("playlist name is empty")
        return n

    def _get_playlist(self, name: str) -> Playlist:
        with self._lock:
            pl = self._playlists.get(name)
        if pl is None:
            raise PlaylistError(f"No playlist named {name!r}")
        return pl

    def _session_for(self, speaker_name: str) -> PlaybackSession:
        speaker, _ = self._resolve_coordinator(speaker_name)
        with self._lock:
            sess = self._sessions.get(speaker.uid)
        if sess is None:
            raise PlaylistError(
                f"No playlist currently playing on {speaker.player_name!r}"
            )
        return sess

    def _signal_stop(self, sess: PlaybackSession) -> None:
        sess.stop_event.set()
