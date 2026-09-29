"""Test fakes for Sonos hardware.

`SoCoFake` is a minimal stand-in for the SoCo speaker object, covering the
surface the controller and playlist worker actually call. It is intentionally
independent of the real SoCo library — this module never imports it. Tests
construct fakes directly and inspect their explicit state rather than mock
call counts.

Extend the surface only as tests demand it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FakeGroup:
    coordinator: "SoCoFake"
    members: list["SoCoFake"] = field(default_factory=list)


@dataclass
class FakeZoneGroupState:
    """Stand-in for SoCo's per-household `ZoneGroupState`.

    Real SoCo shares one `ZoneGroupState` instance across every speaker in
    a household (`soco/core.py:SoCo.zone_group_state`); this fake mirrors
    that by having `SoCoFake` instances constructed with the same
    `household_id` share one `FakeZoneGroupState` via `_builders.py` /
    test setup, when a test cares about that. `clear_cache()` just counts
    calls so tests can assert which forced-refresh paths cleared it.
    """

    clear_cache_count: int = 0

    def clear_cache(self) -> None:
        self.clear_cache_count += 1


@dataclass
class SoCoFake:
    player_name: str = "Kitchen"
    uid: str = "RINCON_FAKE000000000"
    ip_address: str = "192.168.1.50"
    household_id: str = "Sonos_FAKE_HOUSEHOLD"
    zone_group_state: FakeZoneGroupState = field(default_factory=FakeZoneGroupState)
    _transport: dict = field(default_factory=lambda: {"current_transport_state": "STOPPED"})
    _track: dict = field(
        default_factory=lambda: {
            "uri": "",
            "title": "",
            "artist": "",
            "album": "",
            "position": "0:00:00",
            "duration": "0:00:00",
            "playlist_position": "0",
        }
    )
    _volume: int = 40
    _mute: bool = False
    _queue: list = field(default_factory=list)
    _play_mode: str = "NORMAL"
    # Real SoCo's add_multiple_to_queue / play_from_queue / clear_queue are
    # decorated with @only_on_master.  Mark the fake as a coordinator so tests
    # that go through those paths don't need to separately stub the guard.
    is_coordinator: bool = True
    # Call-recording counters for transport commands.
    next_call_count: int = field(default=0)
    previous_call_count: int = field(default=0)
    stop_call_count: int = field(default=0)
    # Ordered call log for sequencing assertions (e.g. play_mode before play_from_queue).
    # Each entry is a string token such as "play_mode" or "play_from_queue".
    call_log: list = field(default_factory=list)
    # Controls for error injection: if play_from_queue_raise is set, play_from_queue
    # raises that exception on the first call only, then succeeds subsequently.
    play_from_queue_raise: "Exception | None" = field(default=None)
    # Last index passed to play_from_queue — lets tests assert the resume index.
    play_from_queue_last_index: "int | None" = field(default=None)
    # Controls for error injection: if seek_raise is set, seek raises that exception.
    seek_raise: "Exception | None" = field(default=None)
    # Last timestamp passed to seek — lets tests assert the seek position.
    seek_last: "str | None" = field(default=None)
    # Opt-in link to a shared FakeHousehold (see below). When set, join()/
    # unjoin()/stop() delegate to it for hardware-accurate multi-group
    # semantics. When None (the default), the simplistic self-contained
    # behavior below is unchanged — no existing test is affected.
    household: "FakeHousehold | None" = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.group = FakeGroup(coordinator=self, members=[self])

    def is_visible(self) -> bool:
        return True

    def get_current_transport_info(self) -> dict:
        return dict(self._transport)

    def get_current_track_info(self) -> dict:
        return dict(self._track)

    def play_uri(self, uri: str, title: Optional[str] = None, force_radio: bool = False) -> None:
        # MERGE into _track rather than replacing it: preserves playlist_position,
        # artist, album, etc. so snapshot tests can read these fields after a
        # play_uri call (e.g. _with_queue_resume reads playlist_position from
        # get_current_track_info() which returns a copy of _track).
        self._track = {**self._track, "uri": uri, "title": title or ""}
        self._transport = {"current_transport_state": "PLAYING"}

    def pause(self) -> None:
        self._transport = {"current_transport_state": "PAUSED_PLAYBACK"}

    def stop(self) -> None:
        self.stop_call_count += 1
        self._transport = {"current_transport_state": "STOPPED"}
        if self.household is not None:
            self.household.do_stop(self.uid)

    def next(self) -> None:
        self.next_call_count += 1

    def previous(self) -> None:
        self.previous_call_count += 1

    @property
    def volume(self) -> int:
        return self._volume

    @volume.setter
    def volume(self, v: int) -> None:
        self._volume = int(v)

    @property
    def mute(self) -> bool:
        return self._mute

    @mute.setter
    def mute(self, v: bool) -> None:
        self._mute = bool(v)

    def partymode(self) -> None:
        # No-op for tests that exercise the _say_all path; group modelling
        # is not needed for queue-resume assertions.
        pass

    def unjoin(self) -> None:
        if self.household is not None:
            self.household.do_unjoin(self.uid)
            return
        # Fake doesn't model multi-group state — just refresh group-of-one.
        self.group = FakeGroup(coordinator=self, members=[self])

    def join(self, other: "SoCoFake") -> None:
        if self.household is not None:
            self.household.do_join(self.uid, other.uid)
            return
        # Simplistic: this becomes a member of other's group.
        self.group = FakeGroup(coordinator=other, members=[other, self])
        other.group = FakeGroup(coordinator=other, members=[other, self])

    # add_to_queue / clear_queue: minimal no-ops; tests that need queue state
    # can extend this fake or use a MagicMock for the specific call.
    def add_to_queue(self, uri_or_track) -> int:
        return 1

    def clear_queue(self) -> None:
        self._queue.clear()

    def add_multiple_to_queue(self, items: list) -> None:
        """Append DIDL items to the fake queue. Returns None like real SoCo."""
        self._queue.extend(items)
        return None

    def play_from_queue(self, index: int = 0) -> None:
        """Simulate starting playback from queue position `index`.

        If `play_from_queue_raise` is set, raises that exception on the first
        call and clears the flag so subsequent calls succeed.
        """
        self.call_log.append("play_from_queue")
        self.play_from_queue_last_index = index
        if self.play_from_queue_raise is not None:
            exc = self.play_from_queue_raise
            self.play_from_queue_raise = None
            raise exc
        self._transport = {"current_transport_state": "PLAYING"}
        if 0 <= index < len(self._queue):
            item = self._queue[index]
            # DidlMusicTrack exposes .title; fall back gracefully in tests.
            title = getattr(item, "title", "")
            self._track = {"uri": "", "title": title}

    def seek(self, timestamp: str) -> None:
        """Simulate seeking to `timestamp` (e.g. "0:01:30").

        Records the last seek value so tests can assert it.  If `seek_raise`
        is set, raises that exception instead (simulates a host that rejects
        HTTP range requests).
        """
        self.seek_last = timestamp
        if self.seek_raise is not None:
            exc = self.seek_raise
            self.seek_raise = None
            raise exc

    @property
    def queue_size(self) -> int:
        return len(self._queue)

    @property
    def play_mode(self) -> str:
        return self._play_mode

    @play_mode.setter
    def play_mode(self, value: str) -> None:
        self._play_mode = value
        self.call_log.append("play_mode")


@dataclass
class FakeHousehold:
    """Shared group-membership model for a set of attached `SoCoFake`s.

    Models the hardware-verified firmware semantics from Flight 2's design
    decisions (see `mcp_sonos/targeting.py`'s module docstring):

    - `join(other)` moves only the speaker it's called on.
    - A coordinator's `unjoin()` delegates its remaining members to the
      first remaining member (sorted by UID, for determinism) — they do
      NOT each become standalone.
    - A follower's `unjoin()` leaves just that one speaker standalone; its
      former group is otherwise untouched.
    - `join()` on a speaker that currently coordinates other members
      **raises `AssertionError`** — this is what makes tests built on a
      `FakeHousehold` enforce the executor invariant "never join() a
      speaker that coordinates others."
    - `stop()` marks that speaker's whole group as stopped (tracked so
      tests can assert on it); joining/unjoining doesn't implicitly
      change stopped-ness.

    Opt-in: a `SoCoFake` only consults its household when `.household` is
    set, via `attach()`. Unattached fakes are untouched by any of this —
    they keep today's simplistic, self-contained `join`/`unjoin`, so no
    existing test's behavior changes.

    Every group is recomputed from scratch (`_sync_groups`) after each
    mutation, so no attached fake's `.group` is ever left stale.
    """

    speakers: dict[str, "SoCoFake"] = field(default_factory=dict)
    coordinator_of: dict[str, str] = field(default_factory=dict)
    stopped_groups: set[str] = field(default_factory=set)

    def attach(self, *speakers: "SoCoFake") -> "FakeHousehold":
        for s in speakers:
            s.household = self
            self.speakers[s.uid] = s
            self.coordinator_of.setdefault(s.uid, s.uid)
        self._sync_groups()
        return self

    def group(self, coordinator: "SoCoFake", members: list["SoCoFake"]) -> "FakeHousehold":
        """Test-setup helper: force `coordinator` + `members` into one group
        directly, bypassing join/unjoin (for building initial topology)."""
        for m in [coordinator, *members]:
            self.coordinator_of[m.uid] = coordinator.uid
        self._sync_groups()
        return self

    def members_of(self, coordinator_uid: str) -> list[str]:
        return sorted(uid for uid, c in self.coordinator_of.items() if c == coordinator_uid)

    def is_coordinator(self, uid: str) -> bool:
        return self.coordinator_of.get(uid, uid) == uid

    def do_join(self, uid: str, other_uid: str) -> None:
        if self.is_coordinator(uid) and len(self.members_of(uid)) > 1:
            raise AssertionError(
                f"FakeHousehold: join() issued on {uid!r}, which still "
                "coordinates other members. The executor must peel a "
                "coordinator's followers off (or unjoin it) before ever "
                "joining it elsewhere."
            )
        self.coordinator_of[uid] = other_uid
        self._sync_groups()

    def do_unjoin(self, uid: str) -> None:
        if self.is_coordinator(uid):
            remaining = [m for m in self.members_of(uid) if m != uid]
            self.coordinator_of[uid] = uid
            if remaining:
                delegate = sorted(remaining)[0]
                for m in remaining:
                    self.coordinator_of[m] = delegate
        else:
            self.coordinator_of[uid] = uid
        self._sync_groups()

    def do_stop(self, coordinator_uid: str) -> None:
        # Whichever group the stopped speaker currently coordinates (or, if
        # it's a follower, its own group's coordinator) is marked stopped.
        actual_coord = self.coordinator_of.get(coordinator_uid, coordinator_uid)
        self.stopped_groups.add(actual_coord)

    def _sync_groups(self) -> None:
        by_coord: dict[str, list["SoCoFake"]] = {}
        for uid, coord_uid in self.coordinator_of.items():
            by_coord.setdefault(coord_uid, []).append(self.speakers[uid])
        for coord_uid, members in by_coord.items():
            coord = self.speakers[coord_uid]
            grp = FakeGroup(coordinator=coord, members=sorted(members, key=lambda s: s.uid))
            for m in members:
                m.group = grp
