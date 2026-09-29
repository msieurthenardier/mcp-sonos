# Behavior Test: Zero-Config Discovery

**Slug**: `zero-config-discovery`
**Status**: active
**Created**: 2026-09-28
**Last Run**: 2026-09-29-02-27-28

> Revised 2026-09-28 (in flight): the timing expectations were split into a cold first call and later calls, after leg 02 added learned seeds and a rate-limited scan. See the Flight 01 log.

## Intent
This test verifies that the MCP server finds every visible speaker in the
operator's real Sonos household. It checks four situations:
- no configuration at all
- configured IPs used as a way in, where unlisted speakers are still found
  and a dead seed is skipped
- configured IPs that are all dead, falling back to the network scan
- total discovery failure, which must produce an error that explains what was
  tried and what to set

Unit tests cover the pipeline logic with fakes. Only the real LAN shows
whether the bounded scan, the seed expansion, and invisible-device filtering
(the Boost bridge) actually behave on this network, across repeated runs.

## Preconditions
- The operator's household is powered on and reachable. Visible speakers:
  Dining Room `192.168.86.50`, Fireplace Room `.51`, Lounge `.52`,
  Kitchen `.53`, Patio `.49`. A Boost bridge at `.48` must never be listed.
  *Active check*: step 1.
- The flight's `discovery_smoke.py` exists at the repo root, and the venv at
  `.venv` has the package installed.
- `192.168.86.200` and `192.168.86.201` are unused on the LAN, so they serve
  as dead seeds. *Active check*: step 1.
- Each step runs the script as a **fresh process** from the repo root, and
  sets only the environment variables that step names. `SONOS_IPS` and
  `SONOS_SCAN_NETWORKS` must be unset unless the step sets them. Clear them
  explicitly with `env -u`.

## Observables Required
- shell (stdout JSON lines, stderr, exit code, measured via Bash)

## Steps

| # | Actions | Expected Results |
|---|---------|------------------|
| 1 | Precondition probe: ping `192.168.86.53` once. Try a TCP connection to port 1400 on `192.168.86.200` and `192.168.86.201` with a 1 s timeout. | `.53` answers. Neither `.200` nor `.201` accepts a connection on port 1400. |
| 2 | With neither `SONOS_IPS` nor `SONOS_SCAN_NETWORKS` set, run `.venv/bin/python discovery_smoke.py --runs 3`. | Exit code 0. Every call (3 × `list_speakers` + `refresh_speakers`) lists exactly these five names: Dining Room, Fireplace Room, Kitchen, Lounge, Patio. Each name has the IP from the preconditions. `Boost` never appears. The first `list_speakers` call (the cold start, which may scan) reports
`elapsed_s` under 5 s. Every later call, including `refresh_speakers`,
reports under 1.5 s, because learned seeds serve it without a scan. |
| 3 | Repeat step 2 twice more, as two more fresh processes. | Both runs meet all of step 2's results. Together with step 2, that is 3 fresh processes with every call listing all five speakers. |
| 4 | Set `SONOS_IPS=192.168.86.53` (Kitchen only) and run `discovery_smoke.py --runs 1`. | Exit code 0. Every call lists all five speakers, not just Kitchen, including Patio at `.49`. `Boost` does not appear. |
| 5 | Set `SONOS_IPS=192.168.86.200,192.168.86.49` (a dead seed first, then Patio) and run `discovery_smoke.py --runs 1`. | Exit code 0. Every call lists all five speakers. The first call's `elapsed_s` is under 3 s, meaning the dead seed didn't stall discovery for the ~4 s a bare UPnP attempt costs. |
| 6 | Set `SONOS_IPS=192.168.86.200,192.168.86.201` (all dead) and run `discovery_smoke.py --runs 1`. | Exit code 0. Every call lists all five speakers, found by falling back to the network scan. `Boost` does not appear. *(No timing bound on purpose: dead configured seeds are re-probed on every call, about 1 s each, and the cold call includes the scan.)* |
| 7 | Set `SONOS_IPS=192.168.86.200` and `SONOS_SCAN_NETWORKS=10.254.254.0/30` (no speakers there), and run `discovery_smoke.py --runs 1`. SSDP is known to find nothing on this host. | Exit code non-zero. The printed error says no Sonos speakers were found. It names the seed `192.168.86.200` and its failure, the network `10.254.254.0/30` as scanned, and the SSDP attempt. It suggests at least `SONOS_IPS`, `SONOS_SCAN_NETWORKS`, and `HOST_IP`. It is not an empty list and not a "No speaker named" message. *If this step instead lists speakers, SSDP started working on this host. Record that as an environment deviation, not a product failure.* |
| 8 | Set `SONOS_SCAN_NETWORKS=192.168.86.0/24` and run `discovery_smoke.py --runs 1`. | Exit code 0. Every call lists all five speakers, and `Boost` does not appear. |

## Out of Scope
- Target-set playback and grouping (Mission 04 Flight 2 has its own behavior tests).
- Name-miss re-discovery: covered by unit tests. It can't be forced on
  hardware without renaming a speaker.
- Multi-household networks, and subnets larger than /24 (not present on the
  operator's LAN).
- SSDP success paths (SSDP doesn't work on this host).
- Audio playback of any kind.

## Variants (optional)
None.
