# Leg: discovery-pipeline

**Status**: completed
**Flight**: [Zero-Config Discovery](../flight.md)

## Objective
Replace `discover_speakers` with a three-stage pipeline:
1. Seeds: the first live seed is expanded to the household.
2. Bounded subnet scan.
3. SSDP, as a last resort.

When every stage fails, raise a diagnostic `NoSpeakersFound`. Make every forced
refresh bypass SoCo's topology cache. Then bring the tests, tool descriptions,
docs and smoke scripts in line, and set the version to 0.4.0.

## Context
- All flight design decisions apply. Read the flight's **Design Decisions**
  section in full before starting. It is the authoritative spec for:
  - the pipeline order, seed handling and scan bound
  - diagnostics
  - cache freshness
  - forced refreshes bypassing SoCo's cache
  - error taxonomy
  - interface preservation
  - smoke scripts, the `discovery_smoke.py` apparatus, and the version
- Planning probes from 2026-09-28, recorded in the flight log:
  - The bounded scan of `192.168.86.0/24` takes about 0.5 s and is reliable.
  - A dead seed costs about 4.1 s without a TCP gate.
  - `visible_zones` excludes the Boost; `all_zones` includes it.
  - FastMCP forwards exception text word for word.
- `tests/conftest.py` pins `HOST_IP=127.0.0.1`. Unit tests must inject the
  stage functions and adapter data rather than rely on a real scan.
- **Do not contact the real Sonos speakers.** The flight has a separate
  hardware leg (02) for that. Unit tests must be hardware-free.
  - Exception: you may run `discovery_smoke.py --runs 1` once, as a final
    sanity check that it executes. It is read-only against the speakers
    (discovery calls only, no audio).

## Inputs
- `main` at `573d6f2` plus the flight planning commit on branch
  `flight/01-zero-config-discovery`.
- Suite green: 78 passed.

## Outputs
Files modified or created:
- `mcp_sonos/speakers.py`
- `mcp_sonos/controller.py`
- `mcp_sonos/server.py`
- `mcp_sonos/__init__.py`
- `tests/_fakes.py`
- `tests/test_discovery.py` (new)
- `tests/test_version.py`
- `README.md`
- `.env.example`
- `CLAUDE.md`
- `smoke_test.py`, `playlist_smoke.py`, `queue_smoke.py`, `reap_smoke.py`
- `discovery_smoke.py` (new, repo root)

## Acceptance Criteria

**Pipeline (`speakers.py`)**
- [ ] `discover_speakers()` is still callable with zero arguments and returns a
  non-empty `list[SoCo]` sorted by `player_name`. Any new parameters are
  keyword-only and have defaults.
- [ ] Stage 1, seeds. `SONOS_IPS` entries are read at call time and tried in
  order.
  - Each seed is gated by a TCP connect to port 1400 with a timeout of 1 s or
    less.
  - The first seed that passes and returns a non-empty set of visible zones
    ends the stage. That set is `visible_zones`, filtered by
    `_safe_is_visible`.
  - A seed that fails the gate, or raises during expansion, is recorded in the
    trace and skipped.
- [ ] Stage 2, scan. It runs only when stage 1 produced no speakers.
  - Default network: the adapter network (from `ifaddr`) that carries
    `lan_host_ip()`, with its prefix clamped to at least /24. If no adapter
    carries that IP, the IP's /24 is used.
  - `SONOS_SCAN_NETWORKS` (comma-separated CIDRs) replaces the derived network
    entirely when set.
  - Entries that are malformed, or broader than /16, are skipped and recorded.
    If no valid entry remains, the scan is skipped and recorded.
  - The scan is `soco.discovery.scan_network(networks_to_scan=...,
    multi_household=False, include_invisible=False)`, and its results are
    filtered by `_safe_is_visible`.
- [ ] Stage 3, SSDP. `soco.discover(timeout=<existing 5 s default>,
  allow_network_scan=False)` runs only when stages 1 and 2 both produced no
  speakers.
