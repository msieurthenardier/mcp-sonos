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
# Live-coordinator control: no-session path (Leg 1, Flight 2)
# ---------------------------------------------------------------------------

def test_next_track_no_session_invokes_coord_next():
    """next_track with no session calls coord.next() and returns live track info."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_NOSESS001")
    speaker._track = {
        "uri": "http://cdn.example.com/track1.mp3",
        "title": "Track One",
        "artist": "Artist A",
        "album": "Album X",
        "position": "0:00:05",
        "duration": "0:03:00",
        "playlist_position": "1",
    }
    speaker._transport = {"current_transport_state": "PLAYING"}
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    result = mgr.next_track("Kitchen")

    assert speaker.next_call_count == 1, "coord.next() must be invoked"
    assert result.get("engine") == "native_queue"
    assert result.get("artist") == "Artist A"
    assert result.get("album") == "Album X"
    assert "speaker" in result
    assert "controllable" not in result


def test_previous_track_no_session_invokes_coord_previous():
    """previous_track with no session calls coord.previous() and returns live track info."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_NOSESS002")
    speaker._track = {
        "uri": "http://cdn.example.com/track0.mp3",
        "title": "Track Zero",
        "artist": "Artist B",
        "album": "Album Y",
        "position": "0:00:02",
        "duration": "0:04:00",
        "playlist_position": "0",
    }
    speaker._transport = {"current_transport_state": "PLAYING"}
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    result = mgr.previous_track("Kitchen")

    assert speaker.previous_call_count == 1, "coord.previous() must be invoked"
    assert result.get("engine") == "native_queue"
    assert result.get("artist") == "Artist B"
    assert result.get("album") == "Album Y"
    assert "speaker" in result
    assert "controllable" not in result


def test_stop_no_session_calls_coord_stop_and_does_not_clear_queue():
    """stop with no session calls coord.stop(); queue is left intact."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_NOSESS003")
    # Pre-populate a queue to verify it's not cleared.
    # The fake _queue is just a list, so any items work.
    speaker._queue = ["item1", "item2"]
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    result = mgr.stop("Kitchen")

    assert speaker.stop_call_count == 1, "coord.stop() must be invoked"
    assert result.get("stopped") is True
    assert result.get("engine") == "native_queue"
    assert "speaker" in result
    # Queue must not be cleared.
    assert len(speaker._queue) == 2, "stop must not clear the native queue"


def test_status_no_session_returns_live_state():
    """status with no session reads live transport/track state from the coordinator."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_NOSESS004")
    speaker._transport = {"current_transport_state": "PLAYING"}
    speaker._track = {
        "uri": "http://cdn.example.com/song.mp3",
        "title": "My Song",
        "artist": "Cool Band",
        "album": "Best Album",
        "position": "0:01:30",
        "duration": "0:04:20",
        "playlist_position": "2",
    }
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    result = mgr.status("Kitchen")

    assert result.get("engine") == "native_queue"
    assert result.get("state") == "PLAYING"
    assert result.get("artist") == "Cool Band"
    assert result.get("album") == "Best Album"
    assert result.get("position") == "0:01:30"
    assert result.get("duration") == "0:04:20"
    assert result.get("uri") == "http://cdn.example.com/song.mp3"
    assert result.get("playlist_position") == "2"
    assert "speaker" in result


def test_status_no_session_stopped_returns_idle():
    """status with no session returns idle dict when transport is STOPPED."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_NOSESS005")
    # Default state: STOPPED, empty uri
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    result = mgr.status("Kitchen")

    assert result.get("running") is False
    assert result.get("engine") == "native_queue"
    assert "speaker" in result


def test_next_track_no_session_swallows_soco_error():
    """next_track swallows SoCo errors and returns a sensible dict."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_NOSESS006")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    # Patch next() to raise.
    def bad_next():
        raise RuntimeError("SoCo UPnP error: end of queue")
    speaker.next = bad_next  # type: ignore

    result = mgr.next_track("Kitchen")

    # Must not raise; returns a dict with engine key.
    assert result.get("engine") == "native_queue"
    assert "speaker" in result


def test_worker_session_path_unchanged_for_next():
    """Worker-session path: next_track signals skip_event, not coord.next()."""
    import mcp_sonos.playlists as playlists_mod

    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_SESS001")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    # Start a worker session via a TTS (MCP-hosted) playlist.
    mgr.create("worker_pl")
    mgr.add_many("worker_pl", [{"url": _MCP_URL, "title": "TTS"}])
    old_interval = playlists_mod.POLL_INTERVAL
    playlists_mod.POLL_INTERVAL = 0.01
    try:
        mgr.play("Kitchen", "worker_pl")
        assert speaker.uid in mgr._sessions

        result = mgr.next_track("Kitchen")

        # Must use worker signaling, not coord.next().
        assert result.get("signaled") == "next"
        assert result.get("engine") == "worker"
        assert speaker.next_call_count == 0, "coord.next() must NOT be called on worker path"
    finally:
        playlists_mod.POLL_INTERVAL = old_interval
        try:
            mgr.stop("Kitchen")
        except Exception:
            pass


def test_worker_session_path_unchanged_for_previous():
    """Worker-session path: previous_track signals back_event, not coord.previous(), and returns engine:'worker'."""
    import mcp_sonos.playlists as playlists_mod

    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_SESS002")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    # Start a worker session via a TTS (MCP-hosted) playlist.
    mgr.create("worker_prev_pl")
    mgr.add_many("worker_prev_pl", [{"url": _MCP_URL, "title": "TTS"}])
    old_interval = playlists_mod.POLL_INTERVAL
    playlists_mod.POLL_INTERVAL = 0.01
    try:
        mgr.play("Kitchen", "worker_prev_pl")
        assert speaker.uid in mgr._sessions

        result = mgr.previous_track("Kitchen")

        # Must use worker signaling (back_event), not coord.previous().
        assert result.get("signaled") == "previous"
        assert result.get("engine") == "worker"
        assert speaker.previous_call_count == 0, "coord.previous() must NOT be called on worker path"
    finally:
        playlists_mod.POLL_INTERVAL = old_interval
        try:
            mgr.stop("Kitchen")
        except Exception:
            pass


