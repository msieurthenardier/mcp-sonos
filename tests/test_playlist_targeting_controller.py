"""Controller-level tests for `playlist_play` / `playlist_from_page`
target-set support (flight 2, leg 2).

The target-group planner itself is covered exhaustively in
`tests/test_targeting.py`, and the controller's stop/unjoin/join execution
order and error shapes are covered in `tests/test_target_group_controller.py`
(exercised through `play_url`/`say`). These tests focus on the wiring that's
specific to the playlist path: `_plan_targets` -> `_execute_plan` ->
`PlaylistManager.play(c0.player_name, ...)`, the merged response shape, the
`"all"` rejection, and `playlist_from_page`'s `speakers`/`detach` passthrough
(including the `speakers=[]` edge case).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_sonos import controller as controller_mod
from mcp_sonos.controller import SonosController

from tests._fakes import FakeHousehold, SoCoFake


@pytest.fixture
def stub_controller(monkeypatch, tmp_path):
    """SonosController with no real audio host, no Piper TTS, no blocking
    waits, and no real sleeping in the grouping confirmation poll."""
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
    ctl = SonosController(cache_dir=tmp_path)
    ctl._sleep = lambda *_: None  # confirmation poll must not cost real time
    return ctl


def _wire_household(monkeypatch, controller: SonosController, speakers: list[SoCoFake]) -> None:
    monkeypatch.setattr(controller_mod.sp, "discover_speakers", lambda: list(speakers))
    controller._speakers_ts = 0.0


def _make_playlist(controller: SonosController, name: str, url: str = "http://cdn.example.com/a.mp3") -> None:
    controller.playlists.create(name)
    controller.playlists.add(name, url, title="Track A")


def _make_mcp_hosted_playlist(controller: SonosController, name: str) -> None:
    """An MCP-hosted URL routes `playlist_play` to the worker engine, so
    `has_active_session` becomes observable (external URLs route to the
    native-queue engine, which tracks no session — see
    `PlaylistManager.has_active_session`'s docstring)."""
    url = f"http://{controller._host_ip}:{controller.audio.port}/tts/fake.wav"
    controller.playlists.create(name)
    controller.playlists.add(name, url, title="Track A")


# ---------------------------------------------------------------------------
# playlist_play: group formation + engine wiring
# ---------------------------------------------------------------------------


def test_playlist_play_forms_group_then_plays_on_c0(monkeypatch, stub_controller):
    household = FakeHousehold()
    k = SoCoFake(player_name="Kitchen", uid="K")
    p = SoCoFake(player_name="Patio", uid="P")
    household.attach(k, p)
    _wire_household(monkeypatch, stub_controller, [k, p])
    _make_mcp_hosted_playlist(stub_controller, "mix")

    result = stub_controller.playlist_play(["Kitchen", "Patio"], "mix")

    # Target-set keys present alongside the engine's own keys.
    for key in ("targets", "coordinator", "group_members", "stopped", "detached", "engine"):
        assert key in result
    assert result["targets"] == ["Kitchen", "Patio"]
    assert result["detached"] is True
    assert result["stopped"] == []
    assert set(result["group_members"]) == {"Kitchen", "Patio"}
    # c0 is the first-listed target (neither is PLAYING, no bystanders) —
    # both `speaker` (the engine's own key) and `coordinator` hold its name.
    assert result["coordinator"] == "Kitchen"
    assert result["speaker"] == "Kitchen"
    # The session was actually started on the resolved coordinator.
    assert stub_controller.playlists.has_active_session(k.uid)
    stub_controller.playlists.stop("Kitchen")


def test_playlist_play_stops_bystander_and_separates(monkeypatch, stub_controller):
    household = FakeHousehold()
    k = SoCoFake(player_name="Kitchen", uid="K")
    b = SoCoFake(player_name="Bystander", uid="B")
    household.attach(k, b)
    household.group(k, [b])
    _wire_household(monkeypatch, stub_controller, [k, b])
    _make_playlist(stub_controller, "mix")

    result = stub_controller.playlist_play(["Kitchen"], "mix")

    assert result["stopped"] == ["Bystander"]
    assert result["group_members"] == ["Kitchen"]
    # Per the detach algorithm, the executor stops the GROUP's coordinator
    # (K), not the bystander directly — stopping a real Sonos coordinator
    # silences its whole group. FakeHousehold models this via `do_stop`.
    assert k.stop_call_count >= 1
    stub_controller.playlists.stop("Kitchen")


def test_playlist_play_detach_false_keeps_existing_group(monkeypatch, stub_controller):
    household = FakeHousehold()
    k = SoCoFake(player_name="Kitchen", uid="K")
    b = SoCoFake(player_name="Bystander", uid="B")
    household.attach(k, b)
    household.group(k, [b])
    _wire_household(monkeypatch, stub_controller, [k, b])
    _make_playlist(stub_controller, "mix")

    result = stub_controller.playlist_play(["Kitchen"], "mix", detach=False)

    assert result["detached"] is False
    assert result["stopped"] == []
    assert set(result["group_members"]) == {"Kitchen", "Bystander"}
    stub_controller.playlists.stop("Kitchen")


def test_playlist_play_rejects_all(stub_controller):
    with pytest.raises(ValueError):
        stub_controller.playlist_play(["all"], "mix")


def test_playlist_play_passes_shuffle_and_start_index(monkeypatch, stub_controller):
    household = FakeHousehold()
    k = SoCoFake(player_name="Kitchen", uid="K")
    household.attach(k)
    _wire_household(monkeypatch, stub_controller, [k])
    stub_controller.playlists.create("mix2")
    stub_controller.playlists.add("mix2", "http://cdn.example.com/a.mp3")
    stub_controller.playlists.add("mix2", "http://cdn.example.com/b.mp3")

    result = stub_controller.playlist_play(["Kitchen"], "mix2", shuffle=False, start_index=1)

    assert result["start_index"] == 1
    stub_controller.playlists.stop("Kitchen")


# ---------------------------------------------------------------------------
# playlist_from_page: speakers / detach passthrough
# ---------------------------------------------------------------------------


def _stub_extract(monkeypatch, items):
    monkeypatch.setattr(
        controller_mod, "extract_audio_urls", lambda *a, **kw: items
    )


def test_playlist_from_page_without_speakers_only_builds(monkeypatch, stub_controller):
    _stub_extract(monkeypatch, [{"url": "http://cdn.example.com/x.mp3", "title": "X"}])

    result = stub_controller.playlist_from_page("blog", "http://example.com/page")

    assert result["playing"] is False
    assert "targets" not in result
    assert len(stub_controller.playlists.get("blog").items) == 1


def test_playlist_from_page_with_speakers_plays_through_target_path(monkeypatch, stub_controller):
    household = FakeHousehold()
    k = SoCoFake(player_name="Kitchen", uid="K")
    p = SoCoFake(player_name="Patio", uid="P")
    household.attach(k, p)
    _wire_household(monkeypatch, stub_controller, [k, p])
    _stub_extract(monkeypatch, [{"url": "http://cdn.example.com/x.mp3", "title": "X"}])

    result = stub_controller.playlist_from_page(
        "blog2", "http://example.com/page", speakers=["Kitchen", "Patio"]
    )

    assert result["playing"] is True
    for key in ("targets", "coordinator", "group_members", "stopped", "detached", "engine"):
        assert key in result
    assert set(result["group_members"]) == {"Kitchen", "Patio"}
    stub_controller.playlists.stop(result["coordinator"])


def test_playlist_from_page_empty_speakers_list_raises(monkeypatch, stub_controller):
    household = FakeHousehold()
    k = SoCoFake(player_name="Kitchen", uid="K")
    household.attach(k)
    _wire_household(monkeypatch, stub_controller, [k])
    _stub_extract(monkeypatch, [{"url": "http://cdn.example.com/x.mp3", "title": "X"}])

    # The playlist is still built even though the play step is rejected.
    with pytest.raises(ValueError):
        stub_controller.playlist_from_page("blog3", "http://example.com/page", speakers=[])

    assert stub_controller.playlists.get("blog3") is not None
