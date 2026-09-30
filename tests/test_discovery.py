"""Unit tests for the zero-config discovery pipeline (Flight 1, Legs 1-2).

Hardware-free throughout: every stage function (`_probe_port`,
`_expand_seed`/`SoCo`, `_scan_networks`, `_scan`, `_ssdp`) and the
`ifaddr` adapter lookup are monkeypatched. No real sockets, scans, or
SSDP traffic. `tests/conftest.py` pins `HOST_IP=127.0.0.1`, so any test
that cares about the derived scan network overrides `speakers.lan_host_ip`
explicitly rather than relying on that pinned value.

An autouse fixture resets the module-level learned-seed state
(`sp._reset_learned_seeds()`) before and after every test, so no test's
outcome depends on execution order.

Covers, per the legs' acceptance criteria:
  - pipeline order and short-circuiting (seeds -> learned seeds -> scan ->
    SSDP)
  - seed fallback past dead/failed seeds, and seed-expansion visibility
    filtering
  - scan-network derivation (adapter clamp, no-adapter fallback,
    SONOS_SCAN_NETWORKS override, malformed/too-broad rejection)
  - scan concurrency (`max_threads=SCAN_MAX_THREADS`)
  - learned seeds: recorded on success, tried before the scan, skipped
    when already tried as a configured seed, untouched on total failure
  - NoSpeakersFound message content and RuntimeError base
  - the controller's name-miss re-discovery (success and exhaustion)
  - every forced-refresh path clearing SoCo's own topology cache, and
    plain TTL expiry NOT clearing it
  - NoSpeakersFound propagating through the stale-coordinator retry from
    both `say()` and `PlaylistManager._play_via_queue`
"""

from __future__ import annotations

from pathlib import Path

import pytest
from soco.exceptions import SoCoSlaveException

from mcp_sonos import controller as controller_mod
from mcp_sonos import speakers as sp
from mcp_sonos.controller import SonosController
from mcp_sonos.playlists import PlaylistManager
from mcp_sonos.speakers import NoSpeakersFound, SpeakerNotFound

from tests._builders import _AUDIO_PORT, _HOST_IP
from tests._fakes import SoCoFake


# ---------------------------------------------------------------------------
# Local fakes for the speakers-module seam (sp.SoCo, ifaddr adapters).
#
# These are intentionally separate from tests/_fakes.py::SoCoFake, which
# models the controller/playlists surface (a coordinator-of-one with
# transport methods). `speakers.py` only ever touches `.player_name` and
# `.is_visible` (a plain attribute access, `bool(speaker.is_visible)` —
# NOT a method call) on the objects `_expand_seed`/`_scan`/`_ssdp` return.
# ---------------------------------------------------------------------------


class _FakeZone:
    def __init__(
        self,
        name: str,
        visible: bool = True,
        raise_on_visible: bool = False,
        ip_address: str | None = None,
    ):
        self.player_name = name
        self.ip_address = ip_address if ip_address is not None else f"10.99.0.{abs(hash(name)) % 250 + 1}"
        self._visible = visible
        self._raise_on_visible = raise_on_visible

    @property
    def is_visible(self):
        if self._raise_on_visible:
            raise RuntimeError("zone went offline mid-discovery")
        return self._visible


class _SeedSoCo:
    """Stand-in for `SoCo(ip)`, as used by `_expand_seed`."""

    def __init__(self, zones=None, raise_exc: Exception | None = None):
        self._zones = zones or []
        self._raise_exc = raise_exc

    @property
    def visible_zones(self):
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._zones


def _seed_socos(mapping: dict) -> callable:
    """Return a callable to monkeypatch `sp.SoCo` with, keyed by ip.

    `mapping[ip]` is either a list of `_FakeZone`s or an `Exception`
    instance to raise when `.visible_zones` is accessed.
    """

    def factory(ip):
        cfg = mapping[ip]
        if isinstance(cfg, Exception):
            return _SeedSoCo(raise_exc=cfg)
        return _SeedSoCo(zones=cfg)

    return factory


