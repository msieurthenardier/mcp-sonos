"""Exhaustive, hardware-free tests for the pure target-set planner.

`plan_target_group` is a pure function over a topology snapshot — no SoCo,
no fakes, no I/O. Every case here constructs a `GroupInfo` topology by hand
and asserts on the returned `TargetPlan`.
"""

from __future__ import annotations

import pytest

from mcp_sonos.targeting import GroupInfo, TargetPlan, plan_target_group


def g(coordinator_uid: str, member_uids: tuple[str, ...], state: str | None = "STOPPED") -> GroupInfo:
    return GroupInfo(coordinator_uid=coordinator_uid, member_uids=member_uids, state=state)


# ---------------------------------------------------------------------------
# Exact-match fast path (detach=True)
# ---------------------------------------------------------------------------


def test_fast_path_exact_match_keeps_existing_coordinator():
    topology = [g("K", ("K", "P")), g("D", ("D",))]
    plan = plan_target_group(topology, ["K", "P"], detach=True)
    assert plan.fast_path is True
    assert plan.coordinator_uid == "K"
    assert plan.stop == ()
    assert plan.unjoin == ()
    assert plan.join == ()
    assert plan.bystanders == ()
    assert set(plan.final_members) == {"K", "P"}


def test_fast_path_is_idempotent_regardless_of_target_order():
    topology = [g("K", ("K", "P"))]
    plan_a = plan_target_group(topology, ["K", "P"], detach=True)
    plan_b = plan_target_group(topology, ["P", "K"], detach=True)
    assert plan_a.fast_path is True
    assert plan_b.fast_path is True
    assert plan_a.coordinator_uid == plan_b.coordinator_uid == "K"


def test_fast_path_single_standalone_target():
    topology = [g("K", ("K",)), g("P", ("P",))]
    plan = plan_target_group(topology, ["K"], detach=True)
    assert plan.fast_path is True
    assert plan.coordinator_uid == "K"
    assert plan.stop == () and plan.unjoin == () and plan.join == ()


# ---------------------------------------------------------------------------
# Coordinator choice, all four rules (detach=True, non-fast-path)
# ---------------------------------------------------------------------------


def test_rule2_prefers_playing_target_coordinator_over_idle_target():
    # T = [Kitchen(idle standalone), Patio(playing, coordinating Fireplace)]
    topology = [
        g("K", ("K",), state="STOPPED"),
        g("P", ("P", "F"), state="PLAYING"),
    ]
    plan = plan_target_group(topology, ["K", "P"], detach=True)
    assert plan.coordinator_uid == "P"


def test_rule2_first_listed_playing_target_wins_over_second():
    topology = [
        g("K", ("K",), state="PLAYING"),
        g("P", ("P",), state="PLAYING"),
    ]
    plan = plan_target_group(topology, ["K", "P"], detach=True)
    assert plan.coordinator_uid == "K"


def test_rule2_own_group_has_bystanders():
    # c0 is chosen by rule 2 even though its own group contains a bystander.
    topology = [
        g("K", ("K", "B"), state="PLAYING"),
        g("T2", ("T2",), state="STOPPED"),
    ]
    plan = plan_target_group(topology, ["K", "T2"], detach=True)
    assert plan.coordinator_uid == "K"
    assert "K" in plan.stop  # c0's own group has a bystander, so it's stopped
    assert "B" in plan.unjoin
    assert "B" in plan.bystanders
    assert "T2" in plan.unjoin and "T2" in plan.join


def test_rule3_prefers_bystander_free_coordinator_when_no_target_playing():
    # Neither target is PLAYING; T2 coordinates a bystander-free group.
    topology = [
        g("K", ("K", "B"), state="STOPPED"),  # has a bystander -> rule 3 excludes it
        g("T2", ("T2",), state="STOPPED"),
    ]
    plan = plan_target_group(topology, ["K", "T2"], detach=True)
    assert plan.coordinator_uid == "T2"


def test_rule4_fallback_to_first_listed_target():
    # No target is PLAYING, and no target coordinates a bystander-free group
    # (both targets are followers of bystander coordinators).
    topology = [
        g("B1", ("B1", "K"), state="STOPPED"),
        g("B2", ("B2", "T2"), state="STOPPED"),
    ]
    plan = plan_target_group(topology, ["K", "T2"], detach=True)
    assert plan.coordinator_uid == "K"  # first-listed


# ---------------------------------------------------------------------------
# Detach algorithm shape
# ---------------------------------------------------------------------------


def test_target_follower_of_bystander_coordinator_is_pulled_standalone_then_joined():
    topology = [
        g("B", ("B", "K"), state="STOPPED"),
        g("T2", ("T2",), state="STOPPED"),
    ]
    plan = plan_target_group(topology, ["T2", "K"], detach=True)
    # c0 = T2 (rule 3: bystander-free coordinator; T2 listed first and is a
    # standalone coordinator with no bystanders)
    assert plan.coordinator_uid == "T2"
    assert "B" in plan.stop
    assert "K" in plan.unjoin
    assert "K" in plan.join
    assert "B" in plan.bystanders


