"""One-speaker debug: prove TTS playback works end-to-end on Kitchen.

    python -m poc.debug_play

Verbose: prints every transport state transition, the URI being
played, and whether the HTTP audio server saw a GET from the speaker.
"""

from __future__ import annotations

import http.server
import socketserver
import tempfile
import threading
import time
from pathlib import Path

from soco import SoCo

from .speakers import lan_host_ip
from .tts import synthesize


TARGET_IP = "192.168.1.53"  # Kitchen
TARGET_NAME = "Kitchen"


def main() -> int:
    host_ip = lan_host_ip()
    print(f"Host IP for audio server: {host_ip}")

    sp = SoCo(TARGET_IP)
    print(f"Connected to {sp.player_name} ({sp.ip_address})")
    print(f"  current volume: {sp.volume}")
    print(f"  group coordinator: {sp.group.coordinator.player_name if sp.group.coordinator else 'NONE'}")

    # Make sure it's a coordinator-of-one.
    try:
        sp.unjoin()
    except Exception as e:
        print(f"  unjoin: {e}")
    time.sleep(0.5)

    sp.volume = 40
    print(f"  set volume: {sp.volume}")

    with tempfile.TemporaryDirectory(prefix="sonos-tts-") as tmp:
        tmp_path = Path(tmp)
        mp3 = synthesize(
            "Hello, this is Sonos speaker Kitchen. Testing one two three.",
            tmp_path / "kitchen.mp3",
        )
        size = mp3.stat().st_size
        print(f"  TTS file: {mp3.name} ({size} bytes)")

        # Logging HTTP handler so we see exactly what the speaker fetches.
        hits: list[str] = []

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=str(tmp_path), **kw)
            def log_message(self, fmt, *args):
                line = fmt % args
                hits.append(line)
                print(f"    [http] {line}")

        # Pick a fixed port we can verify.
        port = 8765
        httpd = http.server.HTTPServer(("0.0.0.0", port), Handler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        print(f"  HTTP server on 0.0.0.0:{port}")

        try:
            url = f"http://{host_ip}:{port}/{mp3.name}"
            print(f"\nPlaying URL: {url}")
            sp.play_uri(url, title="DEBUG")

            # Poll transport state for 12 seconds.
            for i in range(24):
                time.sleep(0.5)
                ti = sp.get_current_transport_info()
                tr = sp.get_current_track_info()
                print(
                    f"  t+{i*0.5:>4.1f}s  state={ti.get('current_transport_state'):<14} "
                    f"position={tr.get('position'):<8} uri={tr.get('uri','')[:60]}"
                )
                if i > 4 and ti.get("current_transport_state") == "STOPPED":
                    break

            print(f"\nTotal HTTP hits from speaker: {len(hits)}")
            if not hits:
                print("  ❌ Speaker never fetched the audio — likely a network-reachability issue.")
                print(f"     From this WSL: curl -I http://{host_ip}:{port}/{mp3.name}")
        finally:
            httpd.shutdown()
            httpd.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
