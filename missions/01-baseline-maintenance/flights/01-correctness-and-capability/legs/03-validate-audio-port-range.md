# Leg: 03-validate-audio-port-range

**Status**: ready
**Flight**: [Correctness and Capability Hardening](../flight.md)

## Objective
Enforce that `AUDIO_PORT` falls inside the 8000–8999 range documented by the firewall rule; otherwise raise a clear `ValueError` at startup (Finding F3 from [Maintenance Report 2026-05-18](../../../../maintenance/2026-05-18.md)).

## Context
- `audio_host.py:25-27` reads `AUDIO_PORT` from env and casts to int with no range check.
- A user setting `AUDIO_PORT=9999` (outside the firewall rule's 8000-8999 range) gets the documented silent failure: speakers go `TRANSITIONING → STOPPED` with no HTTP hits, and the cause is non-obvious.
- The firewall coupling is documented in CLAUDE.md, audio_host.py docstring, and README — but not enforced in code.
- The constant `PORT_RANGE = (8000, 8999)` already exists in `audio_host.py` for the auto-pick path.

## Inputs
- `mcp_sonos/audio_host.py` env-var read block

## Outputs
- Out-of-range `AUDIO_PORT` raises a clear `ValueError` at startup, with a message referencing the firewall rule
- In-range values continue to work as before

## Acceptance Criteria
- [ ] `AUDIO_PORT=9999 mcp-sonos` exits with a clear error message
- [ ] Error message names the range (`8000-8999`) and the rationale (firewall rule)
- [ ] `AUDIO_PORT=8500 mcp-sonos` works as before
- [ ] No `AUDIO_PORT` set: auto-pick still works as before
- [ ] No regression in smoke tests

## Verification Steps
- `AUDIO_PORT=9999 .venv/bin/python -m mcp_sonos.server` exits non-zero with the new error.
- `AUDIO_PORT=8500 .venv/bin/python -m mcp_sonos.server` starts normally.
- `smoke_test.py` passes against live hardware.

## Implementation Guidance

1. **Locate** the env read in `audio_host.py:25-27`:
   ```python
   env = os.environ.get("AUDIO_PORT", "").strip()
   if env:
       return int(env)
   ```

2. **Add range validation**:
   ```python
   env = os.environ.get("AUDIO_PORT", "").strip()
   if env:
       p = int(env)
       if not (PORT_RANGE[0] <= p <= PORT_RANGE[1]):
           raise ValueError(
               f"AUDIO_PORT={p} is outside the {PORT_RANGE[0]}-{PORT_RANGE[1]} "
               f"range. The default Windows Firewall / iptables rule scopes "
               f"inbound traffic to this range; out-of-range ports will be "
               f"silently dropped by the firewall, with speakers transitioning "
               f"then stopping. Set AUDIO_PORT within {PORT_RANGE[0]}-{PORT_RANGE[1]} "
               f"or update the firewall rule."
           )
       return p
   ```

3. **Confirm** `PORT_RANGE` is already defined in the same module (it is — used by the auto-pick logic).

## Files Affected
- `mcp_sonos/audio_host.py` — single function (the env read), ~10 lines added

## Edge Cases
- Non-integer `AUDIO_PORT` (e.g., `"abc"`) already raises `ValueError` via `int()`. Leave that path; it's already a clear error.

---

## Post-Completion Checklist

- [ ] All acceptance criteria verified
- [ ] Smoke test passes
- [ ] Update `../flight-log.md`
- [ ] Set this leg's status to `completed`
- [ ] Check off in `../flight.md`