- [ ] `NoSpeakersFound(RuntimeError)` is raised when all three stages come up
  empty. Its message:
  - names each seed and its outcome
  - names each network scanned, plus any rejected `SONOS_SCAN_NETWORKS` entries
  - names the SSDP result
  - names the hints `SONOS_IPS`, `SONOS_SCAN_NETWORKS` and `HOST_IP`
  - mentions the same-LAN requirement and the Sonos UPnP setting (firmware 85
    and later)
- [ ] The module docstring describes the new pipeline.
- [ ] `resolve_name`, `SpeakerNotFound`, `lan_host_ip` and `safe_filename`
  signatures are unchanged.

**Controller (`controller.py`)**
- [ ] New `SonosController._invalidate_speakers()`:
  - It sets `_speakers_ts = 0.0`.
  - For each distinct `household_id` among the currently cached speakers, it
    calls `zone_group_state.clear_cache()` on one of them.
  - It swallows per-speaker exceptions, and is a no-op on an empty cache.
- [ ] `_invalidate_speakers()` is used by every forced path:
  - `refresh()`, which then re-discovers
  - `reboot()`
  - the `invalidate_speakers_cache` passed to `PlaylistManager`
  - the inline `invalidate=` lambda in `say`'s `_play_clip` closure
- [ ] Plain TTL expiry in `_speakers_fresh` does **not** clear SoCo's cache.
- [ ] `_resolve(name)`: on `SpeakerNotFound` against the cached list, it calls
  `_invalidate_speakers()`, re-discovers once and retries. If the name is
  still missing, it raises `SpeakerNotFound`.
- [ ] `NoSpeakersFound` propagates from `_speakers_fresh`, `refresh` and
  `_resolve` unchanged. It is not wrapped or swallowed.
- [ ] The dead `if not speakers: raise RuntimeError("No speakers available")`
  guard in `_say_all` is removed.
- [ ] The `refresh()` docstring is accurate.

**Server (`server.py`)**
- [ ] The `refresh_speakers` description no longer says "SSDP". It describes
  a forced fresh discovery that bypasses caches.
- [ ] The `list_speakers` description says it raises an explanatory error when
  no speakers can be found.

**Tests**
- [ ] `tests/_fakes.py::SoCoFake` gains:
  - a `household_id` field
  - a `zone_group_state` stub whose `clear_cache()` counts its calls
  All existing tests pass unmodified.
- [ ] A new `tests/test_discovery.py` is hardware-free. It uses injected stage
  functions or monkeypatches, and makes no real sockets or scans. It covers:
  - stage order and short-circuiting: seeds hit, so no scan and no SSDP; scan
    hit, so no SSDP
  - dead seeds skipped, with the next live seed used
  - all seeds dead, falling through to the scan
  - seed expansion excluding invisible zones
  - scan-network derivation:
    - an adapter prefix of /24 and one of /22, both clamped to /24
    - an IP that no adapter carries
    - the override replacing the derived network
    - a malformed entry and a /8 entry, both rejected and recorded
    - all entries invalid, so the scan is skipped
  - SSDP running only when the scan is empty
  - `NoSpeakersFound` being a `RuntimeError`, with message content covering
    each item above
  - the controller's name-miss re-discovery:
    - it succeeds on the second pass
    - it still raises `SpeakerNotFound` after one retry, with exactly one
      extra discovery
  - each forced path clearing SoCo's cache (`refresh`, the name miss,
    `reboot`, the `PlaylistManager` callback and `say`'s inline retry), and
    TTL expiry not clearing it
  - `NoSpeakersFound` propagating through the stale-coordinator retry, from
    both `say` and `PlaylistManager._play_via_queue`
- [ ] `tests/test_version.py` asserts `0.4.0`, and its docstring and comments
  are updated.
- [ ] `.venv/bin/python -m pytest -q` passes: 78 existing tests plus the new
  ones, with no existing assertion weakened.

**Docs, smoke, version**
- [ ] `mcp_sonos/__init__.py` sets `__version__ = "0.4.0"`. Nothing else
  hardcodes the version.
