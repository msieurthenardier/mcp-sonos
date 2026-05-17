"""Tiny threaded HTTP server to host TTS files for Sonos to fetch.

Sonos speakers play HTTP URIs. We can't hand them a local file path —
they need to GET it over the network. So we spin up an ephemeral
server bound to a LAN-reachable IP, hand them URLs, then shut down.
"""

from __future__ import annotations

import contextlib
import socket
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Comment out to see Sonos GET requests for debugging.
        return


# Audio-server ports are constrained to this range so the Windows
# Firewall inbound rule (TCP 8000-8999 from the LAN) actually covers
# whichever port we pick. Override with AUDIO_PORT env var.
PORT_RANGE = (8000, 8999)


def _free_port() -> int:
    # Try each port in [PORT_RANGE]; return the first that binds.
    import os, random
    override = os.environ.get("AUDIO_PORT", "").strip()
    if override:
        return int(override)
    lo, hi = PORT_RANGE
    candidates = list(range(lo, hi + 1))
    random.shuffle(candidates)
    for p in candidates:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", p))
            s.close()
            return p
        except OSError:
            s.close()
            continue
    raise RuntimeError(f"No free port in {PORT_RANGE}")


class AudioServer:
    """Serve a directory over HTTP on a chosen interface.

    Usage:
        with AudioServer(root, host_ip="192.168.1.10") as srv:
            url = srv.url_for("greeting_Kitchen.mp3")
            speaker.play_uri(url)
    """

    def __init__(self, root: Path, host_ip: str, port: int | None = None):
        self.root = Path(root).resolve()
        self.host_ip = host_ip
        self.port = port or _free_port()
        self._httpd: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "AudioServer":
        root = self.root

        class Handler(_QuietHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=str(root), **kw)

        # Bind to 0.0.0.0 so any interface works; URLs use the LAN IP.
        self._httpd = HTTPServer(("0.0.0.0", self.port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()

    def url_for(self, filename: str) -> str:
        return f"http://{self.host_ip}:{self.port}/{filename}"
