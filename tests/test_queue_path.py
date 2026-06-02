"""Hardware-free tests for Leg 3: native Sonos queue playback path.

Tests cover:
- All-external playlist → queue calls (item count, titles, play_from_queue)
- Mixed playlist (any MCP-hosted URL) → worker engine fallback
- Worker-active → queue-play eviction handoff (old session stopped+joined
  BEFORE queue load; DD-D)
- Shuffle → play_mode == "SHUFFLE_NOREPEAT" (DD-B)
- playlist_next / playlist_previous → graceful dict when no session (no raise)
"""

from __future__ import annotations

import threading
import time

import pytest

from mcp_sonos.playlists import PlaylistManager, QUEUE_PARENT_ID
from tests._fakes import SoCoFake


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HOST_IP = "192.168.1.50"
_AUDIO_PORT = 8080
_MCP_URL = f"http://{_HOST_IP}:{_AUDIO_PORT}/tts/abc123.wav"


def _make_manager(speaker: SoCoFake, host_ip: str = "", audio_port: int = 0) -> PlaylistManager:
    """Build a PlaylistManager with an injected resolver for `speaker`."""

    def resolve(name: str) -> tuple:
        return speaker, speaker

    return PlaylistManager(
        resolve_coordinator=resolve,
        host_ip=host_ip,
        audio_port=audio_port,
    )


def _external_playlist(manager: PlaylistManager, name: str, items: list[dict]) -> None:
    """Create a named playlist and bulk-add items (dicts with 'url'/'title')."""
    manager.create(name)
    manager.add_many(name, items)


# ---------------------------------------------------------------------------
# Q1 / Q2: all-external → queue calls
# ---------------------------------------------------------------------------

def test_all_external_enqueues_all_tracks():
    """All-external playlist: add_multiple_to_queue called with all items."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_EXT001")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    tracks = [
        {"url": "http://cdn.example.com/track1.mp3", "title": "Track One"},
        {"url": "http://cdn.example.com/track2.mp3", "title": "Track Two"},
        {"url": "http://cdn.example.com/track3.mp3", "title": "Track Three"},
    ]
    _external_playlist(mgr, "ext_mix", tracks)

    result = mgr.play("Kitchen", "ext_mix")

    assert result["engine"] == "native_queue"
    assert result["total_items"] == 3
    assert speaker.queue_size == 3


def test_all_external_play_from_queue_called():
    """All-external: play_from_queue is called (speaker is in PLAYING state)."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_EXT002")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    _external_playlist(mgr, "ext_q", [
        {"url": "http://cdn.example.com/a.mp3", "title": "A"},
        {"url": "http://cdn.example.com/b.mp3", "title": "B"},
    ])

    mgr.play("Kitchen", "ext_q")

    assert speaker._transport["current_transport_state"] == "PLAYING"


def test_all_external_didl_titles():
    """Q2: DIDL items carry the playlist item's title; fallback to filename."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_EXT003")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    _external_playlist(mgr, "title_test", [
        {"url": "http://cdn.example.com/song.mp3", "title": "My Song"},
        {"url": "http://cdn.example.com/another.mp3"},  # no title → filename fallback
    ])

    mgr.play("Kitchen", "title_test")

    q = speaker._queue
    assert len(q) == 2
    assert q[0].title == "My Song"
    # Fallback: filename from URL
    assert q[1].title == "another.mp3"


def test_all_external_didl_parent_id_not_minus_one():
    """DD-E: parent_id must NOT be '-1'."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_EXT004")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    _external_playlist(mgr, "parent_test", [
        {"url": "http://cdn.example.com/track.mp3", "title": "T"},
    ])

    mgr.play("Kitchen", "parent_test")

    q = speaker._queue
    assert q[0].parent_id != "-1"
    assert q[0].parent_id == QUEUE_PARENT_ID


def test_all_external_didl_item_ids():
    """DD-E: item_id = f'track-{i}'."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_EXT005")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    _external_playlist(mgr, "id_test", [
        {"url": "http://cdn.example.com/t0.mp3", "title": "T0"},
        {"url": "http://cdn.example.com/t1.mp3", "title": "T1"},
    ])

    mgr.play("Kitchen", "id_test")

    q = speaker._queue
    assert q[0].item_id == "track-0"
    assert q[1].item_id == "track-1"


def test_all_external_didl_resource_protocol_info():
    """DD-E: DidlResource protocol_info == 'http-get:*:audio/mpeg:*'."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_EXT006")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    _external_playlist(mgr, "proto_test", [
        {"url": "http://cdn.example.com/track.mp3", "title": "T"},
    ])

    mgr.play("Kitchen", "proto_test")

    resource = speaker._queue[0].resources[0]
    assert resource.protocol_info == "http-get:*:audio/mpeg:*"


