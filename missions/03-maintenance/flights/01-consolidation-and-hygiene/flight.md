# Flight: Consolidation & Hygiene

**Status**: completed
**Mission**: [Maintenance — Consolidation & Hygiene](../../mission.md)

## Contributing to Criteria
- [x] S-1, I-3, I-4, I-5, T-1, T-3, T-4, T-5, T-6, T-7, I-9, I-11, I-12 (all mission criteria — this is the only flight)

---

## Pre-Flight

### Objective
Resolve all 12 actionable findings from the 2026-06-02 maintenance report as
atomic, behavior-preserving legs: shut the `.env` leak, unify the two duplicated
source helpers, add the `_say_all` test seam, consolidate the overlapping tests
behind a shared fixture base, de-risk the SoundHelix smoke dependency, and fix
the redundant/incorrect comments. The existing 63-test suite is the regression
net throughout.

### Open Questions
N/A — maintenance flight; all fixes are concrete and derived from the report.

### Design Decisions

**Single flight, one leg per finding**: Maintainer chose to collapse the
Architect's recommended three flights (source dedup / test consolidation /
hygiene) into one flight. The legs are ordered by dependency, not grouped.
- Rationale: small project; per-leg commits still give git-bisect value; one
  feature branch avoids stacked-PR overhead.
- Trade-off: a larger single flight vs. three smaller ones — acceptable at this
  scale.

**Leg ordering enforces two dependencies**:
- T-5 (shared `conftest.py` builder) lands **before** T-3/T-4 (parametrizations
  that consume it).
- I-3's unified helper subsumes I-4 (the dead return value disappears), so there
  is no separate I-4 leg.

### Prerequisites
- [x] venv present at `<repo-root>/.venv`
- [x] Working tree clean on `main`; suite green at 63 tests

### Pre-Flight Checklist
- [x] All open questions resolved (none)
- [x] Design decisions documented
- [x] Prerequisites verified
- [x] Validation approach defined (existing pytest suite + per-leg verification)
- [x] Legs defined (12)

---

## In-Flight

### Technical Approach
Each leg is a self-contained fix verified by running `pytest` (with the venv
active) and the leg-specific check. Source refactors (I-3, I-5) and test
consolidations (T-3, T-4, T-5, T-6) are behavior-preserving — the suite must
stay green with no assertion weakened. Smoke (T-7) and comment legs (I-9, I-11,
I-12) are independent and can be verified by inspection / a smoke dry-run.

### Checkpoints
- [x] Hygiene leg landed (S-1)
- [x] Source dedup landed (I-3, I-5) with suite green
- [x] Test seam + fixtures + parametrization landed (T-1, T-5, T-6, T-3, T-4) with suite green and reduced redundancy
- [x] Smoke resilience landed (T-7)
- [x] Comment fixes landed (I-9, I-11, I-12)

### Adaptation Criteria

**Divert if**:
- A source refactor (I-3/I-5) cannot be made behavior-preserving without a
  contract change — stop and re-scope rather than alter behavior under a
  maintenance banner.

**Acceptable variations**:
- Merging two trivial comment legs (I-9 + I-12, both `CLAUDE.md`) into one commit
  if convenient — the report records them separately but they touch the same file.
- Adjusting the final test count (consolidation reduces it) — the criterion is
  "suite green, no coverage lost," not "still exactly 63."

### Legs

> Ordered by dependency; one leg per finding.

- [x] `01-gitignore-env` - S-1: add `.env` to `.gitignore`
- [x] `02-unify-stale-coord-retry` - I-3 (+I-4): extract shared `_with_stale_coord_retry`
- [x] `03-extract-live-track-dict` - I-5: extract `_live_track_dict` in `playlists.py`
- [x] `04-say-all-sleep-seam` - T-1: add `sleep_fn` injection seam to `_say_all`
- [x] `05-shared-test-builder` - T-5: hoist track/transport builder + constants into `conftest.py`
- [x] `06-worker-session-fixture` - T-6: extract `worker_session` fixture; fix `:520` cleanup
- [x] `07-parametrize-resume-tests` - T-3: parametrize the shared resume observable
- [x] `08-parametrize-skip-guard-tests` - T-4: parametrize the three skip-guard tests
- [x] `09-smoke-fallback-url` - T-7: fallback external URL in `queue_smoke.py` + `reap_smoke.py`
- [x] `10-reword-tool-count-comment` - I-9: reword `CLAUDE.md` "31 tools" phrasing
- [x] `11-merge-queue-parent-id-comment` - I-11: merge the duplicated `QUEUE_PARENT_ID` comment
- [x] `12-codify-dir-listing-guard` - I-12: codify the directory-listing guard in `CLAUDE.md`

---

## Post-Flight

### Completion Checklist
- [x] All 12 legs completed
- [x] Code merged *(legs 02–08 via PR #8 / `881d152`; legs 01, 09–12 via this flight's PR)*
- [x] Tests passing (adjusted count after consolidation; no coverage lost) — 78 passed
- [x] Documentation updated (`CLAUDE.md` comment fixes)

### Verification
- `pytest` green with the venv active, no weakened assertions
- `git check-ignore .env` resolves
- One `grep` confirms a single stale-coord retry helper and a single
  live-track-read helper
- `queue_smoke.py`/`reap_smoke.py` fall back to the secondary URL when the
  primary is unreachable (dry-run with a bad primary)
