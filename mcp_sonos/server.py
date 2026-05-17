"""FastMCP server exposing Sonos control as MCP tools.

Run as a stand-alone MCP server (stdio):

    python -m mcp_sonos.server

Or import `mcp` and run programmatically.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .controller import SonosController


mcp = FastMCP(
    name="sonos",
    instructions=(
        "Control Sonos speakers locally over WiFi. Speakers are addressed "
        "by their display name (case-insensitive). Transport commands "
        "(play/pause/etc.) act on the group coordinator under the hood — "
        "the response tells you which speakers were affected. Use 'all' "
        "as the target of `say` for a synchronized announcement across "
        "every speaker."
    ),
)

# One controller per process. Audio HTTP server starts on instantiation.
controller = SonosController()


SpeakerName = Annotated[
    str,
    Field(description="Display name of a Sonos speaker, e.g. 'Kitchen'. Case-insensitive."),
]


# ---- queries ----------------------------------------------------------------


@mcp.tool
def list_speakers() -> list[dict]:
    """List every visible Sonos speaker with its IP, group, volume, and mute state."""
    return controller.list_speakers()


@mcp.tool
def list_groups() -> list[dict]:
    """List current group topology: each coordinator with its members."""
    return controller.list_groups()


@mcp.tool
def refresh_speakers() -> list[dict]:
    """Force a fresh SSDP discovery (use if speakers were added/renamed)."""
    return controller.refresh()


@mcp.tool
def now_playing(speaker: SpeakerName) -> dict:
    """Current track, state, and group info for the speaker's group."""
    return controller.now_playing(speaker)


# ---- transport --------------------------------------------------------------


@mcp.tool
def play_url(
    speaker: SpeakerName,
    url: Annotated[str, Field(description="HTTP(S) URL the speaker should play. Must be reachable from the Sonos LAN.")],
    title: Annotated[str | None, Field(description="Optional title shown on the Sonos display.")] = None,
) -> dict:
    """Play an arbitrary HTTP URL on the speaker's group coordinator."""
    return controller.play_url(speaker, url, title=title)


@mcp.tool
def play_file(
    speaker: SpeakerName,
    path: Annotated[str, Field(description="Absolute path to an audio file on the MCP host. It will be staged and served over HTTP.")],
    title: Annotated[str | None, Field(description="Optional title shown on the Sonos display.")] = None,
) -> dict:
    """Play a local audio file by staging it onto the MCP host's audio server."""
    return controller.play_file(speaker, path, title=title)


@mcp.tool
def pause(speaker: SpeakerName) -> dict:
    """Pause playback on the speaker's group."""
    return controller.pause(speaker)


@mcp.tool
def resume(speaker: SpeakerName) -> dict:
    """Resume paused playback on the speaker's group."""
    return controller.resume(speaker)


@mcp.tool
def stop(speaker: SpeakerName) -> dict:
    """Stop playback on the speaker's group."""
    return controller.stop(speaker)


@mcp.tool
def next_track(speaker: SpeakerName) -> dict:
    """Skip to the next track in the speaker's queue."""
    return controller.next_track(speaker)


@mcp.tool
def previous_track(speaker: SpeakerName) -> dict:
    """Skip to the previous track in the speaker's queue."""
    return controller.previous_track(speaker)


# ---- volume -----------------------------------------------------------------


@mcp.tool
def set_volume(
    speaker: SpeakerName,
    level: Annotated[int, Field(ge=0, le=100, description="Volume 0-100.")],
) -> dict:
    """Set the speaker's volume (per-speaker, not group-wide)."""
    return controller.set_volume(speaker, level)


@mcp.tool
def mute(speaker: SpeakerName) -> dict:
    """Mute one speaker."""
    return controller.mute(speaker)


@mcp.tool
def unmute(speaker: SpeakerName) -> dict:
    """Unmute one speaker."""
    return controller.unmute(speaker)


# ---- grouping ---------------------------------------------------------------


@mcp.tool
def group(
    coordinator: SpeakerName,
    members: Annotated[list[str], Field(description="Speaker names to join under the coordinator.")],
) -> dict:
    """Group speakers under one coordinator. Followers mirror the coordinator's audio."""
    return controller.group(coordinator, members)


@mcp.tool
def ungroup(speaker: SpeakerName) -> dict:
    """Detach the speaker from its current group (it becomes coordinator-of-one)."""
    return controller.ungroup(speaker)


@mcp.tool
def partymode(coordinator: SpeakerName) -> dict:
    """Group every visible speaker under one coordinator (synchronized playback)."""
    return controller.partymode(coordinator)


@mcp.tool
def dissolve_all_groups() -> dict:
    """Ungroup every speaker so each plays independently."""
    return controller.dissolve_all_groups()


# ---- TTS --------------------------------------------------------------------


@mcp.tool
def say(
    target: Annotated[str, Field(description="Speaker name, or the literal 'all' to broadcast in sync across every speaker.")],
    text: Annotated[str, Field(description="What to say. Plain text; will be synthesized via gTTS.")],
    volume: Annotated[int | None, Field(ge=0, le=100, description="Optional volume for the announcement (per affected speaker).")] = None,
    lang: Annotated[str, Field(description="gTTS language code, e.g. 'en', 'fr', 'es'.")] = "en",
) -> dict:
    """Speak text on one speaker, the whole group, or 'all' speakers in sync.

    Blocks until playback finishes. Returned dict includes which
    speakers were actually affected.
    """
    return controller.say(target, text, volume=volume, lang=lang)


def main() -> None:
    mcp.run()  # stdio transport by default


if __name__ == "__main__":
    main()
