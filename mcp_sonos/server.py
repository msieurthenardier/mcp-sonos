"""FastMCP server exposing Sonos control as MCP tools.

Run as a stand-alone MCP server (stdio):

    python -m mcp_sonos.server

Or import `mcp` and run programmatically.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import AfterValidator, Field

from . import __version__
from ._urls import validate_http_url
from .controller import SonosController


mcp = FastMCP(
    name="sonos",
    version=__version__,
    instructions=(
        "Control Sonos speakers locally over WiFi. Speakers are addressed "
        "by their display name (case-insensitive). Transport commands "
        "(play/pause/etc.) act on the group coordinator under the hood — "
        "the response tells you which speakers were affected. Use 'all' "
        "as the target of `say` for a synchronized announcement across "
        "every speaker."
    ),
)


SpeakerName = Annotated[
    str,
    Field(description="Display name of a Sonos speaker, e.g. 'Kitchen'. Case-insensitive."),
]


PlaylistName = Annotated[
    str,
    Field(description="Unique name for the playlist, e.g. 'morning_mix'."),
]


def register_tools(mcp: FastMCP, controller: SonosController) -> None:
    """Register all 33 MCP tools as closures bound to the supplied controller.

    Called from `main()` after constructing the controller so module import
    has no side effects (no TCP bind, no SSDP discovery thread).
    """

    # ---- queries ------------------------------------------------------------

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

    # ---- transport ----------------------------------------------------------

    @mcp.tool
    def play_url(
        speaker: SpeakerName,
        url: Annotated[
            str,
            AfterValidator(validate_http_url),
            Field(description="HTTP(S) URL the speaker should play. Must be reachable from the Sonos LAN."),
        ],
        title: Annotated[str | None, Field(description="Optional title shown on the Sonos display.")] = None,
    ) -> dict:
        """Play an arbitrary HTTP URL on the speaker's group coordinator.

        For a finite clip (an .mp3 file). BLOCKS until the clip finishes. Do
        NOT use this for a never-ending radio stream — it will hang. Use
        `play_stream` for live radio.
        """
        return controller.play_url(speaker, url, title=title)

    @mcp.tool
    def play_stream(
        speaker: SpeakerName,
        url: Annotated[
            str,
            AfterValidator(validate_http_url),
            Field(description="HTTP(S) URL of a live radio stream (e.g. an Icecast .mp3 stream)."),
        ],
        title: Annotated[str | None, Field(description="Optional station name shown on the Sonos display.")] = None,
    ) -> dict:
        """Play a live, never-ending radio stream — returns immediately.

        Use this (not `play_url`) for radio streams. Handles the speaker-model
        differences in how live streams must be started, and confirms the
        stream actually began playing before returning. The result includes
        `state` (should be 'PLAYING') and which `scheme` worked.
        """
        return controller.play_stream(speaker, url, title=title)

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

    # ---- volume -------------------------------------------------------------

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

    # ---- maintenance --------------------------------------------------------

    @mcp.tool
    def reboot(speaker: SpeakerName) -> dict:
        """Reboot a single speaker via its firmware control port.

        Per-speaker, not group-wide. The speaker drops off the LAN for
        ~30-60s while it restarts; re-run refresh_speakers before driving it
        again. Best-effort: the firmware HTTP endpoint is undocumented and
        behaviour varies by model/firmware.
        """
        return controller.reboot(speaker)

    # ---- grouping -----------------------------------------------------------

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

    # ---- TTS ----------------------------------------------------------------

    @mcp.tool
    def say(
        target: Annotated[str, Field(description="Speaker name, or the literal 'all' to broadcast in sync across every speaker.")],
        text: Annotated[str, Field(description="What to say. Plain text; synthesized via Piper neural TTS.")],
        volume: Annotated[int | None, Field(ge=0, le=100, description="Optional volume for the announcement (per affected speaker).")] = None,
        lang: Annotated[str, Field(description="Deprecated. Ignored. Voice selection is set process-wide via the PIPER_VOICE env var.")] = "en",
    ) -> dict:
        """Speak text on one speaker, the whole group, or 'all' speakers in sync.

        Blocks until playback finishes. Returned dict includes which
        speakers were actually affected.
        """
        return controller.say(target, text, volume=volume, lang=lang)

    # ---- playlists ----------------------------------------------------------
    #
    # Playlists are in-memory only — they live for the life of the MCP server
    # process. Build them up with `playlist_create` / `playlist_add` (or the
    # bulk `playlist_add_many`), then `playlist_play` to start continuous
    # playback in the background. The agent is free to add more items while a
    # playlist is playing; subsequent tracks will pick them up.

    @mcp.tool
    def playlist_create(name: PlaylistName) -> dict:
        """Create a new empty playlist. Errors if the name already exists."""
        return controller.playlists.create(name).to_dict()

    @mcp.tool
    def playlist_delete(name: PlaylistName) -> dict:
        """Delete a playlist. Stops any in-progress playback of it first."""
        controller.playlists.delete(name)
        return {"deleted": name}

    @mcp.tool
    def playlist_clear(name: PlaylistName) -> dict:
        """Empty a playlist but keep its name registered."""
        return controller.playlists.clear(name).to_dict()

    @mcp.tool
    def playlist_add(
        name: PlaylistName,
        url: Annotated[
            str,
            AfterValidator(validate_http_url),
            Field(description="HTTP(S) URL of an audio track. Prefer plain HTTP MP3 — see README for stream-format gotchas."),
        ],
        title: Annotated[str | None, Field(description="Optional display title for the Sonos UI and `now_playing`.")] = None,
    ) -> dict:
        """Append one item to a playlist."""
        return controller.playlists.add(name, url, title=title).to_dict()

    @mcp.tool
    def playlist_add_many(
        name: PlaylistName,
        items: Annotated[
            list[dict],
            Field(
                description=(
                    "List of items. Each dict needs 'url'; 'title' is optional. "
                    "Use this instead of repeated playlist_add calls to keep tool "
                    "round-trips down."
                )
            ),
        ],
    ) -> dict:
        """Append many items to a playlist in one call. Use this for bulk-loading."""
        # Scheme validation up front so the MCP response carries a clean
        # per-index error before we even reach the controller. Dict-shape
        # enforcement is intentionally lax here — PlaylistManager.add_many
        # already rejects missing/empty `url` with the same idiom.
        for i, raw in enumerate(items):
            if isinstance(raw, dict) and "url" in raw:
                try:
                    validate_http_url(str(raw["url"]).strip())
                except ValueError as e:
                    raise ValueError(f"items[{i}]: {e}")
        return controller.playlists.add_many(name, items).to_dict()

    @mcp.tool
    def playlist_from_page(
        name: PlaylistName,
        page_url: Annotated[
            str,
            AfterValidator(validate_http_url),
            Field(
                description=(
                    "Web page (e.g. a music blog) to scan for direct .mp3 "
                    "links. The page is fetched and parsed on the server; the "
                    "audio URLs are loaded straight into the playlist without "
                    "passing through you."
                )
            ),
        ],
        limit: Annotated[
            int,
            Field(ge=1, le=30, description="Max number of tracks to load. Default 5."),
        ] = 5,
        offset: Annotated[
            int,
            Field(
                ge=0,
                description=(
                    "Skip the first `offset` matching links, then take `limit`. "
                    "Use for paging: offset=0 is the top of the page, offset=5 "
                    "is the next 5, etc. Ignored when shuffle=True. Default 0."
                ),
            ),
        ] = 0,
        shuffle: Annotated[
            bool,
            Field(
                description=(
                    "If true, load a RANDOM selection of `limit` tracks from "
                    "anywhere on the page instead of the first ones. Use for "
                    "'random'/'surprise me' requests. Default false."
                )
            ),
        ] = False,
    ) -> dict:
        """Build a playlist from .mp3 links found on a web page, in one call.

        Use this to make a playlist from a music blog (e.g. Said the
        Gramophone) when you only have the page URL, not the individual track
        URLs. Creates the playlist if it doesn't exist, or replaces its
        contents if it does. By default it takes the first `limit` tracks; use
        `offset` to page deeper or `shuffle=true` for a random selection.
        Returns a small summary (count + track titles) — then call
        `playlist_play` to start it. Raises an error if the page has no direct
        audio links.
        """
        return controller.playlist_from_page(name, page_url, limit, offset=offset, shuffle=shuffle)

    @mcp.tool
    def playlist_remove(
        name: PlaylistName,
        index: Annotated[int, Field(ge=0, description="0-based index of the item to remove.")],
    ) -> dict:
        """Remove the item at `index` from a playlist."""
        return controller.playlists.remove(name, index).to_dict()

    @mcp.tool
    def playlist_get(name: PlaylistName) -> dict:
        """Return the playlist's name, item count, and full item list."""
        return controller.playlists.get(name).to_dict()

    @mcp.tool
    def playlist_list() -> list[dict]:
        """List every named playlist with its item count."""
        return controller.playlists.list_all()

    @mcp.tool
    def playlist_play(
        speaker: SpeakerName,
        name: PlaylistName,
        shuffle: Annotated[bool, Field(description="Randomize order. Starts with the item at `start_index`, then shuffles the rest.")] = False,
        start_index: Annotated[int, Field(ge=0, description="0-based index of the first item to play.")] = 0,
    ) -> dict:
        """Start continuous background playback of a playlist.

        Returns immediately with session info. The server plays items
        back-to-back on the speaker's group coordinator until the playlist
        ends or playback is preempted (by another `say`, `play_url`, or
        `stop`). External interruptions cleanly end the session.
        """
        return controller.playlists.play(speaker, name, shuffle=shuffle, start_index=start_index)

    @mcp.tool
    def playlist_next(speaker: SpeakerName) -> dict:
        """Skip to the next item in the currently-playing playlist on this speaker."""
        return controller.playlists.next_track(speaker)

    @mcp.tool
    def playlist_previous(speaker: SpeakerName) -> dict:
        """Go back to the previous item in the currently-playing playlist."""
        return controller.playlists.previous_track(speaker)

    @mcp.tool
    def playlist_stop(speaker: SpeakerName) -> dict:
        """Stop the playlist currently playing on this speaker and halt playback."""
        return controller.playlists.stop(speaker)

    @mcp.tool
    def playlist_status(speaker: SpeakerName) -> dict:
        """Return the status of the playlist currently playing on this speaker."""
        return controller.playlists.status(speaker)


def main() -> None:
    # One controller per process. Audio HTTP server starts on instantiation.
    controller = SonosController()
    register_tools(mcp, controller)
    mcp.run()  # stdio transport by default


if __name__ == "__main__":
    main()
