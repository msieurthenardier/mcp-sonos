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
.venv/bin/python smoke_test.py            # basic tools: say, list, etc.
.venv/bin/python playlist_smoke.py        # playlists: natural end, skip, stop

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

**`mcp_sonos/playlists.py`** — in-memory named playlists with one
background worker thread per active session.

Critical design decision: **sessions are keyed by the originally-named
speaker's UID, NOT the coordinator's UID.** The worker re-resolves the
group coordinator on every track iteration so the playlist follows
the speaker through grouping changes. Keying by coordinator UID
breaks the moment someone groups the speaker (the lookup goes to a
different key) — this was the first design and it crashed
immediately during multi-test runs. If you refactor this, preserve
the speaker-UID keying invariant.

Worker signals: `stop_event`, `skip_event`, `back_event` are
`threading.Event`s. Worker polls them at 4 Hz inside its inner wait
loop. External takeover (a different URI playing) is detected by
comparing `current_track_info().uri` to the item URL — when they
diverge during a `PLAYING` state, the worker exits cleanly. This is
how `say`, `play_url`, manual Sonos-app interaction, etc. reliably
end a playlist without explicit coordination.

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

## Important context

- **Repo is public**, no auth needed to clone or `uvx` install.
- **Agent system prompt** is in README under "System prompt for your
  agent" — keep it in sync when adding/removing tools or behaviors.
- **The user runs from WSL2 with mirrored networking** (LAN
  192.168.86.0/24, host 192.168.86.38, 5 Connect:Amp speakers at
  .49/.50/.51/.52/.53). The Windows Firewall rule "WSL-Sonos-Audio"
  is already in place on their machine.

## Flight Operations

This project uses [Flight Control](https://github.com/msieurthenardier/mission-control).

**Before any mission/flight/leg work, read these files in order:**
1. `.flightops/README.md` — What the flightops directory contains
2. `.flightops/FLIGHT_OPERATIONS.md` — **The workflow you MUST follow**
3. `.flightops/ARTIFACTS.md` — Where all artifacts are stored
4. `.flightops/agent-crews/` — Project crew definitions for each phase (read the relevant crew file)
