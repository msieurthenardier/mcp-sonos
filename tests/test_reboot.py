"""Tests for the speaker reboot path.

Sonos has no documented reboot API; the controller hits the firmware's
undocumented HTTP control port (1400). These tests pin two things without
touching the network:

* `_reboot_via_http` delivery semantics — a dropped/reset/timed-out request
  is the EXPECTED success signal (the device tears down its socket as it goes
  down); only a clean refusal/DNS failure surfaces as an error.
* `SonosController.reboot` resolves the named speaker, fires the request at
  its IP, and invalidates the speaker cache so the next access re-discovers
  the (briefly absent) device.
"""

from __future__ import annotations

import urllib.error
from http.client import RemoteDisconnected

import pytest

from mcp_sonos import controller as controller_mod
from mcp_sonos.controller import SonosController, _reboot_via_http

from tests._fakes import SoCoFake


# ---- _reboot_via_http semantics ---------------------------------------------


def _patch_urlopen(monkeypatch, behaviour):
    """Replace urlopen with `behaviour(url, timeout)` (raises or returns a cm)."""
    captured = {}

    def _fake_urlopen(url, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        return behaviour()

    monkeypatch.setattr(controller_mod.urllib.request, "urlopen", _fake_urlopen)
    return captured


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_reboot_http_targets_control_port(monkeypatch):
    captured = _patch_urlopen(monkeypatch, lambda: _FakeResponse())
    _reboot_via_http("192.168.1.51")
    assert captured["url"] == "http://192.168.1.51:1400/reboot"
    assert captured["timeout"] == controller_mod.REBOOT_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "exc",
    [
        RemoteDisconnected("device went down"),
        ConnectionResetError("connection reset"),
        TimeoutError("timed out"),
        urllib.error.HTTPError("u", 400, "Bad Request", {}, None),
        urllib.error.URLError(RemoteDisconnected("reset during reboot")),
        urllib.error.URLError(TimeoutError("timed out")),
    ],
)
def test_reboot_http_treats_teardown_as_success(monkeypatch, exc):
    """The device dropping the connection is how a reboot looks — no raise."""

    def _raise():
        raise exc

    _patch_urlopen(monkeypatch, _raise)
    _reboot_via_http("192.168.1.51")  # must not raise


def test_reboot_http_raises_when_unreachable(monkeypatch):
    """A clean refusal means nothing listened — the command never landed."""

    def _raise():
        raise urllib.error.URLError(ConnectionRefusedError("refused"))

    _patch_urlopen(monkeypatch, _raise)
    with pytest.raises(RuntimeError, match="could not reach"):
        _reboot_via_http("192.168.1.51")


# ---- SonosController.reboot -------------------------------------------------


@pytest.fixture
def stub_controller(monkeypatch, tmp_path):
    """Build a SonosController without binding the audio port or hitting net."""
    monkeypatch.setattr(controller_mod.AudioHost, "start", lambda self: None)
    return SonosController(cache_dir=tmp_path)


def test_controller_reboot_fires_and_invalidates_cache(monkeypatch, stub_controller):
    fake = SoCoFake(player_name="Kitchen", uid="RINCON_K", ip_address="192.168.1.51")
    monkeypatch.setattr(controller_mod.sp, "discover_speakers", lambda *a, **k: [fake])

    seen = {}
    monkeypatch.setattr(
        controller_mod, "_reboot_via_http", lambda ip, *a, **k: seen.setdefault("ip", ip)
    )

    # Warm the cache so we can prove reboot() resets the TTL.
    stub_controller.list_speakers()
    assert stub_controller._speakers_ts != 0.0

    result = stub_controller.reboot("Kitchen")

    assert seen["ip"] == "192.168.1.51"
    assert result == {"speaker": "Kitchen", "ip": "192.168.1.51", "rebooting": True}
    assert stub_controller._speakers_ts == 0.0, "reboot must force re-discovery"
