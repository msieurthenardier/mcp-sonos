# Flight Log: Native Queue Playback Path

**Flight**: [Native Queue Playback Path](flight.md)

## Summary
Planned and design-reviewed. Status `ready`. Execution not yet started.

---

## Leg Progress

### queue-metadata-checkpoint (Leg 1, hard gate)
**Status**: completed
**Started**: 2026-06-01
**Completed**: 2026-06-01

#### Notes
Manual hardware gate, run via a throwaway SoCo spike (not committed) against the
live Kitchen zone (192.168.86.53), whose coordinator is **Patio** (192.168.86.49)
— queue ops correctly resolved to and ran on the coordinator, validating the
per-coordinator design decision live.

**Gate decision: PROCEED.**

Findings (the load-bearing unknown, resolved):
1. **Bare URL strings are rejected.** `add_multiple_to_queue([str, ...])` raises
   `AttributeError("'str' object has no attribute 'resources'")`. The queue path
   MUST build DIDL objects.
2. **DIDL objects work.** `add_multiple_to_queue([DidlMusicTrack(... resources=
   [DidlResource(uri, protocol_info="http-get:*:audio/mpeg:*")])])` enqueues
   successfully; `queue_size`/`get_queue` reflect the items; `play_from_queue(0)`
   starts playback from the queue (`playlist_position=1`, duration loads).
3. **Native multi-track advancement CONFIRMED.** Two real external MP3s (from
   saidthegramophone.com → gramotunes.com) queued and played naturally; track 1
   advanced to track 2 with zero MCP involvement (operator confirmed by ear).
   This is the Q1 mechanism proven on hardware.
4. **Title behavior is inconsistent — Leg 3 must pin it.** Custom DIDL `title`
   persisted in one probe (SoundHelix URLs, `parent_id != "-1"`) but reverted to
   the filename for the gramotunes tracks (also `parent_id != "-1"`). Suspected
   factors: embedded ID3 tags on real files vs. DIDL precedence, and/or
   `parent_id="-1"` definitely loses titles. Filename-derived titles always
   render at minimum, so `playlist_status` always shows *something*. Not gate-
   blocking; the maintainer has **de-scoped the Sonos app display** (it shows an
   empty queue for locally-injected items — accepted, intentional move away from
   the app). What matters is hardware-side queuing + advancement, both confirmed.
5. **No stale-coordinator symptom** observed on `play_from_queue` across runs
   (ran on the coordinator). The precautionary `_play_uri_with_stale_coord_retry`
   wrap (flight DD) is retained as cheap insurance, not a confirmed need.

Recipe handed to Leg 3: build `DidlMusicTrack(title=<user/derived>, parent_id=
<non-"-1">, item_id=<unique>, resources=[DidlResource(uri, "http-get:*:audio/
mpeg:*")])`; URL-encode the URI; `coordinator.add_multiple_to_queue(items)`;
`coordinator.play_from_queue(0)` (wrapped in stale-coord retry); `play_mode` for
ordering. Avoid the single `add_to_queue` path (it overrode the title to filename).

---

### url-classifier (Leg 2)
**Status**: landed
**Started**: 2026-06-01
**Completed**: 2026-06-01

#### Changes Made
- `mcp_sonos/_urls.py` — Added `is_mcp_hosted(url: str, host_ip: str, port: int) -> bool`.
  Wraps the entire body in `try/except Exception: return False` to swallow
  `urlparse(...).port` raising `ValueError` on non-integer port tokens.
  Returns `True` iff `parsed.hostname == host_ip AND parsed.port == port` (exact
  match; `None` port is not a match).
- `tests/test_urls.py` — Added 10 new hardware-free unit tests covering all
  acceptance-criteria bullets: same host+port → True; genuine MCP URL → True;
  bare base URL → True; different host → False; no explicit port → False; same
  host different port → False; non-integer port → False; empty/garbage input →
  False. Updated module docstring to reflect new coverage.

#### Test Result
`pytest -x -q`: **20 passed in 0.26 s** (10 new + 10 pre-existing). Full suite green.

---

### queue-backed-play (Leg 3)
**Status**: landed
**Started**: 2026-06-01
**Completed**: 2026-06-01

#### Changes Made
- `mcp_sonos/_urls.py` — Added `any_mcp_hosted(urls, host_ip, port)` one-liner
  composition over `is_mcp_hosted`; used by `playlist_play` routing.
- `mcp_sonos/playlists.py` — Major additions:
  - Module-level `QUEUE_PARENT_ID = "A:TRACKS"` constant (non-`"-1"`, DD-E).
  - `PlaylistManager.__init__` gains `host_ip` / `audio_port` keyword-only params
    for URL classification.
  - `play()` routing: no host/port → worker (conservative fallback); any MCP-hosted
    URL → worker; all-external → native queue.
  - `_play_via_worker()` — extracted from original `play()` body, adds
    `"engine": "worker"` to return dict.
  - `_play_via_queue()` — new native queue path: evicts worker (DD-D signal+stop+join
    as one unit before queue ops), builds DIDL items per Leg 1 recipe + DD-E,
    `clear_queue` → `add_multiple_to_queue` → set `play_mode` → call
    `_play_from_queue_with_stale_coord_retry`. Returns `"engine": "native_queue"` (DD-C).
  - `_play_from_queue_with_stale_coord_retry()` — DD-A sibling of controller's
    `_play_uri_with_stale_coord_retry`; calls `coord.play_from_queue(index)` with
    one recover-on-SoCoSlaveException retry.
  - `next_track()` / `previous_track()` — graceful no-session path returns
    `{"controllable": False, "engine": "native_queue", "speaker": ...}` instead of
    raising `PlaylistError`.
