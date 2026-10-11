"""Voice items in playlists (sortie 01, leg 1): add paths, routing, live
append (identity scheduling), shuffled status, previous, and the server tools.

Worker-thread tests use a gated fake: every `play_uri` is "held" (reports
PLAYING) until the test releases it, so nothing depends on timing. All waits
are bounded and every test that starts a worker stops it in a `finally`.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from mcp_sonos import controller as controller_mod
from mcp_sonos import playlists as playlists_mod
from mcp_sonos.controller import SonosController
from mcp_sonos.playlists import (
    MAX_VOICE_TEXT_CHARS,
    PlaylistError,
    PlaylistItem,
    PlaylistManager,
)
from mcp_sonos.server import register_tools

from tests._fakes import SoCoFake

HOST = "192.168.1.50"
PORT = 8000
VOICE_URL = f"http://{HOST}:{PORT}/tts_x.wav"


def ext(n) -> str:
    return f"http://ext.example/{n}.mp3"


def u(n) -> str:
    # MCP-hosted track URL: keeps track-only worker tests on the worker engine
    # (an all-external playlist would route to the native queue).
    return f"http://{HOST}:{PORT}/t{n}.mp3"


# ---------------------------------------------------------------------------
# Fakes / helpers
# ---------------------------------------------------------------------------


class GatedFake(SoCoFake):
    """Holds each played URI as PLAYING until `release()`; optional gate
    inside `stop()` (set `stop_gate` to an Event to block)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.cv = threading.Condition()
        self.released = False
        self.stop_gate: threading.Event | None = None
        self.stop_entered = threading.Event()

    def play_uri(self, uri, title=None, force_radio=False):
        super().play_uri(uri, title)
        with self.cv:
            self.released = False
            self.cv.notify_all()

    def get_current_transport_info(self):
        if self.released or not self.play_uri_log:
            return {"current_transport_state": "STOPPED"}
        return {"current_transport_state": "PLAYING"}

    def stop(self):
        self.stop_entered.set()
        if self.stop_gate is not None:
            self.stop_gate.wait(5.0)
        self.stop_call_count += 1
        self.released = True

    def release(self):
        self.released = True

    def wait_plays(self, n: int, timeout: float = 2.0) -> bool:
        with self.cv:
            return self.cv.wait_for(lambda: len(self.play_uri_log) >= n, timeout)

    def uris(self) -> list[str]:
        return [x[0] for x in self.play_uri_log]


def make(speaker=None, *, synth=True, host=True):
    speaker = speaker or GatedFake(player_name="Kitchen", uid="RINCON_T1")
    calls: list[str] = []

    def synthesize(text: str) -> str:
        calls.append(text)
        return VOICE_URL

    mgr = PlaylistManager(
        resolve_coordinator=lambda name: (speaker, speaker),
        host_ip=HOST if host else "",
        audio_port=PORT if host else 0,
        synthesize_voice=synthesize if synth else None,
    )
    mgr.synth_calls = calls
    return mgr, speaker


@pytest.fixture(autouse=True)
def fast_poll(monkeypatch):
    monkeypatch.setattr(playlists_mod, "POLL_INTERVAL", 0.005)


def finish(mgr, speaker):
    """Release everything and stop the worker; assert the thread is gone."""
    if isinstance(speaker, GatedFake):
        if speaker.stop_gate is not None:
            speaker.stop_gate.set()
        speaker.release()
    sessions = list(mgr._sessions.values())
    for s in sessions:
        s.stop_event.set()
    for s in sessions:
        if s.thread:
            s.thread.join(2.0)
            assert not s.thread.is_alive()


def wait_gone(mgr, speaker, timeout=2.0):
    deadline = time.monotonic() + timeout
    while speaker.uid in mgr._sessions and time.monotonic() < deadline:
        time.sleep(0.005)
    return speaker.uid not in mgr._sessions


# ---------------------------------------------------------------------------
# AC1-AC4: item kind and add paths (no worker)
# ---------------------------------------------------------------------------


def test_to_dict_kinds():
    assert PlaylistItem(url="http://a/x.mp3", title="T").to_dict() == {
        "kind": "track", "url": "http://a/x.mp3", "title": "T",
    }
    d = PlaylistItem(url=VOICE_URL, title="DJ: hi", text="hi").to_dict()
    assert d == {"kind": "voice", "url": VOICE_URL, "title": "DJ: hi", "text": "hi"}


