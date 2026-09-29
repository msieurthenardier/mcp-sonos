# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An MCP server (FastMCP) that exposes a Sonos household for local LAN
control via SoCo's UPnP. Tools span discovery, transport, volume,
grouping, TTS announcements, maintenance (reboot), live-radio streaming
(`play_stream`), web-page playlist extraction (`playlist_from_page`), and
in-memory playlists. Designed to be
driven by an agentic system, not a human CLI.

## Commands

```bash
# One-time setup
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'

# Run the MCP server (stdio transport — for an agent to spawn)
.venv/bin/python -m mcp_sonos.server
# Or via uvx without a local checkout:
uvx --from git+https://github.com/msieurthenardier/mcp-sonos mcp-sonos

# Hardware-free unit suite (tests/) — run this first, on every change
.venv/bin/python -m pytest -q

# Smoke tests against real hardware (in-process FastMCP Client; same
# code path the agent uses, no stdio in the middle). Need a reachable
# Sonos household on the LAN. Discovery is zero-config (seeds -> bounded
# scan -> SSDP), so no env var is required; set SONOS_IPS=ip1,ip2,... first
# if this host's default scan/SSDP can't reach the household.
.venv/bin/python smoke_test.py            # basic tools: say, list, etc.
.venv/bin/python playlist_smoke.py        # playlists: natural end, skip, stop
.venv/bin/python queue_smoke.py           # native-queue engine: play, next, stop
.venv/bin/python reap_smoke.py --load     # reap-survival phase 1: loads queue + exits (= the reap)
.venv/bin/python reap_smoke.py --control  # reap-survival phase 2: fresh process drives the live queue
.venv/bin/python discovery_smoke.py --runs 1  # discovery pipeline: list_speakers xN + refresh_speakers
.venv/bin/python targeting_smoke.py topology  # target-set behavior-test apparatus (see --help for every subcommand)

# Build wheel (sanity check on packaging changes)
.venv/bin/pip install build
.venv/bin/python -m build --wheel
```

The pytest unit suite (`tests/`, hardware-free) is the primary regression
net; smoke scripts above are the hardware-only secondary check, for
behavior that only shows up against real speakers. No linter is
configured.

## Architecture

Two layers, deliberately.

**`mcp_sonos/server.py`** is a thin wrapper. Each `@mcp.tool` function
does input validation via Pydantic `Annotated[..., Field(...)]`, then
delegates to `controller`. **Never put business logic in `server.py`** —
the controller is testable standalone (no MCP, no stdio) and any new
behavior belongs there.

**`mcp_sonos/controller.py`** owns the `SonosController` — singleton
per process. Owns:
- Cached speaker list (30 s TTL, refreshed lazily by `_speakers_fresh`)
- The audio HTTP host (started at init, lives for the process)
- The TTS cache directory
- The `PlaylistManager`

Three helpers in `controller.py` are non-obvious but load-bearing:
- `_coordinator_of(speaker)` — returns the speaker itself if SoCo
  reports `coordinator=None` (transient post-group-dissolve state).
- `_group_members_of(speaker)` — same guard for group enumeration, by name.
- `_group_member_uids_of(speaker)` — same guard, by UID (used by the
  target-group planner/executor, which addresses speakers by UID).
Every method that touches `speaker.group.coordinator` or
`speaker.group.members` must go through one of these, otherwise rapid
grouping changes will produce `AttributeError: NoneType ...` crashes.

