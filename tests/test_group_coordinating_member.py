"""Regression test for squawk 0006: `SonosController.group` used to call
`m.join(coord)` on a member that currently coordinates other speakers.
Firmware delegates coordination instead of moving such a speaker, so the
join silently did nothing useful even though the call returned.

The fix: before joining a member, re-read its own view fresh and, if it
still coordinates other speakers, `unjoin()` it first so the join lands on
a standalone speaker (see `mcp_sonos/controller.py:SonosController.group`).

Uses `tests/_fakes.py::FakeHousehold`, whose `do_join` raises
`AssertionError` if ever issued on a still-coordinating speaker — so this
test fails loudly (via that assertion) if the fix regresses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_sonos import controller as controller_mod
from mcp_sonos.controller import SonosController

from tests._fakes import FakeHousehold, SoCoFake


@pytest.fixture
def stub_controller(monkeypatch, tmp_path):
    """SonosController with no real audio host, and no real sleeping in
    `group`'s topology-settle pauses."""
    monkeypatch.setattr(controller_mod.AudioHost, "start", lambda self: None)
    monkeypatch.setattr(controller_mod.time, "sleep", lambda *_: None)
    return SonosController(cache_dir=tmp_path)


def _wire_household(monkeypatch, controller: SonosController, speakers: list[SoCoFake]) -> None:
    monkeypatch.setattr(controller_mod.sp, "discover_speakers", lambda: list(speakers))
    controller._speakers_ts = 0.0


def test_group_unjoins_member_that_coordinates_others_before_joining(
    monkeypatch, stub_controller
):
    """`group("Kitchen", ["Fireplace Room"])` where Fireplace Room already
    coordinates two followers (F1, F2). Without the fix, `join()` would be
    issued directly on Fireplace Room while it still coordinates F1/F2 —
    `FakeHousehold.do_join` raises `AssertionError` for exactly that. With
    the fix, Fireplace Room is unjoined (peeled off) first, so the join
    lands on a standalone speaker and succeeds; its former followers stay
    grouped together under a firmware-elected delegate."""
    household = FakeHousehold()
    kitchen = SoCoFake(player_name="Kitchen", uid="K")
    fireplace = SoCoFake(player_name="Fireplace Room", uid="FP")
    f1 = SoCoFake(player_name="F1", uid="F1")
    f2 = SoCoFake(player_name="F2", uid="F2")
    household.attach(kitchen, fireplace, f1, f2)
    household.group(fireplace, [f1, f2])  # Fireplace Room coordinates F1, F2
    _wire_household(monkeypatch, stub_controller, [kitchen, fireplace, f1, f2])

    result = stub_controller.group("Kitchen", ["Fireplace Room"])

    assert result["coordinator"] == "Kitchen"
    assert result["joined"] == ["Fireplace Room"]
    assert set(result["group_members"]) == {"Kitchen", "Fireplace Room"}

    # Fireplace Room actually ended up in Kitchen's group (ground truth).
    assert {m.uid for m in kitchen.group.members} == {kitchen.uid, fireplace.uid}
    assert kitchen.group.coordinator.uid == kitchen.uid

    # F1/F2 stayed grouped together under a delegate (one of themselves),
    # per the firmware-verified unjoin-delegation semantics — they were
    # NOT each scattered to standalone.
    assert f1.group.coordinator.uid == f2.group.coordinator.uid
    delegate_uid = f1.group.coordinator.uid
    assert delegate_uid in {f1.uid, f2.uid}
    assert {m.uid for m in f1.group.members} == {f1.uid, f2.uid}