def test_add_voice_default_and_custom_title_and_strip():
    mgr, _ = make()
    mgr.create("p")
    long_text = "x" * 60
    mgr.add("p", text=f"  {long_text}  ")
    mgr.add("p", text="  hello  ", title="Intro")
    a, b = mgr.get("p").items
    assert a.text == long_text and a.title == "DJ: " + "x" * 40 and a.url == VOICE_URL
    assert b.text == "hello" and b.title == "Intro" and b.kind == "voice"
    assert mgr.synth_calls == [long_text, "hello"]


def test_add_many_mixed_preserves_order():
    mgr, _ = make()
    mgr.create("p")
    mgr.add_many("p", [{"url": u(1)}, {"text": "hi"}, {"url": u(2), "title": "Two"}])
    items = mgr.get("p").items
    assert [i.kind for i in items] == ["track", "voice", "track"]
    assert items[1].url == VOICE_URL and items[2].title == "Two"


def test_none_missing_whitespace_count_as_absent():
    mgr, _ = make()
    mgr.create("p")
    mgr.add_many("p", [{"url": None, "text": "a"}, {"url": "   ", "text": "b"},
                       {"url": u(1), "text": None}, {"url": u(2), "text": "  "}])
    assert [i.kind for i in mgr.get("p").items] == ["voice", "voice", "track", "track"]
    mgr.add("p", None, text="c")
    assert mgr.get("p").items[-1].kind == "voice"


@pytest.mark.parametrize(
    "item,needle",
    [
        ({"url": 5}, "items[1]"),
        ({"text": 5}, "items[1]"),
        ({"url": u(1), "title": 7}, "items[1]"),
        ({"url": u(1), "text": "hi"}, "exactly one"),
        ({}, "items[1]"),
        ({"url": None, "text": None}, "items[1]"),
        ({"text": "x" * (MAX_VOICE_TEXT_CHARS + 1)}, "max is"),
        ({"url": "ftp://x/y"}, "items[1]"),
    ],
)
def test_add_many_invalid_items(item, needle):
    mgr, _ = make()
    mgr.create("p")
    with pytest.raises(PlaylistError, match="items\\[1\\]|exactly one|max is") as ei:
        mgr.add_many("p", [{"text": "ok"}, item])
    assert needle in str(ei.value)
    # Validation precedes synthesis: nothing synthesized, nothing appended.
    assert mgr.synth_calls == []
    assert mgr.get("p").items == []


def test_add_both_neither_and_cap_boundary():
    mgr, _ = make()
    mgr.create("p")
    with pytest.raises(PlaylistError):
        mgr.add("p", u(1), text="hi")
    with pytest.raises(PlaylistError):
        mgr.add("p")
    mgr.add("p", text="y" * MAX_VOICE_TEXT_CHARS)  # exactly at the cap is fine
    with pytest.raises(PlaylistError, match="max is"):
        mgr.add("p", text="y" * (MAX_VOICE_TEXT_CHARS + 1))
    assert len(mgr.get("p").items) == 1


def test_no_synthesizer_is_a_clear_error():
    mgr, _ = make(synth=False)
    mgr.create("p")
    with pytest.raises(PlaylistError, match="unavailable"):
        mgr.add("p", text="hi")
    mgr.add("p", u(1))  # tracks still work
    assert len(mgr.get("p").items) == 1


def test_synthesis_failure_wrapped_and_playlist_unchanged():
    speaker = GatedFake()
    boom = RuntimeError("piper exploded")

    def synth(text):
        if text == "bad":
            raise boom
        return VOICE_URL

    mgr = PlaylistManager(lambda n: (speaker, speaker), synthesize_voice=synth)
    mgr.create("p")
    mgr.add("p", u(0))
    with pytest.raises(PlaylistError) as ei:
        mgr.add_many("p", [{"url": u(1)}, {"text": "good"}, {"text": "bad"}])
    assert ei.value.__cause__ is boom
    assert [i.url for i in mgr.get("p").items] == [u(0)]


def test_synthesis_runs_outside_lock():
    speaker = GatedFake()
    seen = []

    def synth(text):
        seen.append(mgr._lock.locked())
        return VOICE_URL

    mgr = PlaylistManager(lambda n: (speaker, speaker), synthesize_voice=synth)
    mgr.create("p")
    mgr.add("p", text="a")
    mgr.add_many("p", [{"text": "b"}])
    assert seen == [False, False]


