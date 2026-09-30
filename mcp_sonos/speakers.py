"""Speaker discovery + name resolution.

Zero-config discovery pipeline, in order, each stage running only if the
previous one found nothing visible:

1. **Configured seeds** (`SONOS_IPS`, optional). Each configured IP is
   gated by a quick TCP probe on the Sonos control port (1400) before any
   UPnP call is attempted, then the first seed that answers is expanded
   via its `visible_zones` — this returns the whole visible household,
   not just the seed itself. A dead or non-Sonos seed is recorded and
   skipped; the next seed is tried.
2. **Learned seeds** (in-process, no configuration). The IPs from the
   last *successful* discovery in this process, tried the same
   gate-then-expand way as configured seeds, skipping any IP already
   tried in stage 1. This is what keeps steady-state discovery from
   ever re-scanning: once the household has been found once, subsequent
   calls in the same process go straight back to it. A stale or dead
   learned seed is harmless — it just falls through to the next stage.
3. **Bounded subnet scan** (`soco.discovery.scan_network`), derived from
   the advertised host IP's local /24-or-narrower network. Override with
   `SONOS_SCAN_NETWORKS` (comma-separated CIDRs). Deliberately
   rate-limited (a moderate thread count) — a full-speed scan briefly
   disrupts LAN connections to the real speakers on some hosts (observed
   under WSL2 mirrored networking).
4. **SSDP**, as a last resort (`soco.discover`, network-scan fallback
   disabled — stage 3 already covers that case).

When all stages find nothing, `discover_speakers` raises
`NoSpeakersFound`, a diagnostic `RuntimeError` naming every seed's
outcome (configured and learned), the networks scanned (and any rejected
`SONOS_SCAN_NETWORKS` entries), the SSDP result, and what the operator
can set. Learned seeds are left untouched on total failure, and replaced
wholesale on the next success.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Iterable

import ifaddr
import soco
import soco.discovery
from soco import SoCo


# Sonos device control port. Used both as the seed reachability gate and
# (historically) as the firmware reboot endpoint (see controller.py).
SEED_PORT = 1400

# Seed TCP-reachability probe timeout. A dead seed costs ~4.1s via a raw
# UPnP call (probed 2026-09-28); gating with a sub-second TCP connect first
# keeps a dead/stale SONOS_IPS entry cheap.
SEED_PROBE_TIMEOUT = 1.0

# The derived default scan network is clamped to at least /24 (<= 254
# hosts) regardless of how broad the adapter's own network is.
MIN_SCAN_PREFIX = 24

# SONOS_SCAN_NETWORKS entries broader than /16 are rejected outright —
# unlike the derived default, explicit overrides are not clamped, only
# bounded, so a fat-fingered /8 doesn't turn into an accidental full-LAN
# sweep.
SCAN_OVERRIDE_MIN_PREFIX = 16

# soco.discovery.scan_network's default (256 threads, ~254 simultaneous TCP
# connects) was measured on 2026-09-28 to disrupt in-flight connections to
# the real speakers for 1-3s afterward (ENETUNREACH/EHOSTUNREACH/timeouts;
# observed under WSL2 mirrored networking). 32 threads took ~2.5s with zero
# anomalies across trials, vs. ~0.55s at 256 and ~8.5s at 8. Not an env var:
# this is an internal safety margin, not something an operator should need
# to tune.
SCAN_MAX_THREADS = 32


def _ips_from_env() -> list[str]:
    raw = os.environ.get("SONOS_IPS", "").strip()
    if not raw:
        return []
    return [ip.strip() for ip in raw.split(",") if ip.strip()]


def _from_ips(ips: Iterable[str]) -> list[SoCo]:
    out: list[SoCo] = []
    for ip in ips:
        try:
            s = SoCo(ip)
            _ = s.player_name  # touch UPnP to validate
            out.append(s)
        except Exception:
            # Caller logs; we just skip silently here.
            continue
    return out


# ---- stage 1: configured seeds ----------------------------------------------


def _probe_port(ip: str, port: int = SEED_PORT, timeout: float = SEED_PROBE_TIMEOUT) -> bool:
    """Quick TCP reachability gate, cheaper than a UPnP round-trip."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _expand_seed(ip: str) -> list[SoCo]:
    """Expand a live seed IP to its full visible household.

    May raise (not-Sonos device, UPnP failure, etc.) — the caller records
    the failure and moves on to the next seed.
    """
    seed = SoCo(ip)
    zones = seed.visible_zones
    return [z for z in zones if _safe_is_visible(z)]


def _gate_and_expand_stage(ips: list[str], label: str) -> tuple[list[SoCo], list[str]]:
    """Shared gate-then-expand loop for both seed stages.

    Tries each IP in order: a TCP reachability gate, then `_expand_seed`.
    The first one that answers the gate AND expands to a non-empty visible
    household wins; every IP's outcome is recorded for diagnostics.
    `label` ("seed" / "learned seed") only affects trace-line wording, so
    the two stages read distinctly in a `NoSpeakersFound` message.
    """
    trace: list[str] = []
    for ip in ips:
        if not _probe_port(ip):
            trace.append(f"{label} {ip}: unreachable (TCP {SEED_PORT} probe failed)")
            continue
        try:
            zones = _expand_seed(ip)
        except Exception as e:
            trace.append(f"{label} {ip}: reachable but expansion failed ({e})")
            continue
        if not zones:
            trace.append(f"{label} {ip}: reachable, no visible zones")
            continue
        trace.append(f"{label} {ip}: expanded to {len(zones)} visible zone(s)")
        return zones, trace
    return [], trace