class _FakeIfaddrIP:
    def __init__(self, ip: str, prefix: int, is_ipv4: bool = True):
        self.ip = ip
        self.network_prefix = prefix
        self.is_IPv4 = is_ipv4


class _FakeIfaddrAdapter:
    def __init__(self, ips: list):
        self.ips = ips


@pytest.fixture(autouse=True)
def _reset_learned_seeds():
    """Leg 02: learned-seed state is module-level/process-wide. Reset it
    around every test so none depends on execution order or leaks into
    another test file (every other test file stubs `discover_speakers`
    wholesale, so this state only matters here)."""
    sp._reset_learned_seeds()
    yield
    sp._reset_learned_seeds()


# ---------------------------------------------------------------------------
# Stage order and short-circuiting
# ---------------------------------------------------------------------------


def test_seed_hit_short_circuits_scan_and_ssdp(monkeypatch):
    monkeypatch.setattr(sp, "_ips_from_env", lambda: ["10.0.0.5"])
    monkeypatch.setattr(sp, "_probe_port", lambda ip, *a, **k: True)
    monkeypatch.setattr(
        sp, "SoCo", _seed_socos({"10.0.0.5": [_FakeZone("Patio"), _FakeZone("Kitchen")]})
    )

    def _boom(*a, **k):
        raise AssertionError("must not run once seeds succeed")

    monkeypatch.setattr(sp, "_scan_networks", _boom)
    monkeypatch.setattr(sp, "_scan", _boom)
    monkeypatch.setattr(sp, "_ssdp", _boom)

    result = sp.discover_speakers()
    assert [s.player_name for s in result] == ["Kitchen", "Patio"]


def test_scan_hit_short_circuits_ssdp(monkeypatch):
    monkeypatch.setattr(sp, "_ips_from_env", lambda: [])
    monkeypatch.setattr(sp, "_scan_networks", lambda: (["192.168.1.0/24"], []))
    monkeypatch.setattr(sp, "_scan", lambda networks: [_FakeZone("Office")])

    def _boom(*a, **k):
        raise AssertionError("ssdp must not run once the scan succeeds")

    monkeypatch.setattr(sp, "_ssdp", _boom)

    result = sp.discover_speakers()
    assert [s.player_name for s in result] == ["Office"]


def test_ssdp_runs_only_when_scan_empty(monkeypatch):
    monkeypatch.setattr(sp, "_ips_from_env", lambda: [])
    monkeypatch.setattr(sp, "_scan_networks", lambda: (["192.168.1.0/24"], []))
    monkeypatch.setattr(sp, "_scan", lambda networks: [])
    ssdp_calls: list[int] = []

    def _ssdp(timeout):
        ssdp_calls.append(timeout)
        return [_FakeZone("Attic")]

    monkeypatch.setattr(sp, "_ssdp", _ssdp)

    result = sp.discover_speakers(timeout=7)
    assert ssdp_calls == [7]
    assert [s.player_name for s in result] == ["Attic"]


# ---------------------------------------------------------------------------
# Seed fallback and expansion
# ---------------------------------------------------------------------------


def test_dead_seed_skipped_next_live_seed_used(monkeypatch):
    monkeypatch.setattr(sp, "_ips_from_env", lambda: ["10.0.0.1", "10.0.0.2"])
    monkeypatch.setattr(sp, "_probe_port", lambda ip, *a, **k: ip == "10.0.0.2")
    monkeypatch.setattr(sp, "SoCo", _seed_socos({"10.0.0.2": [_FakeZone("Bedroom")]}))

    result = sp.discover_speakers()
    assert [s.player_name for s in result] == ["Bedroom"]


def test_seed_raising_on_expansion_skipped_next_seed_used(monkeypatch):
    monkeypatch.setattr(sp, "_ips_from_env", lambda: ["10.0.0.1", "10.0.0.2"])
    monkeypatch.setattr(sp, "_probe_port", lambda ip, *a, **k: True)
    monkeypatch.setattr(
        sp,
        "SoCo",
        _seed_socos(
            {
                "10.0.0.1": RuntimeError("not a Sonos device"),
                "10.0.0.2": [_FakeZone("Kitchen")],
            }
        ),
    )

    result = sp.discover_speakers()
    assert [s.player_name for s in result] == ["Kitchen"]


