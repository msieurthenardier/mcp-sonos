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
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import quote, urlparse

from soco import SoCo
from soco.data_structures import DidlMusicTrack, DidlResource

from ._urls import any_mcp_hosted, validate_http_url


# Parent ID used for DIDL items loaded into the native Sonos queue.
# Must NOT be "-1" — Leg 1 hardware testing confirmed that "-1" causes
# title metadata to be discarded by the firmware; any other value preserves
# the title field. "A:TRACKS" is the conventional music-library container.
# NOTE: Flight 1 hardware finding — parent_id="-1" loses track titles on
# firmware; any non-"-1" value (e.g. "A:TRACKS") preserves them. Audit
# any future DidlMusicTrack construction to ensure this invariant holds.
QUEUE_PARENT_ID = "A:TRACKS"


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

    def __init__(
        self,
        resolve_coordinator: Callable[[str], tuple[SoCo, SoCo]],
        *,
        host_ip: str = "",
        audio_port: int = 0,
        invalidate_speakers_cache: Callable[[], None] = lambda: None,
    ):
        """`resolve_coordinator(name) -> (named_speaker, coordinator)` is
        injected so tests / future refactors don't pull in the whole
        SonosController.

        `host_ip` and `audio_port` are the MCP in-process audio server's
        coordinates, used by `play()` to classify URLs and decide whether to
        use the native Sonos queue path or the worker-thread engine.  When both
        are zero/empty the classification falls back to the worker engine for
        everything (safe default; the production controller always supplies
        real values).

        `invalidate_speakers_cache` is called before re-resolving the
        coordinator on a SoCoSlaveException retry, ensuring the cache TTL is
        bypassed and a fresh discovery is forced.  Defaults to a no-op so
        existing direct constructions and tests don't break.
        """
        self._resolve_coordinator = resolve_coordinator
        self._host_ip = host_ip
        self._audio_port = audio_port
        self._invalidate_speakers_cache = invalidate_speakers_cache
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

        # Route: classify URLs only when we have a known host/port.
        # - any MCP-hosted URL → worker engine (audio server must stay reachable)
        # - all-external       → native Sonos queue (survives MCP restarts)
        # - no host/port       → worker engine (safe conservative fallback;
        #                        can't classify without coordinates)
        urls = [item.url for item in pl.items]
        if not self._host_ip or not self._audio_port:
            # Classification not possible — use worker engine.
            return self._play_via_worker(speaker, pl, playlist_name, shuffle, start_index)

        if any_mcp_hosted(urls, self._host_ip, self._audio_port):
            log.debug(
                "playlist %r: MCP-hosted URL detected — using worker engine",
                playlist_name,
            )
            return self._play_via_worker(speaker, pl, playlist_name, shuffle, start_index)

        return self._play_via_queue(speaker, pl, playlist_name, shuffle, start_index)

    def _play_via_worker(
        self,
        speaker: SoCo,
        pl: "Playlist",
        playlist_name: str,
        shuffle: bool,
        start_index: int,
    ) -> dict:
        """Worker-thread engine path (unchanged behavior — MCP-hosted fallback)."""
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
            "engine": "worker",
        }

    def _play_via_queue(
        self,
        speaker: SoCo,
        pl: "Playlist",
        playlist_name: str,
        shuffle: bool,
        start_index: int,
    ) -> dict:
        """Native Sonos queue engine path for all-external playlists.

        DD-D: evict any live worker session as ONE unit — signal_stop +
        coord.stop() + join to completion — BEFORE touching the queue.
        """
        _, coord = self._resolve_coordinator(speaker.player_name)

        with self._lock:
            prev = self._sessions.get(speaker.uid)

        # DD-D: eviction must complete before any queue operation.
        if prev:
            self._signal_stop(prev)
            try:
                coord.stop()
            except Exception:
                pass
            if prev.thread:
                prev.thread.join(timeout=2.0)

        # Build DIDL items per the Leg 1 recipe + DD-E.
        items = []
        for i, item in enumerate(pl.items):
            # Title: use the playlist item's title; fall back to the filename
            # derived from the URL when the title field is empty.
            title = item.title
            if not title:
                path = urlparse(item.url).path
                title = os.path.basename(path) or f"track-{i + 1}"

            # URL-encode the URI as required by DidlResource (RFC 3986).
            encoded_uri = quote(item.url, safe=":/?=&#@+%")

            resource = DidlResource(
                uri=encoded_uri,
                protocol_info="http-get:*:audio/mpeg:*",
            )
            didl_item = DidlMusicTrack(
                title=title,
                parent_id=QUEUE_PARENT_ID,  # DD-E: must NOT be "-1"
                item_id=f"track-{i}",
                resources=[resource],
            )
            items.append(didl_item)

        coord.clear_queue()
        coord.add_multiple_to_queue(items)

        # DD-B: SHUFFLE_NOREPEAT intentional — one pass, like worker path.
        # SoCo's "SHUFFLE" mode implies repeat=True (loops forever); we want
        # a single pass through the shuffled order, so SHUFFLE_NOREPEAT is
        # the correct constant here.
        coord.play_mode = "SHUFFLE_NOREPEAT" if shuffle else "NORMAL"

        self._play_from_queue_with_stale_coord_retry(
            speaker.player_name, coord, start_index
        )

        first_item = pl.items[start_index]
        return {
            "started": True,
            "playlist": playlist_name,
            "speaker": speaker.player_name,
            "total_items": len(pl.items),
            "start_index": start_index,
            "shuffle": shuffle,
            "first_item": first_item.to_dict(),
            "engine": "native_queue",  # DD-C: so Flight 2 can detect engine type
        }

    def next_track(self, speaker_name: str) -> dict:
        speaker, coord = self._resolve_coordinator(speaker_name)
        with self._lock:
            sess = self._sessions.get(speaker.uid)
        if sess is None:
            # No worker session — drive the live coordinator directly.
            # NOTE: SoCoSlaveException is swallowed here with no stale-coord
            # retry (unlike say(), which retries once after invalidating the
            # cache). Best-effort: if the coordinator view is stale during
            # group churn, the advance may be silently lost.
            try:
                coord.next()
                track = coord.get_current_track_info()
            except Exception:
                track = {}
            return {
                "engine": "native_queue",
                "speaker": speaker.player_name,
                "title": track.get("title", ""),
                "artist": track.get("artist", ""),
                "album": track.get("album", ""),
                "position": track.get("position", ""),
                "duration": track.get("duration", ""),
                "uri": track.get("uri", ""),
                "playlist_position": track.get("playlist_position", ""),
            }
        sess.skip_event.set()
        return {"engine": "worker", "signaled": "next", **sess.to_dict()}

    def previous_track(self, speaker_name: str) -> dict:
        speaker, coord = self._resolve_coordinator(speaker_name)
        with self._lock:
            sess = self._sessions.get(speaker.uid)
        if sess is None:
            # No worker session — drive the live coordinator directly.
            # NOTE: SoCoSlaveException is swallowed here with no stale-coord
            # retry (unlike say(), which retries once after invalidating the
            # cache). Best-effort: if the coordinator view is stale during
            # group churn, the advance may be silently lost.
            try:
                coord.previous()
                track = coord.get_current_track_info()
            except Exception:
                track = {}
            return {
                "engine": "native_queue",
                "speaker": speaker.player_name,
                "title": track.get("title", ""),
                "artist": track.get("artist", ""),
                "album": track.get("album", ""),
                "position": track.get("position", ""),
                "duration": track.get("duration", ""),
                "uri": track.get("uri", ""),
                "playlist_position": track.get("playlist_position", ""),
            }
        sess.back_event.set()
        return {"engine": "worker", "signaled": "previous", **sess.to_dict()}

    def stop(self, speaker_name: str) -> dict:
        speaker, coord = self._resolve_coordinator(speaker_name)
        with self._lock:
            sess = self._sessions.get(speaker.uid)
        if not sess:
            # No worker session — stop the live coordinator; do NOT clear the queue.
            try:
                coord.stop()
            except Exception:
                pass
            return {
                "stopped": True,
                "engine": "native_queue",
                "speaker": speaker.player_name,
            }
        self._signal_stop(sess)
        try:
            coord.stop()
        except Exception:
            pass
        return {"engine": "worker", "stopped": True, **sess.to_dict()}

    def status(self, speaker_name: str) -> dict:
        speaker, coord = self._resolve_coordinator(speaker_name)
        with self._lock:
            sess = self._sessions.get(speaker.uid)
        if not sess:
            # No worker session — read live coordinator state.
            try:
                transport = coord.get_current_transport_info()
                state = transport.get("current_transport_state", "STOPPED")
                track = coord.get_current_track_info()
            except Exception:
                return {"running": False, "engine": "native_queue", "speaker": speaker.player_name}
            if state in ("STOPPED", "") or not track.get("uri"):
                return {"running": False, "engine": "native_queue", "speaker": speaker.player_name}
            return {
                "engine": "native_queue",
                "speaker": speaker.player_name,
                "state": state,
                "title": track.get("title", ""),
                "artist": track.get("artist", ""),
                "album": track.get("album", ""),
                "position": track.get("position", ""),
                "duration": track.get("duration", ""),
                "uri": track.get("uri", ""),
                "playlist_position": track.get("playlist_position", ""),
            }
        info = {"engine": "worker", **sess.to_dict()}
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

    def _play_from_queue_with_stale_coord_retry(
        self, name: str, coord: SoCo, index: int
    ) -> None:
        """Call `coord.play_from_queue(index)`, recovering once from a stale
        coordinator view (DD-A).

        Mirrors `SonosController._play_uri_with_stale_coord_retry` but calls
        `play_from_queue` instead of `play_uri`. The stale-coord symptom was
        not observed during Leg 1 hardware testing, but the precautionary wrap
        is cheap insurance given the retry pattern is already established.

        On SoCoSlaveException, the speakers cache is explicitly invalidated
        (resetting the TTL so the next re-resolution forces a fresh discovery)
        before re-resolving the coordinator.  Re-resolving alone is insufficient
        because `_resolve_coordinator` → `_speakers_fresh` uses a 30 s TTL; a
        retry within that window would reuse the stale coordinator.
        """
        from soco.exceptions import SoCoSlaveException

        try:
            coord.play_from_queue(index)
        except SoCoSlaveException:
            # Flush the speakers cache so _resolve_coordinator forces a fresh
            # discovery, then retry once.  If firmware still rejects, propagate.
            self._invalidate_speakers_cache()
            _, fresh_coord = self._resolve_coordinator(name)
            fresh_coord.play_from_queue(index)

    def has_active_session(self, speaker_uid: str) -> bool:
        """Return True if a worker-engine session exists for `speaker_uid`.

        Keyed on the named speaker's UID (same key used by _sessions), so
        callers should pass the UID of the speaker the agent originally named,
        not the coordinator's UID.

        Check-then-act race: benign.  Tool calls are serialised at the MCP
        transport layer (single-threaded from the controller's perspective), so
        the session state cannot change between this check and the subsequent
        action within the same tool call.
        """
        with self._lock:
            sess = self._sessions.get(speaker_uid)
            if sess is None:
                return False
            return sess.thread is not None and sess.thread.is_alive()

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

    def _signal_stop(self, sess: PlaybackSession) -> None:
        sess.stop_event.set()