- `mcp_sonos/controller.py` — `PlaylistManager(...)` construction now passes
  `host_ip=self._host_ip, audio_port=self.audio.port`.
- `tests/_fakes.py` — `SoCoFake` extended: list-backed `_queue`, `_play_mode`,
  `is_coordinator = True`, `add_multiple_to_queue` (appends, returns None),
  `play_from_queue` (sets transport PLAYING), `clear_queue` (clears list),
  `queue_size` property, `play_mode` get/set property.
- `tests/test_queue_path.py` — 16 new hardware-free tests covering all AC bullets.

#### Test Result
`pytest -x -q`: **36 passed in 0.31 s** (16 new + 20 pre-existing). Full suite green.

---

### verify-integration (Leg 4)
**Status**: landed
**Started**: 2026-06-01
**Completed**: 2026-06-01

#### Changes Made
- `queue_smoke.py` (new) — Queue-path smoke script mirroring `smoke_test.py` /
  `playlist_smoke.py` conventions: `os.environ.setdefault("SONOS_IPS", ...)`,
  `FastMCP.Client` in-process, `controller = SonosController()` / `register_tools(mcp,
  controller)` at module level. Uses three external SoundHelix MP3 URLs (NOT
  MCP-hosted). Asserts `engine == "native_queue"` and `total_items == len(EXTERNAL_TRACKS)`,
  prints `now_playing` for operator confirmation, then stops and deletes the playlist.
  Fails fast with a clear message if no hardware is reachable.

#### Test Result
`pytest -x -q`: **36 passed in 0.25 s**. No regressions.

#### Manual HAT steps (Leg 5 / operator-run)
- **Q1 reap test**: while queue is active, kill the MCP process and confirm the
  speaker advances tracks autonomously (no MCP involvement).
- **Title-stickiness check**: confirm DIDL titles appear on the hardware side
  during queue playback.

---

## Manual HAT — Q1 reap test (shipped code path)

**Status**: PASS — playback-survival AND native advancement confirmed by operator
(track 1 → track 2 occurred with the MCP process already dead).

Ran the real code path (`playlist_play` → `_play_via_queue`) via the in-process
FastMCP client against the live Kitchen/Patio group, using real saidthegramophone
blog MP3 links (gramotunes.com) with literal spaces in the URL, then exited the
process WITHOUT cleanup (the exit = the reap).

- `playlist_play` returned `engine: "native_queue"`, `total_items: 2`, `started: true`.
- URL encoding verified on a real spaced URL: `…/01%20Anna%20von%20Hausswolff%20-%20Stardust.mp3`
  — encoded once to `%20`, no double-encoding (Leg-3 fix #4 holds on the real path).
- now_playing: `PLAYING`, coordinator Patio; artist/album populated from the file's
  ID3 tags ("Anna von Hausswolff" / "ICONOCLASTS"); now-playing `title` blank
  (title-stickiness nuance — non-blocking, follow-up).
- **Operator confirmed the speaker kept playing after the MCP process exited** —
  Q1 (survive-reaping) proven on the shipped code, not just the Leg-1 raw spike.

## Decisions

_None yet._

---

## Deviations

### Leg 3: conservative worker fallback when no host/port configured
**Deviation**: When `PlaylistManager` is constructed without `host_ip`/`audio_port`
(e.g. in older tests or callers that pre-date Leg 3), all playlists route to the
**worker engine** rather than to the native queue.

**Rationale**: Without audio host coordinates we cannot distinguish MCP-hosted URLs
from external ones. Routing all unconfigured-context playlists to the queue would be
incorrect (a TTS URL would land in the Sonos queue and become unreachable after an MCP
restart). The conservative fallback preserves all pre-Leg-3 behavior and keeps existing
tests green without requiring test refactoring. The production `SonosController` always
supplies real coordinates, so the queue path is taken in production.

---

## Anomalies

_None yet._

---

## Session Notes

### Flight Director Notes
- Loaded `leg-execution.md` crew file (well-formed). Branch `flight/01-native-queue-playback`
  created off `main`; planning artifacts carried along (uncommitted).
- Flight marked `in-flight`. Leg 1 is a manual HAT hard gate → per skill, skipping the
  autonomous Developer design-review/implementation cycle; Flight Director guides the
  operator through verification. Justified: no source code, exploratory hardware spike.
- Legs 2–5 held until the gate lands (Leg 3 design depends on the metadata finding).

### Design review (Architect)
Verdict: **approve with changes**. Three findings folded into the spec before
marking `ready`:
- [high] Classifier can't be a pure `_urls.py` predicate — MCP-hosted URLs are
  host/port-relative (resolved per-process). Reframed to `is_mcp_hosted(url,
  host_ip, port)`, exact host+port match. Still hardware-free testable.
- [medium] `SoCoFake` lacks queue methods (`add_multiple_to_queue` etc.) —
  extending it is in-scope (Leg 3), not a satisfied prerequisite.
- [medium] Worker-eviction race: queue-path play must stop+join any live worker
  session for the speaker before loading the queue. Added as a DD + Leg 3 AC +
  test; pulled the worker-eviction half of mission Q6 into this flight.
Also pre-decided to wrap `play_from_queue` in `_play_uri_with_stale_coord_retry`
(confirm cheaply during the Leg 1 hardware gate). Second review cycle skipped —
changes were direct incorporations of the Architect's own recommendations.