**`mcp_sonos/targeting.py`** (Flight 2) is the pure, I/O-free planner
behind every audio tool's target-set grouping (`play_url`, `play_file`,
`play_stream`, `say`). It's a cycle-free leaf module, like `_retry.py`
and `_urls.py` — never imports `soco`, never sleeps, never mutates
anything. `plan_target_group(topology, targets, *, detach)` takes a
`GroupInfo` topology snapshot (coordinator UID + member UIDs + the
coordinator's transport state, one entry per group) and an ordered list
of target UIDs, and returns a `TargetPlan`: which coordinators to stop,
in what order to unjoin and join, which UIDs end up as bystanders, and
the plan's `final_members` (the expected membership to confirm against —
for `detach=False` this can be a superset of the targets, since merged
groups pull in their other members too). The planner enforces, by
construction and by an internal simulate-and-check pass
(`_check_join_invariant`), that no `join` in the plan ever targets a UID
that still coordinates other members at that point in the sequence — see
the invariant below.

`SonosController` owns the I/O half, split in two:
- `_plan_targets(names, *, detach)` — read-only. Resolves names via
  `_resolve` (dedupes by UID, keeping the first occurrence), clears
  SoCo's `ZoneGroupState` cache once per household (see the invariant
  below), snapshots the live topology, and calls `plan_target_group`.