def test_all_seeds_dead_falls_through_to_scan(monkeypatch):
    monkeypatch.setattr(sp, "_ips_from_env", lambda: ["10.0.0.1", "10.0.0.2"])
    monkeypatch.setattr(sp, "_probe_port", lambda ip, *a, **k: False)
    monkeypatch.setattr(sp, "_scan_networks", lambda: (["192.168.1.0/24"], []))
    monkeypatch.setattr(sp, "_scan", lambda networks: [_FakeZone("Garage")])

    result = sp.discover_speakers()
    assert [s.player_name for s in result] == ["Garage"]


def test_seed_expansion_excludes_invisible_zones(monkeypatch):
    monkeypatch.setattr(sp, "_ips_from_env", lambda: ["10.0.0.5"])
    monkeypatch.setattr(sp, "_probe_port", lambda ip, *a, **k: True)
    visible = _FakeZone("Kitchen", visible=True)
    invisible = _FakeZone("Boost", visible=False)
    offline = _FakeZone("Ghost", raise_on_visible=True)
    monkeypatch.setattr(sp, "SoCo", _seed_socos({"10.0.0.5": [visible, invisible, offline]}))

    result = sp.discover_speakers()
    assert [s.player_name for s in result] == ["Kitchen"]


def test_seed_with_zero_visible_zones_counts_as_no_speakers_and_continues(monkeypatch):
    """A Boost-only seed: expansion succeeds but yields nothing visible."""
    monkeypatch.setattr(sp, "_ips_from_env", lambda: ["10.0.0.5", "10.0.0.6"])
    monkeypatch.setattr(sp, "_probe_port", lambda ip, *a, **k: True)
    monkeypatch.setattr(
        sp,
        "SoCo",
        _seed_socos(
            {
                "10.0.0.5": [_FakeZone("Boost", visible=False)],
                "10.0.0.6": [_FakeZone("Kitchen")],
            }
        ),
    )

    result = sp.discover_speakers()
    assert [s.player_name for s in result] == ["Kitchen"]


def test_no_seeds_configured_falls_through_to_scan(monkeypatch):
    monkeypatch.setattr(sp, "_ips_from_env", lambda: [])
    monkeypatch.setattr(sp, "_scan_networks", lambda: (["192.168.1.0/24"], []))
    monkeypatch.setattr(sp, "_scan", lambda networks: [_FakeZone("Den")])

    result = sp.discover_speakers()
    assert [s.player_name for s in result] == ["Den"]


# ---------------------------------------------------------------------------
# Learned seeds (Leg 02)
# ---------------------------------------------------------------------------


def test_successful_scan_records_learned_seed_used_by_next_call(monkeypatch):
    monkeypatch.setattr(sp, "_ips_from_env", lambda: [])
    monkeypatch.setattr(sp, "_scan_networks", lambda: (["192.168.1.0/24"], []))
    monkeypatch.setattr(
        sp, "_scan", lambda networks: [_FakeZone("Office", ip_address="192.168.1.42")]
    )

    def _ssdp_boom(*a, **k):
        raise AssertionError("ssdp must not run once the scan succeeds")

    monkeypatch.setattr(sp, "_ssdp", _ssdp_boom)

    first = sp.discover_speakers()
    assert [s.player_name for s in first] == ["Office"]
    assert sp._learned_seed_ips == ["192.168.1.42"]

    # Second call: no configured seeds, learned seed answers. `_scan` must
    # not run.
    monkeypatch.setattr(sp, "_probe_port", lambda ip, *a, **k: ip == "192.168.1.42")
    monkeypatch.setattr(
        sp, "SoCo", _seed_socos({"192.168.1.42": [_FakeZone("Office", ip_address="192.168.1.42")]})
    )

    def _scan_boom(*a, **k):
        raise AssertionError("must not scan once a learned seed answers")

    monkeypatch.setattr(sp, "_scan", _scan_boom)

    second = sp.discover_speakers()
    assert [s.player_name for s in second] == ["Office"]