def test_unknown_playlist_fails_before_synthesis():
    mgr, _ = make()
    with pytest.raises(PlaylistError):
        mgr.add("nope", text="hi")
    assert mgr.synth_calls == []


# ---------------------------------------------------------------------------
# AC5: routing
# ---------------------------------------------------------------------------


def test_mixed_playlist_routes_to_worker_and_tracks_only_to_queue():
    mgr, sp = make()
    mgr.create("mixed")
    mgr.add_many("mixed", [{"url": ext(1)}, {"text": "hi"}, {"url": ext(2)}])
    mgr.create("ext")
    mgr.add_many("ext", [{"url": ext(1)}, {"url": ext(2)}])
    try:
        r = mgr.play("Kitchen", "mixed")
        assert r["engine"] == "worker"
        assert r["first_item"]["kind"] == "track" and r["total_items"] == 3
        assert sp.wait_plays(1)
        finish(mgr, sp)
        r2 = mgr.play("Kitchen", "ext")
        assert r2["engine"] == "native_queue"
        assert r2["first_item"]["kind"] == "track"
    finally:
        finish(mgr, sp)


def test_controller_synthesizer_wiring(monkeypatch, tmp_path):
    monkeypatch.setattr(controller_mod.AudioHost, "start", lambda self: None)
    seen = {}

    def fake_synth(text, cache_dir, **kw):
        seen["args"] = (text, Path(cache_dir))
        return Path(cache_dir) / "tts_abc.wav"

    monkeypatch.setattr(controller_mod, "synthesize", fake_synth)
    monkeypatch.setattr(
        controller_mod.AudioHost, "url_for", lambda self, name: f"http://h.invalid/{name}"
    )
    ctl = SonosController(cache_dir=tmp_path)
    ctl.playlists.create("p")
    ctl.playlists.add("p", text="hello there")
    item = ctl.playlists.get("p").items[0]
    assert item.url == "http://h.invalid/tts_abc.wav"
    assert seen["args"] == ("hello there", Path(ctl.cache_dir))


# ---------------------------------------------------------------------------
# AC6: worker plays voice in order
# ---------------------------------------------------------------------------


def test_worker_plays_items_in_order_voice_not_takeover(caplog):
    mgr, sp = make()
    mgr.create("p")
    mgr.add_many("p", [{"url": u(0)}, {"text": "hi"}, {"url": u(2)}])
    try:
        with caplog.at_level(logging.INFO):
            mgr.play("Kitchen", "p")
            for n in (1, 2, 3):
                assert sp.wait_plays(n)
                sp.release()
            assert wait_gone(mgr, sp)
        assert sp.uris() == [u(0), VOICE_URL, u(2)]
        assert "preempted" not in caplog.text
        assert [t for _, t in sp.play_uri_log][1].startswith("DJ: hi")
    finally:
        finish(mgr, sp)


# ---------------------------------------------------------------------------
# AC7: live append (identity scheduling)
# ---------------------------------------------------------------------------


def test_append_while_on_last_item_plays_once():
    mgr, sp = make()
    mgr.create("p")
    mgr.add_many("p", [{"url": u(0)}, {"url": u(1)}])
    try:
        mgr.play("Kitchen", "p")
        assert sp.wait_plays(1)
        sp.release()
        assert sp.wait_plays(2)  # held on last item
        mgr.add("p", text="outro")
        sp.release()
        assert sp.wait_plays(3)
        sp.release()
        assert wait_gone(mgr, sp)
        assert sp.uris() == [u(0), u(1), VOICE_URL]
    finally:
        finish(mgr, sp)


def test_skip_on_last_racing_append_plays_appended_once():
    mgr, sp = make()
    mgr.create("p")
    mgr.add("p", u(0))
    try:
        mgr.play("Kitchen", "p")
        assert sp.wait_plays(1)
        sp.stop_gate = threading.Event()
        mgr.next_track("Kitchen")
        assert sp.stop_entered.wait(2.0)
        mgr.add("p", u(9))  # appended while the skip is mid-flight
        sp.stop_gate.set()
        assert sp.wait_plays(2)
        sp.release()
        assert wait_gone(mgr, sp)
        assert sp.uris() == [u(0), u(9)]
    finally:
        finish(mgr, sp)