def test_worker_session_stop_returns_engine_worker():
    """Worker-session path: stop signals stop_event and returns engine:'worker'."""
    import mcp_sonos.playlists as playlists_mod

    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_SESS003")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    # Start a worker session via a TTS (MCP-hosted) playlist.
    mgr.create("worker_stop_pl")
    mgr.add_many("worker_stop_pl", [{"url": _MCP_URL, "title": "TTS"}])
    old_interval = playlists_mod.POLL_INTERVAL
    playlists_mod.POLL_INTERVAL = 0.01
    try:
        mgr.play("Kitchen", "worker_stop_pl")
        assert speaker.uid in mgr._sessions

        result = mgr.stop("Kitchen")

        # Must signal stop and return engine:'worker'; also stops the coordinator.
        assert result.get("stopped") is True
        assert result.get("engine") == "worker"
    finally:
        playlists_mod.POLL_INTERVAL = old_interval


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


# ---------------------------------------------------------------------------
# Leg 2: play_mode-before-play_from_queue ordering invariant
# ---------------------------------------------------------------------------

def test_play_mode_set_before_play_from_queue():
    """play_mode must be set BEFORE play_from_queue is called.

    Swapping the order would be a real bug: Sonos applies the play mode
    to whatever is currently in the queue *at the moment play_from_queue
    runs*, so setting play_mode after would mean playback starts in the
    wrong mode and only takes effect on the next track.
    """
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_ORD001")
    mgr = _make_manager(speaker, _HOST_IP, _AUDIO_PORT)

    _external_playlist(mgr, "ordering_pl", [
        {"url": "http://cdn.example.com/t1.mp3", "title": "T1"},
        {"url": "http://cdn.example.com/t2.mp3", "title": "T2"},
    ])

    mgr.play("Kitchen", "ordering_pl")

    # Both tokens must be present.
    assert "play_mode" in speaker.call_log, "play_mode was never set"
    assert "play_from_queue" in speaker.call_log, "play_from_queue was never called"

    pm_idx = speaker.call_log.index("play_mode")
    pfq_idx = speaker.call_log.index("play_from_queue")
    assert pm_idx < pfq_idx, (
        f"Ordering invariant violated: play_mode (pos {pm_idx}) must precede "
        f"play_from_queue (pos {pfq_idx}) in the call log {speaker.call_log!r}"
    )


# ---------------------------------------------------------------------------
# Leg 2: SoCoSlaveException retry flushes the speakers cache
# ---------------------------------------------------------------------------

def test_slave_exception_retry_flushes_cache_and_succeeds():
    """On SoCoSlaveException, invalidate_speakers_cache is called before re-resolving.

    The retry must:
    1. Call invalidate_speakers_cache() exactly once.
    2. Re-resolve the coordinator (a second speaker is returned the second time).
    3. Call play_from_queue on the fresh coordinator; the whole play() succeeds.
    """
    from soco.exceptions import SoCoSlaveException

    stale_coord = SoCoFake(player_name="Kitchen", uid="RINCON_STALE001")
    fresh_coord = SoCoFake(player_name="Kitchen", uid="RINCON_FRESH001")

    # play() itself calls _resolve_coordinator once to get the speaker, then
    # _play_via_queue calls it a second time to get the coordinator.  Both of
    # those initial calls must return stale_coord so the coordinator handed to
    # _play_from_queue_with_stale_coord_retry is stale.  The third call (the
    # retry inside the exception handler) must return fresh_coord.
    resolve_calls: list[str] = []

    def resolve(name: str) -> tuple:
        resolve_calls.append(name)
        if len(resolve_calls) <= 2:
            return stale_coord, stale_coord
        return fresh_coord, fresh_coord

    # stale_coord.play_from_queue raises SoCoSlaveException on its first call.
    stale_coord.play_from_queue_raise = SoCoSlaveException("not the coordinator")

    # Pre-populate stale_coord queue so add_multiple_to_queue records items there.
    # (The queue path clears + loads into whatever coord is returned first.)
    # We need both fakes to have queue support; stale_coord does the queue ops,
    # fresh_coord only gets play_from_queue.

    invalidate_calls: list[int] = []

    def spy_invalidate() -> None:
        invalidate_calls.append(1)

    mgr = PlaylistManager(
        resolve_coordinator=resolve,
        host_ip=_HOST_IP,
        audio_port=_AUDIO_PORT,
        invalidate_speakers_cache=spy_invalidate,
    )

    _external_playlist(mgr, "retry_pl", [
        {"url": "http://cdn.example.com/r1.mp3", "title": "R1"},
    ])

    result = mgr.play("Kitchen", "retry_pl")

    # Play succeeded.
    assert result["engine"] == "native_queue"
    assert result["started"] is True

    # invalidate_speakers_cache was called exactly once during the retry.
    assert len(invalidate_calls) == 1, (
        f"Expected invalidate_speakers_cache called once, got {len(invalidate_calls)}"
    )

    # Re-resolution happened (resolve called more than once: initial + retry).
    assert len(resolve_calls) >= 2, (
        f"Expected coordinator re-resolved on retry, got {len(resolve_calls)} resolve calls"
    )

    # The fresh coordinator's play_from_queue succeeded (it's in PLAYING state).
    assert fresh_coord._transport["current_transport_state"] == "PLAYING"
