"""Tests for `PlaylistManager._session_for` — the control-tool session-lookup
fallback added in flight 2, leg 2.

Background: `playlist_play` may now be called with a target *set*
(`speakers`), and the worker/native-queue session it starts is keyed by the
chosen coordinator's (`c0`'s) UID. A control-tool call (`playlist_next`,
`previous`, `stop`, `status`) may legitimately name any member of the group
`playlist_play` formed, not just `c0`. `_session_for(speaker, coord)` looks
up the session by the named speaker's UID first, falling back to the
session keyed on that speaker's CURRENT coordinator's UID.

Uses `tests._fakes.FakeHousehold` for hardware-accurate group modelling
(`speaker.group.coordinator` reflects live topology) and a resolver that
mirrors `SonosController._resolve_coordinator`'s shape:
`resolve(name) -> (named_speaker, named_speaker.group.coordinator)`.
"""

from __future__ import annotations

import pytest

from mcp_sonos import playlists as playlists_mod
from mcp_sonos.playlists import PlaylistManager

from tests._builders import _MCP_URL
from tests._fakes import FakeHousehold, SoCoFake


def _household_resolver(speakers_by_name: dict[str, SoCoFake]):
    def resolve(name: str):
        speaker = speakers_by_name[name]
        return speaker, speaker.group.coordinator

    return resolve


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch):
    # Keep the worker's inner wait loop from dominating test wall-clock —
    # same pattern as test_playlists_takeover.py.
    monkeypatch.setattr(playlists_mod, "POLL_INTERVAL", 0.01)


def _start_worker_session(mgr: PlaylistManager, speaker_name: str, playlist_name: str = "fallback_pl"):
    """Create a one-item MCP-hosted playlist and start it, waiting for the
    worker to begin polling (so the session is guaranteed live for the
    fallback lookup that follows)."""
    mgr.create(playlist_name)
    mgr.add_many(playlist_name, [{"url": _MCP_URL, "title": "TTS"}])
    mgr.play(speaker_name, playlist_name)
    assert mgr._iteration_event.wait(timeout=2.0), "worker never started polling"


@pytest.fixture
def household_manager():
    """Kitchen (c0) coordinating Patio; Bedroom stands alone in an
    unrelated group. Returns (manager, speakers_by_name)."""
    household = FakeHousehold()
    k = SoCoFake(player_name="Kitchen", uid="K")
    p = SoCoFake(player_name="Patio", uid="P")
    bedroom = SoCoFake(player_name="Bedroom", uid="BR")
    household.attach(k, p, bedroom)
    household.group(k, [p])  # Bedroom stays standalone — unrelated group.
    speakers_by_name = {"Kitchen": k, "Patio": p, "Bedroom": bedroom}
    mgr = PlaylistManager(resolve_coordinator=_household_resolver(speakers_by_name))
    return mgr, speakers_by_name


def test_stop_via_follower_signals_worker_session(household_manager):
    mgr, speakers_by_name = household_manager
    _start_worker_session(mgr, "Kitchen")
    k = speakers_by_name["Kitchen"]
    session = mgr._sessions.get(k.uid)
    assert session is not None

    result = mgr.stop("Patio")  # Patio is a follower of Kitchen (c0)

    assert result["engine"] == "worker"
    assert session.stop_event.is_set()
    mgr.stop("Kitchen")  # belt-and-suspenders cleanup


def test_status_via_follower_reaches_worker_session(household_manager):
    mgr, speakers_by_name = household_manager
    _start_worker_session(mgr, "Kitchen")

    result = mgr.status("Patio")

    assert result["engine"] == "worker"
    assert result["playlist"] == "fallback_pl"
    mgr.stop("Kitchen")


def test_next_track_via_follower_signals_worker_session(household_manager):
    mgr, speakers_by_name = household_manager
    _start_worker_session(mgr, "Kitchen")
    k = speakers_by_name["Kitchen"]
    session = mgr._sessions.get(k.uid)
    assert session is not None

    result = mgr.next_track("Patio")

    assert result["engine"] == "worker"
    assert result["signaled"] == "next"
    assert session.skip_event.is_set()
    mgr.stop("Kitchen")


def test_previous_track_via_follower_signals_worker_session(household_manager):
    mgr, speakers_by_name = household_manager
    _start_worker_session(mgr, "Kitchen")
    k = speakers_by_name["Kitchen"]
    session = mgr._sessions.get(k.uid)
    assert session is not None

    result = mgr.previous_track("Patio")

    assert result["engine"] == "worker"
    assert result["signaled"] == "previous"
    assert session.back_event.is_set()
    mgr.stop("Kitchen")


def test_unrelated_group_speaker_gets_no_session_path(household_manager):
    mgr, speakers_by_name = household_manager
    _start_worker_session(mgr, "Kitchen")
    k = speakers_by_name["Kitchen"]
    session = mgr._sessions.get(k.uid)
    assert session is not None

    # Bedroom is standalone — not a member of Kitchen's group — so the
    # fallback must NOT find Kitchen's session.
    result = mgr.stop("Bedroom")

    assert result["engine"] == "native_queue"
    assert not session.stop_event.is_set()
    mgr.stop("Kitchen")  # cleanup the still-live session