def test_all_external_start_index_respected():
    """start_index maps directly to queue position."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_EXT007")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    _external_playlist(mgr, "idx_test", [
        {"url": "http://cdn.example.com/t0.mp3", "title": "T0"},
        {"url": "http://cdn.example.com/t1.mp3", "title": "T1"},
        {"url": "http://cdn.example.com/t2.mp3", "title": "T2"},
    ])

    result = mgr.play("Kitchen", "idx_test", start_index=1)

    assert result["start_index"] == 1
    assert result["first_item"]["url"] == "http://cdn.example.com/t1.mp3"


# ---------------------------------------------------------------------------
# Q3: shuffle → SHUFFLE_NOREPEAT
# ---------------------------------------------------------------------------

def test_shuffle_sets_shuffle_norepeat():
    """DD-B: shuffle=True → play_mode == 'SHUFFLE_NOREPEAT'."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_SHUF001")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    _external_playlist(mgr, "shuffle_pl", [
        {"url": "http://cdn.example.com/s1.mp3", "title": "S1"},
        {"url": "http://cdn.example.com/s2.mp3", "title": "S2"},
    ])

    mgr.play("Kitchen", "shuffle_pl", shuffle=True)

    # SHUFFLE_NOREPEAT intentional — one pass, like worker path (DD-B)
    assert speaker.play_mode == "SHUFFLE_NOREPEAT"


def test_no_shuffle_sets_normal():
    """DD-B: shuffle=False → play_mode == 'NORMAL'."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_SHUF002")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    _external_playlist(mgr, "normal_pl", [
        {"url": "http://cdn.example.com/n1.mp3", "title": "N1"},
    ])

    mgr.play("Kitchen", "normal_pl", shuffle=False)

    assert speaker.play_mode == "NORMAL"


# ---------------------------------------------------------------------------
# Q5: mixed playlist (MCP-hosted URL) → worker engine
# ---------------------------------------------------------------------------

def test_mixed_playlist_routes_to_worker():
    """Any MCP-hosted URL in the playlist → worker engine (not native queue)."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_MIX001")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    mgr.create("mixed_pl")
    mgr.add_many("mixed_pl", [
        {"url": "http://cdn.example.com/external.mp3", "title": "Ext"},
        {"url": _MCP_URL, "title": "TTS clip"},
    ])

    result = mgr.play("Kitchen", "mixed_pl")

    # Worker engine takes over; queue must remain empty (no add_multiple_to_queue)
    assert result.get("engine") == "worker"
    assert speaker.queue_size == 0


