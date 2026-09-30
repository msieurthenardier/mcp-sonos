"""Controller-level tests for target-set grouping (`_plan_targets` /
`_execute_plan`), exercised through the public `play_url` / `say` methods.

Uses `tests/_fakes.py::FakeHousehold` to model the hardware-verified
multi-group semantics (join moves only self, a coordinator's unjoin
delegates its remaining members, join() on a still-coordinating speaker
raises). The planner itself is covered exhaustively, pure and
fake-free, in `tests/test_targeting.py` — these tests are about the I/O
half: execution order, confirmation, error shapes, and response wiring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_sonos import controller as controller_mod
from mcp_sonos import speakers as sp
from mcp_sonos.controller import GroupingError, SonosController

from tests._builders import make_speaker_playing_queue
from tests._fakes import FakeHousehold, SoCoFake


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_controller(monkeypatch, tmp_path):
    """SonosController with no real audio host, no Piper TTS, no blocking
    waits, and no real sleeping in the grouping confirmation poll."""
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
    ctl._sleep = lambda *_: None  # confirmation poll must not cost real time
    return ctl


def _wire_household(monkeypatch, controller: SonosController, speakers: list[SoCoFake]) -> None:
    monkeypatch.setattr(controller_mod.sp, "discover_speakers", lambda: list(speakers))
    controller._speakers_ts = 0.0


def _track_calls(speakers: list[SoCoFake]) -> list[tuple]:
    """Wrap stop/unjoin/join on each fake to record call order, while still
    delegating to the real (household-aware) implementation."""
    log: list[tuple] = []

    def _wrap(s: SoCoFake) -> None:
        orig_stop, orig_unjoin, orig_join = s.stop, s.unjoin, s.join

        def _stop():
            log.append(("stop", s.uid))
            return orig_stop()

        def _unjoin():
            log.append(("unjoin", s.uid))
            return orig_unjoin()

        def _join(other):
            log.append(("join", s.uid, other.uid))
            return orig_join(other)

        s.stop, s.unjoin, s.join = _stop, _unjoin, _join

    for s in speakers:
        _wrap(s)
    return log


# ---------------------------------------------------------------------------
# Execution order
# ---------------------------------------------------------------------------


def test_stop_precedes_unjoin(monkeypatch, stub_controller):
    household = FakeHousehold()
    k = SoCoFake(player_name="Kitchen", uid="K")
    b = SoCoFake(player_name="Bystander", uid="B")
    household.attach(k, b)
    household.group(k, [b])
    _wire_household(monkeypatch, stub_controller, [k, b])
    calls = _track_calls([k, b])

    stub_controller.play_url(["Kitchen"], "http://example.com/clip.mp3")

    ops = [c[0] for c in calls]
    stop_idxs = [i for i, op in enumerate(ops) if op == "stop"]
    unjoin_idxs = [i for i, op in enumerate(ops) if op == "unjoin"]
    assert stop_idxs and unjoin_idxs
    assert max(stop_idxs) < min(unjoin_idxs)


def test_no_join_ever_issued_on_a_speaker_coordinating_others(monkeypatch, stub_controller):
    # T2 coordinates two bystanders; the household's do_join raises if ever
    # called on a still-coordinating speaker (see FakeHousehold docstring).
    household = FakeHousehold()
    k = SoCoFake(player_name="Kitchen", uid="K")
    t2 = SoCoFake(player_name="T2", uid="T2")
    b1 = SoCoFake(player_name="B1", uid="B1")
    b2 = SoCoFake(player_name="B2", uid="B2")
    household.attach(k, t2, b1, b2)
    household.group(t2, [b1, b2])
    _wire_household(monkeypatch, stub_controller, [k, t2, b1, b2])

    result = stub_controller.play_url(["Kitchen", "T2"], "http://example.com/clip.mp3")

    assert set(result["group_members"]) == {"Kitchen", "T2"}
    assert set(result["stopped"]) == {"B1", "B2"}


def test_untouched_groups_receive_zero_calls(monkeypatch, stub_controller):
    household = FakeHousehold()
    k = SoCoFake(player_name="Kitchen", uid="K")
    p = SoCoFake(player_name="Patio", uid="P")
    x = SoCoFake(player_name="X", uid="X")
    y = SoCoFake(player_name="Y", uid="Y")
    household.attach(k, p, x, y)
    household.group(x, [y])
    _wire_household(monkeypatch, stub_controller, [k, p, x, y])
    calls = _track_calls([x, y])

    stub_controller.play_url(["Kitchen", "Patio"], "http://example.com/clip.mp3")

    assert calls == []


# ---------------------------------------------------------------------------
# Partial failure
# ---------------------------------------------------------------------------


def test_unknown_name_raises_speaker_not_found_with_zero_mutation_calls(
    monkeypatch, stub_controller
):
    k = SoCoFake(player_name="Kitchen", uid="K")
    _wire_household(monkeypatch, stub_controller, [k])
    calls = _track_calls([k])

    with pytest.raises(sp.SpeakerNotFound):
        stub_controller.play_url(["Nonexistent"], "http://example.com/clip.mp3")

    assert calls == []


def test_mid_step_exception_raises_grouping_error_with_topology(monkeypatch, stub_controller):
    household = FakeHousehold()
    k = SoCoFake(player_name="Kitchen", uid="K")
    b = SoCoFake(player_name="Bystander", uid="B")
    household.attach(k, b)
    household.group(k, [b])
    _wire_household(monkeypatch, stub_controller, [k, b])

    def _boom():
        raise RuntimeError("simulated failure")

    b.unjoin = _boom

    with pytest.raises(GroupingError) as excinfo:
        stub_controller.play_url(["Kitchen"], "http://example.com/clip.mp3")

    msg = str(excinfo.value)
    assert "mutation" in msg
    assert "Kitchen" in msg
    assert "simulated failure" in msg


def test_confirmation_timeout_raises_grouping_error(monkeypatch, stub_controller):
    household = FakeHousehold()
    k = SoCoFake(player_name="Kitchen", uid="K")
    t2 = SoCoFake(player_name="T2", uid="T2")
    household.attach(k, t2)
    _wire_household(monkeypatch, stub_controller, [k, t2])

    # A join() that silently doesn't change household membership: the
    # confirmation poll can never observe the planned final membership.
    t2.join = lambda other: None

    counter = {"t": 0.0}

    def fake_monotonic():
        counter["t"] += 1.0
        return counter["t"]

    monkeypatch.setattr(controller_mod.time, "monotonic", fake_monotonic)

    with pytest.raises(GroupingError, match="confirmation"):
        stub_controller.play_url(["Kitchen", "T2"], "http://example.com/clip.mp3")


def test_bystander_still_playing_raises_grouping_error(monkeypatch, stub_controller):
    household = FakeHousehold()
    k = SoCoFake(player_name="Kitchen", uid="K")
    b = SoCoFake(player_name="Bystander", uid="B")
    household.attach(k, b)
    household.group(k, [b])
    _wire_household(monkeypatch, stub_controller, [k, b])

    # Simulate the hazard the confirmation guards against: after separation,
    # the bystander's (now its own) coordinator still reports PLAYING.
    b.get_current_transport_info = lambda: {"current_transport_state": "PLAYING"}

    with pytest.raises(GroupingError, match="bystander"):
        stub_controller.play_url(["Kitchen"], "http://example.com/clip.mp3")


# ---------------------------------------------------------------------------
# Queue snapshot / resume ordering (rule 2, c0's own group has bystanders)
# ---------------------------------------------------------------------------


def test_queue_snapshot_before_stop_and_resume_lands_on_c0(monkeypatch, stub_controller):
    household = FakeHousehold()
    k = make_speaker_playing_queue(player_name="Kitchen", uid="K", playlist_position="2")
    b = SoCoFake(player_name="Bystander", uid="B")
    t2 = SoCoFake(player_name="T2", uid="T2")
    household.attach(k, b, t2)
    household.group(k, [b])
    _wire_household(monkeypatch, stub_controller, [k, b, t2])

    stub_controller.say(["Kitchen", "T2"], "hello")

    # The snapshot read Kitchen's PLAYING/queued state before stop-first
    # executed — proven by the resume actually firing afterwards.
    assert k.play_from_queue_last_index == 1  # position "2" -> index 1
    # Final group is Kitchen + T2; the bystander was separated.
    assert {m.uid for m in k.group.members} == {"K", "T2"}


# ---------------------------------------------------------------------------
# say(["all"]) and the "all" sentinel
# ---------------------------------------------------------------------------


def test_say_all_still_dissolves_and_returns_old_shape(monkeypatch, stub_controller):
    k = SoCoFake(player_name="Kitchen", uid="K")
    p = SoCoFake(player_name="Patio", uid="P")
    _wire_household(monkeypatch, stub_controller, [k, p])

    result = stub_controller.say(["all"], "hello everyone")

    assert result["spoken_on"] == "all"
    assert "coordinator_used" in result
    assert set(result["speakers"]) == {"Kitchen", "Patio"}
    assert "targets" not in result


def test_all_mixed_with_names_raises(stub_controller):
    with pytest.raises(ValueError):
        stub_controller.say(["all", "Kitchen"], "hello")


def test_all_rejected_by_play_url(stub_controller):
    with pytest.raises(ValueError):
        stub_controller.play_url(["all"], "http://example.com/clip.mp3")


def test_all_rejected_by_play_stream(stub_controller):
    with pytest.raises(ValueError):
        stub_controller.play_stream(["all"], "http://example.com/stream.mp3")


# ---------------------------------------------------------------------------
# say() volume applies to exactly final_members
# ---------------------------------------------------------------------------


def test_say_volume_excludes_stopped_bystanders(monkeypatch, stub_controller):
    household = FakeHousehold()
    k = SoCoFake(player_name="Kitchen", uid="K", _volume=10)
    b = SoCoFake(player_name="Bystander", uid="B", _volume=10)
    t2 = SoCoFake(player_name="T2", uid="T2", _volume=10)
    household.attach(k, b, t2)
    household.group(k, [b])
    _wire_household(monkeypatch, stub_controller, [k, b, t2])

    stub_controller.say(["Kitchen", "T2"], "hello", volume=55)

    assert k.volume == 55
    assert t2.volume == 55
    assert b.volume == 10  # bystander: stopped, never gets the volume


def test_say_volume_detach_false_includes_pulled_in_non_target(monkeypatch, stub_controller):
    household = FakeHousehold()
    k = SoCoFake(player_name="Kitchen", uid="K", _volume=1)
    t2 = SoCoFake(player_name="T2", uid="T2", _volume=1)
    z = SoCoFake(player_name="Z", uid="Z", _volume=1)  # non-target, in T2's group
    household.attach(k, t2, z)
    household.group(t2, [z])
    _wire_household(monkeypatch, stub_controller, [k, t2, z])

    stub_controller.say(["Kitchen", "T2"], "hello", volume=77, detach=False)

    assert k.volume == 77
    assert t2.volume == 77
    assert z.volume == 77  # pulled in, playing -> gets the volume too


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


def test_play_url_response_shape(monkeypatch, stub_controller):
    household = FakeHousehold()
    k = SoCoFake(player_name="Kitchen", uid="K")
    household.attach(k)
    _wire_household(monkeypatch, stub_controller, [k])

    result = stub_controller.play_url(["Kitchen"], "http://example.com/clip.mp3", detach=False)

    for key in ("targets", "coordinator", "group_members", "stopped", "detached", "url"):
        assert key in result
    assert result["targets"] == ["Kitchen"]
    assert result["detached"] is False
    assert "requested" not in result
    assert "played_on_coordinator" not in result


# ---------------------------------------------------------------------------
# say() with a target set under a lagging bystander view (operator-approved
# scope addition alongside squawk 0006 — see squawks/0006's Corrective
# Action). Mirrors
# tests/test_coordinator_view_hardening.py::test_play_stream_survives_lagging_bystander_view,
# but for a two-name target set going through `say()`. `say()` shares
# `_execute_plan` / `_confirm_bystanders_stopped` with `play_stream`, so
# this proves the same leg-4 fix (the trailing `_sync_view(c0,
# expect_coordinator=True)` in `_execute_plan`) covers `say()` too.
# ---------------------------------------------------------------------------


def test_say_target_set_survives_lagging_bystander_view(monkeypatch, stub_controller):
    """Kitchen is already standalone (picked as c0 via the planner's
    subset-match rule); T2 is a follower of bystander Dining Room.
    `say(["Kitchen", "T2"], ...)` must: stop Dining Room (now a
    bystander-of-one after T2 leaves), unjoin T2 from it, and join T2 into
    Kitchen's group. Dining Room's own view lags behind the unjoin — it
    still reports T2 as its follower when polled during
    `_confirm_bystanders_stopped` — modeling the exact leg 3 hardware
    staleness (same mechanism as
    `test_coordinator_view_hardening.py::test_play_stream_survives_lagging_bystander_view`,
    but here c0 -- Kitchen -- is untouched by the stale view and a second
    target -- T2 -- is pulled out of the lagging group instead). `say()`
    must still succeed and report accurate `group_members`."""
    household = FakeHousehold().enable_lag()
    kitchen = SoCoFake(player_name="Kitchen", uid="K")
    dining = SoCoFake(player_name="Dining Room", uid="D")
    t2 = SoCoFake(player_name="T2", uid="T2")
    household.attach(kitchen, dining, t2)
    household.group(dining, [t2])  # Dining Room coordinates T2
    dining._transport = {"current_transport_state": "PLAYING"}
    _wire_household(monkeypatch, stub_controller, [kitchen, dining, t2])

    # Dining Room's own view hasn't caught up with T2 leaving yet. Queued
    # TWICE, same reasoning as the play_stream hardening test: the first
    # is consumed (harmlessly) by the per-stop `_sync_view(dining)`, the
    # second by `_confirm_bystanders_stopped`'s later read-through-Dining.
    stale_view = {dining.uid: dining.uid, t2.uid: dining.uid}
    household.queue_stale_override(dining.uid, stale_view)
    household.queue_stale_override(dining.uid, stale_view)

    result = stub_controller.say(["Kitchen", "T2"], "hello")

    assert result["targets"] == ["Kitchen", "T2"]
    assert result["coordinator"] == "Kitchen"
    assert set(result["group_members"]) == {"Kitchen", "T2"}
    assert result["stopped"] == ["Dining Room"]
    assert kitchen.get_current_transport_info()["current_transport_state"] == "PLAYING"
