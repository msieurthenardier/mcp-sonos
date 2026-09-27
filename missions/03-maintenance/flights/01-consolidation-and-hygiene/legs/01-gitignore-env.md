# Leg: gitignore-env

**Status**: completed
**Flight**: [Consolidation & Hygiene](../flight.md)

## Objective
Add `.env` to `.gitignore` so a real-IP `.env` can never be committed to the public repo (finding S-1).

## Context
- Maintenance report 2026-06-02, finding **S-1** (Action Required, Security).
- `.gitignore` has no `.env` entry; `git check-ignore .env` currently returns nothing.
- `.env.example` is the intended-tracked template; only `.env` (the operator's filled copy with real LAN IPs) must be ignored.
- No credentials live in this project's config — impact is LAN-topology disclosure on a public repo — but the leak is irreversible once pushed, and the fix is one line.

## Inputs
- `.gitignore` exists and tracks `.env.example` (do not ignore the example).

## Outputs
- `.gitignore` contains a `.env` entry.

## Acceptance Criteria
- [ ] `git check-ignore .env` resolves (prints `.env`)
- [ ] `git check-ignore .env.example` returns nothing (the template stays tracked)
- [ ] No currently-tracked file is newly ignored (`git status` shows no removals)

## Verification Steps
- `git check-ignore .env` → prints `.env`
- `git check-ignore .env.example` → empty
- `git status --short` → clean except the `.gitignore` edit

## Implementation Guidance

1. **Add the ignore entry**
   - Append `.env` to `.gitignore`. Place it near the existing env/secret-style
     entries if there is a logical grouping; otherwise at the end with a short
     comment (`# local env (real LAN IPs) — never commit; .env.example is the template`).
   - Ensure the pattern does not accidentally match `.env.example` (a bare `.env`
     line matches only `.env`, which is correct; do NOT use `.env*`).

## Edge Cases
- **`.env` already exists untracked locally**: confirm it was never committed
  (`git log --all -- .env` is empty). If it *was* ever committed, flag to the
  maintainer — history scrubbing is out of scope for this leg.

## Files Affected
- `.gitignore` - add `.env`

---

## Post-Completion
Completion steps — status transitions, flight-log update, checking off in the parent flight, and commit — are Flight Control protocol, driven by the execution workflow (flight-end review + single commit). Do not commit; mark the leg `landed` and signal `[LAND:leg]`.

## Citation Audit (Flight Director, 2026-09-26 resume)
- `.gitignore` (2026-09-26): no `.env` entry; `git check-ignore .env` empty. No local `.env` exists and `git log --all -- .env` is empty (never committed). A `.mcp.json` ignore entry was added in the prep commit `38ad841` — unrelated, leave it.
