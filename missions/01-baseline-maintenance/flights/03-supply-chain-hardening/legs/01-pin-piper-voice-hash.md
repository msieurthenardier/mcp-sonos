# Leg: 01-pin-piper-voice-hash

**Status**: ready
**Flight**: [Supply-Chain Hardening](../flight.md)

## Objective
Pin a SHA-256 hash for the default Piper voice and verify it on download; for non-default voices, log a trust-on-first-use warning that includes the observed hash so the operator can pin it later (Finding F8 from [Maintenance Report 2026-05-18](../../../../maintenance/2026-05-18.md)).

## Context
- `tts.py:55-77` downloads ONNX models from huggingface.co over HTTPS using `urllib.request.urlopen`. There is no checksum, signature, or pinned-hash verification — only a `> 1024 bytes` minimum-size sanity check.
- Default urllib *does* verify TLS certs, so the attacker needs real TLS subversion (state actor, corporate-proxy MITM, HuggingFace compromise). Improbable for a hobbyist LAN deployment, but the attack chain (poisoned ONNX → onnxruntime CVE → RCE on host) is real.
- Defense-in-depth recommendation per Architect.

## Inputs
- `mcp_sonos/tts.py:55-77` voice download logic
- Existing voice cache directory layout (`~/.cache/mcp-sonos/voices/`)

## Outputs
- Default voice (`en_US-lessac-medium`) has a hash pinned in code; download verifies against it
- Mismatched hash deletes the bad file and raises a clear error
- Non-default voices log a `warning` with the observed SHA-256 once per download

