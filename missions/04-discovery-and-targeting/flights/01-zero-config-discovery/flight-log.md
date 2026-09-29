# Flight Log: Zero-Config Discovery

**Flight**: [Zero-Config Discovery](flight.md)

## Summary
Flight planned 2026-09-28. Not yet executed.

---

## Leg Progress

---

## Flight Director Notes

### 2026-09-28: Planning probes (ground truth for the design decisions)
- `lan_host_ip()` returns `192.168.86.173` (`eth1 /24`). The other adapters
  are `lo` and `10.255.255.254/32`.
- Bounded `scan_network(networks_to_scan=["192.168.86.0/24"])` found all 5
  speakers in 5 of 5 runs, taking 0.51–0.59 s each.
- `SoCo("192.168.86.53").visible_zones` returns the 5 speakers. `all_zones`
  returns those plus the Boost at `.48`.
- A dead seed (`192.168.86.200`) takes about 4.1 s to fail with
  `ConnectionError`. That cost is why the flight adds a quick TCP 1400 gate.
- FastMCP passes the exception text word for word as `ToolError`.
- Four smoke scripts `setdefault` placeholder `SONOS_IPS` (`192.168.1.5x`).
  Under seed semantics those become dead seeds, so the flight removes them.
- Suite baseline: 78 passed, 1.60 s.

### 2026-09-28: Design review, cycle 1 (Architect)
- Verdict: approve with changes.
- **[high] Fixed.** SoCo's per-household `ZoneGroupState` 5 s cache
  (`POLLING_CACHE_TIMEOUT`) would make the name-miss retry and
  `refresh_speakers` return stale topology. I verified this in
  `soco/zonegroupstate.py` and `soco/core.py`. Added a design decision:
  `_invalidate_speakers()` clears SoCo's cache on every forced-refresh path.
  This also covers reboot and the stale-coordinator invalidate callback.
- **[medium] Accepted and tested.** `NoSpeakersFound` propagates through the
  unguarded `resolve()` in `with_stale_coord_retry`. It can leave the queue
  loaded but unplayed, which is the same outcome as a failed retry today.
- **[low] Fixed.**
  - Removed the dead empty guard in `_say_all`.
  - Named the changes for `dissolve_all_groups`, `partymode`, and `say("all")`,
    which now raise `NoSpeakersFound`.
  - `NoSpeakersFound` subclasses `RuntimeError`.
  - Added a scan-race divert trigger.
- Substantive change (the new cache design decision reaches the retry path),
  so I spawned a second review cycle.

### 2026-09-28: Design review, cycle 2 (Architect), final
- Verdict: approve with changes. Both cycle-1 fixes were verified against the
  SoCo source and the controller.
- **[high] Fixed.** The shared `SoCoFake` has no `household_id` or
  `zone_group_state`, so rerouting the reboot and `say` invalidation would
  break existing tests. Technical Approach step 4 now extends `SoCoFake` first.
- **[high] Fixed.** `say`'s inline retry lambda is a second stale-coordinator
  call site, separate from `PlaylistManager`'s callback. Both are now named
  in the design decision.
- Recorded non-issues: clearing with an empty cache is benign, and
  `clear_cache()` makes no network call.
- These were precision fixes to call sites and test scaffolding with no change
  in direction. This was the last of the maximum 2 cycles, so no further review
  was run.
