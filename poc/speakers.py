"""Speaker discovery + manual-IP fallback.

SoCo's `discover()` uses SSDP multicast, which often fails on:
- WSL2 default (NAT) networking
- Docker bridge networks
- VLAN-isolated guest WiFi
- Some mesh routers with broken IGMP

When that happens, provide a comma-separated list of speaker IPs via
the SONOS_IPS env var, e.g.:

    SONOS_IPS=192.168.1.42,192.168.1.43,192.168.1.44 python -m poc.discover
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
    speakers: list[SoCo] = []
    for ip in ips:
        try:
            s = SoCo(ip)
            _ = s.player_name  # touch UPnP to validate
            speakers.append(s)
        except Exception as e:
            print(f"  [!] {ip} unreachable: {e}")
    return speakers


def discover_speakers(timeout: int = 5) -> list[SoCo]:
    """Return all *visible* Sonos zones on the LAN.

    Visible = not a hidden bonded sub/surround. Stereo pairs and bonded
    groups appear as a single visible zone.
    """
    ips = _ips_from_env()
    if ips:
        print(f"Using SONOS_IPS override: {ips}")
        return [s for s in _from_ips(ips) if s.is_visible]

    print("Running SSDP discovery...")
    found = soco.discover(timeout=timeout, allow_network_scan=True) or set()
    visible: list[SoCo] = []
    for s in found:
        # is_visible touches UPnP — a speaker that's gone offline since
        # SSDP responded will raise. Skip it rather than crash.
        try:
            if s.is_visible:
                visible.append(s)
        except Exception as e:
            print(f"  [!] skipping unreachable speaker {s.ip_address}: {e.__class__.__name__}")
    return sorted(visible, key=lambda s: s.player_name)


def lan_host_ip() -> str:
    """Best-effort LAN-reachable IP for binding the audio HTTP server.

    Override with HOST_IP env var when auto-detection picks the wrong
    interface (common on WSL2 — eth0 is NAT'd, not LAN-routable).
    """
    override = os.environ.get("HOST_IP", "").strip()
    if override:
        return override

    # Preferred trick: open a UDP socket to a public IP; the kernel
    # picks the interface it would actually route through. No packets
    # are sent. Falls back if routing to 8.8.8.8 is momentarily broken.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        pass

    # Fallback: scan interfaces for a non-loopback IPv4 address.
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                return ip
    except OSError:
        pass

    raise RuntimeError(
        "Could not determine LAN host IP. Set HOST_IP=<your-lan-ip> explicitly."
    )


def safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