def _seed_stage(ips: list[str]) -> tuple[list[SoCo], list[str]]:
    """Try each configured seed in order; return (speakers, trace).

    "No seeds configured" is itself recorded for diagnostics.
    """
    if not ips:
        return [], ["seeds: none configured (SONOS_IPS is empty)"]
    return _gate_and_expand_stage(ips, "seed")


# ---- stage 2: learned seeds --------------------------------------------------

# IPs from the last *successful* discover_speakers() call, process-wide.
# Replaced wholesale on every success (see `_record_learned_seeds`); left
# untouched when a call raises NoSpeakersFound. Plain IP strings, not SoCo
# objects — SoCo objects are per-IP singletons anyway, and strings keep
# tests simple. Assigning a new list object (never mutating in place) keeps
# this safe without a lock: discovery runs within a single MCP request at
# a time.
_learned_seed_ips: list[str] = []


def _reset_learned_seeds() -> None:
    """Test-only: clear learned-seed state so tests don't leak between runs."""
    global _learned_seed_ips
    _learned_seed_ips = []


def _record_learned_seeds(speakers: list[SoCo]) -> None:
    """Replace the learned-seed IPs wholesale from a successful discovery.

    `speakers` is expected already sorted by player name (discover_speakers
    sorts before calling this), so learned seeds are recorded in that same
    order — cosmetic, since the learned stage just tries them in order.
    """
    global _learned_seed_ips
    _learned_seed_ips = [s.ip_address for s in speakers]


def _learned_seed_stage(configured_ips: list[str]) -> tuple[list[SoCo], list[str]]:
    """Try each learned seed in order, skipping any already tried as a
    configured seed this call; return (speakers, trace).

    Silent (no trace lines) on a cold start (no learned seeds recorded
    yet in this process) — there is nothing to report. When every learned
    seed is filtered out by overlap with the configured seeds, that's
    recorded distinctly so diagnostics don't look like the stage never ran.
    """
    if not _learned_seed_ips:
        return [], []
    candidates = [ip for ip in _learned_seed_ips if ip not in configured_ips]
    if not candidates:
        return [], ["learned seeds: all already tried as configured seeds"]
    return _gate_and_expand_stage(candidates, "learned seed")


# ---- stage 3: bounded subnet scan ------------------------------------------


def _adapter_prefix_for(ip: str) -> int | None:
    """Return the network_prefix of the adapter carrying `ip`, or None."""
    try:
        adapters = ifaddr.get_adapters()
    except Exception:
        return None
    for adapter in adapters:
        for a_ip in adapter.ips:
            if a_ip.is_IPv4 and a_ip.ip == ip:
                return a_ip.network_prefix
    return None


def _default_scan_network(host_ip: str) -> str:
    """CIDR for `host_ip`'s adapter, prefix clamped to >= MIN_SCAN_PREFIX.

    Falls back to `host_ip`'s own /MIN_SCAN_PREFIX when no adapter carries it
    (e.g. HOST_IP overridden to something not locally bound).
    """
    prefix = _adapter_prefix_for(host_ip)
    prefix = MIN_SCAN_PREFIX if prefix is None else max(prefix, MIN_SCAN_PREFIX)
    return str(ipaddress.ip_network(f"{host_ip}/{prefix}", strict=False))


def _scan_networks() -> tuple[list[str], list[str]]:
    """Return (networks_to_scan, rejected) for stage 3.

    `SONOS_SCAN_NETWORKS` (comma-separated CIDRs), when set, replaces the
    derived default entirely. Its entries are validated but NOT clamped;
    malformed entries or ones broader than /SCAN_OVERRIDE_MIN_PREFIX are
    skipped and recorded in `rejected`.
    """
    override = os.environ.get("SONOS_SCAN_NETWORKS", "").strip()
    if not override:
        return [_default_scan_network(lan_host_ip())], []

    networks: list[str] = []
    rejected: list[str] = []
    for raw in override.split(","):
        entry = raw.strip()
        if not entry:
            continue
        try:
            net = ipaddress.ip_network(entry, strict=False)
        except ValueError as e:
            rejected.append(f"{entry!r} (malformed: {e})")
            continue
        if net.prefixlen < SCAN_OVERRIDE_MIN_PREFIX:
            rejected.append(f"{entry!r} (broader than /{SCAN_OVERRIDE_MIN_PREFIX})")
            continue
        networks.append(str(net))
    return networks, rejected


