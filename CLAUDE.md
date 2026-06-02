# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An MCP server (FastMCP) that exposes a Sonos household for local LAN
control via SoCo's UPnP. 32 tools across discovery, transport, volume,
grouping, TTS announcements, and in-memory playlists. Designed to be
driven by an agentic system, not a human CLI.

## Commands

```bash
# One-time setup
python3 -m venv .venv && .venv/bin/pip install -e .

# Run the MCP server (stdio transport — for an agent to spawn)
.venv/bin/python -m mcp_sonos.server
# Or via uvx without a local checkout:
uvx --from git+https://github.com/msieurthenardier/mcp-sonos mcp-sonos

# Smoke tests against real hardware (in-process FastMCP Client; same
# code path the agent uses, no stdio in the middle). Need a reachable
# Sonos household on the LAN.
SONOS_IPS=192.168.1.51,... .venv/bin/python smoke_test.py            # basic tools: say, list, etc.
SONOS_IPS=192.168.1.51,... .venv/bin/python playlist_smoke.py        # playlists: natural end, skip, stop
SONOS_IPS=192.168.1.51,... .venv/bin/python queue_smoke.py           # native-queue engine: play, next, stop
SONOS_IPS=192.168.1.51,... .venv/bin/python reap_smoke.py --load     # reap-survival phase 1: loads queue + exits (= the reap)
SONOS_IPS=192.168.1.51,... .venv/bin/python reap_smoke.py --control  # reap-survival phase 2: fresh process drives the live queue

# Build wheel (sanity check on packaging changes)
.venv/bin/pip install build
.venv/bin/python -m build --wheel
```

No test framework, no linter configured. Smoke tests are the regression net.

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

Two helpers in `controller.py` are non-obvious but load-bearing:
- `_coordinator_of(speaker)` — returns the speaker itself if SoCo
  reports `coordinator=None` (transient post-group-dissolve state).
- `_group_members_of(speaker)` — same guard for group enumeration.
Every method that touches `speaker.group.coordinator` or
`speaker.group.members` must go through these, otherwise rapid
grouping changes will produce `AttributeError: NoneType ...` crashes.

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
- **`say("all")` leaves all speakers ungrouped after the clip.**
  `_say_all` dissolves all groups, forms party mode, plays the clip,
  then dissolves again. No group reconstruction occurs. This is
  state-destructive: any custom groupings before the call are gone.
  The agent must re-group speakers explicitly if needed.
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
  doesn't traverse routers, Sonos can't reach hosts outside its
  broadcast domain, and the audio HTTP server needs to be reachable
  from each speaker.
- **SSDP discovery is unreliable under load** (especially during
  group churn). Prefer `SONOS_IPS=ip1,ip2,...` for deterministic
  startup; SSDP is the convenience path, not the contract.
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
  `_group_members_of`. Don't bypass them.
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
- **Env vars that can be invalid (paths, ports, etc.)** → parse eagerly at
  `SonosController.__init__`, validate lazily at first use. Example:
  `AUDIO_MEDIA_ROOT` is read once at init and resolved into
  `self.media_root: Path | None`; the `is_dir()` check + extension
  allow-list run on every `play_file` call. Rationale: a misconfigured
  path doesn't crash the MCP server at import time — the other 31 tools
  keep working, and the affected tool returns a clear error pointing at
  the env var. Note: this trades startup-fast-fail for graceful
  degradation; pick accordingly per new env var.

## Versioning

Single source of truth: `mcp_sonos/__init__.py` → `__version__` (currently `"0.2.0"`).
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

This project uses [Flight Control](https://github.com/msieurthenardier/mission-control).

**Before any mission/flight/leg work, read these files in order:**
1. `.flightops/README.md` — What the flightops directory contains
2. `.flightops/FLIGHT_OPERATIONS.md` — **The workflow you MUST follow**
3. `.flightops/ARTIFACTS.md` — Where all artifacts are stored
4. `.flightops/agent-crews/` — Project crew definitions for each phase (read the relevant crew file)
