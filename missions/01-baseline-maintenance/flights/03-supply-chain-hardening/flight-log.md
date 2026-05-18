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

(Append entries here as legs land.)

---

## Decisions

---

## Deviations

---

## Anomalies

---

## Session Notes