def test_dead_learned_seeds_fall_through_to_scan(monkeypatch):
    monkeypatch.setattr(sp, "_learned_seed_ips", ["10.0.0.9"], raising=False)
    monkeypatch.setattr(sp, "_ips_from_env", lambda: [])
    monkeypatch.setattr(sp, "_probe_port", lambda ip, *a, **k: False)
    monkeypatch.setattr(sp, "_scan_networks", lambda: (["192.168.1.0/24"], []))
    monkeypatch.setattr(sp, "_scan", lambda networks: [_FakeZone("Garage")])

    result = sp.discover_speakers()
    assert [s.player_name for s in result] == ["Garage"]


def test_learned_seeds_not_overwritten_by_failed_call(monkeypatch):
    monkeypatch.setattr(sp, "_learned_seed_ips", ["10.0.0.9"], raising=False)
    monkeypatch.setattr(sp, "_ips_from_env", lambda: [])
    monkeypatch.setattr(sp, "_probe_port", lambda ip, *a, **k: False)
    monkeypatch.setattr(sp, "_scan_networks", lambda: ([], ["'bad' (malformed)"]))
    monkeypatch.setattr(sp, "_ssdp", lambda timeout: [])

    with pytest.raises(NoSpeakersFound):
        sp.discover_speakers()

    assert sp._learned_seed_ips == ["10.0.0.9"], "a failed call must not touch learned seeds"


def test_configured_seed_already_tried_not_reprobed_as_learned_seed(monkeypatch):
    monkeypatch.setattr(sp, "_learned_seed_ips", ["10.0.0.1", "10.0.0.2"], raising=False)
    monkeypatch.setattr(sp, "_ips_from_env", lambda: ["10.0.0.1"])
    probe_calls: list[str] = []

    def _probe(ip, *a, **k):
        probe_calls.append(ip)
        return ip == "10.0.0.2"

    monkeypatch.setattr(sp, "_probe_port", _probe)
    monkeypatch.setattr(sp, "SoCo", _seed_socos({"10.0.0.2": [_FakeZone("Kitchen")]}))

    result = sp.discover_speakers()

    assert [s.player_name for s in result] == ["Kitchen"]
    # 10.0.0.1 probed once (as a configured seed); never re-probed as a
    # learned seed.
    assert probe_calls.count("10.0.0.1") == 1
    assert probe_calls.count("10.0.0.2") == 1


def test_scan_passes_max_threads(monkeypatch):
    monkeypatch.setattr(sp, "_ips_from_env", lambda: [])
    monkeypatch.setattr(sp, "lan_host_ip", lambda: "192.168.1.10")
    monkeypatch.delenv("SONOS_SCAN_NETWORKS", raising=False)
    monkeypatch.setattr(sp.ifaddr, "get_adapters", lambda: [])
    calls = {}

    def _fake_scan_network(**kwargs):
        calls.update(kwargs)
        return set()

    monkeypatch.setattr(sp.soco.discovery, "scan_network", _fake_scan_network)
    monkeypatch.setattr(sp, "_ssdp", lambda timeout: [])

    with pytest.raises(NoSpeakersFound):
        sp.discover_speakers()

    assert calls["max_threads"] == sp.SCAN_MAX_THREADS == 32


def test_no_speakers_found_message_includes_learned_seed_outcomes(monkeypatch):
    monkeypatch.setattr(sp, "_learned_seed_ips", ["10.0.0.9"], raising=False)
    monkeypatch.setattr(sp, "_ips_from_env", lambda: [])
    monkeypatch.setattr(sp, "_probe_port", lambda ip, *a, **k: False)
    monkeypatch.setattr(sp, "_scan_networks", lambda: ([], ["'bad' (malformed)"]))
    monkeypatch.setattr(sp, "_ssdp", lambda timeout: [])

    with pytest.raises(NoSpeakersFound) as exc_info:
        sp.discover_speakers()

    msg = str(exc_info.value)
    assert "learned seed 10.0.0.9" in msg
    assert "unreachable" in msg


