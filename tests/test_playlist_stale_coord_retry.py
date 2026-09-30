"""Leg 4 (coordinator-view hardening): stale-coordinator retry coverage for
`playlists.py`'s two engines.

Both `_play_via_queue`'s `coord.clear_queue()` and `_worker`'s
`coord.play_uri(...)` are coordinator-only calls (`@only_on_master` on real
SoCo) that can hit the same per-speaker view-lag class documented in
CLAUDE.md — a false `SoCoSlaveException` right after group formation.
Before this leg, `_play_via_queue`'s `clear_queue()` had no retry at all
(an uncaught exception), and `_worker`'s `play_uri` had no retry either — a
false failure there silently skipped an otherwise-playable track. Both now
go through the existing `with_stale_coord_retry` helper (already used by
`_play_via_queue`'s `play_from_queue` and by `say()`).
"""

from __future__ import annotations

import logging
import time

from soco.exceptions import SoCoSlaveException

from mcp_sonos import playlists as playlists_mod
from mcp_sonos.playlists import PlaylistManager

from tests._builders import _AUDIO_PORT, _HOST_IP
from tests._fakes import SoCoFake


def test_play_via_queue_clear_queue_retries_after_stale_coordinator():
    """`clear_queue()` raises once (stale view), the retry invalidates +
    re-resolves, and the second attempt succeeds — the queue load then
    proceeds normally. Without the leg 4 fix this raises `SoCoSlaveException`
    straight out of `play()`."""
    coord = SoCoFake(player_name="Kitchen", uid="RINCON_QCLEAR")
    coord.clear_queue_raise = SoCoSlaveException(
        "clear_queue can only be called/used on the coordinator in a group"
    )
    invalidated = {"n": 0}

    def resolve_coordinator(name: str):
        assert name == "Kitchen"
        return coord, coord

    manager = PlaylistManager(
        resolve_coordinator=resolve_coordinator,
        host_ip=_HOST_IP,
        audio_port=_AUDIO_PORT,
        invalidate_speakers_cache=lambda: invalidated.__setitem__("n", invalidated["n"] + 1),
    )
    manager.create("pl")
    manager.add_many(
        "pl", [{"url": "http://external.example.com/a.mp3", "title": "A"}]
    )

    result = manager.play("Kitchen", "pl")

    assert result["engine"] == "native_queue"
    assert invalidated["n"] == 1, "clear_queue's SoCoSlaveException must trigger exactly one invalidate"
    # add_multiple_to_queue only runs AFTER clear_queue succeeds — proves
    # execution actually continued past the retried clear_queue() call.
    assert coord.queue_size == 1


def test_worker_play_uri_retries_after_stale_coordinator(monkeypatch):
    """`play_uri()` raises once on the first track (stale view right after
    group formation), the retry invalidates + re-resolves, and the second
    attempt succeeds — the track actually plays instead of being skipped.
    Without the leg 4 fix, this hits the worker's "log and skip" fallback:
    the track never plays and `current_index` advances past it immediately."""
    monkeypatch.setattr(playlists_mod, "POLL_INTERVAL", 0.01)

    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_WPLAY")
    speaker.play_uri_raise = SoCoSlaveException(
        "play_uri can only be called/used on the coordinator in a group"
    )
    invalidated = {"n": 0}

    def resolve_coordinator(name: str):
        assert name == "Kitchen"
        return speaker, speaker

    manager = PlaylistManager(
        resolve_coordinator=resolve_coordinator,
        invalidate_speakers_cache=lambda: invalidated.__setitem__("n", invalidated["n"] + 1),
    )
    manager.create("pl")
    manager.add_many("pl", [{"url": "http://test/a.mp3", "title": "A"}])

    try:
        manager.play("Kitchen", "pl")

        deadline = time.monotonic() + 3.0
        while speaker._track.get("uri") != "http://test/a.mp3" and time.monotonic() < deadline:
            time.sleep(0.02)

        assert speaker._track.get("uri") == "http://test/a.mp3", (
            "the track never actually played — the worker took the "
            "log-and-skip fallback instead of retrying"
        )
        assert invalidated["n"] == 1

        sess = manager._sessions.get(speaker.uid)
        assert sess is not None
        # The track was NOT skipped: current_index is still 0 (it only
        # advances once the track naturally ends or is skipped/stopped).
        assert sess.current_index == 0
    finally:
        try:
            manager.stop("Kitchen")
        except Exception:
            pass
