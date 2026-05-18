# Flight Log: Supply-Chain Hardening

**Flight**: [Supply-Chain Hardening](flight.md)

## Summary
(Filled in during execution.)

---

### Flight Director Notes

**2026-05-18 — Flight start**

- Mission stayed `active`. Flight flipped: `ready` → `in-flight`.
- Feature branch: `flight/03-supply-chain-hardening` created off `flight/02-documentation-cleanup` at `2c9bc72` (which includes the Flight 03 planning commit).
- Crew loaded from `.flightops/agent-crews/leg-execution.md` (Developer + Reviewer, both Sonnet).
- Agent pattern per Flight 02 lesson: F8 gets split design-review + implementation (touches `tts.py` download path with TLS/file-write semantics — runtime non-trivial). F13 + F17 consolidate review+implement (textually independent and runtime-inert).
- Commit cadence: per-leg commits, matching Flights 01 + 02 convention.
- All three legs are hardware-independent for verification (Flight 02 debrief observation). No live Sonos needed.

---

## Reconnaissance Report

Verified each scope item against current code at flight planning time (2026-05-18, after Flights 01 + 02 landed; current HEAD on `flight/02-documentation-cleanup` at `136b333`). Source artifact: [`maintenance/2026-05-18.md`](../../../../maintenance/2026-05-18.md). Verified by direct file reads and pip introspection.

| Item | Classification | Evidence | Recommendation |
|------|----------------|----------|----------------|
| F8 — Piper voice download no integrity verification | `confirmed-live` | `mcp_sonos/tts.py:55-58` `_download` uses `urllib.request.urlopen` with TLS-only verification. Existing size check at `:84` (`onnx.stat().st_size < 1024`) is sanity-only, not content. `hashlib` is already imported at `:13` (used for the TTS content cache key) — pin will reuse it. | Add `KNOWN_VOICE_HASHES: dict[str, str]` in tts.py with SHA-256 pin for default voice (`en_US-lessac-medium`); compute SHA-256 of the downloaded `.part` file before atomic rename; mismatch → delete + raise. Non-default voices get a `warning`-level log with observed hash for operator pinning. |
| F13 — pyproject.toml fastmcp unbounded | `confirmed-live` | `pyproject.toml` deps: `"fastmcp>=3.0"` (no upper). Installed `fastmcp==3.3.1` and `fastmcp-slim==3.3.1` in the venv. | Set `"fastmcp>=3.0,<4"`. Other deps (`soco>=0.30`, `piper-tts>=1.3`, `pydantic>=2.0`) remain unbounded per flight design decision. |
| F17 — no `[project.optional-dependencies]` block; pip-audit not installed | `confirmed-live` | `pyproject.toml` has no `optional-dependencies` section. `.venv/bin/pip list` shows no `pip-audit`. | Add `[project.optional-dependencies] dev = ["pip-audit"]`; run baseline scan; capture severity counts + top 3 findings in flight log. |

**No items retired or scoped down — all 3 confirmed-live.** No drift in line numbers or symbol names.

### Additional Observations