def test_non_c0_target_coordinating_two_bystanders_is_delegated_and_stays_grouped():
    topology = [
        g("K", ("K",), state="STOPPED"),
        g("T2", ("T2", "B1", "B2"), state="STOPPED"),
    ]
    plan = plan_target_group(topology, ["K", "T2"], detach=True)
    assert plan.coordinator_uid == "K"
    assert "T2" in plan.stop  # T2's own group has bystanders
    assert "T2" in plan.unjoin
    assert "T2" in plan.join
    assert set(plan.bystanders) == {"B1", "B2"}
    # B1/B2 are never unjoined or joined explicitly — they stay together,
    # delegated by the firmware, and stopped.
    assert "B1" not in plan.unjoin and "B2" not in plan.unjoin
    assert "B1" not in plan.join and "B2" not in plan.join


def test_untouched_groups_receive_no_mention():
    topology = [
        g("K", ("K",), state="STOPPED"),
        g("P", ("P",), state="STOPPED"),
        g("X", ("X", "Y"), state="PLAYING"),
    ]
    plan = plan_target_group(topology, ["K", "P"], detach=True)
    assert "X" not in plan.stop
    assert "X" not in plan.unjoin and "Y" not in plan.unjoin
    assert "X" not in plan.join and "Y" not in plan.join
    assert "X" not in plan.bystanders and "Y" not in plan.bystanders
    assert ("X", "Y") in plan.untouched_groups


def test_duplicates_deduped_keeping_first_occurrence():
    topology = [g("K", ("K",)), g("P", ("P",))]
    plan = plan_target_group(topology, ["K", "K", "P", "k".upper()], detach=True)
    assert set(plan.final_members) == {"K", "P"}
    assert plan.join.count("P") <= 1


def test_stop_precedes_conceptually_every_affected_bystander_group():
    # Two separate bystander-containing affected groups both get stopped.
    topology = [
        g("K", ("K", "B1"), state="PLAYING"),
        g("P", ("P", "B2"), state="STOPPED"),
    ]
    plan = plan_target_group(topology, ["K", "P"], detach=True)
    assert set(plan.stop) == {"K", "P"}
    assert set(plan.bystanders) == {"B1", "B2"}


# ---------------------------------------------------------------------------
# Opt-out semantics (detach=False)
# ---------------------------------------------------------------------------


def test_opt_out_single_target_no_changes():
    topology = [g("K", ("K", "X"), state="PLAYING")]
    plan = plan_target_group(topology, ["K"], detach=False)
    assert plan.fast_path is True
    assert plan.stop == () and plan.unjoin == () and plan.join == ()
    assert plan.bystanders == ()
    assert set(plan.final_members) == {"K", "X"}
    assert plan.coordinator_uid == "K"


def test_opt_out_targets_already_in_one_group_no_changes():
    topology = [g("K", ("K", "P"), state="STOPPED")]
    plan = plan_target_group(topology, ["K", "P"], detach=False)
    assert plan.fast_path is True
    assert plan.stop == () and plan.unjoin == () and plan.join == ()


def test_opt_out_multi_group_merge_joins_followers_before_old_coordinator():
    topology = [
        g("K", ("K", "F1"), state="STOPPED"),  # target's group, has a follower F1
        g("P", ("P", "F2"), state="STOPPED"),  # other target's group
    ]
    plan = plan_target_group(topology, ["K", "P"], detach=False)
    assert plan.coordinator_uid == "K"
    assert plan.stop == () and plan.unjoin == ()
    # followers of the merged group join before its old coordinator
    assert plan.join.index("F2") < plan.join.index("P")
    assert set(plan.final_members) == {"K", "F1", "P", "F2"}
    assert plan.bystanders == ()


def test_opt_out_merge_pulls_in_non_target_members():
    topology = [
        g("K", ("K",), state="STOPPED"),
        g("P", ("P", "Z"), state="STOPPED"),  # Z is not a target
    ]
    plan = plan_target_group(topology, ["K", "P"], detach=False)
    assert "Z" in plan.join
    assert "Z" in plan.final_members
    assert plan.bystanders == ()  # not stopped; pulled in and playing


# ---------------------------------------------------------------------------
# The join invariant, enforced by the planner itself
# ---------------------------------------------------------------------------


def test_no_join_ever_targets_a_speaker_still_coordinating_others():
    # A battery of adversarial topologies; plan_target_group asserts the
    # invariant internally (raises AssertionError on violation), so simply
    # not raising is the test.
    topologies = [
        [g("K", ("K", "B")), g("T2", ("T2", "B2", "B3"))],
        [g("B", ("B", "K")), g("T2", ("T2",))],
        [g("K", ("K",)), g("P", ("P",)), g("X", ("X", "Y"))],
        [g("K", ("K", "P"))],
    ]
    target_sets = [["K", "T2"], ["K", "T2"], ["K", "P"], ["K", "P"]]
    for topology, targets in zip(topologies, target_sets):
        for detach in (True, False):
            plan_target_group(topology, targets, detach=detach)  # must not raise


def test_missing_targets_raises_value_error():
    with pytest.raises(ValueError):
        plan_target_group([g("K", ("K",))], [], detach=True)
