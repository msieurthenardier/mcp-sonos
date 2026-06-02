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
class SoCoFake:
    player_name: str = "Kitchen"
    uid: str = "RINCON_FAKE000000000"
    ip_address: str = "192.168.1.50"
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
        # Fake doesn't model multi-group state — just refresh group-of-one.
        self.group = FakeGroup(coordinator=self, members=[self])

    def join(self, other: "SoCoFake") -> None:
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
