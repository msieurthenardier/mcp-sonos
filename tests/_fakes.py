"""Test fakes for Sonos hardware.

`SoCoFake` is a minimal stand-in for the SoCo speaker object, covering the
surface the controller and playlist worker actually call. It is intentionally
independent of the real SoCo library's object model — this module never
imports `soco.core` or constructs a real `SoCo`. The one exception (leg 4) is
`soco.exceptions.SoCoSlaveException`, imported lazily inside the fake's
coordinator-only methods: callers (`controller.py`, `playlists.py`) catch
that exact exception class, so a fake modeling `@only_on_master` behavior
must raise the same class, not a look-alike. Tests construct fakes directly
and inspect their explicit state rather than mock call counts.

Extend the surface only as tests demand it.
"""

from __future__ import annotations

from collections import deque
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

    `household` (leg 4, opt-in): when a `FakeHousehold.attach()` gives every
    attached speaker this SAME instance (mirroring the real one-per-household
    sharing), `clear_cache()` also invalidates that household's lag-mode
    view cache — mirroring `speaker.zone_group_state.clear_cache()` being
    the real trigger for `_sync_view`'s forced-fresh-poll. `None` (the
    default) when no household is involved, or a household with lag mode
    off — no behavior change from before this leg.
    """

    clear_cache_count: int = 0
    household: "FakeHousehold | None" = field(default=None, repr=False, compare=False)

    def clear_cache(self) -> None:
        self.clear_cache_count += 1
        if self.household is not None:
            self.household.clear_view_cache()


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
    # decorated with @only_on_master.  Backing flag for the `is_coordinator`
    # property below (mirrors real SoCo's `_is_coordinator`). Defaults True
    # so tests that go through those paths don't need to separately stub the
    # guard. Only consulted when unattached, or attached to a household with
    # lag mode off (see the property) — leg 4 is opt-in.
    _is_coordinator_flag: bool = field(default=True, repr=False)
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
    # Controls for error injection (leg 4): raised once (then cleared) by
    # clear_queue() / play_uri() respectively — same "raise once" contract as
    # play_from_queue_raise / seek_raise above, for testing the stale-coord
    # retry wired around each in playlists.py.
    clear_queue_raise: "Exception | None" = field(default=None)
    play_uri_raise: "Exception | None" = field(default=None)
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

    def _check_coordinator_only(self, name: str) -> None:
        """Model real SoCo's `@only_on_master` guard (leg 4): raise
        `SoCoSlaveException` if this speaker's OWN cached view says it isn't
        the coordinator. Opt-in — only enforced when attached to a
        `FakeHousehold` with lag mode on (`household.enable_lag()`); every
        other fake (unattached, or attached with lag off) keeps today's
        behavior of never raising here, exactly like before this leg.

        Reads `self.is_coordinator` (the property below), the same call
        real SoCo's `only_on_master` decorator makes — so this triggers the
        exact same lag-mode poll-through-self semantics.
        """
        if self.household is not None and self.household.lag_enabled and not self.is_coordinator:
            from soco.exceptions import SoCoSlaveException

            raise SoCoSlaveException(
                f'The method or property "{name}" can only be called/used '
                "on the coordinator in a group"
            )

    def play_uri(self, uri: str, title: Optional[str] = None, force_radio: bool = False) -> None:
        self._check_coordinator_only("play_uri")
        if self.play_uri_raise is not None:
            exc = self.play_uri_raise
            self.play_uri_raise = None
            raise exc
        # MERGE into _track rather than replacing it: preserves playlist_position,
        # artist, album, etc. so snapshot tests can read these fields after a
        # play_uri call (e.g. _with_queue_resume reads playlist_position from
        # get_current_track_info() which returns a copy of _track).
        self._track = {**self._track, "uri": uri, "title": title or ""}
        self._transport = {"current_transport_state": "PLAYING"}

    def pause(self) -> None:
        self._transport = {"current_transport_state": "PAUSED_PLAYBACK"}

    def stop(self) -> None:
        self._check_coordinator_only("stop")
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
    def is_coordinator(self) -> bool:
        """Mirrors real SoCo's `is_coordinator` property (`soco/core.py`):
        reading it triggers a poll — here, `household.cached_is_coordinator`,
        which is where the opt-in lag-mode caching model lives. Unattached,
        or attached with lag mode off: just the plain flag, same as every
        fake before this leg."""
        if self.household is not None and self.household.lag_enabled:
            return self.household.cached_is_coordinator(self.uid)
        return self._is_coordinator_flag

    @is_coordinator.setter
    def is_coordinator(self, value: bool) -> None:
        self._is_coordinator_flag = bool(value)

    @property
    def group(self) -> "FakeGroup":
        """Mirrors real SoCo's `group` property: reading it polls. In lag
        mode, builds the `FakeGroup` from the household's CACHED (possibly
        stale) view rather than ground truth — modeling a poll made through
        `self`, which may return another speaker's lagging snapshot (see
        `FakeHousehold.cached_coordinator_of`'s docstring). Unattached, or
        attached with lag mode off: the plain ground-truth attribute, same
        as every fake before this leg."""
        if self.household is not None and self.household.lag_enabled:
            coord_uid = self.household.cached_coordinator_of(self.uid)
            member_uids = self.household.cached_members_of(coord_uid)
            coord = self.household.speakers.get(coord_uid, self)
            members = [
                self.household.speakers[u] for u in member_uids if u in self.household.speakers
            ] or [self]
            return FakeGroup(coordinator=coord, members=members)
        return self._group_ground_truth

    @group.setter
    def group(self, value: "FakeGroup") -> None:
        self._group_ground_truth = value

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
        self._check_coordinator_only("clear_queue")
        if self.clear_queue_raise is not None:
            exc = self.clear_queue_raise
            self.clear_queue_raise = None
            raise exc
        self._queue.clear()

    def add_multiple_to_queue(self, items: list) -> None:
        """Append DIDL items to the fake queue. Returns None like real SoCo.

        NOT coordinator-only in real SoCo (verified in `soco/core.py` — no
        `@only_on_master`), so no `_check_coordinator_only` call here.
        """
        self._queue.extend(items)
        return None

    def play_from_queue(self, index: int = 0) -> None:
        """Simulate starting playback from queue position `index`.

        If `play_from_queue_raise` is set, raises that exception on the first
        call and clears the flag so subsequent calls succeed.
        """
        self._check_coordinator_only("play_from_queue")
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

    **Lag mode (leg 4, opt-in via `enable_lag()`)**: models SoCo's real
    per-household `ZoneGroupState` cache sitting on top of per-speaker,
    eventually-consistent views. Ground truth (`coordinator_of` above) is
    unaffected — it always reflects the CURRENT real topology, updated
    immediately by `do_join`/`do_unjoin`/`do_stop`, same as before this leg.
    Layered on top, when lag mode is on:

    - A single shared "cached view" (`_cached_view`, a `{uid: coordinator_uid}`
      snapshot) plus a `_cache_valid` flag — mirrors SoCo's one
      `ZoneGroupState` instance per household.
    - `clear_view_cache()` invalidates it — called by
      `FakeZoneGroupState.clear_cache()` when that instance is shared across
      the household's speakers (which `attach()` does below).
    - A poll THROUGH a given speaker (`_poll_through`) is what
      `SoCoFake.is_coordinator` / `.group` trigger when lag mode is on. If
      the cache is invalid, it's refreshed — from that speaker's queued
      stale override (`queue_stale_override`) if one is pending, else from
      ground truth — and marked valid. A poll through a DIFFERENT speaker
      while the cache is still valid is a cache HIT: it returns whatever
      view is already cached, even if that view is stale w.r.t. ground
      truth. This is the exact mechanism behind the leg 3 hardware bug: a
      poll through a lagging bystander can leave the whole household's
      cache holding a view where `c0` is still a follower.
    - `last_polled_uid` records which speaker's poll last actually
      refreshed the cache (not merely read it) — lets tests assert "the
      last poll came from c0."
    """

    speakers: dict[str, "SoCoFake"] = field(default_factory=dict)
    coordinator_of: dict[str, str] = field(default_factory=dict)
    stopped_groups: set[str] = field(default_factory=set)
    lag_enabled: bool = False
    last_polled_uid: "str | None" = None
    _cache_valid: bool = field(default=False, repr=False)
    _cached_view: dict[str, str] = field(default_factory=dict, repr=False)
    _stale_overrides: "dict[str, deque[dict[str, str]]]" = field(
        default_factory=dict, repr=False
    )
    _shared_zgs: FakeZoneGroupState = field(default_factory=FakeZoneGroupState, repr=False)

    def attach(self, *speakers: "SoCoFake") -> "FakeHousehold":
        for s in speakers:
            s.household = self
            # Share ONE FakeZoneGroupState across the household, mirroring
            # real SoCo's one-instance-per-household_id sharing. This is
            # what lets `s.zone_group_state.clear_cache()` (called from
            # `controller._clear_socos_zgs_cache`, deduped per household_id)
            # invalidate this household's lag-mode cache regardless of which
            # attached speaker happened to be first in the dedup loop.
            self._shared_zgs.household = self
            s.zone_group_state = self._shared_zgs
            self.speakers[s.uid] = s
            self.coordinator_of.setdefault(s.uid, s.uid)
        self._sync_groups()
        return self

    def enable_lag(self) -> "FakeHousehold":
        """Opt into per-speaker view-lag modeling. Existing tests that never
        call this keep today's eager, always-fresh, no-caching behavior."""
        self.lag_enabled = True
        return self

    def clear_view_cache(self) -> None:
        """Mirrors real SoCo's `ZoneGroupState.clear_cache()` — invalidates
        the shared cached view. The next poll-through-a-speaker refreshes
        it. A no-op effect-wise when lag mode is off (nothing ever reads
        `_cache_valid` in that case)."""
        self._cache_valid = False

    def queue_stale_override(self, uid: str, snapshot: dict[str, str]) -> None:
        """Queue a stale `{uid: coordinator_uid}` snapshot to be served the
        NEXT time `uid`'s view is polled (instead of ground truth), models
        that speaker's own device not yet having caught up with a just-made
        topology change. FIFO per uid; a copy is stored so later mutating
        the caller's dict has no effect."""
        self._stale_overrides.setdefault(uid, deque()).append(dict(snapshot))

    def _poll_through(self, uid: str) -> None:
        """Model a real `GetZoneGroupState` call made TO speaker `uid`. A
        no-op (besides recording `last_polled_uid`) if the shared cache is
        still valid — exactly like real SoCo's 5s cache short-circuiting a
        repeat poll. Otherwise refreshes the shared cache from `uid`'s next
        queued stale override if one is pending, else from ground truth."""
        self.last_polled_uid = uid
        if self._cache_valid:
            return
        overrides = self._stale_overrides.get(uid)
        if overrides:
            self._cached_view = overrides.popleft()
        else:
            self._cached_view = dict(self.coordinator_of)
        self._cache_valid = True

    def cached_coordinator_of(self, uid: str) -> str:
        """Poll through `uid`, then answer from the (possibly now-stale,
        possibly another speaker's) cached view."""
        self._poll_through(uid)
        return self._cached_view.get(uid, uid)

    def cached_is_coordinator(self, uid: str) -> bool:
        return self.cached_coordinator_of(uid) == uid

    def cached_members_of(self, coordinator_uid: str) -> list[str]:
        """Read the CURRENTLY cached view's membership of `coordinator_uid`
        without triggering a new poll — call `cached_coordinator_of`/
        `_poll_through` first if a fresh-or-cached poll is needed."""
        return sorted(u for u, c in self._cached_view.items() if c == coordinator_uid)

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
