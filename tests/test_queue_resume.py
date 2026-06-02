"""Tests for the queue-aware snapshot→clip→resume mechanism (Leg 4).

Covers:
- say() single-speaker resumes the queue after the announcement.
- play_url() resumes the queue and blocks until clip-end.
- play_file() inherits resume behaviour via play_url().
- No-queue: resume is skipped (play_from_queue never called).
- Worker session active: resume is skipped.
- say("all"): _say_all path; resume not attempted.
- Resume failure: play_from_queue raises, exception is swallowed (no raise).

_wait_until_stopped is patched to return promptly in all tests so they run
without live hardware and without real time delays.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_sonos import controller as controller_mod
from mcp_sonos.controller import SonosController
from tests._fakes import SoCoFake


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_controller(monkeypatch, tmp_path):
    """Minimal SonosController with no real audio host, no Piper TTS, and
    no blocking waits.  _wait_until_stopped is patched to return immediately.
    """
    monkeypatch.setattr(controller_mod.AudioHost, "start", lambda self: None)

    def _fake_synthesize(text, cache_dir, **kwargs):
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        out = cache_dir / "fake_tts.wav"
        out.write_bytes(b"RIFFfake")
        return out

    monkeypatch.setattr(controller_mod, "synthesize", _fake_synthesize)
    monkeypatch.setattr(
        controller_mod.AudioHost,
        "url_for",
        lambda self, filename: f"http://test.invalid/{filename}",
    )
    monkeypatch.setattr(
        SonosController, "_wait_until_stopped", staticmethod(lambda *a, **kw: None)
    )
    return SonosController(cache_dir=tmp_path)


def _make_speaker_playing_queue(
    player_name: str = "Kitchen",
    uid: str = "RINCON_FAKE001",
    playlist_position: str = "2",
    play_mode: str = "NORMAL",
) -> SoCoFake:
    """Return a SoCoFake that appears to be actively playing from a queue."""
    s = SoCoFake(player_name=player_name, uid=uid)
    # Populate the native queue with two fake items.
    s._queue = ["item0", "item1", "item2"]
    # Set PLAYING transport state.
    s._transport = {"current_transport_state": "PLAYING"}
    # Set a meaningful track position inside the queue.
    s._track = {
        "uri": "http://example.com/track2.mp3",
        "title": "Track 2",
        "artist": "Artist",
        "album": "Album",
        "position": "0:01:30",
        "duration": "0:04:00",
        "playlist_position": playlist_position,
    }
    s._play_mode = play_mode
    return s


def _wire_speaker(monkeypatch, controller: SonosController, speaker: SoCoFake) -> None:
    """Monkeypatch the controller so `_resolve_coordinator` returns `speaker`."""
    import mcp_sonos.speakers as sp_mod

    monkeypatch.setattr(sp_mod, "discover_speakers", lambda: [speaker])
    monkeypatch.setattr(sp_mod, "resolve_name", lambda speakers, name: speaker)
    # Force cache expiry so the fake is returned.
    controller._speakers_ts = 0.0


# ---------------------------------------------------------------------------
# say() single-speaker resumes the queue
# ---------------------------------------------------------------------------


def test_say_resumes_queue_after_announcement(monkeypatch, stub_controller):
    """say() must snapshot, play the TTS clip, then resume the queue at the
    correct 0-based index, and restore play_mode."""
    speaker = _make_speaker_playing_queue(playlist_position="2", play_mode="NORMAL")
    _wire_speaker(monkeypatch, stub_controller, speaker)

    stub_controller.say("Kitchen", "hello")

    # play_from_queue should have been called with index = playlist_position - 1 = 1
    assert speaker.play_from_queue_last_index == 1, (
        f"expected resume at index 1, got {speaker.play_from_queue_last_index}"
    )
    # play_mode should have been restored to "NORMAL"
    assert speaker._play_mode == "NORMAL"
    # play_mode set should be recorded after play_from_queue in call_log
    pfq_pos = speaker.call_log.index("play_from_queue")
    pm_pos = speaker.call_log.index("play_mode")
    assert pfq_pos < pm_pos, "play_from_queue should be called before play_mode restore"


def test_say_resumes_with_non_default_play_mode(monkeypatch, stub_controller):
    """play_mode is saved and restored faithfully even when non-default."""
    speaker = _make_speaker_playing_queue(
        playlist_position="1", play_mode="SHUFFLE_NOREPEAT"
    )
    _wire_speaker(monkeypatch, stub_controller, speaker)

    stub_controller.say("Kitchen", "shuffle test")

    assert speaker.play_from_queue_last_index == 0
    assert speaker._play_mode == "SHUFFLE_NOREPEAT"


# ---------------------------------------------------------------------------
# play_url() resumes the queue and blocks
# ---------------------------------------------------------------------------


def test_play_url_resumes_queue_and_blocks(monkeypatch, stub_controller):
    """play_url() must block (wait_until_stopped called) and resume the queue."""
    speaker = _make_speaker_playing_queue(playlist_position="3")
    _wire_speaker(monkeypatch, stub_controller, speaker)

    wait_called = []
    real_wait = SonosController._wait_until_stopped

    def _capturing_wait(coord, timeout=None):
        wait_called.append(timeout)

    monkeypatch.setattr(SonosController, "_wait_until_stopped", staticmethod(_capturing_wait))

    stub_controller.play_url("Kitchen", "http://example.com/clip.mp3", title="Test clip")

    # Must have blocked.
    assert len(wait_called) == 1, "play_url must block via _wait_until_stopped"
    # Timeout must be the generous cap, not TTS_TIMEOUT_SECONDS (30).
    assert wait_called[0] == controller_mod.PLAY_URL_RESUME_TIMEOUT_SECONDS

    # Queue resumed at correct index.
    assert speaker.play_from_queue_last_index == 2  # position 3 → index 2


def test_play_url_returns_post_resume_state(monkeypatch, stub_controller):
    """play_url() must return _track_state(coord) AFTER resume (not the clip state)."""
    speaker = _make_speaker_playing_queue(playlist_position="1")
    _wire_speaker(monkeypatch, stub_controller, speaker)

    result = stub_controller.play_url("Kitchen", "http://example.com/clip.mp3")

    # After play_from_queue the fake sets transport to PLAYING.
    assert result["state"] == "PLAYING"
    # The return dict has the standard fields.
    assert "url" in result
    assert "played_on_coordinator" in result


# ---------------------------------------------------------------------------
# play_file() inherits resume via play_url()
# ---------------------------------------------------------------------------


def test_play_file_inherits_resume(monkeypatch, tmp_path, stub_controller):
    """play_file() calls play_url() internally; queue resume is inherited."""
    speaker = _make_speaker_playing_queue(playlist_position="1")
    _wire_speaker(monkeypatch, stub_controller, speaker)

    # Set up media root and a fake audio file.
    media_root = tmp_path / "media"
    media_root.mkdir()
    audio_file = media_root / "clip.mp3"
    audio_file.write_bytes(b"ID3fake")
    stub_controller.media_root = media_root

    # Stub audio staging to avoid real HTTP server.
    monkeypatch.setattr(
        controller_mod.AudioHost, "stage", lambda self, path: "http://test.invalid/staged.mp3"
    )

    stub_controller.play_file("Kitchen", str(audio_file), title="file clip")

    # Queue resume happened (inherits from play_url).
    assert speaker.play_from_queue_last_index == 0


# ---------------------------------------------------------------------------
# No-queue: resume skipped
# ---------------------------------------------------------------------------


def test_no_queue_skip_no_play_from_queue(monkeypatch, stub_controller):
    """When queue_size == 0, no snapshot is taken and play_from_queue is never called."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_FAKE001")
    # Empty queue (queue_size = 0), PLAYING, but playlist_position "1".
    speaker._transport = {"current_transport_state": "PLAYING"}
    speaker._track = {
        "uri": "http://example.com/stream",
        "title": "Stream",
        "artist": "",
        "album": "",
        "position": "0:00:00",
        "duration": "0:00:00",
        "playlist_position": "1",
    }
    _wire_speaker(monkeypatch, stub_controller, speaker)

    stub_controller.say("Kitchen", "no queue test")

    assert speaker.play_from_queue_last_index is None, "should not resume when queue is empty"


