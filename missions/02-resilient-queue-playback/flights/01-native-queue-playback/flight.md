# Flight: Native Queue Playback Path

**Status**: completed
**Mission**: [Resilient Queue-Backed Playback](../../mission.md)

## Contributing to Criteria
- [ ] Q1 — All-external playlist keeps advancing after the MCP is killed (not respawned)
- [ ] Q2 — External HTTP MP3s bulk-enqueue with titles that render in `playlist_status`/the Sonos app
- [ ] Q3 — Shuffle/normal ordering handled speaker-side; no in-process permutation on the queue path
- [ ] Q5 — Playlist containing any MCP-hosted URL falls back to the existing worker engine, unchanged
- [ ] Q6 (partial) — Worker-eviction half only: a queue-path play cleanly tears down any
  live worker session on the same speaker. The `say`/`play_url` takeover half is deferred to Flight 2.

---

## Pre-Flight

### Objective
Re-back the existing `playlist_play` tool on Sonos's native queue for
all-external playlists, so playback advances speaker-side and survives an MCP
reap. A URL classifier routes any MCP-hosted (local-file/TTS) playlist to the
unchanged worker engine. Same tool surface, new engine behind the
all-external path.

### Open Questions
- [ ] Does `add_multiple_to_queue` carry title/DIDL metadata for bare HTTP MP3
  URLs, or is an explicit DIDL object required? → resolved by Leg 1 (hard gate).

### Design Decisions

**Routing by URL classification**: All-external playlist → native queue path;
any MCP-hosted URL in the playlist → existing worker engine.
- Rationale: MCP-hosted URLs die when `audio_host.py` (in-process daemon) is
  reaped, so they can't survive on the queue. Hybrid satisfies Q5.
- Trade-off: Two playback engines to maintain; classification must be reliable.

**Classifier is host/port-relative, not a static URL predicate**: An MCP-hosted
URL is `http://{host_ip}:{port}/{file}`, where both are resolved per-process at
`SonosController.__init__` (`audio_host.py:36-52`, env-overridable via `HOST_IP`/
`AUDIO_PORT`). The classifier signature takes the audio host's `(host_ip, port)`
as input — e.g. `is_mcp_hosted(url, host_ip, port)` — matching on **exact host
AND port** against `controller.audio`. Leg 3 wires `controller.audio` into it.
- Rationale: "Is this URL MCP-hosted?" is only answerable relative to the live
  audio host; it is *not* analogous to `validate_http_url`.
- Trade-off: Not a pure sibling of `_urls.py`; can live there only if it takes
  host/port as params, otherwise it belongs nearer the controller/audio host.
- Still fully unit-testable hardware-free (pass synthetic host/port).

**Native `play_mode` for ordering**: Queue path uses Sonos `play_mode`
(`NORMAL`/`SHUFFLE`*) instead of the in-process permutation at `playlists.py:227`.
- Rationale: Speaker-side ordering survives reap (Q3); no worker needed.
- Trade-off: Worker path keeps its own permutation (fixed head + shuffled rest)
  — divergent shuffle semantics across the two paths. Leave a code note so a
  future reader doesn't "fix" the inconsistency.

**Queue is per-coordinator**: All queue calls resolve the coordinator via
`_resolve_coordinator`/`_coordinator_of` (CLAUDE.md invariant) and run on the
coordinator; never touch `group.coordinator` directly. SoCo raises
`SoCoSlaveException` on a follower otherwise.

**Wrap `play_from_queue` in stale-coordinator retry**: Pre-decided (was an open
question). `play_from_queue` is the transport-starting call, analogous to
`play_uri`, so wrap it in the existing `_play_uri_with_stale_coord_retry`
recover-once pattern. Leg 1 observed **no** stale-coord symptom across runs, so
this is retained as cheap insurance rather than a confirmed need.

**Queue items: `add_multiple_to_queue` + `DidlMusicTrack` (empirical, Leg 1)**:
Bare URL strings raise `AttributeError`; the queue path must build
`DidlMusicTrack(title=<user/derived>, parent_id=<non-"-1">, item_id=<unique>,
resources=[DidlResource(url, "http-get:*:audio/mpeg:*")])` with URL-encoded URIs,
then `coordinator.add_multiple_to_queue(items)`. `parent_id="-1"` loses titles.
Avoid the single `add_to_queue` path — Leg 1 saw it override titles to filename.
- **Title-stickiness is a Leg 3 sub-task.** Leg 1 saw custom titles persist for
  some URLs but revert to filename for others (suspected ID3-tag precedence).
  Leg 3 must pin the rule; filename-derived titles always render as a floor, and
  the Sonos app display is de-scoped (mission Verification Approach), so this is
  a quality detail, not a blocker.

**Evict any live worker session before queue-path play**: On a queue-path
`playlist_play`, first stop+join any existing `_sessions[speaker.uid]` worker
(`playlists.py:104,210-214`) before clearing/loading the queue. Otherwise the
dying worker's takeover-detection loop (`playlists.py:392`) races the queue
start and its `coord.stop()` can land on top of the just-started native queue.
- This is the worker-eviction half of mission Q6 (the controllable, testable
  part). The `say`/`play_url` takeover half stays in Flight 2.

