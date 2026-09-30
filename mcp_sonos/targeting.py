"""Pure, I/O-free target-set grouping planner.

This module computes *what to do* to reshape a Sonos household's group
topology so that a target set of speakers ends up playing together,
either exclusively (``detach=True``, the default) or merged with whatever
groups the targets were already in (``detach=False``). It never touches
SoCo, never sleeps, and never mutates anything — see `controller.py`'s
`_plan_targets` / `_execute_plan` for the I/O half.

Firmware grouping semantics this planner's algorithm is built on
(hardware-verified — see the flight's design decisions):

- ``join(other)`` moves only the speaker it is called on. Bringing a whole
  group along requires joining each of its members individually.
- A coordinator's ``unjoin()`` leaves its remaining followers grouped
  together, under a firmware-elected delegate (the "new coordinator" is
  not something a caller gets to choose).
- A follower's ``unjoin()`` leaves just that one speaker standalone; its
  former group is otherwise unaffected.
- ``join()`` on a speaker that currently coordinates other members is
  unreliable and must never be issued. Every speaker this planner adds to
  `TargetPlan.join` is guaranteed, by construction, to be standalone by
  the time the executor would issue that call (see
  `_check_join_invariant` below, which verifies this for every plan
  before it is returned).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class GroupInfo:
    """One group in a topology snapshot.

    ``member_uids`` always includes ``coordinator_uid`` — mirroring SoCo's
    own ``group.members``, which includes the coordinator.
    """

    coordinator_uid: str
    member_uids: tuple[str, ...]
    state: str | None  # the coordinator's transport state, e.g. "PLAYING"


@dataclass(frozen=True)
class TargetPlan:
    """The result of planning a target-set regroup. Carries no SoCo objects
    — everything is addressed by UID so this stays a pure data structure.
    """

    coordinator_uid: str
    stop: tuple[str, ...]
    unjoin: tuple[str, ...]
    join: tuple[str, ...]
    bystanders: tuple[str, ...]
    untouched_groups: tuple[tuple[str, ...], ...]
    fast_path: bool
    final_members: tuple[str, ...]


def _dedupe_preserve_order(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _check_join_invariant(topology: Sequence[GroupInfo], plan: TargetPlan) -> None:
    """Simulate `plan`'s mutations against `topology` and assert that no
    `join` ever targets a UID that, at that moment, still coordinates other
    members.

    This mirrors the firmware semantics documented in the module docstring:
    a coordinator's `unjoin()` delegates its remaining members to a new
    (arbitrarily-chosen) coordinator; a follower's `unjoin()` only removes
    itself. `stop` has no structural effect on membership. Raises
    AssertionError naming the offending UID if the invariant is violated —
    this should never happen for a correctly-constructed plan; it exists as
    a safety net the exhaustive planner tests exercise directly.
    """
    coord_of: dict[str, str] = {}
    members_of: dict[str, set[str]] = {}
    for g in topology:
        for uid in g.member_uids:
            coord_of[uid] = g.coordinator_uid
        members_of[g.coordinator_uid] = set(g.member_uids)

    def is_coordinating_others(uid: str) -> bool:
        members = members_of.get(uid)
        return bool(members) and len(members) > 1 and coord_of.get(uid) == uid

    def do_unjoin(uid: str) -> None:
        old_coord = coord_of.get(uid, uid)
        if old_coord == uid:
            # uid was a coordinator (of itself, at least): delegate any
            # remaining members to the first remaining one.
            remaining = sorted(m for m in members_of.get(uid, {uid}) if m != uid)
            members_of[uid] = {uid}
            coord_of[uid] = uid
            if remaining:
                delegate = remaining[0]
                members_of[delegate] = set(remaining)
                for m in remaining:
                    coord_of[m] = delegate
        else:
            members_of.setdefault(old_coord, set()).discard(uid)
            members_of[uid] = {uid}
            coord_of[uid] = uid

    def do_join(uid: str, target_coord: str) -> None:
        if is_coordinating_others(uid):
            raise AssertionError(
                f"targeting planner invariant violated: join() would be issued "
                f"on {uid!r}, which still coordinates other members"
            )
        old_coord = coord_of.get(uid, uid)
        if old_coord == uid:
            members_of.pop(uid, None)
        else:
            members_of.setdefault(old_coord, set()).discard(uid)
        coord_of[uid] = target_coord
        members_of.setdefault(target_coord, set()).add(uid)

    for uid in plan.unjoin:
        do_unjoin(uid)
    for uid in plan.join:
        do_join(uid, plan.coordinator_uid)


def plan_target_group(
    topology: Sequence[GroupInfo], targets: Sequence[str], *, detach: bool
) -> TargetPlan:
    """Compute a `TargetPlan` for regrouping `targets` under one coordinator.

    `topology` must describe every group in the household (not just the
    ones touching `targets`) — the planner needs the full picture to find
    the exact-match fast path and to report `untouched_groups`. `targets`
    is an ordered list of speaker UIDs; duplicates are removed, keeping the
    first occurrence, exactly as the controller's own name-to-UID
    resolution does (this planner re-dedupes defensively so it is safe to
    call directly, e.g. from tests).
    """
    targets = _dedupe_preserve_order(targets)
    if not targets:
        raise ValueError("plan_target_group requires at least one target")
    targets_set = set(targets)

    affected = [g for g in topology if targets_set & set(g.member_uids)]
    affected_coord_uids = {g.coordinator_uid for g in affected}
    untouched = tuple(
        g.member_uids for g in topology if g.coordinator_uid not in affected_coord_uids
    )

    if detach:
        plan = _plan_detach(topology, targets, targets_set, affected)
    else:
        plan = _plan_no_detach(targets, affected)

    plan = TargetPlan(
        coordinator_uid=plan.coordinator_uid,
        stop=plan.stop,
        unjoin=plan.unjoin,
        join=plan.join,
        bystanders=plan.bystanders,
        untouched_groups=untouched,
        fast_path=plan.fast_path,
        final_members=plan.final_members,
    )
    _check_join_invariant(topology, plan)
    return plan


def _plan_detach(
    topology: Sequence[GroupInfo],
    targets: list[str],
    targets_set: set[str],
    affected: list[GroupInfo],
) -> TargetPlan:
    # 1. Exact-match fast path: some existing group's membership already
    # equals the target set exactly. No topology change; keep its
    # coordinator. Idempotent by construction.
    for g in topology:
        if set(g.member_uids) == targets_set:
            return TargetPlan(
                coordinator_uid=g.coordinator_uid,
                stop=(),
                unjoin=(),
                join=(),
                bystanders=(),
                untouched_groups=(),
                fast_path=True,
                final_members=tuple(targets),
            )

    # Bystanders: non-target members of any affected group.
    bystanders = _dedupe_preserve_order(
        [uid for g in affected for uid in g.member_uids if uid not in targets_set]
    )

    # Stop-first: every affected group containing at least one bystander.
    stop = [g.coordinator_uid for g in affected if any(u not in targets_set for u in g.member_uids)]

    # 2. Coordinator choice, in precedence order.
    coord_of_group: dict[str, GroupInfo] = {g.coordinator_uid: g for g in topology}
    c0: str | None = None
    for t in targets:
        g = coord_of_group.get(t)
        if g is not None and g.state == "PLAYING":
            c0 = t
            break
    if c0 is None:
        for t in targets:
            g = coord_of_group.get(t)
            if g is not None and set(g.member_uids) <= targets_set:
                c0 = t
                break
    if c0 is None:
        c0 = targets[0]

    group_of_member: dict[str, GroupInfo] = {
        uid: g for g in topology for uid in g.member_uids
    }
    c0_group = group_of_member[c0]
    c0_is_coordinator = c0_group.coordinator_uid == c0
    c0_original_members = set(c0_group.member_uids)

    # 3. Separate, in order.
    unjoin: list[str] = []
    if not c0_is_coordinator:
        unjoin.append(c0)
    if c0_is_coordinator:
        for uid in c0_group.member_uids:
            if uid != c0 and uid not in targets_set:
                unjoin.append(uid)

    join: list[str] = []
    for t in targets:
        if t == c0:
            continue
        if t in c0_original_members:
            continue
        unjoin.append(t)
        join.append(t)

    return TargetPlan(
        coordinator_uid=c0,
        stop=tuple(stop),
        unjoin=tuple(unjoin),
        join=tuple(join),
        bystanders=tuple(bystanders),
        untouched_groups=(),
        fast_path=False,
        final_members=tuple(targets),
    )


def _plan_no_detach(targets: list[str], affected: list[GroupInfo]) -> TargetPlan:
    if len(affected) <= 1:
        g = affected[0]
        return TargetPlan(
            coordinator_uid=g.coordinator_uid,
            stop=(),
            unjoin=(),
            join=(),
            bystanders=(),
            untouched_groups=(),
            fast_path=True,
            final_members=tuple(g.member_uids),
        )

    group_of_member: dict[str, GroupInfo] = {
        uid: g for g in affected for uid in g.member_uids
    }
    c0_group = group_of_member[targets[0]]
    c0 = c0_group.coordinator_uid

    join: list[str] = []
    final_members: list[str] = list(c0_group.member_uids)
    for g in affected:
        if g.coordinator_uid == c0:
            continue
        followers = [uid for uid in g.member_uids if uid != g.coordinator_uid]
        join.extend(followers)
        join.append(g.coordinator_uid)
        final_members.extend(g.member_uids)

    return TargetPlan(
        coordinator_uid=c0,
        stop=(),
        unjoin=(),
        join=tuple(join),
        bystanders=(),
        untouched_groups=(),
        fast_path=False,
        final_members=tuple(final_members),
    )
