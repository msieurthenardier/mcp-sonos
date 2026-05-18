# Leg: 03-run-pip-audit-baseline

**Status**: ready
**Flight**: [Supply-Chain Hardening](../flight.md)

## Objective
Add `pip-audit` to a `dev` optional-dependency group, run a baseline vulnerability scan against the current dependency tree, and capture the results in the flight log so the next inspection has a delta to compare against (Finding F17 from [Maintenance Report 2026-05-18](../../../../maintenance/2026-05-18.md)).

## Context
- `pip-audit` was not installed in the venv at inspection time, so Category 3 (Dependency Health) was not actually scanned. This is a process gap.
- Goal: make it possible to run `pip-audit` quickly from the existing venv whenever a maintenance cycle starts, and seed the baseline now.

## Inputs
- `pyproject.toml` (needs `[project.optional-dependencies]` section)
- Existing `.venv`

## Outputs
- `[project.optional-dependencies] dev` group added with `pip-audit` (and possibly other dev tools left for future legs)
- Documented baseline run output in the flight log
- Any high/critical CVEs reported → either resolved (if trivial) or logged as a follow-up finding (defer to next maintenance cycle)

## Acceptance Criteria
- [ ] `pyproject.toml` declares `[project.optional-dependencies] dev = ["pip-audit", ...]`
- [ ] `.venv/bin/pip install -e ".[dev]"` succeeds and installs pip-audit
- [ ] `.venv/bin/pip-audit` runs without error
- [ ] Output captured in `../flight-log.md` (summarize, don't dump raw output — if many findings, list count by severity and the top 3)
- [ ] If any high/critical CVE found against a direct dep, raise as a deviation in the flight log and decide: fix-in-this-flight or open a follow-up

## Verification Steps
- `.venv/bin/pip install -e ".[dev]"` succeeds.
- `.venv/bin/pip-audit --version` returns a version.
- `.venv/bin/pip-audit` produces a report.

## Implementation Guidance

1. **Add to `pyproject.toml`**:
   ```toml
   [project.optional-dependencies]
   dev = [
       "pip-audit",
   ]
   ```
   You may want to bundle `ruff` and `pytest` here too if Flight 4 hasn't landed yet, but keeping this leg scoped to pip-audit only is cleanest. Flight 4 will add pytest separately.

2. **Install**:
   ```bash
   cd /home/cprch/projects/mcp-sonos
   .venv/bin/pip install -e ".[dev]"
   ```

3. **Run baseline**:
   ```bash
   .venv/bin/pip-audit
   ```
   Optionally `pip-audit --strict` for tighter posture.

4. **Capture summary in flight log**: severity counts (none / X low / Y medium / Z high / W critical), top 3 findings if any. Don't paste raw output — reference and summarize.

5. **Triage any findings**:
   - Low/medium against direct deps with available fixes: consider adding a leg in this flight to bump the version (or note as a deferred follow-up).
   - High/critical: probably warrant immediate action — discuss in flight log under Decisions.

## Files Affected
- `pyproject.toml` — new `[project.optional-dependencies]` section

## Edge Cases
- **pip-audit needs internet** (queries OSV database). Document this in the flight log if running offline.
- **OSV reports many advisories on transitive deps**: focus on direct deps; transitive advisories without a usable fix can be noted but not actioned in this leg.

---

## Post-Completion Checklist

- [ ] All acceptance criteria verified
- [ ] Baseline summary captured in flight log
- [ ] Any high/critical CVEs decided on (fix vs. defer)
- [ ] Update `../flight-log.md`
- [ ] Set this leg's status to `completed`
- [ ] Check off in `../flight.md`
