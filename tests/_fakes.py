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
    _track: dict = field(default_factory=lambda: {"uri": "", "title": ""})
    _volume: int = 40
    _mute: bool = False

    def __post_init__(self) -> None:
        self.group = FakeGroup(coordinator=self, members=[self])

    def is_visible(self) -> bool:
        return True

    def get_current_transport_info(self) -> dict:
        return dict(self._transport)

    def get_current_track_info(self) -> dict:
        return dict(self._track)

    def play_uri(self, uri: str, title: Optional[str] = None, force_radio: bool = False) -> None:
        self._track = {"uri": uri, "title": title or ""}
        self._transport = {"current_transport_state": "PLAYING"}

    def pause(self) -> None:
        self._transport = {"current_transport_state": "PAUSED_PLAYBACK"}

    def stop(self) -> None:
        self._transport = {"current_transport_state": "STOPPED"}

    def next(self) -> None:
        pass

    def previous(self) -> None:
        pass

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
        pass