def test_remove_then_add_while_held_plays_new_exactly_once():
    mgr, sp = make()
    mgr.create("p")
    mgr.add_many("p", [{"url": u(0)}, {"url": u(1)}, {"url": u(2)}])
    try:
        mgr.play("Kitchen", "p")
        assert sp.wait_plays(1)
        mgr.remove("p", 2)
        mgr.add("p", u(9))
        sp.release()
        assert sp.wait_plays(2)
        sp.release()
        assert sp.wait_plays(3)
        sp.release()
        assert wait_gone(mgr, sp)
        assert sp.uris() == [u(0), u(1), u(9)]
    finally:
        finish(mgr, sp)


def test_remove_middle_item_is_skipped_and_worker_exits_cleanly(caplog):
    mgr, sp = make()
    mgr.create("p")
    mgr.add_many("p", [{"url": u(0)}, {"url": u(1)}, {"url": u(2)}])
    try:
        with caplog.at_level(logging.ERROR):
            mgr.play("Kitchen", "p")
            assert sp.wait_plays(1)
            thread = mgr._sessions[sp.uid].thread
            mgr.remove("p", 1)
            sp.release()
            assert sp.wait_plays(2)
            sp.release()
            assert wait_gone(mgr, sp)
            thread.join(2.0)
        assert not thread.is_alive()
        assert sp.uris() == [u(0), u(2)]
        assert "crashed" not in caplog.text
    finally:
        finish(mgr, sp)


def test_add_after_worker_exit_is_inert():
    mgr, sp = make()
    mgr.create("p")
    mgr.add("p", u(0))
    try:
        mgr.play("Kitchen", "p")
        assert sp.wait_plays(1)
        thread = mgr._sessions[sp.uid].thread
        sp.release()
        assert wait_gone(mgr, sp)
        thread.join(2.0)
        assert not thread.is_alive()
        mgr.add("p", text="late")
        assert not mgr.has_active_session(sp.uid)
        time.sleep(0.05)
        assert sp.uris() == [u(0)]
    finally:
        finish(mgr, sp)


def test_clear_then_add_many_while_held_replaces_remaining():
    """The `playlist_from_page` pattern: clear + add_many during playback."""
    mgr, sp = make()
    mgr.create("p")
    mgr.add_many("p", [{"url": u(0)}, {"url": u(1)}, {"url": u(2)}])
    try:
        mgr.play("Kitchen", "p")
        assert sp.wait_plays(1)
        mgr.clear("p")
        mgr.add_many("p", [{"url": u(7)}, {"text": "page intro"}, {"url": u(8)}])
        sp.release()
        for n in (2, 3, 4):
            assert sp.wait_plays(n)
            sp.release()
        assert wait_gone(mgr, sp)
        assert sp.uris() == [u(0), u(7), VOICE_URL, u(8)]
    finally:
        finish(mgr, sp)


def test_identical_voice_items_both_play():
    mgr, sp = make()
    mgr.create("p")
    mgr.add_many("p", [{"text": "same"}, {"text": "same"}])
    try:
        mgr.play("Kitchen", "p")
        for n in (1, 2):
            assert sp.wait_plays(n)
            sp.release()
        assert wait_gone(mgr, sp)
        assert sp.uris() == [VOICE_URL, VOICE_URL]
    finally:
        finish(mgr, sp)


# ---------------------------------------------------------------------------
# AC8: shuffled status
# ---------------------------------------------------------------------------


def test_shuffled_status_reports_the_item_actually_playing(monkeypatch):
    monkeypatch.setattr(playlists_mod.random, "shuffle", lambda x: x.reverse())
    mgr, sp = make()
    mgr.create("p")
    mgr.add_many("p", [{"url": u(0)}, {"url": u(1)}, {"url": u(2)}, {"url": u(3)}])
    try:
        mgr.play("Kitchen", "p", shuffle=True)  # order: 0, 3, 2, 1
        assert sp.wait_plays(1)
        sp.release()
        assert sp.wait_plays(2)  # second item playing
        st = mgr.status("Kitchen")
        assert sp.uris()[1] == u(3)
        assert st["current_item"]["url"] == u(3)
        assert st["current_index"] == 1            # play-order position
        assert st["current_playlist_index"] == 3   # playlist position
        mgr.remove("p", 3)
        assert mgr.status("Kitchen")["current_playlist_index"] == -1
        assert mgr.status("Kitchen")["current_item"]["url"] == u(3)
    finally:
        finish(mgr, sp)