# ---------------------------------------------------------------------------
# Scan-network derivation
# ---------------------------------------------------------------------------


def test_scan_network_adapter_prefix_24_stays_24(monkeypatch):
    monkeypatch.delenv("SONOS_SCAN_NETWORKS", raising=False)
    monkeypatch.setattr(sp, "lan_host_ip", lambda: "192.168.86.173")
    adapter = _FakeIfaddrAdapter([_FakeIfaddrIP("192.168.86.173", 24)])
    monkeypatch.setattr(sp.ifaddr, "get_adapters", lambda: [adapter])

    networks, rejected = sp._scan_networks()
    assert networks == ["192.168.86.0/24"]
    assert rejected == []


def test_scan_network_adapter_prefix_22_clamped_to_24(monkeypatch):
    monkeypatch.delenv("SONOS_SCAN_NETWORKS", raising=False)
    monkeypatch.setattr(sp, "lan_host_ip", lambda: "10.0.4.55")
    adapter = _FakeIfaddrAdapter([_FakeIfaddrIP("10.0.4.55", 22)])
    monkeypatch.setattr(sp.ifaddr, "get_adapters", lambda: [adapter])

    networks, rejected = sp._scan_networks()
    assert networks == ["10.0.4.0/24"]
    assert rejected == []


def test_scan_network_ip_not_on_any_adapter_falls_back_to_its_own_24(monkeypatch):
    monkeypatch.delenv("SONOS_SCAN_NETWORKS", raising=False)
    monkeypatch.setattr(sp, "lan_host_ip", lambda: "172.16.5.9")
    monkeypatch.setattr(sp.ifaddr, "get_adapters", lambda: [])

    networks, rejected = sp._scan_networks()
    assert networks == ["172.16.5.0/24"]
    assert rejected == []


def test_scan_network_override_replaces_derived_entirely(monkeypatch):
    monkeypatch.setenv("SONOS_SCAN_NETWORKS", "10.1.2.0/24, 10.1.3.0/25")

    def _boom():
        raise AssertionError("override must short-circuit adapter derivation")

    monkeypatch.setattr(sp, "lan_host_ip", _boom)

    networks, rejected = sp._scan_networks()
    assert networks == ["10.1.2.0/24", "10.1.3.0/25"]
    assert rejected == []


def test_scan_network_override_rejects_malformed_and_too_broad(monkeypatch):
    monkeypatch.setenv("SONOS_SCAN_NETWORKS", "not-a-cidr, 10.0.0.0/8, 192.168.1.0/24")

    networks, rejected = sp._scan_networks()
    assert networks == ["192.168.1.0/24"]
    assert len(rejected) == 2
    assert any("not-a-cidr" in r for r in rejected)
    assert any("10.0.0.0/8" in r for r in rejected)


def test_scan_network_all_entries_invalid_yields_no_networks(monkeypatch):
    monkeypatch.setenv("SONOS_SCAN_NETWORKS", "garbage, 10.0.0.0/8")

    networks, rejected = sp._scan_networks()
    assert networks == []
    assert len(rejected) == 2


def test_scan_skipped_when_all_networks_invalid_falls_through_to_ssdp(monkeypatch):
    monkeypatch.setattr(sp, "_ips_from_env", lambda: [])
    monkeypatch.setenv("SONOS_SCAN_NETWORKS", "garbage")

    def _boom(*a, **k):
        raise AssertionError("scan must not run with no valid networks")

    monkeypatch.setattr(sp, "_scan", _boom)
    monkeypatch.setattr(sp, "_ssdp", lambda timeout: [_FakeZone("Loft")])

    result = sp.discover_speakers()
    assert [s.player_name for s in result] == ["Loft"]


# ---------------------------------------------------------------------------
# NoSpeakersFound: RuntimeError base + message content
# ---------------------------------------------------------------------------