## Acceptance Criteria
- [ ] `KNOWN_VOICE_HASHES` (or similar) dict in `tts.py` mapping voice name → SHA-256 hex string; populated with at least the default voice's hash
- [ ] **Pin obtained from a known-good source, not just whatever's already on disk.** Cross-reference against HuggingFace's blob metadata at `https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx` (HF UI shows the file's SHA-256 in the metadata; the API at `/api/models/rhasspy/piper-voices` exposes it programmatically). Record the source of truth in the flight log alongside the hash for auditability
- [ ] Download path computes SHA-256 of the `.part` file before atomic rename; compares against the pin (if present)
- [ ] **Verify-existing path**: if `onnx.exists() and st_size >= 1024` AND a pin is known for that voice, hash the existing file and verify. On mismatch: rename to `.onnx.suspect`, log a clear error, force re-download by treating the file as missing. (This catches users with pre-pin tampered files who would otherwise skip the new check entirely.)
- [ ] Mismatch on download or verify-existing: file moved to `.suspect` suffix or deleted; `RuntimeError` raised with a message naming the expected and observed hashes
- [ ] Non-default voice (no pin): emit a `warning`-level log with the observed hash, suggesting the operator add it to `KNOWN_VOICE_HASHES`
- [ ] First-run download of `en_US-lessac-medium` succeeds against the pinned hash (proves the pin value is correct)
- [ ] Hash-only verify path is cached in-process — don't re-hash the existing file on every `_ensure_voice` call after the first verify in this process

## Verification Steps

**Hardware-independent path (preferred — `smoke_test.py` is currently failing per mission Known Issues so don't gate on it):**
- Delete `~/.cache/mcp-sonos/voices/en_US-lessac-medium.onnx` (back it up to `.bak` first to save bandwidth).
- Run: `.venv/bin/python -c "from mcp_sonos.tts import _ensure_voice; _ensure_voice('en_US-lessac-medium')"`. Should download fresh and verify against the pin without error.
- Tamper test: restore the backup but flip a byte (`dd if=/dev/urandom of=<voice>.onnx bs=1 count=1 conv=notrunc seek=1024`). Re-run the `_ensure_voice` call → should detect mismatch and either rename to `.onnx.suspect` or re-download.
- Trust-on-first-use: pick a voice with no pin (e.g. `en_GB-alan-medium`); run `_ensure_voice('en_GB-alan-medium')` and confirm the `warning` log appears with the observed SHA-256.
- Verify-existing path: with the pinned voice file already present and unchanged, call `_ensure_voice('en_US-lessac-medium')` — first call hashes; subsequent calls in the same process should be cached and skip the hash work.

**Hardware path (optional, only if hardware happens to be reachable)**: smoke tests touch `say()` which would exercise the voice path indirectly. Don't gate on this — the direct calls above are sufficient.

## Implementation Guidance

1. **Acquire the pinned SHA-256 from a known-good source, not just whatever's on local disk.** The default voice (`en_US-lessac-medium.onnx`) lives publicly at `https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx`. HuggingFace publishes file-level SHA-256s via:
   - The UI: the file detail page shows "SHA256:" in the metadata sidebar
   - The API: `curl -s https://huggingface.co/api/models/rhasspy/piper-voices | jq` returns blob metadata
   - The LFS pointer: `curl -sL <raw_url>` returns a small pointer file containing `oid sha256:<hash>`
   - Cross-checking against your local sha256: `sha256sum ~/.cache/mcp-sonos/voices/en_US-lessac-medium.onnx`

   If the local hash matches the upstream-published hash, record the value. If they diverge, **stop and surface the divergence** — your local file may be tampered, or upstream has been republished. In the flight log, record both the hash value AND the source you used to verify it (the URL or API endpoint). This is the audit trail for the pin.

   Note: the JSON config file (`.onnx.json`) is small metadata-only; pinning it is optional. The ONNX is the executable surface.

2. **Add a hashes module** (or extend `tts.py`):
   ```python
   KNOWN_VOICE_HASHES: dict[str, str] = {
       "en_US-lessac-medium": "<sha256-hex-from-step-1>",
   }
   ```

3. **In the download path**, after the file is fully written but before the atomic rename, compute the SHA-256. Factor out a small helper so the same hash-then-decide logic is used by the verify-existing path in step 5:
   ```python
   import hashlib

   def _hash_voice_file(p: Path) -> str:
       h = hashlib.sha256()
       with open(p, "rb") as f:
           for chunk in iter(lambda: f.read(1 << 16), b""):
               h.update(chunk)
       return h.hexdigest()

   def _verify_or_log(voice_name: str, observed: str, file_for_quarantine: Path) -> None:
       """Compare against pin; on mismatch raise; on no-pin log warning."""
       expected = KNOWN_VOICE_HASHES.get(voice_name)
       if expected is None:
           log.warning(
               "Piper voice %r has no pinned hash. Observed SHA-256: %s. "
               "Add to KNOWN_VOICE_HASHES to pin.",
               voice_name, observed,
           )
           return
       if observed != expected:
           # Quarantine, don't delete — operator can inspect
           quarantine = file_for_quarantine.with_suffix(file_for_quarantine.suffix + ".suspect")
           file_for_quarantine.rename(quarantine)
           raise RuntimeError(
               f"Piper voice {voice_name!r} hash mismatch. "
               f"Expected {expected[:16]}..., got {observed[:16]}.... "
               f"File moved to {quarantine.name}; investigate before retrying."
           )
   ```

4. **In `_download`**, call `_verify_or_log(voice_name, _hash_voice_file(part_path), part_path)` before the atomic rename. The `.part` file is the file in quarantine on mismatch.

5. **In `_ensure_voice`**, add a verify-existing path. Currently the function returns early when `onnx.exists() and st_size >= 1024`; extend to also verify the hash on first call per process. Cache the verified-set in a module-level `set` so subsequent calls in the same process skip the hash work:
   ```python
   _verified_voices: set[str] = set()

   def _ensure_voice(voice: str, cache: Path | None = None) -> Path:
       onnx, cfg = _voice_paths(voice, cache)
       if not onnx.exists() or onnx.stat().st_size < 1024:
           _download(...)  # download path verifies via step 4
       elif voice not in _verified_voices:
           # Pre-pin file or first run with a new pin — verify now
           observed = _hash_voice_file(onnx)
           _verify_or_log(voice, observed, onnx)  # raises on mismatch
           _verified_voices.add(voice)
       # cfg path: same logic if you want to pin it too; skip otherwise
       if not cfg.exists():
           _download(_hf_url(voice, ".onnx.json"), cfg, label="voice config")
       return onnx
   ```
   This closes the "pre-pin tampered cached file" gap — every existing user upgrading the package will get verification on the next `say()` call.

6. **Then proceed with the atomic rename** in the download path as today.

5. **Document** in README (Configuration section): briefly note that the default voice is hash-pinned and that non-default voices are trust-on-first-use.

## Files Affected
- `mcp_sonos/tts.py` — hash dict + verification block in the download path
- `README.md` — short note in the configuration section

## Edge Cases
- **HuggingFace re-uploads with a new hash**: when this happens, the pin is wrong and downloads fail until the maintainer updates `KNOWN_VOICE_HASHES`. That's the intended behavior — failure is the alert.
- **Partial download interrupted**: the `.part` file is cleaned up on raise; existing logic should handle this.
- **JSON config file**: optional pin; not security-critical (metadata, not executable). Skip for now.

---

## Post-Completion Checklist

- [ ] All acceptance criteria verified
- [ ] First-time download of default voice succeeds with the pinned hash
- [ ] Update `../flight-log.md` with the recorded SHA-256 for traceability
- [ ] Set this leg's status to `completed`
- [ ] Check off in `../flight.md`
