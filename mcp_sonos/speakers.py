"""Speaker discovery + name resolution.

SSDP first, then SONOS_IPS env-var fallback for environments where
multicast is unreliable (WSL2 default networking, Docker bridges,
guest-VLAN-isolated WiFi).
"""

from __future__ import annotations

import os
import socket
from typing import Iterable

import soco
from soco import SoCo


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


def discover_speakers(timeout: int = 5) -> list[SoCo]:
    """Return all *visible* Sonos zones on the LAN, sorted by name."""
    ips = _ips_from_env()
    if ips:
        speakers = [s for s in _from_ips(ips) if _safe_is_visible(s)]
    else:
        found = soco.discover(timeout=timeout, allow_network_scan=True) or set()
        speakers = [s for s in found if _safe_is_visible(s)]
    return sorted(speakers, key=lambda s: s.player_name)


def _safe_is_visible(speaker: SoCo) -> bool:
    # `is_visible` touches UPnP; a speaker that's gone offline since
    # SSDP responded will raise. Treat as not-visible.
    try:
        return bool(speaker.is_visible)
    except Exception:
        return False


def lan_host_ip() -> str:
    """LAN-reachable IP for binding the audio HTTP server.

    Override with HOST_IP. Falls back through a UDP-routing probe and
    then an interface scan.
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