1. **Installed `fastmcp==3.3.1`** — within the `>=3.0,<4` cap that F13 will set, so no resolver re-pick triggered. F13 is preventative for future installs, not a backport.
2. **Transitive outdated deps shifted slightly**: maintenance report counted 4 outdated transitives (click, importlib_metadata, rich-rst, watchfiles); current count is 5 (added `cyclopts==4.13.0` vs `4.14.0`). All still transitive — no direct exposure — and remain Pass per the maintenance-report classification. F17's pip-audit scan will surface anything CVE-relevant.
3. **`hashlib` is already imported in `tts.py:13`** (used by `cache_key`'s sha1). F8's sha256 pin reuses the existing import — no new dependency surface.
4. **Flight 02 debrief carry-forwards NOT bundled into Flight 03**: the `controller.py:86` class-docstring drift and the `audio_host.py:Handler` directory-listing-disabled CLAUDE.md codification both touch surfaces orthogonal to supply-chain hardening. Keeping Flight 03 thematically clean (supply-chain only); those carry forward to Flight 04 or a future micro-flight.
5. **SSDP-discovery flakiness** (Flight 02 debrief) is a Flight 04 prerequisite, not Flight 03 scope. F17's pip-audit doesn't require live hardware.

---

---

## Leg Progress

**2026-05-18 — Leg 01 (`01-pin-piper-voice-hash`) landed**

- Implemented per the leg's prescriptive Implementation Guidance: added `KNOWN_VOICE_HASHES` module-level dict in `mcp_sonos/tts.py`, `_hash_voice_file` helper (sha256 in 64 KB chunks), `_verify_or_log` helper handling both the no-pin (warning) and mismatch (quarantine + raise) branches, `_verified_voices: set[str]` per-process cache, `_download` extended with `voice_name: str | None` parameter, `_ensure_voice` keeps its `(voice: str) -> Path` signature and gained the verify-existing path.
- Added `log = logging.getLogger("mcp_sonos.tts")` (module had no logger before); matches the `mcp_sonos.<module>` convention used in `playlists.py`.
- README updated with a one-liner in the Configuration section noting hash-pinning + trust-on-first-use.
- Verification (all hardware-independent):
  1. `py_compile mcp_sonos/tts.py` — clean.
  2. Happy path on cached pinned voice — succeeds; per-process cache populated; 2nd call skips re-hash.
  3. Tamper test (`dd` flipped one byte at offset 1024) — raised `RuntimeError` with full expected/observed hash prefixes and full quarantine path; file renamed to `<voice>.onnx.suspect`. Restored from backup after.
  4. Trust-on-first-use (simulated by clearing `KNOWN_VOICE_HASHES` temporarily — avoids ~60 MB download of a second voice) — `WARNING` log emitted with observed hash and "Add to KNOWN_VOICE_HASHES to pin." guidance.
- Leg status: `ready` → `landed`. Not committed (handoff to reviewer per `/agentic-workflow` Phase 2d).

**2026-05-18 — Leg 02 (`02-cap-fastmcp-version`) landed**

- One-line edit to `pyproject.toml`: `"fastmcp>=3.0"` → `"fastmcp>=3.0,<4"`. Other deps (`soco>=0.30`, `piper-tts>=1.3`, `pydantic>=2.0`) intentionally left unbounded per flight design.
- Installed versions at pin time (delta baseline for next maintenance cycle): `fastmcp==3.3.1`, `soco==0.31.0`, `piper-tts==1.4.2`, `pydantic==2.13.4`. Resolver no-op as predicted — installed `fastmcp` sits within the new cap.
- Verification (all hardware-independent): `.venv/bin/pip install -e .` succeeded; `pip show fastmcp` confirmed `3.3.1`; `python -c "import fastmcp"` reported `3.3.1`; `py_compile mcp_sonos/server.py` clean (server is the FastMCP consumer).
- Leg status: `ready` → `in-flight` → `landed`. Not committed (handoff to reviewer per `/agentic-workflow` Phase 2d).

---

## Decisions

**2026-05-18 — Pinned SHA-256 for `en_US-lessac-medium`** (Leg 01)

- **Pinned value**: `5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f`
- **Source of truth**: HuggingFace LFS pointer at `https://huggingface.co/rhasspy/piper-voices/raw/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx` (the `raw/main/` URL returns the small LFS pointer file containing `oid sha256:<hash>` and `size <N>` per git-lfs spec v1).
- **Local-vs-upstream comparison**: **match**. Local `~/.cache/mcp-sonos/voices/en_US-lessac-medium.onnx` (size 63201294 bytes, downloaded 2026-05-17) hashed to the same value as the upstream LFS pointer's `oid sha256:`. Size also matches the LFS pointer's declared `size 63201294`. No divergence to resolve.
- **Audit trail**: the pin in `KNOWN_VOICE_HASHES` is annotated with the source URL pattern in a comment above the dict.

---

## Deviations

---

## Anomalies

---

## Session Notes
