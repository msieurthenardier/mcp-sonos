# mcp-sonos

MCP server for **local** Sonos control — no Sonos app, no cloud, just
UPnP over your LAN. Built on [SoCo](https://github.com/SoCo/SoCo) and
[FastMCP](https://github.com/jlowin/fastmcp). Offline neural TTS via
[Piper](https://github.com/rhasspy/piper) for announcements.

Designed to drop into an agentic system (Claude Code, custom agents,
Home Assistant, anything that speaks MCP) so the agent can play your
own music and speak on your speakers.

## What it does

33 MCP tools:

| group | tools |
|---|---|
| queries | `list_speakers`, `list_groups`, `refresh_speakers`, `now_playing` |
| transport | `play_url`, `play_file`, `pause`, `resume`, `stop`, `next_track`, `previous_track` |
| volume | `set_volume`, `mute`, `unmute` |
| maintenance | `reboot` |
| grouping | `group`, `ungroup`, `partymode`, `dissolve_all_groups` |
| TTS | `say` (target=`"all"` for synced broadcast across every speaker) |
| playlists | `playlist_create`, `playlist_delete`, `playlist_clear`, `playlist_add`, `playlist_add_many`, `playlist_remove`, `playlist_get`, `playlist_list`, `playlist_play`, `playlist_next`, `playlist_previous`, `playlist_stop`, `playlist_status` |

Speakers are addressed by name (case-insensitive). Transport commands
auto-route to the group coordinator; responses include `group_members`
so the agent always sees what got affected.

`playlist_play` uses **two engines** depending on URL type: all-external
URLs → native Sonos queue (survives MCP restart/reap, speaker advances
independently); any MCP-hosted or local-file URL → in-process worker
thread. The response includes an `engine` key (`native_queue` or
`worker`) so the agent knows which path is active.

## Install & run

### With `uvx` (zero install, recommended)

```bash
uvx --from git+https://github.com/msieurthenardier/mcp-sonos mcp-sonos
```

`uvx` handles the virtualenv, dependencies, and runs the server over
stdio. The first invocation downloads the Piper voice model (~60 MB)
into `~/.cache/mcp-sonos/voices/` — subsequent runs reuse it.

### As an MCP server in Claude Code / Claude Desktop / your agent

```json
{
  "mcpServers": {
    "sonos": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/msieurthenardier/mcp-sonos",
        "mcp-sonos"
      ],
      "env": {
        "SONOS_IPS": "192.168.1.10,192.168.1.11,192.168.1.12",
        "HOST_IP": "192.168.1.50"
      }
    }
  }
}
```

The `env` block is optional but recommended — see [Configuration](#configuration-env-vars) below.

### From source

```bash
git clone https://github.com/msieurthenardier/mcp-sonos.git
cd mcp-sonos
uv venv && source .venv/bin/activate
uv pip install -e .
mcp-sonos
```

## Configuration (env vars)

All optional. Set them in the MCP client's `env` block, or via a `.env`
file when running from source. See `.env.example` in the repo.

| var | default | when to set it |
|---|---|---|
| `SONOS_IPS` | _(empty — auto-discover via SSDP)_ | Comma-separated speaker IPs. **Recommended** when SSDP multicast is unreliable (WSL2 default networking, Docker bridges, isolated guest VLANs, mesh WiFi with broken IGMP) or just for deterministic startup. Bypasses SSDP entirely. Get the IPs from your router or the Sonos app. |
| `HOST_IP` | _(auto-detected by routing probe + interface scan)_ | LAN IP the audio HTTP server should advertise to speakers. Override when auto-detection picks the wrong interface — common when the host has multiple interfaces (Docker, VPN, WSL2 in NAT mode). Must be an IP **the speakers can reach**. |
| `AUDIO_PORT` | _(first free TCP port in 8000-8999)_ | Pin the audio server to a specific port. Useful when your firewall rule allows only one port instead of a range, or for stable logs. |
| `AUDIO_MEDIA_ROOT` | _(unset — `play_file` disabled)_ | Directory the `play_file` tool is allowed to stage from. Capability scoping against a misaligned agent: when unset, `play_file` returns an error and stages nothing. Paths are resolved (symlinks followed) before the containment check; extensions are restricted to `.mp3`/`.wav`/`.flac`/`.m4a`/`.ogg`. Does not secure the audio HTTP host itself — see [Networking / topology limitations](#networking--topology-limitations). |
| `PLAY_URL_RESUME_TIMEOUT_SECONDS` | `3600` | Maximum time `play_url()` (and `play_file()`, which calls it) blocks waiting for a clip to finish before giving up and attempting to resume a native Sonos queue (mid-track, best-effort). Generous default covers most long-form content; live streams that never stop won't auto-resume after this cap (silently swallowed). |
| `PIPER_VOICE` | `en_US-lessac-medium` | Any [Piper voice](https://huggingface.co/rhasspy/piper-voices). Format: `<lang>-<speaker>-<quality>`. Higher quality voices are larger; "medium" is a good balance (~60 MB). |
| `PIPER_DATA_DIR` | `~/.cache/mcp-sonos/voices` | Where voice models are cached. Set this if you want the cache to persist somewhere specific (e.g., a shared volume across container restarts). |

The default voice (`en_US-lessac-medium`) is pinned to a known SHA-256
and verified on download and on the first use of an existing cached
file each process; mismatches are quarantined as `<voice>.onnx.suspect`
and raise. Non-default voices are trust-on-first-use — a `warning` log
prints the observed hash so you can add it to `KNOWN_VOICE_HASHES` in
`mcp_sonos/tts.py` to pin it.

### Picking values

- **Same machine as the server you ran from source**: leave everything empty, auto-detection handles it.
- **You hit "No speakers found" or sporadic discovery failures**: set `SONOS_IPS` explicitly. SSDP is a luxury, not a requirement.
- **Audio server binds but speakers never fetch (`TRANSITIONING → STOPPED` with no HTTP hits)**: `HOST_IP` is wrong, or a firewall is blocking. Set `HOST_IP` to the IP a speaker on the LAN would use to reach this host.
- **Container / VPN / multi-NIC host**: set both `SONOS_IPS` and `HOST_IP` so nothing is guessed.

## Network requirements

The host running the MCP server must be on the **same LAN/VLAN/SSID**
as the speakers, with:

1. SSDP multicast reachable (or speakers listed via `SONOS_IPS`).
2. **Inbound TCP** from each speaker to the host's audio server. Speakers
   pull audio over HTTP, so the OS firewall, host firewall, and any router
   ACLs between them and the host all need to allow the audio port range
   (default 8000-8999, scope to your LAN CIDR).
3. Speakers reachable on **TCP 1400** outbound from the host (SoCo's UPnP
   control port). Usually not blocked, but VLAN ACLs sometimes do.

### WSL2 specifics

Two extra speedbumps if you're hosting from WSL2:

**1. Networking mode.** Default WSL2 NATs the distro to a `172.x.x.x`
address that speakers can't reach. Enable mirrored mode in
`%USERPROFILE%\.wslconfig`:

```ini
[wsl2]
networkingMode=mirrored
```

Then `wsl --shutdown` from Windows and reopen. WSL now shares the host's
network interfaces and gets a real LAN IP.

**2. Windows Firewall (inbound).** Even with mirrored mode, Windows
blocks inbound connections to services bound in WSL. Open the audio
server's port range from an elevated PowerShell:

```powershell
New-NetFirewallRule -DisplayName 'WSL-Sonos-Audio' `
  -Direction Inbound -Action Allow -Protocol TCP `
  -LocalPort 8000-8999 -RemoteAddress 192.168.1.0/24 `
  -Profile Private,Domain,Public
```

Replace `192.168.1.0/24` with your actual LAN CIDR. To remove later:
`Remove-NetFirewallRule -DisplayName 'WSL-Sonos-Audio'`.

## Limitations

Read these before you wire the server into an agent — they save real time.

### Stream format limitations (Sonos-side)

- **No HLS support.** Sonos cannot play `.m3u8` (HTTP Live Streaming) URLs.
  Many radio stations, especially international ones (BBC, etc.), are
  HLS-only. There's no workaround short of transcoding to MP3 on the fly
  via an ffmpeg proxy (not built in — see [Roadmap](#roadmap)).
- **AAC is finicky.** Some AAC streams work; some return "Illegal
  MIME-Type." The pattern usually is: AAC over HTTP with
  `Content-Type: audio/aacp` mostly works; AAC over HTTPS with chunked
  encoding often fails. When in doubt, find the station's MP3 stream.
- **MP3 over plain HTTP is the safe path.** Always prefer
  `http://<host>/<station>.mp3` style URLs. They Just Work.
- **HTTPS streams sometimes work, sometimes don't** depending on the
  speaker's firmware version and the server's cert chain. Plain HTTP is
  more reliable for radio streams.
- **No DRM / no streaming services.** Spotify, Apple Music, YouTube
  Music, etc. require their own auth and DRM. This server has none of
  that — it plays raw audio URLs. (You can still drive Sonos's
  *built-in* music-service integrations via the Sonos app; this MCP
  just doesn't add that capability.)
- **Supported formats**: MP3 (CBR 128-320 kbps, 44.1 kHz preferred),
  WAV (8-48 kHz, 16-bit PCM), FLAC. Avoid 48 kHz where you can; some
  older Sonos hardware glitches on it.

### Sonos / SoCo limitations

- **Coordinator-only commands.** `play_uri`, `pause`, `next`, etc. only
  work on a group coordinator. The controller auto-routes; the agent
  doesn't need to track this, but it's why every response includes
  `group_members`.
- **Transient `None` coordinator** can occur for a few seconds after
  rapid group dissolves. The controller treats it as "speaker is its
  own coordinator" — robust, but if you write new tooling that touches
  `speaker.group.coordinator` directly, mimic this guard.
- **Bonded speakers** (subs, surrounds, stereo pairs) show up as one
  visible zone. Bonded units (the second member of a stereo pair, the
  sub) are hidden — that's intentional, you control them via the visible
  zone.
- **Portable speakers (Move, Roam, Roam SL)** vanish from SSDP when on
  Bluetooth or asleep on battery. They rejoin on wake. Don't cache
  IPs forever (the controller refreshes every 30 s).
- **Firmware 85.0+ Security Settings panel** added a per-household UPnP
  toggle (defaults on). If a user disables it, this MCP can't reach
  that household. Surface the error verbatim — it's clear enough.
- **Music-service auth in SoCo is broken** (Spotify/Apple/Amazon). This
  is fine for our use case (we play raw URLs), but if you ever try to
  use SoCo's `add_to_queue` with a service URI, expect breakage.

### TTS / `say` limitations

- **`say` interrupts current playback, then auto-resumes a native queue
  (mid-track, best-effort).** If the speaker had a native Sonos queue
  active (`engine: "native_queue"` from a prior `playlist_play`), the
  controller snapshots the queue position before the clip and resumes
  at that track after `say` returns (seek to the captured position;
  falls back to start-of-track if the seek fails). For radio streams,
  one-shot `play_url` calls, or a worker-engine playlist, no
  auto-resume occurs — the agent must capture `now_playing` first,
  then `play_url` the original URL after `say` returns.
- **`say("all")` leaves every speaker ungrouped after the clip.** The
  implementation dissolves all groups, forms party mode, broadcasts the
  clip, then dissolves again — no group reconstruction. If the speakers
  were in custom groups before the announcement, those groups are gone;
  the agent must re-group them explicitly.
- **`resume`/`pause` only work for queue-based playback**, not for
  radio streams or one-shot `play_url` calls. After `stop` on a
  stream, you have to `play_url` again to restart it.
- **First `say` per process is slow (~2 s)**: Piper voice load + ONNX
  Runtime init. Subsequent calls are ~30 ms (voice cached in memory
  *and* content-hashed file cache, so identical text never re-synths).
- **Voice model download requires internet** on first use. After that,
  fully offline. Pre-warm by running `mcp-sonos` once before going
  offline.
- **Language ≠ accent ≠ voice.** "Spanish" via the default English voice
  sounds bad. Change `PIPER_VOICE` to e.g. `es_ES-mls_10246-medium`.

### Networking / topology limitations

- **Same LAN / VLAN / SSID required.** Multicast doesn't traverse most
  routers, and "guest network isolation" on consumer routers blocks
  the in-LAN traffic Sonos needs.
- **Cloud / remote hosts cannot work** unless you VPN them onto the
  LAN. There's no proxy that solves "the agent runs on a public VM and
  speakers are at home."
- **Audio server is unauthenticated.** Anything served by the audio
  HTTP server (TTS cache + staged `play_file` content) is readable by
  anyone on the LAN who can reach the port. The Windows Firewall rule
  scopes it to your subnet, but on a hostile LAN treat it as
  effectively public. Two narrowings worth knowing: (a) `play_file`
  cannot stage files outside `AUDIO_MEDIA_ROOT` (and rejects calls
  entirely when that env var is unset), so a misaligned agent cannot
  copy e.g. `~/.ssh/id_rsa` into the serve root; (b) directory listing
  is disabled — `GET /` returns 404, so a LAN listener cannot enumerate
  what's inside the serve root. Direct access by known filename still
  works (Sonos needs that to fetch audio), so any file already in the
  serve root remains readable to anyone who can guess or learn its
  name.
- **Discovery cache is 30 s.** A speaker rename or a new speaker
  showing up takes up to 30 s to reflect in `list_speakers` unless
  the agent calls `refresh_speakers` explicitly.
- **`now_playing` for radio streams is incomplete.** Most streams
  expose only the stream URL, not the current song's metadata. ICY
  metadata parsing isn't implemented (SoCo doesn't do it either).

### Playlist limitations

- **In-memory only.** Playlists vanish on server restart. No
  persistence. Treat them as scratch space for the agent within a
  single conversation/session.
- **Two engines; routing is automatic.** `playlist_play` inspects the
  playlist URLs and picks the engine:
  - **Native Sonos queue** (`engine: "native_queue"`) — all URLs are
    external (not served by this MCP process). Items are bulk-loaded
    into the speaker's hardware queue. The speaker advances tracks
    independently; playback **survives an MCP restart or reap**.
    `playlist_status`, `playlist_next`, `playlist_previous`, and
    `playlist_stop` drive the live coordinator directly — they work
    even after a reap (operating on whatever the coordinator is
    currently playing).
  - **Worker thread** (`engine: "worker"`) — any URL is MCP-hosted
    (served by this process's audio HTTP server) or the server's
    host/port isn't yet known. An in-process background thread drives
    `play_uri` for each track. Playback stops when the MCP process
    exits or is reaped.
- **The Sonos app shows an empty queue for native-queue items.** Items
  injected via `add_multiple_to_queue` appear in the hardware queue
  but not in the Sonos app's "Queue" view. This is a firmware display
  artefact — playback is unaffected.
- **Per-speaker, not per-coordinator.** A session is keyed by the
  speaker the agent named. The worker re-resolves the group
  coordinator on every track so the playlist follows the speaker
  through grouping changes — but you can't run the same playlist on
  two speakers in different groups simultaneously (workaround: group
  them first, then play once on the coordinator).
- **At most one playlist per speaker.** Calling `playlist_play` on a
  speaker that already has an active session stops the old one and
  starts the new.
- **External commands end a worker session.** For the worker engine,
  `say`, `play_url`, manual Sonos-app interaction, or any other source
  taking over the speaker is detected (different URI playing) and the
  worker exits cleanly. For the native-queue engine, control tools
  act on whatever the coordinator is currently playing — there's no
  worker to evict.
- **Polling-based (worker engine).** The worker polls transport state
  every 500 ms. Track-to-track transitions have ~500 ms of dead air.
  Fine for the agent's use case, suboptimal for gapless playback.

### Operational

- **TTS cache grows unbounded** in `/tmp/mcp-sonos-audio/`. On
  long-running deployments, prune it periodically or restart the
  server.
- **Single process, single audio host.** Two MCP server instances on
  the same host will fight over ports unless `AUDIO_PORT` is set
  differently. Don't run two.

## System prompt for your agent

Paste this (or an edited subset) into your agent's system prompt:

````markdown
You have local control of a Sonos sound system via the `sonos` MCP server.
The speakers are on the user's home network; you operate them directly,
no Sonos cloud involved.

## Tools at your disposal

- Discovery: `list_speakers`, `list_groups`, `refresh_speakers`, `now_playing`
- Playback: `play_url(speaker, url, title?)`, `play_file(speaker, path, title?)`
- Transport: `pause`, `resume`, `stop`, `next_track`, `previous_track`
- Volume: `set_volume(speaker, 0-100)`, `mute`, `unmute`
- Maintenance: `reboot(speaker)` — restarts one speaker (drops off the
  LAN ~30-60s; re-run `refresh_speakers` before driving it again)
- Grouping: `group(coordinator, [members])`, `ungroup`,
  `partymode(coordinator)`, `dissolve_all_groups`
- Voice: `say(target, text, volume?)` — target can be a speaker name or
  `"all"` for a synchronized announcement across every speaker
- Playlists (in-memory, named):
  `playlist_create`, `playlist_add(name, url, title?)`,
  `playlist_add_many(name, items[])`, `playlist_play(speaker, name,
  shuffle?, start_index?)` → returns `engine` (`native_queue` or
  `worker`), `playlist_next`, `playlist_previous`,
  `playlist_stop`, `playlist_status`, plus
  `playlist_list`/`get`/`remove`/`clear`/`delete`

## How to use it well

1. Speakers are addressed by display name, case-insensitive. Call
   `list_speakers` if you're unsure what's available.

2. Transport commands auto-route to the group coordinator. You never
   need to track which speaker is leading a group. Each response
   includes `group_members` so you can see what was affected. Trust it.

3. For radio and streams, prefer plain HTTP MP3. Sonos does NOT support
   HLS (`.m3u8`) at all. AAC is hit-or-miss. If a user names a radio
   station, look for its direct MP3 URL (commonly
   `http://<host>/<station>.mp3`). HTTPS sometimes works but plain HTTP
   is safer.

4. For announcements, use `say` — don't synthesize audio yourself.
   `say` handles TTS, hosting, and (for `target="all"`) the full
   group-then-broadcast-then-ungroup dance. It blocks until playback
   finishes.

5. Volume conventions: 0-100. 30-40 is background, 50-60 is actively
   listening, 70+ is loud. Default to ~40 unless the user signals
   otherwise.

6. "Play X everywhere": call `partymode("<any speaker>")` first, then
   `play_url("<that coordinator>", "<url>")`. Don't ungroup afterward
   unless the user wants speakers independent.

7. "Stop everything": enumerate groups via `list_groups`, call `stop`
   on each coordinator.

8. `say` and `play_url` interrupt whatever was playing and then
   **auto-resume** (mid-track, best-effort) if the speaker had a native
   Sonos queue active: the server snapshots the queue position, plays
   the clip, then resumes at that track (seeking to the captured
   position; falls back to start-of-track if the host rejects the seek).
   No manual capture/replay needed for the native-queue path.

   If the playlist used the **worker engine** (`engine: "worker"` in
   `playlist_play` response) — or if there was no active playlist — the
   auto-resume does not apply. For radio/URL playback or worker-engine
   playlists: capture `now_playing` before the announcement, then
   `play_url` the same URI again afterward. `resume`/`pause` only work
   for queue-based playback, not radio streams.

9. Tool responses already include resulting state. Don't follow up
   with `now_playing` to confirm — read the response.

10. For multi-song playback, use playlists. Build with
    `playlist_create` + `playlist_add_many` (one call with all items
    beats N individual `playlist_add` calls), then `playlist_play`.
    The response includes `engine: "native_queue"` or `engine:
    "worker"` — check this key. With `native_queue` (all-external
    URLs), playback lives on the speaker hardware and survives an MCP
    restart or reap; `playlist_status`, `playlist_next`,
    `playlist_previous`, and `playlist_stop` work even after a reap
    by driving the live coordinator directly. With `worker`, playback
    runs in-process and stops if the MCP server exits. Playlists are
    in-memory only (no persistence across server restart), and adding
    items to a playlist that's already playing is fine — newly-appended
    tracks will be picked up when the worker reaches them.

11. Playlist control after interruption differs by engine. For the
    **worker engine**: `say`, `play_url`, or external Sonos-app
    interaction terminates the worker (it detects the takeover via URI
    mismatch and exits). Call `playlist_stop` rather than Sonos
    `pause` — use `playlist_play(start_index=N)` to resume from a
    saved index. For the **native-queue engine**: there is no worker to
    evict; control tools (`playlist_stop`, `playlist_next`, etc.) drive
    the live coordinator directly. `say` / `play_url` will auto-resume
    the queue mid-track (best-effort) after the clip finishes — you do
    not need to manually restart the playlist.

## What NOT to do

- Don't pass HLS (`.m3u8`) URLs — Sonos will reject them.
- Don't pass Spotify/YouTube/Apple Music URLs — this MCP has no
  service auth. Stick to direct audio URLs (MP3/AAC/WAV/FLAC over HTTP).
- Don't manually generate TTS files and pass URLs to `play_url` —
  use `say`.
- Don't poll `now_playing` to wait for an announcement to finish; `say`
  already blocks until playback completes.
- Don't make announcements unless the user explicitly asks for one or
  context makes it clearly desired (timer fires, the user said "tell
  everyone dinner's ready"). A speaker playing music is a deliberate
  state — don't interrupt for status updates the user didn't request.

## Error handling

Unknown speaker names return an error listing the valid names — surface
that to the user verbatim rather than guessing. Network errors ("No
route to host") usually mean a speaker is sleeping or off-network;
suggest the user power-cycle it or check the Sonos app.
````

## Architecture

```
mcp_sonos/
├── server.py       # FastMCP — 33 tools, stdio transport
├── controller.py   # All business logic; MCP-agnostic, unit-testable
├── speakers.py     # Discovery (SSDP + SONOS_IPS) + name resolution
├── audio_host.py   # Persistent HTTP server hosting TTS / staged files
├── playlists.py    # Named playlists + two-engine playback (native queue / worker)
└── tts.py          # Piper voice loading + content-hash cache
```

- One `SonosController` per process. Audio HTTP server starts on
  controller init and stays up for the life of the server.
- Playlist routing: `playlist_play` checks whether any URL is
  MCP-hosted (same `host_ip:audio_port` as this server). All-external
  → native Sonos queue (survives restarts). Any local/MCP-hosted URL
  → worker thread (requires this process to stay alive).
- `say()` and `play_url()` auto-resume a native queue mid-track
  (best-effort) when a queue was active before the clip started:
  snapshot `playlist_position`, play clip, then `play_from_queue` +
  seek. Seek failure falls back to start-of-track silently.
- Piper voice loaded lazily on first `say()`, cached process-wide.
- TTS output cached by `(text, voice, length_scale)` hash — same
  announcement never re-synthesizes.

## Roadmap

Hardening ideas for when this gets picked back up:

- **Stream proxy / transcoder** (ffmpeg-based) so HLS and finicky AAC
  stations Just Work. New tool: `play_radio(speaker, url, title)`.
- **Playlist persistence** — playlists currently live only in RAM and
  vanish on server restart. A small SQLite store or JSON file would
  let "morning_mix" survive across restarts.
- **Sonos Favorites + TuneIn** read-only access, so the agent can say
  "play the radio station I favorited."
- **ICY metadata parsing** so `now_playing` for radio streams returns
  the actual song title.
- ~~**`say` with snapshot/restore**~~ — **Done.** `say` and
  `play_url` now snapshot a native Sonos queue before the clip and
  resume mid-track (best-effort) after it. See `_with_queue_resume`
  in `controller.py`.
- **TTS cache eviction** (LRU or age-based) so `/tmp/mcp-sonos-audio/`
  doesn't grow forever.
- **Authenticated audio host** so the served files aren't readable by
  anyone on the LAN. Bearer token in URL is enough.
- **Multi-household support** — current code assumes one Sonos system
  per process. Multiple households would need scoping.
- **Async SoCo wrapping** — SoCo is sync; wrap each tool call in
  `asyncio.to_thread()` so the FastMCP event loop isn't blocked
  during long ops like `say`.

## Acknowledgements

- [SoCo](https://github.com/SoCo/SoCo) — the unofficial Sonos Python
  library, still going strong against current S2 firmware.
- [FastMCP](https://github.com/jlowin/fastmcp) — Pythonic MCP server.
- [Piper](https://github.com/rhasspy/piper) — fast, local neural TTS.
- [svrooij/sonos-api-docs](https://github.com/svrooij/sonos-api-docs)
  — the best raw Sonos UPnP protocol reference.

## License

MIT.