- [ ] README:
  - Configuration table: `SONOS_IPS` described as optional seeds, not an
    exhaustive list. It is no longer "recommended", and the README notes it no
    longer hides unlisted speakers. `SONOS_SCAN_NETWORKS` added as a new row.
    `HOST_IP` also noted as bounding the default scan.
  - The MCP config example no longer implies `SONOS_IPS` is needed.
  - Troubleshooting, prerequisites, the "Discovery cache is 30 s" caveat (now
    mentioning the name-miss refresh), the portable-speakers note and the file
    tree comment are all updated.
  - The agent system prompt is checked. Update it only if it mentions
    discovery.
- [ ] `.env.example` covers `SONOS_IPS` as seeds and adds `SONOS_SCAN_NETWORKS`.
- [ ] CLAUDE.md:
  - The Commands section's smoke lines drop the `SONOS_IPS=...` prefix, with a
    note that it can still be set.
  - A `discovery_smoke.py` line is added.
  - The "Operating constraints" SSDP bullets describe the new contract (scan
    first, seeds optional, SSDP as last resort).
  - The SoCo 5 s cache and `_invalidate_speakers()` are noted as an invariant
    for any new forced-refresh path.
- [ ] None of the four smoke scripts contains `setdefault("SONOS_IPS"`.
- [ ] `reap_smoke.py`'s two `list_speakers` reachability checks are wrapped in
  `try/except Exception` so that a `ToolError` reaches `_fail(...)` instead of
  crashing, matching the pattern `queue_smoke.py` already uses.
- [ ] Stale "set `SONOS_IPS` to the correct IPs" failure text in
  `queue_smoke.py` and `reap_smoke.py` now reflects the seeds / scan / SSDP
  contract.
- [ ] New root-level `discovery_smoke.py`:
  - It follows the other smoke scripts' pattern: an in-process FastMCP
    `Client` with `register_tools`.
  - `--runs N` (default 3) calls `list_speakers` N times, then
    `refresh_speakers` once.
  - It prints one JSON line per call:
    `{"call": "...", "elapsed_s": float, "speakers": [{"name", "ip"}]}`.
  - On a tool error it prints the error text to stderr and exits non-zero.
  - It sets no env defaults.

## Verification Steps
- `.venv/bin/python -m pytest -q --timeout=60`. If `pytest-timeout` isn't
  installed, use `timeout 180 .venv/bin/python -m pytest -q`.
- `grep -n 'setdefault("SONOS_IPS"' *.py` should return nothing.
- `grep -n "SSDP" mcp_sonos/server.py` should return no inaccurate claim.
- `grep -rn "0\.3\.0" mcp_sonos tests` should return nothing.
- `timeout 60 .venv/bin/python discovery_smoke.py --runs 1` should print two
  JSON lines listing five speakers and exit 0. This is the one permitted
  read-only hardware check.

## Implementation Guidance
1. **Read the flight Design Decisions first**, then
   `soco/discovery.py:scan_network` and `soco/zonegroupstate.py:ZoneGroupState`
   (`poll`, `clear_cache`) in `.venv/lib/python3.12/site-packages/`.
2. **`speakers.py`**:
   - Keep each stage as a small private function. Suggested names:
     - `_probe_port(ip, port=1400, timeout)`
     - `_expand_seed(ip)`
     - `_scan_networks()`, which returns `(networks, rejected)`
     - `_scan(networks)`
     - `_ssdp(timeout)`
   - `discover_speakers` orchestrates them and builds a trace. Tests
     monkeypatch these private names.
   - Get adapter data via `ifaddr.get_adapters()`, which is already a SoCo
     dependency. Confirm it is importable in the venv, and add it to
     `pyproject.toml` dependencies only if the project's style lists
     transitive dependencies it uses directly. Check `pyproject.toml`.
3. **`controller.py`**:
   - Add `_invalidate_speakers()`. Switch the four forced call sites to it.
   - In `__init__`, the `PlaylistManager` callback becomes
     `invalidate_speakers_cache=self._invalidate_speakers`.
   - `_resolve` adds the miss-retry. Keep `_resolve_coordinator` unchanged; it
     calls `_resolve`.
