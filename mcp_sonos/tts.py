"""Offline TTS via Piper (neural, local, ~real-time).

Voice models live in ~/.cache/mcp-sonos/voices/ and are auto-downloaded
on first use. The voice is loaded once per process (PiperVoice.load is
expensive — ~1s + ONNX session init).

Cache strategy: same (text, voice, length_scale) → same WAV file.
Avoids re-synthesizing identical announcements.
"""

from __future__ import annotations

import hashlib
import os
import sys
import threading
import urllib.request
import wave
from pathlib import Path
from typing import ClassVar

from piper import PiperVoice, SynthesisConfig


# Default voice. Override via env var PIPER_VOICE. Format is the
# "<lang>-<speaker>-<quality>" used on huggingface.co/rhasspy/piper-voices.
DEFAULT_VOICE = "en_US-lessac-medium"

# Where on Hugging Face the voice files live. Path layout is
# en/<region>/<speaker>/<quality>/<file>. We parse the voice name to
# build the URL.
HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


def _voices_cache_dir() -> Path:
    override = os.environ.get("PIPER_DATA_DIR", "").strip()
    base = Path(override) if override else Path.home() / ".cache" / "mcp-sonos" / "voices"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _voice_paths(voice: str, cache_dir: Path) -> tuple[Path, Path]:
    return cache_dir / f"{voice}.onnx", cache_dir / f"{voice}.onnx.json"


def _hf_url(voice: str, suffix: str) -> str:
    # voice: en_US-lessac-medium → en/en_US/lessac/medium/<voice><suffix>
    lang_full, speaker, quality = voice.split("-")
    lang_short = lang_full.split("_")[0]
    return (
        f"{HF_BASE}/{lang_short}/{lang_full}/{speaker}/{quality}/{voice}{suffix}"
    )


def _download(url: str, dest: Path, label: str) -> None:
    print(f"  Downloading {label} → {dest.name} ...", file=sys.stderr, flush=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as f:
        total = int(resp.headers.get("Content-Length", 0))
        read = 0
        chunk = 1 << 16
        while True:
            b = resp.read(chunk)
            if not b:
                break
            f.write(b)
            read += len(b)
            if total:
                pct = read * 100 // total
                print(
                    f"\r    {read/1e6:6.1f} MB / {total/1e6:6.1f} MB  ({pct}%)",
                    end="",
                    file=sys.stderr,
                    flush=True,
                )
    print("", file=sys.stderr, flush=True)
    tmp.rename(dest)


def _ensure_voice(voice: str) -> Path:
    """Make sure both <voice>.onnx and <voice>.onnx.json exist locally. Returns the model path."""
    cache = _voices_cache_dir()
    onnx, cfg = _voice_paths(voice, cache)
    if not onnx.exists() or onnx.stat().st_size < 1024:
        _download(_hf_url(voice, ".onnx"), onnx, label="voice model")
    if not cfg.exists():
        _download(_hf_url(voice, ".onnx.json"), cfg, label="voice config")
    return onnx


class _VoiceCache:
    """Process-wide voice cache. PiperVoice.load is the expensive bit."""

    _lock: ClassVar[threading.Lock] = threading.Lock()
    _voices: ClassVar[dict[str, PiperVoice]] = {}

    @classmethod
    def get(cls, voice: str) -> PiperVoice:
        with cls._lock:
            if voice not in cls._voices:
                model_path = _ensure_voice(voice)
                cls._voices[voice] = PiperVoice.load(str(model_path))
            return cls._voices[voice]


def _cache_key(text: str, voice: str, length_scale: float) -> str:
    h = hashlib.sha1(
        f"{voice}|{length_scale}|{text}".encode("utf-8")
    ).hexdigest()[:16]
    return f"tts_{h}.wav"


def synthesize(
    text: str,
    cache_dir: Path,
    *,
    voice: str | None = None,
    length_scale: float = 1.0,
    # `lang` kept for API parity with the old gTTS-based synthesize.
    # Ignored — voice selection happens via the `voice` argument.
    lang: str | None = None,
) -> Path:
    """Synthesize `text` to a WAV in `cache_dir`. Returns the path.

    Re-uses an existing cached file when the (text, voice, length_scale)
    triple matches. WAV output works fine on Sonos at Piper's native
    22050 Hz / 16-bit PCM / mono.
    """
    voice_name = (voice or os.environ.get("PIPER_VOICE") or DEFAULT_VOICE).strip()
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / _cache_key(text, voice_name, length_scale)
    if out.exists() and out.stat().st_size > 0:
        return out

    pv = _VoiceCache.get(voice_name)
    syn_config = SynthesisConfig(length_scale=length_scale)
    tmp = out.with_suffix(".wav.part")
    with wave.open(str(tmp), "wb") as wav:
        pv.synthesize_wav(text, wav, syn_config=syn_config)
    tmp.rename(out)
    return out
