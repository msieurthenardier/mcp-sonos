"""List Sonos speakers + groups on the LAN.

    python -m poc.discover
"""

from __future__ import annotations

from .speakers import discover_speakers, lan_host_ip


def main() -> int:
    print(f"Host LAN IP (audio server would bind here): {lan_host_ip()}")
    speakers = discover_speakers()
    if not speakers:
        print(
            "No speakers found.\n"
            "  - On WSL2: enable mirrored networking, or set SONOS_IPS=ip1,ip2,..\n"
            "  - On any host: confirm same VLAN/SSID as the speakers\n"
        )
        return 1

    print(f"\nFound {len(speakers)} visible speaker(s):\n")
    groups_seen = {}
    for s in speakers:
        info = s.get_speaker_info()
        coord = s.group.coordinator
        groups_seen.setdefault(coord.uid, coord)
        print(f"  {s.player_name:<24} {s.ip_address:<16} "
              f"model={info.get('model_name', '?')}  "
              f"coordinator={coord.player_name}")

    print(f"\n{len(groups_seen)} group(s):")
    for coord in groups_seen.values():
        members = ", ".join(sorted(m.player_name for m in coord.group.members))
        print(f"  [{coord.player_name}] -> {members}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
