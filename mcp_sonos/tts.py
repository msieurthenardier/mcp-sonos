"""Offline TTS via Piper (neural, local, ~real-time).

Voice models live in ~/.cache/mcp-sonos/voices/ and are auto-downloaded
on first use. The voice is loaded once per process (PiperVoice.load is
expensive — ~1s + ONNX session init).

Cache strategy: same (text, voice, length_scale) → same WAV file.
Avoids re-synthesizing identical announcements.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
import threading
import urllib.request
import wave
from pathlib import Path
from typing import ClassVar

from piper import PiperVoice, SynthesisConfig


log = logging.getLogger("mcp_sonos.tts")


# Default voice. Override via env var PIPER_VOICE. Format is the
# "<lang>-<speaker>-<quality>" used on huggingface.co/rhasspy/piper-voices.
DEFAULT_VOICE = "en_US-lessac-medium"

# Where on Hugging Face the voice files live. Path layout is
# en/<region>/<speaker>/<quality>/<file>. We parse the voice name to
# build the URL.
HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


# Pinned SHA-256 hashes for known Piper voice ONNX models. Cross-referenced
# against HuggingFace's LFS pointer metadata at
# https://huggingface.co/rhasspy/piper-voices/raw/main/<path>/<voice>.onnx
# Voices not listed here are trust-on-first-use — _verify_or_log will emit a
# warning with the observed hash so the operator can pin it.
KNOWN_VOICE_HASHES: dict[str, str] = {
    "en_US-lessac-medium": "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f",
}


# Per-process cache of voice names that have been hash-verified against
# KNOWN_VOICE_HASHES (or warned-on for the no-pin case). Lets _ensure_voice
# skip the ~0.5s hash work on subsequent calls in the same process.
#
# Note: this set is mutated only inside _ensure_voice, which is called
# under _VoiceCache._lock by the existing caller. No additional locking
# needed — but if a future caller bypasses _VoiceCache, add a lock.
_verified_voices: set[str] = set()


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


def _hash_voice_file(p: Path) -> str:
    """SHA-256 of file at `p`, computed in 64 KB chunks."""
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_or_log(voice_name: str, observed: str, file_for_quarantine: Path) -> None:
    """Compare `observed` SHA-256 against the pin for `voice_name`.

    - If no pin is known: log a `warning` with the observed hash so the
      operator can pin it. Returns normally (trust-on-first-use).
    - If pinned and mismatched: rename `file_for_quarantine` with a
      `.suspect` suffix and raise RuntimeError naming both hashes.
    - If pinned and matched: return normally.
    """
    expected = KNOWN_VOICE_HASHES.get(voice_name)
    if expected is None:
        log.warning(
            "Piper voice %r has no pinned hash. Observed SHA-256: %s. "
            "Add to KNOWN_VOICE_HASHES to pin.",
            voice_name,
            observed,
        )
        return
    if observed != expected:
        # Quarantine, don't delete — operator can inspect.
        quarantine = file_for_quarantine.with_suffix(
            file_for_quarantine.suffix + ".suspect"
        )
        file_for_quarantine.rename(quarantine)
        raise RuntimeError(
            f"Piper voice {voice_name!r} hash mismatch. "
            f"Expected {expected[:16]}..., got {observed[:16]}.... "
            f"File moved to {quarantine}; investigate before retrying."
        )


def _download(url: str, dest: Path, label: str, voice_name: str | None) -> None:
    """Download `url` to `dest` atomically. If `voice_name` is not None,
    verify the downloaded `.part` file against KNOWN_VOICE_HASHES before
    the atomic rename. Pass `voice_name=None` for non-voice-model files
    (e.g. the JSON config) to skip the hash check entirely.
    """
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
    if voice_name is not None:
        observed = _hash_voice_file(tmp)
        _verify_or_log(voice_name, observed, tmp)
    tmp.rename(dest)


def _ensure_voice(voice: str) -> Path:
    """Make sure both <voice>.onnx and <voice>.onnx.json exist locally. Returns the model path.

    Hash-verifies the ONNX file against KNOWN_VOICE_HASHES on first call
    per process (both fresh downloads and pre-existing files). Per-process
    `_verified_voices` cache skips the hash work on subsequent calls.
    """
    cache_dir = _voices_cache_dir()
    onnx, cfg = _voice_paths(voice, cache_dir)
    if not onnx.exists() or onnx.stat().st_size < 1024:
        _download(_hf_url(voice, ".onnx"), onnx, label="voice model", voice_name=voice)
        _verified_voices.add(voice)
    elif voice not in _verified_voices:
        # Pre-pin file or first run with a new pin — verify now.
        observed = _hash_voice_file(onnx)
        _verify_or_log(voice, observed, onnx)  # raises on mismatch
        _verified_voices.add(voice)
    if not cfg.exists():
        _download(_hf_url(voice, ".onnx.json"), cfg, label="voice config", voice_name=None)
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
