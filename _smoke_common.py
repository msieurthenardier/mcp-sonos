"""Shared external MP3 track pools + reachability-based selection for the
native-queue smoke scripts (`queue_smoke.py`, `reap_smoke.py`).

Not a package module: it lives at the repo root next to the smoke scripts
that import it, is not part of `mcp_sonos` (only `mcp_sonos/` is packaged
per `[tool.hatch.build.targets.wheel]` in pyproject.toml), and is not
collected by pytest (`testpaths = ["tests"]`). It exists purely so
`queue_smoke.py` and `reap_smoke.py` don't each hardcode the same
copy-pasted track list.

Why this exists: both smoke scripts used to hardcode a single external
host (SoundHelix) for their "all-external" playlist, which is what makes
`playlist_play` route to the native-queue engine instead of the worker
engine (see CLAUDE.md "Two-engine architecture"). A SoundHelix outage
silently darkened both acceptance paths with no fallback. This module adds
a second, different-host pool and a short reachability probe that picks
the first pool that answers.

Scope of the fix — read this before assuming more coverage than exists:
- This only covers a SINGLE external-host outage. It does not make the
  smoke scripts work with no network at all; they already require a
  reachable Sonos household on the LAN (see each script's docstring), and
  if every candidate pool fails the probe we fall through to the last pool
  anyway so the caller gets a clear playlist_play/enqueue failure instead
  of a silent no-op.
- The probe runs FROM THE MACHINE RUNNING THE SMOKE SCRIPT (the MCP host),
  not from the Sonos speaker. That's a proxy for "can the speaker fetch
  this," not a guarantee — but per CLAUDE.md's operating constraints the
  MCP host and the speakers share the same LAN/egress path, so it's the
  best signal available without hardware in the loop.
"""

from __future__ import annotations

import urllib.error
import urllib.request

PROBE_TIMEOUT_SECONDS = 5.0

# Primary: SoundHelix — the long-standing default for these scripts.
EXTERNAL_TRACKS_PRIMARY = [
    {
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
        "title": "SoundHelix Song 1",
    },
    {
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3",
        "title": "SoundHelix Song 2",
    },
    {
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3",
        "title": "SoundHelix Song 3",
    },
]

# Fallback: filesamples.com — a different host from SoundHelix, so a
# single-host outage doesn't take out both pools. Verified 2026-09-26
# with `curl -sI --max-time 5` (200, Content-Type: audio/mpeg) and a
# ranged GET confirming a real MP3 (ID3) body at each URL below.
EXTERNAL_TRACKS_FALLBACK = [
    {
        "url": "https://filesamples.com/samples/audio/mp3/sample1.mp3",
        "title": "Filesamples Sample 1",
    },
    {
        "url": "https://filesamples.com/samples/audio/mp3/sample2.mp3",
        "title": "Filesamples Sample 2",
    },
    {
        "url": "https://filesamples.com/samples/audio/mp3/sample3.mp3",
        "title": "Filesamples Sample 3",
    },
]

# Ordered pools to try, primary first.
TRACK_POOLS = [EXTERNAL_TRACKS_PRIMARY, EXTERNAL_TRACKS_FALLBACK]


def _reachable(url: str, timeout: float = PROBE_TIMEOUT_SECONDS) -> bool:
    """Best-effort reachability check with a short timeout.

    Stdlib-only (urllib), no extra dependency. Tries HEAD first; if the
    host rejects HEAD (some CDNs return 405/501 for it), retries with a
    1-byte ranged GET so we still confirm *something* answers without
    pulling the whole file.
    """
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except urllib.error.HTTPError as e:
        if e.code in (405, 501):
            try:
                ranged = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
                with urllib.request.urlopen(ranged, timeout=timeout) as resp:
                    return resp.status in (200, 206)
            except Exception:
                return False
        return False
    except Exception:
        return False


def select_track_pool(pools=TRACK_POOLS, timeout: float = PROBE_TIMEOUT_SECONDS):
    """Return the first pool whose representative (first) track is reachable.

    Probes only the first URL of each pool — one short request is a
    sufficient proxy for "is this host up" without paying 3x the latency
    per candidate pool. If no pool's first track answers, returns the last
    pool anyway (unprobed) so callers still get a URL set to try; a total
    network outage at smoke time surfaces as a clear playlist_play/enqueue
    failure rather than an empty playlist.
    """
    for pool in pools:
        if not pool:
            continue
        if _reachable(pool[0]["url"], timeout=timeout):
            return pool
    return pools[-1]