def test_all_mcp_hosted_routes_to_worker():
    """Playlist entirely of MCP-hosted URLs → worker engine."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_MIX002")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    mgr.create("tts_only")
    mgr.add_many("tts_only", [
        {"url": f"http://{_HOST_IP}:{_AUDIO_PORT}/tts/clip1.wav", "title": "C1"},
        {"url": f"http://{_HOST_IP}:{_AUDIO_PORT}/tts/clip2.wav", "title": "C2"},
    ])

    result = mgr.play("Kitchen", "tts_only")

    assert result.get("engine") == "worker"
    assert speaker.queue_size == 0


def test_no_host_config_routes_to_worker():
    """When host_ip/port are not configured (empty), falls back to worker engine.

    Without audio host coordinates we can't classify URLs, so the conservative
    fallback is the worker engine (unchanged pre-Leg-3 behavior).
    """
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_NOHOST001")
    # No host_ip / audio_port → classification not possible → worker fallback
    mgr = _make_manager(speaker, host_ip="", audio_port=0)

    mgr.create("no_host_pl")
    mgr.add_many("no_host_pl", [
        {"url": "http://cdn.example.com/track.mp3", "title": "T"},
    ])

    result = mgr.play("Kitchen", "no_host_pl")

    assert result.get("engine") == "worker"
    assert speaker.queue_size == 0


# ---------------------------------------------------------------------------
# Q6-partial: worker-active → queue-play eviction handoff (DD-D)
# ---------------------------------------------------------------------------

def test_queue_play_evicts_worker_before_queue_load():
    """DD-D: existing worker session stopped+joined BEFORE queue is cleared/loaded.

    We verify the invariant by patching coord.clear_queue to assert the worker
    thread has already exited at the moment the queue is cleared.
    """
    import mcp_sonos.playlists as playlists_mod

    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_EVICT001")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    # Start a worker session first (MCP-hosted → worker engine).
    mgr.create("worker_pl")
    mgr.add_many("worker_pl", [
        {"url": _MCP_URL, "title": "TTS"},
    ])
    # Patch POLL_INTERVAL to keep worker from spinning during test.
    old_interval = playlists_mod.POLL_INTERVAL
    playlists_mod.POLL_INTERVAL = 0.01
    try:
        mgr.play("Kitchen", "worker_pl")  # worker engine: session in _sessions
        assert speaker.uid in mgr._sessions
        worker_session = mgr._sessions[speaker.uid]
        worker_thread = worker_session.thread

        # Now start an all-external playlist — should evict the worker.
        mgr.create("queue_pl")
        mgr.add_many("queue_pl", [
            {"url": "http://cdn.example.com/a.mp3", "title": "A"},
            {"url": "http://cdn.example.com/b.mp3", "title": "B"},
        ])

        # Track when clear_queue is invoked relative to worker thread state.
        clear_queue_worker_alive = []
        original_clear = speaker.clear_queue

        def patched_clear():
            clear_queue_worker_alive.append(worker_thread.is_alive())
            original_clear()

        speaker.clear_queue = patched_clear

        result = mgr.play("Kitchen", "queue_pl")

        assert result["engine"] == "native_queue"
        # At the time clear_queue was called, the worker thread must be dead.
        assert len(clear_queue_worker_alive) >= 1, "clear_queue was never called"
        assert not clear_queue_worker_alive[0], (
            "DD-D violated: clear_queue was called while the worker thread was still alive"
        )
    finally:
        playlists_mod.POLL_INTERVAL = old_interval
        # Belt-and-suspenders cleanup.
        try:
            mgr.stop("Kitchen")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Graceful no-session: playlist_next / playlist_previous (scope boundary)
# ---------------------------------------------------------------------------

def test_playlist_next_no_session_returns_graceful_dict():
    """playlist_next returns graceful dict instead of raising when no session."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_NOSESS001")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    result = mgr.next_track("Kitchen")

    assert result.get("controllable") is False
    assert result.get("engine") == "native_queue"
    assert "speaker" in result


def test_playlist_previous_no_session_returns_graceful_dict():
    """playlist_previous returns graceful dict instead of raising when no session."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_NOSESS002")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    result = mgr.previous_track("Kitchen")

    assert result.get("controllable") is False
    assert result.get("engine") == "native_queue"
    assert "speaker" in result


def test_playlist_stop_no_session_does_not_raise():
    """playlist_stop is already graceful (no change needed); confirm no regression."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_NOSESS003")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    result = mgr.stop("Kitchen")

    assert result.get("running") is False


# ---------------------------------------------------------------------------
# URL encoding: no double-encoding of already-percent-encoded URLs
# ---------------------------------------------------------------------------

def test_already_percent_encoded_url_not_double_encoded():
    """URL already containing '%20' must not become '%2520' in the DIDL URI."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_ENC001")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    url_with_existing_escape = "http://cdn.example.com/my%20track.mp3"
    _external_playlist(mgr, "enc_test", [
        {"url": url_with_existing_escape, "title": "Encoded Track"},
    ])

    mgr.play("Kitchen", "enc_test")

    resource_uri = speaker._queue[0].resources[0].uri
    assert "%2520" not in resource_uri, (
        "double-encoding detected: '%20' was re-encoded to '%2520'"
    )
    assert "%20" in resource_uri, "existing '%20' escape should be preserved"


def test_literal_space_in_url_gets_encoded():
    """URL with a literal space must have the space encoded to '%20' in the DIDL URI."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_ENC002")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    url_with_literal_space = "http://cdn.example.com/my track.mp3"
    _external_playlist(mgr, "space_enc_test", [
        {"url": url_with_literal_space, "title": "Space Track"},
    ])

    mgr.play("Kitchen", "space_enc_test")

    resource_uri = speaker._queue[0].resources[0].uri
    assert " " not in resource_uri, "literal space must be percent-encoded"
    assert "%20" in resource_uri, "literal space must be encoded as '%20'"
