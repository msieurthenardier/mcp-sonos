# Leg: learned-seeds-gentle-scan

**Status**: completed
**Flight**: [Zero-Config Discovery](../flight.md)

## Objective
Stop the subnet scan from disrupting the LAN in steady state. After every
successful discovery, the household's IPs are remembered in the process as
**learned seeds**. They are tried after the configured seeds and before any
scan. When a scan does run, it uses a moderated thread count, so it no longer
floods the host's ARP neighbor table.

## Context
This leg was discovered after leg 01 landed. The Flight Director probed the
hardware on 2026-09-28; the full data is in the flight log.

- **The scan disrupts follow-up traffic.** SoCo's default `scan_network` uses
  256 threads and opens about 254 simultaneous TCP connects. For 1–3 s after
  it, connections to the *real* speakers intermittently fail with
  `ENETUNREACH` (101), `EHOSTUNREACH` (113) or 1 s timeouts.
  - Observed end to end: one `discovery_smoke.py` run failed with
    `Error calling tool 'list_speakers': ... [Errno 101] Network is
    unreachable` for `.51`. Cold-call times varied from 0.8 s to 3.9 s.
  - Without a scan, 100 of 100 sequential connects were clean, each under
    25 ms.
- **Measured thread counts:**

  | `max_threads` | Scan time | Anomalies after the scan (5 s window) |
  |---|---|---|
  | 256 | ~0.55 s | 3 of 2 trials (intermittent) |
  | 32 | ~2.55 s | 0 in 2 of 2 trials |
  | 8 | ~8.55 s | 0 in 2 of 2 trials |

- **Learned-seed expansion is cheap.** `SoCo(ip).visible_zones` after
  `clear_cache()` took 0.05 s for all 5 speakers.
- **Flight adaptation criterion triggered:** "bounded scan proves
  unreliable". The re-plan stays inside the flight's scope, and no mission
  criterion changes. Leg 01's pipeline stays. This leg adds one stage and a
  scan parameter.
- The flight's other design decisions still apply: interface preservation
  (`discover_speakers()` is still zero-arg), the diagnostics, and SoCo cache
  invalidation.

## Inputs
- Leg 01 implemented but uncommitted on `flight/01-zero-config-discovery`,
  with 112 tests passing.
- The current structure of `mcp_sonos/speakers.py`:
  - `discover_speakers` orchestrates
    `_seed_stage(ips)` → `_scan_networks()` / `_scan(networks)` → `_ssdp(timeout)`
    and builds a `trace`.
  - `_scan` calls `soco.discovery.scan_network(networks_to_scan=...,
    multi_household=False, include_invisible=False)` without `max_threads`.

## Outputs
- `mcp_sonos/speakers.py` with learned seeds and a moderated scan
- Tests in `tests/test_discovery.py`
- Doc touch-ups in the README and CLAUDE.md
- A flight-log entry

## Acceptance Criteria
- [ ] **Scan concurrency.** `_scan` passes `max_threads=SCAN_MAX_THREADS` to
  `scan_network`.
  - `SCAN_MAX_THREADS = 32` is a module constant, with a comment citing the
    2026-09-28 measurement.
  - It is not an env var.
- [ ] **Learned seeds stored.** Module-level, process-wide state holds the IPs
  of the speakers returned by the last *successful* `discover_speakers()`
  call.
  - It is replaced wholesale on every success.
  - It is left untouched when a call raises `NoSpeakersFound`.
- [ ] **Learned-seed stage.** A new stage runs after the configured-seed stage
  and before the scan. It reuses the same gate-then-expand logic as
  `_seed_stage`: a TCP 1400 probe, then `visible_zones` filtered by
  `_safe_is_visible`.
  - It skips IPs that were already tried as configured seeds in this call.
  - It stops at the first learned seed that yields speakers.
  - The trace records it distinctly, for example `learned seed <ip>: ...`.
- [ ] **Cold start and fallback.** On a cold start (no learned seeds) or when
  every learned seed fails, the pipeline falls through to the scan and then
  SSDP, exactly as in leg 01.
- [ ] **Diagnostics.** `NoSpeakersFound` lists any learned seeds that were
  tried.
- [ ] **Test-only reset.** A reset helper, `_reset_learned_seeds()`, exists.
  `tests/test_discovery.py` uses an autouse fixture to reset the state around
  every test, so no test depends on order.
- [ ] **Interface unchanged.** `discover_speakers()` is still callable with
  zero arguments. No controller change is required. `refresh()` and the
  name-miss retry naturally use learned seeds, which suffices because any live
  household member reports the full, current topology.