4. **Tests**: extend `SoCoFake` first, run the existing suite, then add
   `test_discovery.py`. Use the existing `tests/_builders.py` and `_fakes.py`
   idioms.
   - `_invalidate_speakers()` must never call `discover_speakers` itself.
     `test_say_coordinator.py` asserts `calls["n"] == 2`, and that count holds
     only if invalidation just zeroes the TTL and clears SoCo's cache.
   - `SoCoFake.is_visible` is a plain method, so it is always truthy under
     `bool(...)`. For the "zone dropped by `_safe_is_visible`" case, either
     use an ad hoc fake whose `is_visible` raises or is `False`, or make it a
     settable field without breaking existing callers.
   - To control a seed's `visible_zones` / `all_zones`, monkeypatch `sp.SoCo`,
     the name `speakers.py` imports.
5. **Docs, smoke scripts and version** last. Remove numbers from prose
   wherever you can rather than restating them (a project lesson). For
   example, don't write "35 tools" anew.

## Edge Cases
- **Duplicate or whitespace entries in `SONOS_IPS`**: strip them and skip
  empty entries, as `_ips_from_env` already does.
- **A seed that answers TCP but isn't Sonos**, or whose UPnP call raises:
  record it and continue to the next seed.
- **A seed that expands to zero visible zones**, for example a Boost-only
  seed: this counts as "no speakers" for that seed, so continue.
- **The name-miss retry must not loop.** Exactly one extra discovery.
- **`NoSpeakersFound` raised during the name-miss re-discovery** propagates as
  `NoSpeakersFound`, not `SpeakerNotFound`.
- **`_invalidate_speakers` on speakers without `household_id`** (for example,
  an older fake) must not crash the controller. Guard with a try/except per
  speaker.

## Files Affected
- `mcp_sonos/speakers.py`: the pipeline, `NoSpeakersFound`, and the docstring
- `mcp_sonos/controller.py`: `_invalidate_speakers`, the miss-retry, the four
  call sites, the `_say_all` guard, and the `refresh` docstring
- `mcp_sonos/server.py`: two tool descriptions
- `mcp_sonos/__init__.py`: the version
- `tests/_fakes.py`, `tests/test_discovery.py` (new), `tests/test_version.py`
- `README.md`, `.env.example`, `CLAUDE.md`
- `smoke_test.py`, `playlist_smoke.py`, `queue_smoke.py`, `reap_smoke.py`,
  and `discovery_smoke.py` (new)

## Citation Audit (2026-09-28)
Each citation was checked against `80878fc`, and all were found:
- `speakers.py:discover_speakers`, `_ips_from_env`, `_from_ips`,
  `_safe_is_visible`, `lan_host_ip`, `SpeakerNotFound`, `resolve_name`
- `controller.py:SonosController.__init__`: the `PlaylistManager(...,
  invalidate_speakers_cache=lambda: setattr(self, "_speakers_ts", 0.0))`
  argument
- `controller.py`: `_speakers_fresh`, `refresh`, `_resolve`, `reboot`
  (`self._speakers_ts = 0.0`), `say._play_clip` (`with_stale_coord_retry(...,
  invalidate=lambda: setattr(self, "_speakers_ts", 0.0)`), and `_say_all`
  (`if not speakers: raise RuntimeError("No speakers available")`)
- `playlists.py:_play_via_queue`: `with_stale_coord_retry(...,
  invalidate=self._invalidate_speakers_cache`
- `server.py:refresh_speakers`: "Force a fresh SSDP discovery"
- `tests/_fakes.py:SoCoFake`: it has no `household_id` or `zone_group_state`
- `tests/test_version.py`: it asserts `"0.3.0"`
- The four smoke scripts each contain `os.environ.setdefault("SONOS_IPS", ...)`

---

## Post-Completion
Completion steps — status transitions, flight-log update, checking off in the parent flight, and commit — are Flight Control protocol, driven by the execution workflow. Not repeated here.
