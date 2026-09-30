"""Leg 4 (coordinator-view hardening): regression coverage for the hardware
defect found by leg 3's behavior-test run.

Root cause (see the leg 3 run log and CLAUDE.md's grouping invariant):
each Sonos speaker serves its own, eventually-consistent `ZoneGroupState`
view, and SoCo caches whichever speaker's view it last polled, per
household, for 5s. `_confirm_bystanders_stopped` used to poll THROUGH each
bystander after `c0`'s own confirmation — leaving the shared cache holding
a lagging bystander's view of `c0`, so the very next `@only_on_master` call
on `c0` (`play_uri`, `stop`) falsely raised `SoCoSlaveException`.

These tests use `tests/_fakes.py::FakeHousehold`'s opt-in lag mode
(`enable_lag()` + `queue_stale_override`) to reproduce that exact
mechanism without hardware.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from soco.exceptions import SoCoSlaveException

from mcp_sonos import controller as controller_mod
from mcp_sonos.controller import GroupingError, SonosController

from tests._fakes import FakeHousehold, SoCoFake


# ---------------------------------------------------------------------------
# Shared fixtures / helpers (mirrors tests/test_target_group_controller.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_controller(monkeypatch, tmp_path):
    """SonosController with no real audio host, no Piper TTS, no blocking
    waits, and no real sleeping in any confirmation/resync poll."""
    monkeypatch.setattr(controller_mod.AudioHost, "start", lambda self: None)

    def _fake_synthesize(text, cache_dir, **kwargs):
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        out = cache_dir / "fake_tts.wav"
        out.write_bytes(b"RIFFfake")
        return out

    monkeypatch.setattr(controller_mod, "synthesize", _fake_synthesize)
    monkeypatch.setattr(
        controller_mod.AudioHost,
        "url_for",
        lambda self, filename: f"http://test.invalid/{filename}",
    )
    monkeypatch.setattr(
        SonosController, "_wait_until_stopped", staticmethod(lambda *a, **kw: None)
    )
    ctl = SonosController(cache_dir=tmp_path)
    ctl._sleep = lambda *_: None  # every poll (confirm, sync_view) must not cost real time
    return ctl


def _wire_household(monkeypatch, controller: SonosController, speakers: list[SoCoFake]) -> None:
    monkeypatch.setattr(controller_mod.sp, "discover_speakers", lambda: list(speakers))
    controller._speakers_ts = 0.0


# ---------------------------------------------------------------------------
# 1. Hardware-case reproduction
# ---------------------------------------------------------------------------


def test_play_stream_survives_lagging_bystander_view(monkeypatch, stub_controller):
    """Reproduces the leg 3 hardware trace: Patio is a follower of
    bystander Dining Room; `play_stream(["Patio"])` unjoins Patio (now its
    own coordinator) and must stop Dining Room (now a bystander-of-one).
    Dining Room's view lags — it still reports Patio as its follower — so
    `_confirm_bystanders_stopped`'s read through it leaves the shared cache
    holding a stale view of Patio. Without the leg 4 fix, the subsequent
    `stop`/`play_uri` on Patio falsely raises `SoCoSlaveException` and
    `play_stream` fails exactly as it did on hardware."""
    household = FakeHousehold().enable_lag()
    patio = SoCoFake(player_name="Patio", uid="P")
    dining = SoCoFake(player_name="Dining Room", uid="D")
    household.attach(patio, dining)
    household.group(dining, [patio])  # Dining Room coordinates Patio
    _wire_household(monkeypatch, stub_controller, [patio, dining])

    # Dining Room's own view hasn't caught up with the unjoin yet. Queued
    # TWICE: the leg 4 fix's own per-stop `_sync_view(dining)` (harmlessly,
    # since ground truth still agrees at that pre-unjoin instant) consumes
    # the first one; the second is what `_confirm_bystanders_stopped`'s
    # read-through-Dining-Room later consumes, by which point ground truth
    # has moved on (Patio is standalone) but this override still reports
    # the OLD membership (Patio still Dining Room's follower) — reproducing
    # the exact staleness the leg 3 hardware run hit.
    stale_view = {dining.uid: dining.uid, patio.uid: dining.uid}
    household.queue_stale_override(dining.uid, stale_view)
    household.queue_stale_override(dining.uid, stale_view)

    result = stub_controller.play_stream(["Patio"], "http://example.com/stream.mp3")

    assert result["targets"] == ["Patio"]
    assert result["coordinator"] == "Patio"
    assert result["group_members"] == ["Patio"]
    assert result["stopped"] == ["Dining Room"]
    assert patio.get_current_transport_info()["current_transport_state"] == "PLAYING"


# ---------------------------------------------------------------------------
# 2. _execute_plan's last poll comes from c0
# ---------------------------------------------------------------------------


def test_execute_plan_last_poll_is_from_c0(monkeypatch, stub_controller):
    household = FakeHousehold().enable_lag()
    kitchen = SoCoFake(player_name="Kitchen", uid="K")
    bystander = SoCoFake(player_name="Bystander", uid="B")
    household.attach(kitchen, bystander)
    household.group(kitchen, [bystander])
    _wire_household(monkeypatch, stub_controller, [kitchen, bystander])

    # A lagging bystander view, same as the hardware trace, so
    # `_confirm_bystanders_stopped`'s read through it is what would leave
    # the cache on the wrong speaker without the trailing `_sync_view`.
    household.queue_stale_override(bystander.uid, {kitchen.uid: kitchen.uid, bystander.uid: kitchen.uid})

    stub_controller.play_url(["Kitchen"], "http://example.com/clip.mp3")

    assert household.last_polled_uid == kitchen.uid


# ---------------------------------------------------------------------------
# 3. _on_coordinator retries exactly once, then raises GroupingError
# ---------------------------------------------------------------------------


def test_on_coordinator_retries_exactly_once_then_raises_grouping_error(
    monkeypatch, stub_controller
):
    speaker = SoCoFake(player_name="Kitchen", uid="K")
    call_count = {"n": 0}

    def _always_slave(_speaker):
        call_count["n"] += 1
        raise SoCoSlaveException("can only be called on the coordinator")

    # Stub _sync_view so this test is about _on_coordinator's own retry
    # bookkeeping, not the resync poll (covered separately below).
    monkeypatch.setattr(stub_controller, "_sync_view", lambda *a, **kw: None)

    with pytest.raises(GroupingError) as excinfo:
        stub_controller._on_coordinator(speaker, _always_slave)

    assert call_count["n"] == 2  # initial attempt + exactly one retry
    assert "incompatible" not in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# 4. A planned stop() on a lagging coordinator succeeds after a resync
# ---------------------------------------------------------------------------


def test_planned_stop_on_lagging_coordinator_recovers_after_resync(monkeypatch, stub_controller):
    """Dining Room IS the group's real coordinator (ground truth), and is
    the planned `stop()` target (single-target `["Patio"]`, a follower,
    means Dining Room — the group's current coordinator — is stopped
    first). Its own next self-poll briefly, wrongly, reports it as a
    follower instead (a device that hasn't caught up with its own current
    role) — `_execute_plan`'s per-stop `_sync_view` + retry-once must
    recover from this."""
    household = FakeHousehold().enable_lag()
    dining = SoCoFake(player_name="Dining Room", uid="D")
    patio = SoCoFake(player_name="Patio", uid="P")
    household.attach(dining, patio)
    household.group(dining, [patio])
    # Patio FIRST: the initial topology snapshot's poll-through-the-first-
    # listed-speaker must land on Patio (which has no queued override), so
    # the plan itself is computed from an accurate view. Dining Room's
    # queued override is then only reachable later, at a poll made
    # specifically THROUGH Dining Room (the per-stop `_sync_view`) — not
    # smuggled into the initial snapshot by list order.
    _wire_household(monkeypatch, stub_controller, [patio, dining])

    # Only ONE stale override queued: the pre-stop `_sync_view(dining)`
    # (plain, no `expect_coordinator`) consumes it and forces the first
    # `dining.stop()` attempt to see a stale "I'm a follower" view; the
    # resync-and-retry's `_sync_view(dining, expect_coordinator=True)` then
    # finds the override queue empty and falls through to ground truth
    # (which already, correctly, has Dining Room as coordinator).
    household.queue_stale_override(dining.uid, {dining.uid: patio.uid, patio.uid: patio.uid})

    result = stub_controller.play_url(["Patio"], "http://example.com/clip.mp3")

    assert result["stopped"] == ["Dining Room"]
    assert dining.stop_call_count == 1


# ---------------------------------------------------------------------------
# 5. play_stream's error wording for a slave exception is not "incompatible"
# ---------------------------------------------------------------------------


def test_play_stream_slave_exception_does_not_say_incompatible(monkeypatch, stub_controller):
    household = FakeHousehold()
    kitchen = SoCoFake(player_name="Kitchen", uid="K")
    household.attach(kitchen)
    _wire_household(monkeypatch, stub_controller, [kitchen])

    call_count = {"n": 0}

    def _always_slave(uri, title=None, force_radio=False):
        call_count["n"] += 1
        raise SoCoSlaveException("can only be called on the coordinator")

    kitchen.play_uri = _always_slave
    monkeypatch.setattr(stub_controller, "_sync_view", lambda *a, **kw: None)

    with pytest.raises(GroupingError) as excinfo:
        stub_controller.play_stream(["Kitchen"], "http://example.com/stream.mp3")

    assert "incompatible" not in str(excinfo.value).lower()
    # Exactly one retry, and the scheme fallback ("radio") is skipped
    # entirely — GroupingError propagates immediately.
    assert call_count["n"] == 2