- [ ] **New unit tests**, all hardware-free:
  - After a successful scan-based discovery, a second call uses a learned seed
    and does not call `_scan`.
  - When learned seeds are dead, the call falls through to the scan.
  - Learned seeds are not overwritten by a failed call.
  - A configured seed already tried is not re-probed as a learned seed.
  - `_scan` passes `max_threads=32`.
  - The `NoSpeakersFound` message includes learned-seed outcomes.
- [ ] **Suite passes.** `timeout 180 .venv/bin/python -m pytest -q` passes,
  with 112 or more tests, and no existing assertion is weakened.
- [ ] **Docs.** README (troubleshooting, or the "Discovery cache" caveat) and
  CLAUDE.md (Operating constraints) state the following:
  - The scan runs at cold start, or only when no known speaker answers.
  - The scan is deliberately rate-limited, because a full-speed scan briefly
    disrupts LAN connections on some hosts (observed under WSL2 mirrored
    networking).
  - Remove numbers from the prose wherever you can.

## Verification Steps
- Run `timeout 180 .venv/bin/python -m pytest -q`.
- Run `grep -n "max_threads" mcp_sonos/speakers.py`.
- Run the permitted read-only hardware check:
  `env -u SONOS_IPS -u SONOS_SCAN_NETWORKS timeout 60 .venv/bin/python discovery_smoke.py --runs 3`,
  three times as fresh processes.
  - Exit 0 each time.
  - Five speakers on every call.
  - The `refresh_speakers` line's `elapsed_s` is under 1.5 s, because it is
    served by a learned seed without a scan.
  - Record the cold first-call timings in the flight log.
  - Learned seeds live in the process, so each fresh process starts cold.
    The under-1.5 s expectation holds because the cold `list_speakers`
    call in the *same* process has already recorded the learned seeds.

## Implementation Guidance
1. **Factor the gate-then-expand loop out of `_seed_stage`** so that the
   configured and learned stages share it. It should take a label
   (`"seed"` / `"learned seed"`) for trace lines.
2. **Store learned IPs as a list of strings**, in the
   `sorted(..., key=player_name)` order, from `s.ip_address`. Don't store
   `SoCo` objects: they are per-IP singletons anyway, and plain IPs keep
   tests simple.
3. **Give the test double an `ip_address` before writing any learned-seed
   code.** Recording learned seeds reads `.ip_address` off every returned
   speaker. `tests/test_discovery.py::_FakeZone` has no such attribute, so
   about 10 existing pipeline tests would raise `AttributeError`.
   - Add an `ip_address` constructor parameter with a unique default derived
     from the name, or an explicit default.
   - This changes the fake only. No existing assertion changes.
4. **Pass the configured-seed IPs into the learned-seed stage.** The
   orchestrator passes the configured `ips` into the learned-seed stage,
   which filters its list against them by exact string match before
   probing. `_ips_from_env` already strips whitespace.
5. **Keep the orchestration readable**, in this order: configured seeds →
   learned seeds → scan → SSDP → raise. On success, record the learned seeds,
   then return.

## Edge Cases
- **A learned seed answers but its household changed** (for example, the
  device was factory-reset into another household): take whatever
  `visible_zones` it reports. This is acceptable and documented as the
  multi-household limitation.
- **The DHCP lease moved every speaker:** all learned seeds fail the gate, so
  the pipeline falls through to the scan and the learned seeds are replaced.
  One slow call results. This is acceptable.
- **Thread safety:** discovery runs within a single MCP request at a time.
  Assign the list atomically, replacing the whole list rather than mutating
  it in place, and don't add locking.

## Files Affected
- `mcp_sonos/speakers.py`
- `tests/test_discovery.py`
- `README.md`
- `CLAUDE.md`

## Citation Audit (2026-09-28)
Each citation was checked against the working tree after leg 01:
- `speakers.py:discover_speakers` (seed → scan → SSDP orchestration with `trace`)
- `speakers.py:_seed_stage(ips)`
- `speakers.py:_scan(networks)`: `scan_network(networks_to_scan=..., multi_household=False, include_invisible=False)`, with no `max_threads`
- `speakers.py` constants `SEED_PORT`, `SEED_PROBE_TIMEOUT`, `MIN_SCAN_PREFIX`, `SCAN_OVERRIDE_MIN_PREFIX`

All were found.

---

## Post-Completion
Completion steps — status transitions, flight-log update, checking off in the parent flight, and commit — are Flight Control protocol, driven by the execution workflow. Not repeated here.
