"""Regression test for the F1 external-takeover branch in `PlaylistManager`.

Background: Flight 01 Leg 01 fixed an AttributeError where the takeover
branch (`playlists.py:393`) referenced a non-existent attribute on the
session. Post-fix it uses `session.speaker_name`. This test pins that
the takeover branch:

1. Logs cleanly (no `AttributeError` raised through the worker).
2. Names the speaker in the log message.
3. Lets the worker exit cleanly via the stop_event + finally cleanup,
   removing itself from `_sessions`.

Race shape: `_iteration_event` (Leg 02's scaffolding) signals "worker is
about to observe transport state," not "has observed it." We close that
race by combining `monkeypatch.setattr(POLL_INTERVAL, 0.01)` for fast
iterations with a bounded-retry `while "preempted" not in caplog.text`
loop. Tests should pass with no live Sonos reachable — `SoCoFake` never
talks to the network.
"""

from __future__ import annotations

import logging
import time

from mcp_sonos import playlists as playlists_mod
from mcp_sonos.playlists import PlaylistManager

from tests._fakes import SoCoFake


def test_takeover_logs_cleanly_no_attributeerror(caplog, monkeypatch):
    # Speed up the worker poll loop so the test runs fast and the race
    # window (iteration_event signals "starting", not "completed") is
    # tiny. Combine with a bounded-retry caplog check below.
    monkeypatch.setattr(playlists_mod, "POLL_INTERVAL", 0.01)

    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_TEST001")

    # PlaylistManager constructor takes resolve_coordinator: Callable[[str], tuple[SoCo, SoCo]].
    def resolve_coordinator(name):
        assert name == "Kitchen"
        return speaker, speaker

    manager = PlaylistManager(resolve_coordinator=resolve_coordinator)
    manager.create("morning")
    manager.add_many("morning", [{"url": "http://test/a.mp3", "title": "A"}])

    try:
        with caplog.at_level(logging.INFO):
            manager.play("Kitchen", "morning")

            # Wait for the worker to start polling. _iteration_event signals
            # "about to observe state," not "has observed it" — see Leg 02's
            # design notes for why this is at the top of the inner loop.
            assert manager._iteration_event.wait(timeout=2.0), "worker never started polling"

            # Simulate external takeover: a different URI is now playing.
            speaker._track = {"uri": "http://other/takeover.mp3", "title": ""}
            speaker._transport = {"current_transport_state": "PLAYING"}

            # Bounded retry: poll caplog until the takeover branch logs, or
            # the deadline elapses. POLL_INTERVAL=0.01 means iterations take
            # ~10ms; allow up to 3s for slow runners.
            deadline = time.monotonic() + 3.0
            while "preempted" not in caplog.text and time.monotonic() < deadline:
                time.sleep(0.02)

        # Regression assertions.
        assert "AttributeError" not in caplog.text, \
            "F1 regression — coordinator_name AttributeError reintroduced"
        assert "preempted" in caplog.text, \
            "takeover branch never logged within deadline"
        assert "Kitchen" in caplog.text, \
            "log should mention the speaker name (post-Flight-01 fix)"

        # Pin the session-cleanup branch: after the takeover, the session
        # exits cleanly and is removed from _sessions.
        # (Worker thread may still be in its `finally` cleanup when we get
        # here; give it a brief moment to remove itself from _sessions.)
        cleanup_deadline = time.monotonic() + 2.0
        while speaker.uid in manager._sessions and time.monotonic() < cleanup_deadline:
            time.sleep(0.02)
        assert speaker.uid not in manager._sessions, \
            "worker did not clean up its session entry"
    finally:
        # Belt-and-suspenders cleanup in case the test failed before the
        # worker exited cleanly via the takeover path.
        manager.stop("Kitchen")