### Prerequisites
- [ ] Live Sonos hardware on LAN + a set of reachable external HTTP MP3 URLs (Leg 1 needs both)
- [ ] `.venv` active; existing pytest suite green
- [ ] Note: `SoCoFake` (`tests/_fakes.py:87-92`) has only no-op `add_to_queue`/`clear_queue`;
  it lacks `add_multiple_to_queue`/`play_from_queue`/`play_mode`/`queue_size`. Extending it
  is in-scope work (Leg 3), not a satisfied prerequisite.

### Pre-Flight Checklist
- [x] All open questions resolved — only the metadata unknown remains, resolved by Leg 1 (hard gate) by design
- [x] Design decisions documented
- [ ] Prerequisites verified — live hardware + external MP3 URLs confirmed at Leg 1 start
- [x] Validation approach defined
- [x] Legs defined

---

## In-Flight

### Technical Approach
1. **Gate first.** Leg 1 is a manual HAT spike confirming title/metadata
   behavior of `add_multiple_to_queue` against live hardware. The rest of the
   flight does not start until this is answered.
2. Add an external-vs-MCP-hosted classifier taking `(host_ip, port)` input
   (exact host+port match against `controller.audio`); unit-test hardware-free.
3. Re-back `playlist_play`: evict any live worker session for the speaker;
   resolve the coordinator; if all-external, drive the native queue on the
   coordinator (clear → `add_multiple_to_queue` → `play_from_queue` wrapped in
   stale-coord retry, with `play_mode`); else fall through to the unchanged
   worker engine. Extend `SoCoFake` with real queue state to support tests.
4. Verify: local pytest for classifier/routing/fallback/worker-eviction handoff;
   manual HAT for Q1/Q2.

### Checkpoints
- [ ] Leg 1 gate cleared: titles render (or DIDL workaround identified) + stale-coord wrap confirmed
- [ ] Classifier (host/port-relative) unit-tested
- [ ] `SoCoFake` extended with queue state
- [ ] `playlist_play` routes all-external → queue, mixed → worker; evicts prior worker first
- [ ] Manual HAT: kill MCP, playlist keeps advancing (Q1)

### Adaptation Criteria

**Divert if**:
- Leg 1 shows titles can't be made to render even with an explicit DIDL object
  → return to mission to re-scope Q2.

**Acceptable variations**:
- Classifier lives in `_urls.py` *only if* it takes host/port as params;
  otherwise nearer the controller/audio host — implementer's call.
- `SoCoFake` queue state modeled as a plain list + `play_mode` attr, or richer
  — implementer's call, as long as the queue-path tests are deterministic.

### Legs
1. `queue-metadata-checkpoint` *(hard gate)* — **COMPLETE.** Gate PASSED:
   DIDL objects required (bare URLs rejected); native multi-track advancement
   confirmed on hardware; no stale-coord symptom; title-stickiness inconsistent
   (handed to Leg 3); Sonos app display de-scoped. See flight log for the recipe. (Q2)
2. `url-classifier` *(completed)* — Host/port-relative classifier `is_mcp_hosted(url, host_ip,
   port)` (exact host+port match), unit-tested hardware-free with synthetic
   host/port. (supports Q5 routing)
3. `queue-backed-play` *(completed)* — Re-back `playlist_play` on the native queue for
   all-external playlists, using the Leg 1 recipe (DIDL via `add_multiple_to_queue`,
   `parent_id != "-1"`): evict any live worker session for the speaker;
   resolve+use the coordinator; clear/add/play with native `play_mode`;
   `play_from_queue` wrapped in stale-coord retry. Pin title-stickiness (use the
   playlist item's title; fall back to filename). Route any MCP-hosted URL to the
   unchanged worker engine. Extend `SoCoFake` with queue state. Add tests for
   routing, fallback, and worker-active → queue-play handoff. (Q1, Q2, Q3, Q5, Q6-partial)
4. `verify-integration` *(automated portion completed)* — Local pytest for
   classifier/routing/fallback/eviction green (38 tests); `queue_smoke.py` added.
   Manual HAT smoke (kill MCP, watch advance) for Q1/Q2 remains operator-run.
5. `hat-alignment` *(optional — not run)* — Operator satisfied after the Q1 reap
   HAT; the guided session was not needed.
6. `version-reporting` *(completed)* — Debrief-surfaced fix: the MCP advertised
   FastMCP's framework version (3.3.1); now reports its own `0.2.0` from a single
   source (`__init__.__version__` + hatchling dynamic version), wired into
   `FastMCP(version=…)`, with a guard test. (41 tests green.)

## Verification
- **Automated (local pytest, mocked SoCo)**: classifier, queue-vs-worker
  routing, Q5 fallback. Reuses M1 DI scaffolding.
- **Manual HAT**: Q1 (kill MCP, watch advance) and Q2 (titles render) against
  live speakers via `smoke_test.py`/`playlist_smoke.py`. No behavior-test specs.