- `_execute_plan(ctx)` — issues the plan's stops, then unjoins, then
  joins, confirms the resulting topology by polling (never a fixed
  sleep — see the Flight 1 debrief's recommendation), and raises
  `GroupingError` (no rollback) on a mid-step exception, a confirmation
  timeout, or a bystander whose coordinator is still `PLAYING` after
  separation.

For `play_url` and `say`, grouping happens **inside** `_with_queue_resume`'s
clip phase (the callable passed as `run_clip`), so the pre-existing
native-queue snapshot reads the chosen coordinator's `PLAYING` state
*before* stop-first runs. Splitting `_plan_targets` (before the snapshot)
from `_execute_plan` (inside it) is what makes this ordering possible —
see Flight 2's "Plan / execute split around queue resume" design
decision if you're touching this.

**Grouping invariants** (hardware-verified 2026-09-29, Flight 2):
- **Never `join()` a speaker that currently coordinates other members.**
  Verified on hardware: a coordinator-with-followers' `join()` call
  didn't even move it — coordination silently moved to a different
  speaker instead. Every `join` the executor issues is on a speaker the
  plan has already made standalone (via an earlier `unjoin`, or because
  it was never a coordinator to begin with).
- **A coordinator's `unjoin()` delegates its remaining followers to a
  firmware-chosen new coordinator** — they do NOT each become standalone.
  A follower's `unjoin()` only detaches that one speaker; its former
  group is otherwise unaffected.
- **Always clear SoCo's `ZoneGroupState` cache before a topology read
  used for grouping decisions**, not just before a forced re-discovery.
  `_plan_targets` does this unconditionally on every call (a regroup made
  moments ago — by the Sonos app, or another call — must never feed the
  planner stale topology), and the confirmation poll clears it before
  every read too (SoCo's own cache is 5s).
- **Topology views are per-speaker and eventually consistent; SoCo caches
  whichever speaker it last polled, per household, for 5s.** The last ZGS
  poll before any coordinator-only call must come from that coordinator's
  own view (`_sync_view`). Hardware-verified by Flight 2's leg 3 behavior
  test: `_confirm_bystanders_stopped` polling through a lagging bystander
  after `c0`'s own confirmation left the shared cache holding a view where
  `c0` was still a follower, so the very next `@only_on_master` call on
  `c0` (`play_uri`, `stop`) falsely raised `SoCoSlaveException`. Leg 4
  fixed this with `_sync_view` (force a fresh poll from a given speaker,
  optionally waiting up to 3s for it to report itself coordinator) and
  `_on_coordinator` (run a coordinator-only action, resync-and-retry once
  on `SoCoSlaveException`) — see the "Coordinator-view hardening" section
  below.

### Coordinator-view hardening (Flight 2, leg 4)

- `_sync_view(speaker, *, expect_coordinator=False)` clears SoCo's ZGS
  cache, then reads `speaker.is_coordinator` to force a poll made TO
  `speaker` itself (`zone_group_state.poll(speaker)` — see
  `soco/core.py:is_coordinator` / `soco/zonegroupstate.py:poll`). With
  `expect_coordinator=True`, it re-polls (via `self._sleep`) every 0.1s up
  to 3s until `speaker.is_coordinator` is True, raising `GroupingError`
  naming the view lag if it never is.
- `_on_coordinator(c0, action)` runs a coordinator-only `action(c0)`; on
  `SoCoSlaveException` it resyncs (`_sync_view(c0, expect_coordinator=True)`)
  and retries once, wrapping a second failure as `GroupingError` rather than
  letting the raw SoCo exception escape. Used by `play_stream`'s `stop`/
  `play_uri` and `play_url`'s `play_uri`.
- `_execute_plan` syncs each planned `stop()`'s coordinator immediately
  before calling it (resync-and-retry once on `SoCoSlaveException`), and
  ends — unconditionally, even on the fast path — with
  `_sync_view(c0, expect_coordinator=True)` before reading `group_members`
  from `c0`. `_grouping_error` deliberately does NOT do this trailing sync:
  a `GroupingError` always aborts the caller before any further
  coordinator-only call, so there's nothing left for a stale view to break.
- `playlists.py`'s `_play_via_queue` (`clear_queue`) and `_worker`
  (`play_uri`) both get one stale-coordinator retry via the existing
  `with_stale_coord_retry` helper, for the same reason.
- **Accepted asymmetry, noted as a follow-up candidate**: `say()`'s own
  `with_stale_coord_retry` retry is unbounded-wait (invalidate + re-resolve
  + retry once, no poll loop) rather than `_sync_view`'s bounded
  poll-with-timeout. It passed leg 3's hardware run as-is and was left
  unchanged — `_on_coordinator` was not retrofitted onto `say()`.

**`mcp_sonos/audio_host.py`** — persistent threaded HTTP server. Sonos
plays HTTP URIs, not local paths, so we host the TTS cache (and any
`play_file`-staged files) on a port in 8000-8999. Range is pinned
because the Windows Firewall rule guarding inbound traffic into WSL2
covers exactly that range — don't widen without updating the rule.

**`mcp_sonos/playlists.py`** — in-memory named playlists with a
two-engine playback system.

### Two-engine architecture

`playlist_play` routes to one of two engines based on URL classification:

- **Native Sonos queue** (`engine: "native_queue"`) — used when ALL
  playlist URLs are external (not served by this MCP process's audio
  HTTP server). Items are bulk-loaded into the hardware queue via
  `add_multiple_to_queue`. The speaker handles track advancement;
  playback survives an MCP restart or reap. Control tools
  (`playlist_status`, `playlist_next`, `playlist_previous`,
  `playlist_stop`) drive the live coordinator directly after a reap
  (post-reap identity: tools act on whatever the coordinator is
  currently playing).
- **Worker thread** (`engine: "worker"`) — used when any URL matches
  the MCP audio server's `host_ip:audio_port`, or when `host_ip`/
  `audio_port` are not set (conservative fallback). An in-process
  background thread drives `play_uri` for each track. Playback stops
  when the MCP process exits.

Routing rule: `any_mcp_hosted(urls, host_ip, audio_port)` returns
`True` → worker engine; all-external (or coordinates unknown) →
native-queue engine (or worker fallback if coordinates unknown).

### PlaylistManager dependency injection

`PlaylistManager.__init__` takes four parameters:

- `resolve_coordinator(name) -> (SoCo, SoCo)` — injected so tests
  don't pull in the full `SonosController`.
- `host_ip: str` — the MCP audio server's advertised LAN IP. Used by
  `play()` to classify URLs. Empty string → worker fallback.
- `audio_port: int` — the MCP audio server's TCP port. Zero → worker
  fallback.
- `invalidate_speakers_cache: Callable[[], None]` — resets the
  speakers cache TTL so the next `_resolve_coordinator` forces a fresh
  discovery. Called before a stale-coordinator retry. Defaults to
  no-op so tests don't break.

### Engine discriminator

`playlist_play` (via both `_play_via_queue` and `_play_via_worker`)
returns `engine: "native_queue"` or `engine: "worker"` in its result
dict. Callers (including the agent) should read this key to know which
control path is active after a reap.

### QUEUE_PARENT_ID

```python
QUEUE_PARENT_ID = "A:TRACKS"
```

Used as the `parent_id` for all `DidlMusicTrack` items injected via
`add_multiple_to_queue`. **Must NOT be `"-1"`** — Leg 1 hardware
testing (Flight 1) confirmed that `parent_id="-1"` causes the Sonos
firmware to discard the title field; any other value preserves it.
`"A:TRACKS"` is the conventional music-library container.

### Caveats (behavior that surprises)

- **`status().title` is present but unreliable for queued items.**
  The firmware may return the URI stem, a blank string, or the
  correct title depending on firmware version and how the item was
  injected. Do not assert on `title` in tests or agent logic — prefer
  `artist` and `album`, which are more reliably populated.
- **`say(["all"])` leaves all speakers ungrouped after the clip.**
  `_say_all` dissolves all groups, forms party mode, plays the clip,
  then dissolves again. No group reconstruction occurs. This is
  state-destructive: any custom groupings before the call are gone.
  The agent must re-group speakers explicitly if needed. `detach` is
  ignored for `["all"]` — the broadcast is already whole-house, and
  `"all"` mixed with other names raises `ValueError` (only `say`
  accepts the sentinel at all; the other three audio tools reject it).
- **`detach` (default `True`) reshapes group topology as a side effect
  of every audio-sending tool, not just `say`.** By default, `play_url`,
  `play_file`, `play_stream`, `say`, `playlist_play`, and
  `playlist_from_page` (when given `speakers`) detach their target
  speakers from whatever they were grouped with, group them together, and
  stop (and leave stopped) any bystander that was grouped with a target
  but isn't itself one. Groups containing no target are never touched.
  `detach=False` opts into the old per-group behavior instead — nothing
  is stopped, and if the targets span more than one group, those groups
  are merged (pulling in their other, non-target members too, which is
  the deliberate point of the literal "each target's existing group
  plays as-is" contract). See `targeting.py`'s module docstring and the
  Flight 2 design decisions for the full algorithm.
- **`playlist_from_page(speakers=[])` is rejected, not treated as
  omitted.** Only `speakers=None` (the default — i.e. the parameter left
  out) means "just build the playlist." An explicit empty list reaches
  `playlist_play` -> `_plan_targets`, which raises the same
  `ValueError` every other target-set tool raises for zero targets. The
  playlist is still built before that error surfaces (creation happens
  unconditionally; only the optional play step can fail this way).
- **`next`/`previous` no-session are best-effort (no stale-coord
  retry).** When `next_track` / `previous_track` are called with no
  active worker session, they call `coord.next()` / `coord.previous()`
  directly and swallow any `SoCoSlaveException`. Unlike `say`, there
  is no invalidate-and-retry on slave exception — an advance during
  group churn may be silently lost.
- **`play_url` blocks until clip-end** (or
  `PLAY_URL_RESUME_TIMEOUT_SECONDS` elapses — default 3600 s). The
  method calls `_with_queue_resume`, which polls `_wait_until_stopped`
  before returning. `play_file` inherits this behavior because it
  delegates to `play_url`.

### Session keying (worker engine)

Sessions are keyed by the originally-named speaker's UID, NOT the
coordinator's UID. The worker re-resolves the group coordinator on
every track iteration so the playlist follows the speaker through
grouping changes. Keying by coordinator UID breaks the moment someone
groups the speaker (the lookup goes to a different key) — this was
the first design and it crashed immediately during multi-test runs.
If you refactor, preserve the speaker-UID keying invariant.

**Target sets (Flight 2).** `SonosController.playlist_play(speakers, ...)`
forms the target group first (`_plan_targets` / `_execute_plan`, same as
`play_url`/`say`), then calls `PlaylistManager.play(c0.player_name, ...)`
— `c0`, the chosen coordinator, is the "named speaker" the session gets
keyed on. The group forms once, at start, and is **not** re-imposed
mid-playlist; if someone regroups by hand afterwards, the playlist follows
`c0`, same as always.

Because the agent may now name **any member** of that group in a
control-tool call, not just `c0`, `next_track`/`previous_track`/`stop`/
`status` look up the session via `PlaylistManager._session_for(speaker,
coord)`: try the named speaker's own UID first, then fall back to the UID
of that speaker's *current* coordinator. One helper backs all four call
sites. **Accepted limitation**: the fallback only recovers a session when
the named speaker's current coordinator is still `c0` — if `c0` is later
made a follower of a different coordinator outside this MCP (the `group`
tool, the Sonos app), a control-tool call naming a member of that new
group misses the session. In practice the worker's own URI-mismatch
takeover detection usually ends such a session within one poll anyway —
same best-effort class as the grouping-changes caveat below.

Worker signals: `stop_event`, `skip_event`, `back_event` are
`threading.Event`s. Worker polls them at 4 Hz inside its inner wait
loop. External takeover (a different URI playing) is detected by
comparing `current_track_info().uri` to the item URL — when they
diverge during a `PLAYING` state, the worker exits cleanly. This is
how `say`, `play_url`, manual Sonos-app interaction, etc. reliably
end a worker-engine playlist without explicit coordination.

**`mcp_sonos/tts.py`** — Piper voice loaded lazily, cached
process-wide. Voice ONNX files (~60 MB) auto-download to
`~/.cache/mcp-sonos/voices/` on first use. Output is WAV at 22050 Hz
mono 16-bit — Sonos handles this fine. Cache key is
`sha1(voice|length_scale|text)` so identical announcements don't
re-synthesize.

## Operating constraints (these will bite you)

- **MCP host must be on the same LAN as the speakers.** Multicast SSDP
  and the bounded subnet scan don't traverse routers, Sonos can't reach
  hosts outside its broadcast domain, and the audio HTTP server needs to
  be reachable from each speaker.
- **Discovery is zero-config: configured seeds (optional) -> learned seeds
  -> bounded scan -> SSDP, each stage running only if the previous found
  nothing** (`speakers.py`, Flight 1). `SONOS_IPS` seeds are a way *in*,
  not an exhaustive allow-list — the first live seed's `visible_zones`
  expands to the whole household, so unlisted speakers are still found.
  **Learned seeds** are the IPs from the last successful discovery in this
  process, tried automatically before ever scanning again — this is why
  steady-state discovery normally never scans. The bounded scan
  (`SONOS_SCAN_NETWORKS` overrides it) only runs cold or when every known
  IP has gone quiet, and is deliberately rate-limited
  (`SCAN_MAX_THREADS`): a full-speed scan was found to disrupt in-flight
  connections to the real speakers for a few seconds afterward on some
  hosts (observed under WSL2 mirrored networking), so it isn't an env var
  — it's a fixed safety margin, not something to tune per deployment.
  SSDP is the last resort, kept for hosts whose speakers sit outside the
  scanned network. When every stage comes up empty, discovery raises
  `NoSpeakersFound` (a `RuntimeError`) naming what was tried (including
  any learned seeds) and what env var to set — never an empty list.
- **WSL2 needs both mirrored networking AND a Windows Firewall
  inbound rule** (TCP 8000-8999 from your LAN CIDR). See README's
  "WSL2 specifics" section for the exact PowerShell. Without the
  rule, speakers will go `TRANSITIONING → STOPPED` with zero HTTP
  hits on the audio server — silent failure.
- **Sonos transport commands only work on the coordinator.** SoCo
  raises `SoCoSlaveException` if you call `play_uri` on a follower.
  The controller's `_resolve_coordinator` handles this; the agent
  doesn't need to track it.

## Stream format reality (Sonos-side, not ours)

- **Plain HTTP MP3 is the safe path.** Always.
- **No HLS.** Sonos cannot play `.m3u8`. Period. (Future work in the
  roadmap is an ffmpeg-based transcoding proxy.)
- **AAC is hit-or-miss.** Mostly works as `audio/aacp` over HTTP;
  often fails over HTTPS with chunked encoding.
- **HTTPS is fragile.** Some firmware/cert combinations work, others
  don't. Use HTTP when you have the choice.
- **Sonos firmware ≥85.0** has a per-household UPnP toggle in
  Security Settings. Defaults on; if a user disables it, this MCP
  can't reach that household.

## When extending

- New playback feature → add method to `SonosController`, then a thin
  `@mcp.tool` in `server.py` that calls it. The tool function
  signature is the contract with the agent — annotate inputs with
  `Annotated[..., Field(description=...)]` so the agent gets useful
  parameter descriptions.
- Anything that touches groups must use `_coordinator_of` and
  `_group_members_of` (or `_group_member_uids_of` for UID-based reads).
  Don't bypass them. Anything that *changes* group topology must go
  through `targeting.py`'s planner plus `_plan_targets`/`_execute_plan` —
  never call `.join()`/`.unjoin()` ad hoc against a speaker that might
  currently coordinate others (see the grouping invariants above).
- **Any new forced-refresh path must route through `SonosController._invalidate_speakers()`,
  not just reset `_speakers_ts`.** SoCo caches each household's
  `ZoneGroupState` for 5s process-wide (`POLLING_CACHE_TIMEOUT`,
  `soco/zonegroupstate.py`), underneath our own 30s TTL. Zeroing only
  `_speakers_ts` can still return stale topology if the re-discovery lands
  within that 5s window. `_invalidate_speakers()` clears both layers;
  every existing forced path (`refresh()`, the `_resolve()` name-miss
  retry, `reboot()`, the `PlaylistManager` invalidation callback, `say`'s
  inline stale-coordinator retry) already goes through it. Plain 30s TTL
  expiry deliberately does NOT call it — that path is already past the 5s
  window, so clearing would be wasted work.
- New env vars → document in README's Configuration table AND
  `.env.example`.
- POC scripts in `poc/` are historical; they use Piper via a thin
  re-export wrapper. They still run but aren't the primary surface.
- README's Roadmap section is the punch list for what to harden next.
- **Cross-cutting input validation (defense-in-depth)** → single validator
  module, imported at every enforcement surface. Example:
  `mcp_sonos/_urls.py::validate_http_url` is imported by `server.py`
  (Pydantic `AfterValidator` at the tool boundary), `controller.py`
  (defensive check in `play_url`), and `playlists.py` (in `add` and
  `add_many`, converted to `PlaylistError`). Same policy enforced at every
  entry surface; agents reading the schema see a clean MCP error, direct
  callers see a `ValueError`/`PlaylistError`. Future candidates for this
  pattern: speaker-name normalization, `AUDIO_PORT` range, playlist-name
  validation.
- **Cross-cutting retry behavior** → same single-shared-module pattern, for
  logic rather than validation. Example: `mcp_sonos/_retry.py::with_stale_coord_retry`
  is a cycle-free leaf module (`controller.py` imports `playlists.py`, so the
  retry helper couldn't live in either without creating a circular import) used
  by `controller.py` (`say`) and `playlists.py` (`_play_via_queue`).
  DI callbacks (`invalidate`, `resolve`) let each caller supply its own
  cache-invalidation and re-resolution logic while sharing one retry-and-recover
  implementation.
- **Env vars that can be invalid (paths, ports, etc.)** → parse eagerly at
  `SonosController.__init__`, validate lazily at first use. Example:
  `AUDIO_MEDIA_ROOT` is read once at init and resolved into
  `self.media_root: Path | None`; the `is_dir()` check + extension
  allow-list run on every `play_file` call. Rationale: a misconfigured
  path doesn't crash the MCP server at import time — the remaining tools
  keep working, and the affected tool returns a clear error pointing at
  the env var. Note: this trades startup-fast-fail for graceful
  degradation; pick accordingly per new env var.
- **Directory listing stays disabled on the audio host.** `audio_host.py`
  overrides `list_directory` to return 404 — the host binds `0.0.0.0`
  unauthenticated on the LAN (firewall-scoped, accepted threat model), and
  listing would let anyone on the LAN enumerate the staged-file directory.
  Any refactor of the handler must preserve this guard.

## Versioning

Single source of truth: `mcp_sonos/__init__.py` → `__version__`.
**Change the version here and nowhere else.**

- `pyproject.toml` derives the package version from it via hatchling dynamic version
  (`dynamic = ["version"]` under `[project]` + `[tool.hatch.version] path =
  "mcp_sonos/__init__.py"`). Do NOT add a static `version =` back to `pyproject.toml`.
- `mcp_sonos/server.py` passes `version=__version__` into `FastMCP(...)` so the MCP
  `initialize` handshake advertises the project version (not FastMCP's framework version
  — a regression that previously made the server report `"3.3.1"`).
- `tests/test_version.py` guards the wiring (`mcp.version == __version__`, not `"3.x"`)
  — forgetting to wire a bump fails the suite.

**When to bump**: pre-1.0 semver-style — minor for meaningful new behavior/capabilities,
patch for fixes. Example: native-queue playback capability took it `0.1.0 → 0.2.0`.

## Important context

- **Repo is public**, no auth needed to clone or `uvx` install.
- **Agent system prompt** is in README under "System prompt for your
  agent" — keep it in sync when adding/removing tools or behaviors.
- **The user runs from WSL2 with mirrored networking** (LAN
  192.168.1.0/24, host 192.168.1.50, 5 Connect:Amp speakers at
  .51/.52/.53/.54/.55 in the example). The Windows Firewall rule
  "WSL-Sonos-Audio" is already in place on their machine.

## Flight Operations

This project uses [Flight Control](https://github.com/msieurthenardier/mission-control) via the `mission-control` Claude Code plugin. Skills are invoked as `/mission-control:<skill>` from this project's root.

**Before any mission/flight/leg/squawk work, read these files in order:**
1. `.flightops/README.md` — What the flightops directory contains
2. `.flightops/FLIGHT_OPERATIONS.md` — **The workflow you MUST follow**
3. `.flightops/ARTIFACTS.md` — Where all artifacts are stored
4. `.flightops/agent-crews/` — Project crew definitions for each phase (read the relevant crew file)

**Flight Director role.** This session — the one the human talks to — is the Flight Director: it runs the Flight Control skills, plans directly, and orchestrates spawned crew, and never edits source itself. Spawned agents are crew, never the Flight Director. When a human says a leg is ready to implement, invoke `/mission-control:agentic-workflow`. Do not read the leg spec, plan execution steps, or execute commands directly — the skill orchestrates separate Developer and Reviewer agents and emits `[HANDOFF:...]` and `[COMPLETE:...]` signals. Planning skills (`/mission-control:mission`, `/mission-control:flight`, debriefs, `/mission-control:routine-maintenance`) produce artifacts only and never modify source files.

**Spawned agents** (Developer, Reviewer, Architect, Executor, Validator) do not have the Skill tool. Everything they need is in `.flightops/`; they must not try to load plugin skills.

**Methodology drift.** A SessionStart notice from the plugin means this project is behind the installed plugin version. Recommend `/mission-control:preflight-check` or `/mission-control:init-project` to bring it current; never apply migrations by hand.