def test_no_speakers_found_is_a_runtime_error():
    assert issubclass(NoSpeakersFound, RuntimeError)


def test_no_speakers_found_message_names_every_stage(monkeypatch):
    monkeypatch.setattr(sp, "_ips_from_env", lambda: ["10.0.0.1"])
    monkeypatch.setattr(sp, "_probe_port", lambda ip, *a, **k: False)
    monkeypatch.setenv("SONOS_SCAN_NETWORKS", "not-a-cidr")
    monkeypatch.setattr(sp, "_ssdp", lambda timeout: [])

    with pytest.raises(NoSpeakersFound) as exc_info:
        sp.discover_speakers()

    msg = str(exc_info.value)
    # Seed outcome.
    assert "10.0.0.1" in msg
    assert "unreachable" in msg
    # Rejected SONOS_SCAN_NETWORKS entry + scan-skipped outcome.
    assert "not-a-cidr" in msg
    assert "scan skipped" in msg
    # SSDP outcome.
    assert "SSDP" in msg
    # Hints.
    assert "SONOS_IPS" in msg
    assert "SONOS_SCAN_NETWORKS" in msg
    assert "HOST_IP" in msg
    assert "LAN" in msg
    assert "85" in msg  # firmware ≥85 UPnP toggle


def test_no_speakers_found_message_notes_no_seeds_configured(monkeypatch):
    monkeypatch.setattr(sp, "_ips_from_env", lambda: [])
    monkeypatch.setattr(sp, "_scan_networks", lambda: ([], ["'bad' (malformed)"]))
    monkeypatch.setattr(sp, "_ssdp", lambda timeout: [])

    with pytest.raises(NoSpeakersFound) as exc_info:
        sp.discover_speakers()

    msg = str(exc_info.value)
    assert "none configured" in msg
    assert "bad" in msg


# ---------------------------------------------------------------------------
# Controller: name-miss re-discovery
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_controller(monkeypatch, tmp_path):
    """SonosController without a bound audio port or any real network I/O."""
    monkeypatch.setattr(controller_mod.AudioHost, "start", lambda self: None)
    return SonosController(cache_dir=tmp_path)


def test_resolve_retries_once_on_name_miss_and_succeeds(monkeypatch, stub_controller):
    kitchen = SoCoFake(player_name="Kitchen", uid="RINCON_A", household_id="H1")
    patio = SoCoFake(player_name="Patio", uid="RINCON_B", household_id="H1")
    calls = {"n": 0}

    def _fake_discover(*a, **kw):
        calls["n"] += 1
        return [kitchen] if calls["n"] == 1 else [kitchen, patio]

    monkeypatch.setattr(controller_mod.sp, "discover_speakers", _fake_discover)

    stub_controller.list_speakers()  # warms the cache without Patio
    assert calls["n"] == 1

    result = stub_controller._resolve("Patio")

    assert result.player_name == "Patio"
    assert calls["n"] == 2, "name miss must force exactly one extra discovery"


def test_resolve_raises_speaker_not_found_after_exactly_one_retry(monkeypatch, stub_controller):
    kitchen = SoCoFake(player_name="Kitchen", uid="RINCON_A", household_id="H1")
    calls = {"n": 0}

    def _fake_discover(*a, **kw):
        calls["n"] += 1
        return [kitchen]

    monkeypatch.setattr(controller_mod.sp, "discover_speakers", _fake_discover)

    stub_controller.list_speakers()
    assert calls["n"] == 1

    with pytest.raises(SpeakerNotFound):
        stub_controller._resolve("Nonexistent")

    assert calls["n"] == 2, "must retry exactly once, then give up"


