# mcp-sonos

MCP server for **local** Sonos control — no Sonos app, no cloud, just
UPnP over your LAN. Built on [SoCo](https://github.com/SoCo/SoCo) and
[FastMCP](https://github.com/jlowin/fastmcp). Offline neural TTS via
[Piper](https://github.com/rhasspy/piper) for announcements.

Designed to drop into an agentic system (Claude Code, custom agents,
Home Assistant, anything that speaks MCP) so the agent can play your
own music and speak on your speakers.

## What it does

19 MCP tools:

| group | tools |
|---|---|
| queries | `list_speakers`, `list_groups`, `refresh_speakers`, `now_playing` |
| transport | `play_url`, `play_file`, `pause`, `resume`, `stop`, `next_track`, `previous_track` |
| volume | `set_volume`, `mute`, `unmute` |
| grouping | `group`, `ungroup`, `partymode`, `dissolve_all_groups` |
| TTS | `say` (target=`"all"` for synced broadcast across every speaker) |

Speakers are addressed by name (case-insensitive). Transport commands
auto-route to the group coordinator; responses include `group_members`
so the agent always sees what got affected.

## Install & run

### With `uvx` (zero install, recommended)

```bash
uvx --from git+https://github.com/msieurthenardier/mcp-sonos mcp-sonos
```

For a private repo, use the SSH form so your existing keys work:

```bash
uvx --from git+ssh://git@github.com/msieurthenardier/mcp-sonos mcp-sonos
```

`uvx` handles the virtualenv, dependencies, and runs the server over
stdio. The first invocation downloads the Piper voice model (~60 MB)
into `~/.cache/mcp-sonos/voices/` — subsequent runs reuse it.

### As an MCP server in Claude Code / Claude Desktop

Add to your MCP config:

```json
{
  "mcpServers": {
    "sonos": {
      "command": "uvx",
      "args": [
        "--from", "git+ssh://git@github.com/msieurthenardier/mcp-sonos",
        "mcp-sonos"
      ]
    }
  }
}
```

### From source

```bash
git clone git@github.com:msieurthenardier/mcp-sonos.git
cd mcp-sonos
uv venv && source .venv/bin/activate
uv pip install -e .
mcp-sonos
```

## Configuration (env vars)

| var | default | purpose |
|---|---|---|
| `SONOS_IPS` | _(empty — auto-discover)_ | Comma-separated speaker IPs to bypass SSDP. Use this when multicast is unreliable (WSL2 default networking, Docker bridges, isolated guest VLANs). |
| `HOST_IP` | _(auto-detected)_ | LAN-reachable IP the audio HTTP server binds. Override when auto-detection picks the wrong interface. |
| `AUDIO_PORT` | _(first free in 8000-8999)_ | Fixed port for the audio HTTP server. Useful for a stable firewall rule. |
| `PIPER_VOICE` | `en_US-lessac-medium` | Voice name; any [Piper voice](https://huggingface.co/rhasspy/piper-voices). |
| `PIPER_DATA_DIR` | `~/.cache/mcp-sonos/voices` | Where voice models are cached. |

## Network requirements

The host running the MCP server must be on the **same LAN/VLAN/SSID**
as the speakers, with:

1. SSDP multicast working (or speakers listed via `SONOS_IPS`)
2. **Inbound** TCP from speakers to the host's audio server — speakers
   pull audio over HTTP, so any firewall between them and the host
   needs to allow the audio port.

### WSL2 specifics

If you're on WSL2, you'll hit two extra speedbumps:

1. **Networking mode.** Default WSL2 networking NATs the distro to a
   `172.x.x.x` address that speakers can't reach. Enable mirrored mode
   in `%USERPROFILE%\.wslconfig`:

   ```ini
   [wsl2]
   networkingMode=mirrored
   ```
   Then `wsl --shutdown` and reopen.

2. **Windows Firewall (inbound).** Even with mirrored mode, Windows
   blocks inbound connections to services bound in WSL. Open the audio
   server's port range from an elevated PowerShell:

   ```powershell
   New-NetFirewallRule -DisplayName 'WSL-Sonos-Audio' `
     -Direction Inbound -Action Allow -Protocol TCP `
     -LocalPort 8000-8999 -RemoteAddress 192.168.1.0/24 `
     -Profile Private,Domain,Public
   ```

   Replace `192.168.1.0/24` with your actual LAN CIDR.

## Architecture

```
mcp_sonos/
├── server.py       # FastMCP — 19 tools, stdio transport
├── controller.py   # All business logic; MCP-agnostic, unit-testable
├── speakers.py     # Discovery (SSDP + SONOS_IPS) + name resolution
├── audio_host.py   # Persistent HTTP server hosting TTS / staged files
└── tts.py          # Piper voice loading + content-hash cache
```

- One `SonosController` per process. Audio HTTP server starts on
  controller init and stays up for the life of the server.
- Piper voice loaded lazily on first `say()`, cached process-wide.
- TTS output cached by `(text, voice, length_scale)` hash — same
  announcement never re-synthesizes.

## Known quirks

- **Sonos firmware ≥85.0** adds a Security Settings panel with a UPnP
  toggle. It's on by default; if a user disables it the server can't
  talk to that household. Error responses will surface clearly.
- **Coordinator-only commands.** SoCo enforces that `play_uri`,
  `pause`, `next`, etc. only work on a group coordinator. The
  controller auto-routes; the agent doesn't need to track this.
- **Transient `None` coordinator** after rapid group changes. The
  controller treats "no coordinator" as "speaker is its own
  coordinator" for resilience.
- **Bonded speakers** (subs, surrounds, stereo pairs) appear as a
  single visible zone — that's what you want; the bonded units don't
  need individual control.

## Acknowledgements

- [SoCo](https://github.com/SoCo/SoCo) — the unofficial Sonos Python
  library, still going strong against current S2 firmware.
- [FastMCP](https://github.com/jlowin/fastmcp) — Pythonic MCP server.
- [Piper](https://github.com/rhasspy/piper) — fast, local neural TTS.
- [svrooij/sonos-api-docs](https://github.com/svrooij/sonos-api-docs)
  — the best raw Sonos UPnP protocol reference.

## License

MIT.
