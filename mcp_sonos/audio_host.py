"""Persistent threaded HTTP server hosting audio files for Sonos to fetch.

Lifecycle is owned by SonosController: started once on first use,
stopped at process exit. Pinned to a port in PORT_RANGE so the
Windows Firewall rule (TCP 8000-8999) actually covers it.
"""

from __future__ import annotations

import contextlib
import http.server
import os
import shutil
import socket
import threading
import urllib.parse
from pathlib import Path


PORT_RANGE = (8000, 8999)


def _validate_port(p: int) -> int:
    if not (PORT_RANGE[0] <= p <= PORT_RANGE[1]):
        raise ValueError(
            f"AUDIO_PORT={p} is outside the {PORT_RANGE[0]}-{PORT_RANGE[1]} "
            f"range. The default Windows Firewall / iptables rule scopes "
            f"inbound traffic to this range; out-of-range ports will be "
            f"silently dropped by the firewall, with speakers transitioning "
            f"then stopping. Set AUDIO_PORT within {PORT_RANGE[0]}-{PORT_RANGE[1]} "
            f"or update the firewall rule."
        )
    return p


def _pick_port(preferred: int | None = None) -> int:
    if preferred is not None:
        return _validate_port(preferred)
    env = os.environ.get("AUDIO_PORT", "").strip()
    if env:
        return _validate_port(int(env))
    lo, hi = PORT_RANGE
    # Walk linearly; pick the first free. Deterministic is nicer for
    # logs than random.
    for p in range(lo, hi + 1):
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            try:
                s.bind(("0.0.0.0", p))
                return p
            except OSError:
                continue
    raise RuntimeError(f"No free port in {PORT_RANGE}")


class AudioHost:
    """Long-lived HTTP server serving `root` at http://<host_ip>:<port>/."""

    def __init__(self, root: Path, host_ip: str, port: int | None = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.host_ip = host_ip
        self.port = _pick_port(port)
        self._httpd: http.server.HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._httpd is not None:
            return
        root = self.root

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=str(root), **kw)

            def log_message(self, fmt, *args):  # silence per-request noise
                return

            def list_directory(self, path):  # block GET / enumeration
                self.send_error(404)
                return None

        self._httpd = http.server.HTTPServer(("0.0.0.0", self.port), Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name=f"audio-host-{self.port}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        self._thread = None

    def url_for(self, filename: str) -> str:
        safe = urllib.parse.quote(filename)
        return f"http://{self.host_ip}:{self.port}/{safe}"

    def stage(self, source: Path) -> str:
        """Copy a file into the served root (idempotent) and return its URL.

        Useful for arbitrary local files the agent wants Sonos to play.
        Files in `cache_dir` (where TTS lives) are already served — no
        copy needed; just pass `source.name`.
        """
        source = Path(source).resolve()
        target = self.root / source.name
        if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
            shutil.copy2(source, target)
        return self.url_for(target.name)