def test_status_after_playlist_delete_still_reports_current_item():
    mgr, sp = make()
    mgr.create("p")
    mgr.add_many("p", [{"url": u(0)}, {"url": u(1)}])
    try:
        mgr.play("Kitchen", "p")
        assert sp.wait_plays(1)
        sess = mgr._sessions[sp.uid]
        # Emulate delete's effect without the stop signal racing the check.
        with mgr._lock:
            del mgr._playlists["p"]
        st = mgr.status("Kitchen")
        assert st["current_item"]["url"] == u(0)
        assert st["current_playlist_index"] == -1
        assert sess is mgr._sessions[sp.uid]
    finally:
        finish(mgr, sp)


# ---------------------------------------------------------------------------
# AC9: previous
# ---------------------------------------------------------------------------


def test_back_at_index_zero_replays_zero():
    mgr, sp = make()
    mgr.create("p")
    mgr.add_many("p", [{"url": u(0)}, {"url": u(1)}])
    try:
        mgr.play("Kitchen", "p")
        assert sp.wait_plays(1)
        mgr.previous_track("Kitchen")
        assert sp.wait_plays(2)
        assert sp.uris()[:2] == [u(0), u(0)]
    finally:
        finish(mgr, sp)


def test_back_at_index_one_goes_to_zero():
    mgr, sp = make()
    mgr.create("p")
    mgr.add_many("p", [{"url": u(0)}, {"url": u(1)}, {"url": u(2)}])
    try:
        mgr.play("Kitchen", "p")
        assert sp.wait_plays(1)
        sp.release()
        assert sp.wait_plays(2)
        mgr.previous_track("Kitchen")
        assert sp.wait_plays(3)
        assert sp.uris()[:3] == [u(0), u(1), u(0)]
    finally:
        finish(mgr, sp)


def test_back_skips_removed_previous_item():
    mgr, sp = make()
    mgr.create("p")
    mgr.add_many("p", [{"url": u(0)}, {"url": u(1)}, {"url": u(2)}])
    try:
        mgr.play("Kitchen", "p", start_index=2)
        assert sp.wait_plays(1)
        assert sp.uris() == [u(2)]
        mgr.remove("p", 1)
        mgr.previous_track("Kitchen")
        assert sp.wait_plays(2)
        assert sp.uris()[1] == u(0)
    finally:
        finish(mgr, sp)


# ---------------------------------------------------------------------------
# AC10: server tools through an in-process FastMCP client
# ---------------------------------------------------------------------------


def _server():
    mgr, _ = make()
    mcp = FastMCP("t")
    register_tools(mcp, SimpleNamespace(playlists=mgr))
    mgr.create("p")
    return mcp, mgr


def _call(mcp, tool, args):
    async def go():
        async with Client(mcp) as c:
            return await c.call_tool(tool, args)

    return asyncio.run(go())


def test_server_playlist_add_text_only():
    mcp, mgr = _server()
    res = _call(mcp, "playlist_add", {"name": "p", "text": "good evening"})
    items = res.data["items"]
    assert items[0]["kind"] == "voice" and items[0]["text"] == "good evening"


def test_server_playlist_add_bad_scheme_rejected():
    mcp, mgr = _server()
    with pytest.raises(ToolError):
        _call(mcp, "playlist_add", {"name": "p", "url": "ftp://x/y.mp3"})
    assert mgr.get("p").items == []


def test_server_playlist_add_many_null_url_text():
    mcp, mgr = _server()
    res = _call(
        mcp,
        "playlist_add_many",
        {"name": "p", "items": [{"url": u(1)}, {"url": None, "text": "hi"}]},
    )
    assert [i["kind"] for i in res.data["items"]] == ["track", "voice"]


def test_server_playlist_add_many_bad_scheme_rejected():
    mcp, mgr = _server()
    with pytest.raises(ToolError):
        _call(mcp, "playlist_add_many", {"name": "p", "items": [{"url": "ftp://x"}]})
    assert mgr.get("p").items == []
