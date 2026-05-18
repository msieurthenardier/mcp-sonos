"""Regression test for the `say()` coordinator-routing bug.

Background (mission Known Issues): `smoke_test.py say()` fails with
`play_uri can only be called/used on the coordinator in a group` even
when `list_groups` reports the target speaker as its own singleton
coordinator. Reproduced 2 of 3 prior debrief smoke runs.

Investigation finding (Leg 04 Phase B): the SoCo Python object's
`group.coordinator` view and `coord.uid` agree — there is no
controller-visible divergence before the call. The divergence lives
between SoCo's in-process cache and the Sonos firmware. The fix shape
is therefore a `SoCoSlaveException`-catching retry that invalidates the
speakers cache, re-resolves the coordinator, and retries once.

These tests exercise both halves of that fix:

* `test_say_recovers_after_rediscover_returns_fresh_coordinator` —
  models the realistic recovery path: first `play_uri` fails (stale
  SoCo); cache invalidation + re-resolve returns a fresh SoCo whose
  `play_uri` succeeds. `say()` returns normally — this is what the
  smoke-test will see once the fix lands against hardware.
* `test_say_propagates_when_rediscover_also_returns_stale_coordinator` —
  models the worst case: rediscovery can't find a non-stale view
  either. The retry runs and propagates `SoCoSlaveException`; we don't
  loop forever.

`SoCoSlaveException` is imported here (not in `tests/_fakes.py`), per
the fake's docstring contract that it stays SoCo-free.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from soco.exceptions import SoCoSlaveException

from mcp_sonos import controller as controller_mod
from mcp_sonos.controller import SonosController

from tests._fakes import SoCoFake


class _SlaveOnPlayUriFake(SoCoFake):
    """A SoCoFake whose `group.coordinator` view says coordinator-of-one,
    but whose `play_uri` raises `SoCoSlaveException` — modeling the
    SoCo-cache-vs-firmware divergence the mission Known Issue exhibits."""

    def play_uri(self, uri, title=None, force_radio=False):  # type: ignore[override]
        raise SoCoSlaveException(
            "play_uri can only be called/used on the coordinator in a group"
        )


@pytest.fixture
def stub_controller(monkeypatch, tmp_path):
    """Build a SonosController without binding the audio host port or
    hitting the network, and without invoking Piper TTS."""
    # Don't start the real HTTP audio host (binds a TCP port).
    monkeypatch.setattr(controller_mod.AudioHost, "start", lambda self: None)

    # Don't run Piper — synthesize() would try to download a voice.
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
    # `_wait_until_stopped` polls transport state; the fake transitions
    # to PLAYING on play_uri and never back to STOPPED on its own.
    # Skip the wait — the bug under test is in the play_uri call itself.
    monkeypatch.setattr(
        SonosController, "_wait_until_stopped", staticmethod(lambda *a, **kw: None)
    )

    ctl = SonosController(cache_dir=tmp_path)
    return ctl


def test_say_recovers_after_rediscover_returns_fresh_coordinator(
    monkeypatch, stub_controller
):
    """Happy-path recovery: first `play_uri` raises `SoCoSlaveException`
    (stale SoCo), then `_play_uri_with_stale_coord_retry` invalidates
    the cache, re-resolves, and the fresh SoCo's `play_uri` succeeds.
    `say()` returns normally — the smoke-test outcome we want."""
    stale = _SlaveOnPlayUriFake(player_name="Kitchen", uid="RINCON_STALE001")
    fresh = SoCoFake(player_name="Kitchen", uid="RINCON_FRESH001")

    # First discovery call returns the stale fake; the retry's
    # re-discovery returns the fresh one.
    calls = {"n": 0}

    def _fake_discover(*a, **kw):
        calls["n"] += 1
        return [stale] if calls["n"] == 1 else [fresh]

    monkeypatch.setattr(controller_mod.sp, "discover_speakers", _fake_discover)

    result = stub_controller.say("Kitchen", "hello world")

    # Two discovery passes: initial resolve + retry-triggered re-resolve.
    assert calls["n"] == 2, "fix must force a re-discovery on SoCoSlaveException"
    assert result["spoken_on"] == "Kitchen"
    # The fresh fake actually received the play_uri call.
    assert fresh._track["uri"].startswith("http://test.invalid/")


def test_say_propagates_when_rediscover_also_returns_stale_coordinator(
    monkeypatch, stub_controller
):
    """Worst-case bound: if rediscovery returns another speaker whose
    `play_uri` also raises, `say()` propagates `SoCoSlaveException`
    rather than looping. Pins the single-retry contract."""
    stale_a = _SlaveOnPlayUriFake(player_name="Kitchen", uid="RINCON_STALEA")
    stale_b = _SlaveOnPlayUriFake(player_name="Kitchen", uid="RINCON_STALEB")

    calls = {"n": 0}

    def _fake_discover(*a, **kw):
        calls["n"] += 1
        return [stale_a] if calls["n"] == 1 else [stale_b]

    monkeypatch.setattr(controller_mod.sp, "discover_speakers", _fake_discover)

    with pytest.raises(SoCoSlaveException):
        stub_controller.say("Kitchen", "hello world")

    # Exactly two passes — no infinite retry loop.
    assert calls["n"] == 2
