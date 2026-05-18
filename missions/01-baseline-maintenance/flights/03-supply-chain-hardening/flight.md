# Flight: Supply-Chain Hardening

**Status**: in-flight
**Mission**: [Baseline Maintenance](../../mission.md)

## Contributing to Criteria
- [x] F8 — Default Piper voice has a pinned SHA-256 verified on download
- [ ] F13 — `pyproject.toml` caps `fastmcp` at `<4`
- [ ] F17 — `pip-audit` baseline scan completed; pip-audit in dev extras

---

## Pre-Flight

### Objective
Tighten supply-chain trust assumptions. Three legs: pin the default Piper voice's SHA-256 so a TLS-MITM or HuggingFace compromise can't swap a poisoned ONNX model; cap the most-volatile dependency (FastMCP, young and recently moved 3.0→3.3) so a SemVer-major surprise can't break `uvx --from git+...` users; run a baseline `pip-audit` so the next inspection has a delta to compare against.

### Open Questions
- [x] Where to store the SHA-256 hashes? → Resolved: in `mcp_sonos/tts.py` as a module-level dict keyed by voice name. Keeps the data near the consumer; non-default voices fall through to a logged trust-on-first-use warning.

### Design Decisions

**Hash strategy for non-default voices**: Log a `warning` once per process on first download of an unpinned voice, including the observed SHA-256. Don't block — that breaks the existing UX.
- Rationale: pinning only what we ship as default keeps the surface small; loud-but-non-blocking warning gives the operator a hash to pin if they want
- Trade-off: defense is opt-in for non-default voices

**FastMCP cap range**: `>=3.0,<4`. Don't cap soco, piper-tts, pydantic — they're more stable.
- Rationale: FastMCP is the only dep that's moved fast in months and is pre-stable in spirit
- Trade-off: misses preventing SemVer-major issues in other deps

**Where pip-audit goes in pyproject.toml**: Under `[project.optional-dependencies] dev = [...]`.
- Rationale: standard Python pattern; doesn't bloat the production install
- Trade-off: requires `pip install -e ".[dev]"` to get it

### Prerequisites
- [ ] Have internet access (pip-audit fetches the OSV database)

### Pre-Flight Checklist
- [x] All open questions resolved
- [x] Design decisions documented
- [ ] Prerequisites verified (internet access)
- [x] Validation approach defined
- [x] Legs defined

---

## In-Flight

### Technical Approach
Three legs, ordered F8 → F13 → F17. F8 touches `tts.py`; F13 touches `pyproject.toml`; F17 also touches `pyproject.toml` (new `optional-dependencies` block) plus an installed-state side effect. F17 should follow F13 because both touch the same file and sequential edits avoid hunk conflicts.

**Commit cadence**: per-leg commits (Flights 01 + 02 convention preserved).

**Agent pattern**: Flight 02 emerged a rule of thumb — split design-review and implementation when a leg can fail in non-obvious runtime ways; consolidate when legs are textually independent and runtime-inert. F8 (touches tts download path with TLS / file-write semantics) warrants separate design-review + implementation agents. F13 (one-line cap edit) and F17 (one config-block add + tool invocation) are consolidate-safe.

**Smoke-test relevance**: F8 affects voice-model download — the cached voice already on disk will not re-trigger the path on next run. To validate, F8's Developer must delete the cached `.onnx` file and re-trigger via `say()` (or call the download function directly with a sandbox cache_dir). F13 + F17 have zero smoke-test impact.

### Checkpoints
- [ ] F8: SHA-256 pin in place; manual test by deleting cached voice and re-downloading
- [ ] F13: `pyproject.toml` updated; `pip install -e .` still works
- [ ] F17: pip-audit runs cleanly; results captured in flight log

### Adaptation Criteria

**Divert if**:
- pip-audit reports actual high/critical CVEs against direct deps — then add a fourth leg in this flight or open a follow-up. Decide based on the specific CVE: high-criticality direct-dep finding → fix here; transitive-with-no-fix → log and defer.
- F8's hash pin doesn't match the locally-installed voice model — investigate before committing the pin. The expected baseline IS the user's cached voice; a mismatch implies either the model has been updated on HuggingFace since first download OR the user has a tampered model. Surface the observed hash and let the operator decide.
- `smoke_test.py` starts failing in a way different from the known modes (the `say()` coordinator bug AND the SSDP-discovery race documented in Flight 02 debrief) — halt and investigate.

**Acceptable variations**:
- Hash storage location (could move to a separate JSON file if it grows; one dict is fine for now)
- Whether to also cap `soco`/`piper-tts`/`pydantic` upper bounds — flight design says no, but the Developer can promote during F13 if they discover a specific concern

### Legs

- [x] `01-pin-piper-voice-hash` — F8: SHA-256 pin for default voice + trust-on-first-use warning for others
- [ ] `02-cap-fastmcp-version` — F13: `>=3.0,<4` in pyproject.toml
- [ ] `03-run-pip-audit-baseline` — F17: install pip-audit, run baseline scan, capture findings

---

## Post-Flight

### Completion Checklist
- [ ] All 3 legs completed
- [ ] Smoke tests still pass
- [ ] `pip install -e ".[dev]"` succeeds and pip-audit is available
- [ ] Maintenance report findings F8, F13, F17 ticked in mission.md
- [ ] Flight log filled in (includes the pip-audit baseline output)

### Verification
- Delete `~/.cache/mcp-sonos/voices/en_US-lessac-medium.onnx`, run `mcp-sonos`, trigger `say`, verify voice download verifies against the pinned hash.
- `pip install -e .` works against capped `fastmcp<4`.
- `.venv/bin/pip-audit` runs and produces output (capture in flight log).
