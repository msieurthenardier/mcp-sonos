"""Shared test helpers: builder functions and shared constants.

Imported by ``test_queue_path.py`` and ``test_queue_resume.py`` (and legs
07/08 parametrization tests).  Plain functions, not pytest fixtures, so
they work in both fixture and non-fixture contexts.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from tests._fakes import SoCoFake

# ---------------------------------------------------------------------------
# Shared network constants (used by any test that constructs a PlaylistManager
# with a known host/port, e.g. test_queue_path.py)
# ---------------------------------------------------------------------------

_HOST_IP = "192.168.1.50"
_AUDIO_PORT = 8080
_MCP_URL = f"http://{_HOST_IP}:{_AUDIO_PORT}/tts/abc123.wav"


# ---------------------------------------------------------------------------
# Playing-speaker builder
# ---------------------------------------------------------------------------

def make_speaker_playing_queue(
    player_name: str = "Kitchen",
    uid: str = "RINCON_FAKE001",
    playlist_position: str = "2",
    play_mode: str = "NORMAL",
    # Track-field overrides — any key accepted by SoCoFake._track
    queue: list | None = None,
    transport_state: str = "PLAYING",
    uri: str = "http://example.com/track2.mp3",
    title: str = "Track 2",
    artist: str = "Artist",
    album: str = "Album",
    position: str = "0:01:30",
    duration: str = "0:04:00",
) -> SoCoFake:
    """Return a SoCoFake that appears to be actively playing from a queue.

    All fields have sensible defaults that match the canonical "playing at
    position 2" state used by the resume tests.  Pass keyword overrides to
    represent the guard-triggering variants used by legs 07 and 08.
    """
    s = SoCoFake(player_name=player_name, uid=uid)
    # Populate the native queue with fake items.
    s._queue = queue if queue is not None else ["item0", "item1", "item2"]
    # Transport state.
    s._transport = {"current_transport_state": transport_state}
    # Track info.
    s._track = {
        "uri": uri,
        "title": title,
        "artist": artist,
        "album": album,
        "position": position,
        "duration": duration,
        "playlist_position": playlist_position,
    }
    s._play_mode = play_mode
    return s


# ---------------------------------------------------------------------------
# Worker-session context manager (leg 06)
# ---------------------------------------------------------------------------

@contextmanager
def worker_session(mgr, speaker, playlist_name: str = "_worker_test_pl") -> Generator:
    """Context manager for the worker-session lifecycle boilerplate.

    - Patches ``playlists_mod.POLL_INTERVAL`` to 0.01 to keep the worker
      thread from spinning during tests.
    - Creates and plays an MCP-hosted playlist so the worker engine starts.
    - Yields the ``PlaybackSession`` object (from ``mgr._sessions[speaker.uid]``).
    - On exit: always restores ``POLL_INTERVAL`` and calls ``mgr.stop``.

    The caller receives the session object and may do further assertions or
    patching inside the ``with`` body after ``yield``.
    """
    import mcp_sonos.playlists as playlists_mod

    mgr.create(playlist_name)
    mgr.add_many(playlist_name, [{"url": _MCP_URL, "title": "TTS"}])
    old_interval = playlists_mod.POLL_INTERVAL
    playlists_mod.POLL_INTERVAL = 0.01
    try:
        mgr.play(speaker.player_name, playlist_name)
        yield mgr._sessions.get(speaker.uid)
    finally:
        playlists_mod.POLL_INTERVAL = old_interval
        try:
            mgr.stop(speaker.player_name)
        except Exception:
            pass