def _scan(networks: list[str]) -> list[SoCo]:
    found = (
        soco.discovery.scan_network(
            networks_to_scan=networks,
            multi_household=False,
            include_invisible=False,
            max_threads=SCAN_MAX_THREADS,
        )
        or set()
    )
    return [s for s in found if _safe_is_visible(s)]


# ---- stage 4: SSDP (last resort) -------------------------------------------


def _ssdp(timeout: int) -> list[SoCo]:
    found = soco.discover(timeout=timeout, allow_network_scan=False) or set()
    return [s for s in found if _safe_is_visible(s)]


# ---- diagnostics ------------------------------------------------------------


class NoSpeakersFound(RuntimeError):
    """Raised when configured seeds, learned seeds, the bounded scan, and
    SSDP all find nothing.

    Signals an environment/network failure (same taxonomy as
    `lan_host_ip()`'s failure), not a bad name — see `SpeakerNotFound` for
    that case. The message names every stage's outcome (including any
    learned seeds that were tried) plus actionable hints; FastMCP forwards
    it to the calling agent verbatim.
    """


def _diagnostic_message(trace: list[str]) -> str:
    lines = [
        "No Sonos speakers found (seeds, learned seeds, bounded scan, and "
        "SSDP all came up empty):"
    ]
    lines.extend(f"  - {line}" for line in trace)
    lines.append(
        "Hints: set SONOS_IPS to one or more known speaker IPs, or "
        "SONOS_SCAN_NETWORKS to the correct subnet CIDR(s) (comma-separated, "
        "each /16 or narrower), or HOST_IP if the wrong network adapter was "
        "picked for the default scan. Confirm this host is on the same "
        "LAN/VLAN as the speakers, and that the Sonos household's UPnP "
        "setting is enabled (Security Settings, firmware 85.0 and later)."
    )
    return "\n".join(lines)


# ---- orchestrator ------------------------------------------------------------


def discover_speakers(*, timeout: int = 5) -> list[SoCo]:
    """Return all *visible* Sonos zones on the LAN, sorted by name.

    Four-stage pipeline (configured seeds -> learned seeds -> bounded scan
    -> SSDP), each stage running only if the previous produced nothing.
    See the module docstring for the full contract. Raises
    `NoSpeakersFound` (a `RuntimeError`) with a diagnostic trace when every
    stage is empty; on success, replaces the learned-seed state wholesale.

    `timeout` bounds the SSDP last-resort stage only; it has no effect on
    the seed or scan stages. Keyword-only so future stage-tuning
    parameters can be added the same way without breaking callers — every
    existing call site (the controller included) calls this with zero
    arguments.
    """
    trace: list[str] = []

    ips = _ips_from_env()
    speakers, seed_trace = _seed_stage(ips)
    trace.extend(seed_trace)

    if not speakers:
        speakers, learned_trace = _learned_seed_stage(ips)
        trace.extend(learned_trace)

    if not speakers:
        networks, rejected = _scan_networks()
        for entry in rejected:
            trace.append(f"SONOS_SCAN_NETWORKS rejected {entry}")
        if networks:
            speakers = _scan(networks)
            outcome = f"found {len(speakers)} zone(s)" if speakers else "found nothing"
            trace.append(f"scan of {', '.join(networks)}: {outcome}")
        else:
            trace.append("scan skipped: no valid network to scan")

    if not speakers:
        speakers = _ssdp(timeout)
        outcome = f"found {len(speakers)} zone(s)" if speakers else "found nothing"
        trace.append(f"SSDP: {outcome}")

    if not speakers:
        raise NoSpeakersFound(_diagnostic_message(trace))

    speakers = sorted(speakers, key=lambda s: s.player_name)
    _record_learned_seeds(speakers)
    return speakers


def _safe_is_visible(speaker: SoCo) -> bool:
    # `is_visible` touches UPnP; a speaker that's gone offline since
    # discovery responded will raise. Treat as not-visible.
    try:
        return bool(speaker.is_visible)
    except Exception:
        return False


def lan_host_ip() -> str:
    """LAN-reachable IP for binding the audio HTTP server.

    Override with HOST_IP. Falls back through a UDP-routing probe and
    then an interface scan. Also used (via HOST_IP) to bound the default
    subnet-scan network — see `_default_scan_network`.
    """
    override = os.environ.get("HOST_IP", "").strip()
    if override:
        return override

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                return ip
    except OSError:
        pass

    raise RuntimeError("Could not determine LAN host IP. Set HOST_IP=<lan-ip>.")


def safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


class SpeakerNotFound(ValueError):
    """Raised when a name can't be resolved to a speaker."""

    def __init__(self, name: str, available: list[str]):
        suggestions = ", ".join(repr(n) for n in available)
        super().__init__(
            f"No speaker named {name!r}. Available: {suggestions}"
        )
        self.name = name
        self.available = available


def resolve_name(speakers: Iterable[SoCo], name: str) -> SoCo:
    """Case-insensitive name lookup. Raises SpeakerNotFound on miss."""
    speakers = list(speakers)
    needle = name.strip().casefold()
    for s in speakers:
        if s.player_name.casefold() == needle:
            return s
    raise SpeakerNotFound(name, [s.player_name for s in speakers])
