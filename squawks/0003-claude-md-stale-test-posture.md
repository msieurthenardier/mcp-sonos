# Squawk 0003: CLAUDE.md says there is no test framework

**Status**: completed
**Type**: defect
**Severity**: routine
**Reported**: 2026-09-27
**Completed**: 2026-09-27

## Report
CLAUDE.md's Commands section ends with "No test framework, no linter configured. Smoke tests are
the regression net." pytest has existed since Mission 01; the hardware-free unit suite (78 tests)
is now the primary regression net and smoke scripts are the hardware-only secondary check. The
Commands block never shows how to run the suite. Found by the Mission 03 debrief Architect.

## Evidence
- `CLAUDE.md:39` — "No test framework, no linter configured. Smoke tests are the regression net."
- `pyproject.toml` — `pytest` in dev extras; `[tool.pytest.ini_options] testpaths = ["tests"]`
- `tests/` — conftest.py, _builders.py, _fakes.py, 9 test modules; `.venv/bin/python -m pytest -q` → 78 passed
- CLAUDE.md Versioning already references `tests/test_version.py`, contradicting line 39

## Corrective Action
- `CLAUDE.md` one-time setup: `.venv/bin/pip install -e .` → `.venv/bin/pip install -e '.[dev]'`
  so `pytest` (declared in `pyproject.toml`'s `dev` extra) is available.
- Added a venv-qualified unit-suite invocation to the Commands block, above the hardware
  smoke tests, with a comment marking it hardware-free and "run this first, on every change":
  `.venv/bin/python -m pytest -q`.
- Replaced the stale "No test framework, no linter configured. Smoke tests are the regression
  net." sentence with an accurate posture: the pytest unit suite (`tests/`, hardware-free) is
  the primary regression net; the smoke scripts are the hardware-only secondary check; no
  linter is configured (confirmed — no flake8/ruff/pylint/mypy config anywhere in the repo).
- No test counts or line numbers added, per squawk 0001 precedent (numbers in prose drift).

## Verification
- `grep -n 'No test framework' CLAUDE.md` → no match (exit 1), confirms the stale sentence is gone.
- `grep -n 'ruff\|flake8\|pylint\|mypy' pyproject.toml` and a repo-wide check for `.flake8`/
  `ruff.toml`/`setup.cfg` linter sections → nothing found; "no linter configured" still accurate.
- Ran the documented commands directly:
  - `.venv/bin/pip install -e '.[dev]'` — pytest already present in the venv (installs cleanly
    from a fresh venv too, per `pyproject.toml`'s `dev` extra).
  - `timeout 300 .venv/bin/python -m pytest -q` → `78 passed in 1.48s`.
- Manually re-read the updated Commands block and posture sentence against the squawk's
  Verification checklist: pytest invocation present and venv-qualified, posture sentence names
  unit suite as primary / smoke as hardware-only, no linter claim intact.

## Sign-Off
**Reviewer**: Reviewer agent (Sonnet), batch review — two cycles (cycle 1 blocked 0002 on a nonexistent `_say_one` citation; fixed; cycle 2 confirmed all three)
**Verdict**: confirmed
**Commit**: `squawk: turnaround 2026-09-27` on `squawk/turnaround-2026-09-27`