def test_not_playing_skip_no_play_from_queue(monkeypatch, stub_controller):
    """When transport is STOPPED (nothing playing), no resume attempted."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_FAKE001")
    speaker._queue = ["item0"]
    speaker._transport = {"current_transport_state": "STOPPED"}
    speaker._track = {
        "uri": "",
        "title": "",
        "artist": "",
        "album": "",
        "position": "0:00:00",
        "duration": "0:00:00",
        "playlist_position": "1",
    }
    _wire_speaker(monkeypatch, stub_controller, speaker)

    stub_controller.say("Kitchen", "stopped test")

    assert speaker.play_from_queue_last_index is None


def test_playlist_position_zero_skip_no_play_from_queue(monkeypatch, stub_controller):
    """When playlist_position is '0', int() == 0 → guard fails → no resume."""
    speaker = SoCoFake(player_name="Kitchen", uid="RINCON_FAKE001")
    speaker._queue = ["item0"]
    speaker._transport = {"current_transport_state": "PLAYING"}
    speaker._track = {
        "uri": "http://example.com/stream",
        "title": "Stream",
        "artist": "",
        "album": "",
        "position": "0:00:00",
        "duration": "0:00:00",
        "playlist_position": "0",
    }
    _wire_speaker(monkeypatch, stub_controller, speaker)

    stub_controller.say("Kitchen", "position zero test")

    assert speaker.play_from_queue_last_index is None


# ---------------------------------------------------------------------------
# Worker session active: resume skipped
# ---------------------------------------------------------------------------


def test_worker_session_active_skip_no_play_from_queue(monkeypatch, stub_controller):
    """When a worker session is active for the named speaker, resume is skipped."""
    import threading

    speaker = _make_speaker_playing_queue(playlist_position="1")
    _wire_speaker(monkeypatch, stub_controller, speaker)

    # Inject a live-looking worker session for the speaker's UID.
    from mcp_sonos.playlists import PlaybackSession

    sess = PlaybackSession(
        playlist_name="test",
        speaker_uid=speaker.uid,
        speaker_name=speaker.player_name,
    )
    # Give it a running (daemon) thread so has_active_session() returns True.
    t = threading.Thread(target=lambda: None, daemon=True)
    t.start()
    t.join()  # let it finish — but we'll mark thread alive another way

    # Instead, use a thread that blocks until stop_event.
    import threading as _t

    barrier = _t.Event()

    def _block():
        barrier.wait(timeout=5.0)

    live_thread = _t.Thread(target=_block, daemon=True)
    live_thread.start()
    sess.thread = live_thread
    stub_controller.playlists._sessions[speaker.uid] = sess

    try:
        stub_controller.say("Kitchen", "worker session test")
        assert speaker.play_from_queue_last_index is None, (
            "should not resume when worker session is active"
        )
    finally:
        barrier.set()
        live_thread.join(timeout=2.0)


# ---------------------------------------------------------------------------
# say("all") does NOT attempt resume
# ---------------------------------------------------------------------------


def test_say_all_no_resume(monkeypatch, stub_controller):
    """say('all') goes through _say_all which does not use _with_queue_resume."""
    speakers = [
        SoCoFake(player_name="Kitchen", uid="RINCON_FAKE001"),
        SoCoFake(player_name="Patio", uid="RINCON_FAKE002"),
    ]
    for s in speakers:
        # Looks like a playing queue
        s._queue = ["item0"]
        s._transport = {"current_transport_state": "PLAYING"}
        s._track = {
            "uri": "http://example.com/track.mp3",
            "title": "Track",
            "artist": "",
            "album": "",
            "position": "0:01:00",
            "duration": "0:04:00",
            "playlist_position": "1",
        }

    import mcp_sonos.speakers as sp_mod

    monkeypatch.setattr(sp_mod, "discover_speakers", lambda: speakers)
    monkeypatch.setattr(
        sp_mod, "resolve_name", lambda spks, name: next(s for s in spks if s.player_name == name)
    )
    stub_controller._speakers_ts = 0.0

    result = stub_controller.say("all", "test all")

    assert result["spoken_on"] == "all"
    # Neither speaker should have had play_from_queue called.
    for s in speakers:
        assert s.play_from_queue_last_index is None, (
            f"say('all') must not resume queue on {s.player_name}"
        )


# ---------------------------------------------------------------------------
# Resume failure: play_from_queue raises, exception swallowed
# ---------------------------------------------------------------------------


def test_resume_failure_is_swallowed(monkeypatch, stub_controller):
    """If play_from_queue raises during resume, the exception is swallowed
    and does not propagate to the caller."""
    speaker = _make_speaker_playing_queue(playlist_position="1")
    _wire_speaker(monkeypatch, stub_controller, speaker)

    # Inject a persistent failure (not one-shot: override play_from_queue entirely).
    def _always_raise(index=0):
        raise RuntimeError("coordinator unreachable")

    speaker.play_from_queue = _always_raise  # type: ignore[method-assign]

    # Must not raise.
    result = stub_controller.say("Kitchen", "swallow test")

    assert result["text"] == "swallow test"
