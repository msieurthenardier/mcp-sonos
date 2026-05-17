"""Thin re-export — POC scripts use the same Piper TTS as the MCP server.

POC interface used to take a target path; the production module is
cache-dir based. Adapter below preserves the old call site.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from mcp_sonos.tts import synthesize as _synthesize


def synthesize(text: str, out_path: Path, lang: str = "en", slow: bool = False) -> Path:
    """Write `text` to `out_path` (extension auto-corrected to .wav for Piper)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cached = _synthesize(text, out_path.parent)
    if cached != out_path:
        # Copy under the caller-requested filename; Piper outputs WAV so
        # we ignore the suggested extension if it differs.
        target = out_path.with_suffix(".wav")
        shutil.copy2(cached, target)
        return target
    return cached
