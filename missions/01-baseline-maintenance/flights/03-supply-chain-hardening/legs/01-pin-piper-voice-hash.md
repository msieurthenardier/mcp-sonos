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
- [ ] `KNOWN_VOICE_HASHES` (or similar) dict in `tts.py` mapping voice name → SHA-256 hex string; populated with at least the default voice's hash (computed by running the project once locally and recording the hash)
- [ ] Download path computes SHA-256 of the received file and compares against the pin (if present)
- [ ] Mismatch: file is deleted, `RuntimeError` raised with a message naming the expected and observed hashes
- [ ] Non-default voice (no pin): emit a `warning`-level log with the observed hash, suggesting the operator add it to `KNOWN_VOICE_HASHES`
- [ ] First-run download of `en_US-lessac-medium` succeeds (proves the pin value is correct)

## Verification Steps
- Delete `~/.cache/mcp-sonos/voices/en_US-lessac-medium.onnx` (if present).
- Run the server; trigger `say()`; observe the voice download verifies cleanly.
- Manual tamper test (optional, takes effort): re-download the file from a different source, change one byte, observe the verification raises.
- `say()` with a custom `PIPER_VOICE` that has no pin: observe the trust-on-first-use warning in logs.

## Implementation Guidance

1. **Compute the default voice's SHA-256 once**, locally:
   ```bash
   sha256sum ~/.cache/mcp-sonos/voices/en_US-lessac-medium.onnx
   ```
   Record this hex string. Note: the JSON config file (`.onnx.json`) is typically small and metadata-only; you can optionally pin its hash too, but the ONNX is the executable surface.

2. **Add a hashes module** (or extend `tts.py`):
   ```python
   KNOWN_VOICE_HASHES: dict[str, str] = {
       "en_US-lessac-medium": "<sha256-hex-from-step-1>",
   }
   ```

3. **In the download path**, after the file is fully written but before the atomic rename, compute the SHA-256:
   ```python
   import hashlib
   h = hashlib.sha256()
   with open(part_path, "rb") as f:
       for chunk in iter(lambda: f.read(1 << 16), b""):
           h.update(chunk)
   observed = h.hexdigest()
   expected = KNOWN_VOICE_HASHES.get(voice_name)
   if expected:
       if observed != expected:
           part_path.unlink()
           raise RuntimeError(
               f"Piper voice {voice_name!r} hash mismatch. "
               f"Expected {expected[:16]}..., got {observed[:16]}.... "
               f"Possible supply-chain tampering; aborting."
           )
   else:
       log.warning(
           "Piper voice %r downloaded without a pinned hash. "
           "Observed SHA-256: %s. Add to KNOWN_VOICE_HASHES to pin.",
           voice_name, observed,
       )
   ```

4. **Then proceed with the atomic rename** as today.

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
