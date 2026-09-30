"""Hardware-free regression coverage for squawk 0007: `targeting_smoke.py`'s
`cmd_restore_state` final match-report read must settle-poll a speaker's own
(possibly lagging) view rather than trust a single sample.

Reproduces the mechanism from behavior-test run 2026-09-29-05-02-18 step 12
(see `squawks/0007-restore-state-report-view-lag.md`) using
`tests/_fakes.py::FakeHousehold`'s opt-in lag mode: a speaker's own view can
briefly still report the PRE-restore membership immediately after a join,
even though ground truth (and a moment-later re-read) already reflects it.
Without settle-polling, `cmd_restore_state` reports that speaker
`matched: false` and exits 1 on a restore that actually succeeded.

`targeting_smoke.py` is a root-level CLI script, not a package module, but
it has no import-time side effect that reaches real hardware: constructing
its module-level `controller` only binds a local audio-host port and reads
`HOST_IP` (pinned to 127.0.0.1 by `tests/conftest.py`) — no discovery, no
UPnP calls. These tests replace that module-level `controller` with a stub
wired to a `FakeHousehold` before calling `cmd_restore_state` directly.
"""

from __future__ import annotations

import json

import pytest

import targeting_smoke
from mcp_sonos import controller as controller_mod
from mcp_sonos.controller import SonosController

from tests._fakes import FakeHousehold, SoCoFake


class _FakeClock:
    """Deterministic stand-in for `time.monotonic()` / `time.sleep()`.

    The clock only advances when `sleep` is called (by the amount slept),
    never from real wall-clock time. `targeting_smoke.cmd_restore_state`'s
    settle-poll loop (and its two hardcoded 0.5s settle sleeps) drive a
    real `deadline = time.monotonic() + SYNC_VIEW_TIMEOUT_SECONDS` loop —
    with this clock swapped in, that loop still runs its full, real
    iteration count (so the cap-bounded behavior is genuinely exercised),
    it just costs no actual wall-clock time.
    """

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def fake_clock(monkeypatch):
    """Swap `targeting_smoke`'s `time.monotonic`/`time.sleep` (the real,
    shared `time` module — `targeting_smoke` does `import time`) for a
    `_FakeClock` so `cmd_restore_state`'s settle-poll loop and its
    hardcoded 0.5s sleeps cost no real wall-clock time. Scoped to this
    test via `monkeypatch`, so it's reverted automatically afterward."""
    clock = _FakeClock()
    monkeypatch.setattr(targeting_smoke.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(targeting_smoke.time, "sleep", clock.sleep)
    return clock


@pytest.fixture
def stub_controller(monkeypatch, tmp_path):
    """Same recipe as `tests/test_coordinator_view_hardening.py`'s fixture:
    no real audio host, no real sleeping in any confirmation/sync poll."""
    monkeypatch.setattr(controller_mod.AudioHost, "start", lambda self: None)
    ctl = SonosController(cache_dir=tmp_path)
    ctl._sleep = lambda *_: None
    return ctl


def _wire_household(monkeypatch, controller: SonosController, speakers: list[SoCoFake]) -> None:
    monkeypatch.setattr(controller_mod.sp, "discover_speakers", lambda: list(speakers))
    controller._speakers_ts = 0.0


def test_restore_state_settles_through_transient_view_lag(
    monkeypatch, tmp_path, stub_controller, fake_clock, capsys
):
    """One stale sample of Patio's own view (still self-only, right after
    the restore's join) must NOT be the final word — the settle-poll's next
    iteration re-reads through a cleared cache, finds ground truth already
    converged, and the report shows a clean match."""
    household = FakeHousehold().enable_lag()
    kitchen = SoCoFake(player_name="Kitchen", uid="K", _volume=10, _mute=False)
    patio = SoCoFake(player_name="Patio", uid="P", _volume=20, _mute=False)
    household.attach(kitchen, patio)
    _wire_household(monkeypatch, stub_controller, [kitchen, patio])
    monkeypatch.setattr(targeting_smoke, "controller", stub_controller)

    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "groups": [{"coordinator": "Kitchen", "members": ["Kitchen", "Patio"]}],
                "speakers": {
                    "Kitchen": {"volume": 10, "muted": False},
                    "Patio": {"volume": 20, "muted": False},
                },
            }
        )
    )

    # Queued ONCE: the first poll through Patio's own view (inside the
    # settle-poll's first iteration) reports it as still self-only — a
    # stale sample of the pre-join state. No override is queued for the
    # second iteration, so that poll falls through to ground truth, which
    # has long since converged (the join happened synchronously, in step 2,
    # well before this report is read).
    household.queue_stale_override("P", {"K": "K", "P": "P"})

    targeting_smoke.cmd_restore_state(str(state_path))  # must NOT sys.exit

    payload = json.loads(capsys.readouterr().out)
    report = {row["speaker"]: row for row in payload["report"]}
    assert report["Patio"]["matched"] is True
    assert report["Patio"]["group_members"] == ["Kitchen", "Patio"]
    assert report["Kitchen"]["matched"] is True


def test_restore_state_still_reports_persistent_mismatch(
    monkeypatch, tmp_path, stub_controller, fake_clock, capsys
):
    """The settle-poll has a cap: a restore that genuinely never converges
    must still end up reported as a mismatch (and the command must still
    exit non-zero) rather than retry forever or paper over a real failure."""
    household = FakeHousehold().enable_lag()
    kitchen = SoCoFake(player_name="Kitchen", uid="K", _volume=10, _mute=False)
    patio = SoCoFake(player_name="Patio", uid="P", _volume=20, _mute=False)
    household.attach(kitchen, patio)
    _wire_household(monkeypatch, stub_controller, [kitchen, patio])
    monkeypatch.setattr(targeting_smoke, "controller", stub_controller)

    # Patio's join is permanently broken (best-effort, swallowed by
    # cmd_restore_state's own try/except) — ground truth never groups, so
    # every settle-poll iteration keeps reading the same real mismatch.
    def _broken_join(self, other):
        raise RuntimeError("simulated join failure")

    monkeypatch.setattr(SoCoFake, "join", _broken_join)

    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "groups": [{"coordinator": "Kitchen", "members": ["Kitchen", "Patio"]}],
                "speakers": {
                    "Kitchen": {"volume": 10, "muted": False},
                    "Patio": {"volume": 20, "muted": False},
                },
            }
        )
    )

    with pytest.raises(SystemExit) as exc_info:
        targeting_smoke.cmd_restore_state(str(state_path))
    assert exc_info.value.code == 1

    payload = json.loads(capsys.readouterr().out)
    report = {row["speaker"]: row for row in payload["report"]}
    assert report["Patio"]["matched"] is False
    assert report["Patio"]["group_members"] == ["Patio"]