def test_resolve_propagates_no_speakers_found_from_retry_not_speaker_not_found(
    monkeypatch, stub_controller
):
    kitchen = SoCoFake(player_name="Kitchen", uid="RINCON_A", household_id="H1")
    calls = {"n": 0}

    def _fake_discover(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return [kitchen]
        raise NoSpeakersFound("everything vanished")

    monkeypatch.setattr(controller_mod.sp, "discover_speakers", _fake_discover)

    stub_controller.list_speakers()

    with pytest.raises(NoSpeakersFound):
        stub_controller._resolve("Missing")


# ---------------------------------------------------------------------------
# _invalidate_speakers: cache-clearing contract
# ---------------------------------------------------------------------------


def test_invalidate_speakers_clears_cache_once_per_household(stub_controller):
    a1 = SoCoFake(player_name="A1", uid="RINCON_A1", household_id="H1")
    a2 = SoCoFake(player_name="A2", uid="RINCON_A2", household_id="H1")
    b1 = SoCoFake(player_name="B1", uid="RINCON_B1", household_id="H2")
    stub_controller._speakers = [a1, a2, b1]
    stub_controller._speakers_ts = 12345.0

    stub_controller._invalidate_speakers()

    assert stub_controller._speakers_ts == 0.0
    assert a1.zone_group_state.clear_cache_count == 1
    assert a2.zone_group_state.clear_cache_count == 0, "second H1 speaker not re-cleared"
    assert b1.zone_group_state.clear_cache_count == 1


def test_invalidate_speakers_is_noop_on_empty_cache(stub_controller):
    stub_controller._speakers = []
    stub_controller._speakers_ts = 999.0

    stub_controller._invalidate_speakers()  # must not raise

    assert stub_controller._speakers_ts == 0.0


def test_invalidate_speakers_never_discovers(monkeypatch, stub_controller):
    def _boom(*a, **k):
        raise AssertionError("_invalidate_speakers must never discover")

    monkeypatch.setattr(controller_mod.sp, "discover_speakers", _boom)
    fake = SoCoFake(player_name="Kitchen", uid="RINCON_A", household_id="H1")
    stub_controller._speakers = [fake]

    stub_controller._invalidate_speakers()  # must not raise / must not discover


def test_invalidate_speakers_swallows_missing_household_id(stub_controller):
    class _LegacyFake:
        player_name = "Legacy"

    stub_controller._speakers = [_LegacyFake()]

    stub_controller._invalidate_speakers()  # must not raise

    assert stub_controller._speakers_ts == 0.0


# ---- each forced-refresh path clears SoCo's cache --------------------------


def test_refresh_clears_socos_cache(monkeypatch, stub_controller):
    fake = SoCoFake(player_name="Kitchen", uid="RINCON_A", household_id="H1")
    monkeypatch.setattr(controller_mod.sp, "discover_speakers", lambda *a, **k: [fake])
    stub_controller._speakers = [fake]
    stub_controller._speakers_ts = 999.0

    stub_controller.refresh()

    assert fake.zone_group_state.clear_cache_count == 1


def test_name_miss_retry_clears_socos_cache(monkeypatch, stub_controller):
    fake = SoCoFake(player_name="Kitchen", uid="RINCON_A", household_id="H1")
    monkeypatch.setattr(controller_mod.sp, "discover_speakers", lambda *a, **k: [fake])
    stub_controller.list_speakers()

    with pytest.raises(SpeakerNotFound):
        stub_controller._resolve("Ghost")

    assert fake.zone_group_state.clear_cache_count == 1


def test_reboot_clears_socos_cache(monkeypatch, stub_controller):
    fake = SoCoFake(
        player_name="Kitchen", uid="RINCON_K", ip_address="192.168.1.51", household_id="H1"
    )
    monkeypatch.setattr(controller_mod.sp, "discover_speakers", lambda *a, **k: [fake])
    monkeypatch.setattr(controller_mod, "_reboot_via_http", lambda ip, *a, **k: None)
    stub_controller.list_speakers()

    stub_controller.reboot("Kitchen")

    assert fake.zone_group_state.clear_cache_count == 1


def test_playlist_manager_invalidate_callback_clears_socos_cache(monkeypatch, stub_controller):
    fake = SoCoFake(player_name="Kitchen", uid="RINCON_K", household_id="H1")
    monkeypatch.setattr(controller_mod.sp, "discover_speakers", lambda *a, **k: [fake])
    stub_controller.list_speakers()

    stub_controller.playlists._invalidate_speakers_cache()

    assert fake.zone_group_state.clear_cache_count == 1


@pytest.fixture
def stub_controller_say(monkeypatch, tmp_path):
    """SonosController set up for say()-path tests: no audio host, no Piper,
    no blocking wait (mirrors tests/test_say_coordinator.py's fixture)."""
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


class _SlaveOnPlayUriFake(SoCoFake):
    """SoCoFake whose play_uri always raises SoCoSlaveException, modeling a
    stale SoCo-cache-vs-firmware coordinator view (see test_say_coordinator.py)."""

    def play_uri(self, uri, title=None, force_radio=False):  # type: ignore[override]
        raise SoCoSlaveException("play_uri can only be called on the coordinator")


def test_say_inline_retry_clears_socos_cache(monkeypatch, stub_controller_say):
    stale = _SlaveOnPlayUriFake(player_name="Kitchen", uid="RINCON_STALE", household_id="H1")
    fresh = SoCoFake(player_name="Kitchen", uid="RINCON_FRESH", household_id="H1")
    calls = {"n": 0}

    def _fake_discover(*a, **kw):
        calls["n"] += 1
        return [stale] if calls["n"] == 1 else [fresh]

    monkeypatch.setattr(controller_mod.sp, "discover_speakers", _fake_discover)

    stub_controller_say.say("Kitchen", "hello")

    assert stale.zone_group_state.clear_cache_count == 1


def test_ttl_expiry_does_not_clear_socos_cache(monkeypatch, stub_controller):
    fake = SoCoFake(player_name="Kitchen", uid="RINCON_A", household_id="H1")
    calls = {"n": 0}

    def _fake_discover(*a, **kw):
        calls["n"] += 1
        return [fake]

    monkeypatch.setattr(controller_mod.sp, "discover_speakers", _fake_discover)

    stub_controller.list_speakers()
    assert calls["n"] == 1
    assert fake.zone_group_state.clear_cache_count == 0

    stub_controller._speakers_ts = 0.0  # simulate natural TTL expiry
    stub_controller.list_speakers()

    assert calls["n"] == 2
    assert fake.zone_group_state.clear_cache_count == 0, (
        "plain TTL expiry must not touch SoCo's own topology cache"
    )


# ---------------------------------------------------------------------------
# NoSpeakersFound propagating through the stale-coordinator retry
# ---------------------------------------------------------------------------


def test_say_propagates_no_speakers_found_through_stale_retry(monkeypatch, stub_controller_say):
    stale = _SlaveOnPlayUriFake(player_name="Kitchen", uid="RINCON_STALE", household_id="H1")
    calls = {"n": 0}

    def _fake_discover(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return [stale]
        raise NoSpeakersFound("everything vanished mid-retry")

    monkeypatch.setattr(controller_mod.sp, "discover_speakers", _fake_discover)

    with pytest.raises(NoSpeakersFound):
        stub_controller_say.say("Kitchen", "hello")


def test_play_via_queue_propagates_no_speakers_found_through_stale_retry():
    stale_coord = SoCoFake(player_name="Kitchen", uid="RINCON_STALE001")
    stale_coord.play_from_queue_raise = SoCoSlaveException("not the coordinator")

    resolve_calls: list[str] = []

    def resolve(name: str) -> tuple:
        resolve_calls.append(name)
        if len(resolve_calls) <= 2:
            return stale_coord, stale_coord
        raise NoSpeakersFound("everything vanished mid-retry")

    mgr = PlaylistManager(
        resolve_coordinator=resolve,
        host_ip=_HOST_IP,
        audio_port=_AUDIO_PORT,
        invalidate_speakers_cache=lambda: None,
    )
    mgr.create("retry_pl")
    mgr.add_many("retry_pl", [{"url": "http://cdn.example.com/r1.mp3", "title": "R1"}])

    with pytest.raises(NoSpeakersFound):
        mgr.play("Kitchen", "retry_pl")
