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


SpeakerTargets = Annotated[
    list[str],
    Field(
        min_length=1,
        description=(
            "One or more speaker display names (case-insensitive), in the "
            "order you want them treated as targets. By default (see "
            "`detach`) they are detached from any existing groups and "
            "grouped only with each other, and any bystander left behind "
            "(a speaker that was grouped with a target but isn't itself a "
            "target) is stopped and separated so only the targets make "
            "sound. Duplicates are removed. Groups containing no target are "
            "never touched."
        ),
    ),
]


DetachFlag = Annotated[
    bool,
    Field(
        description=(
            "True (default): detach the targets from any existing groups "
            "and play on exactly that set — bystanders left behind are "
            "stopped. False: keep each target's existing group instead; if "
            "the targets span more than one group, those groups are merged "
            "together (pulling in their other, non-target members too) so "
            "everything plays in sync. Nothing is stopped when False."
        )
    ),
]


PlaylistName = Annotated[
    str,
    Field(description="Unique name for the playlist, e.g. 'morning_mix'."),
]


OptionalSpeakerTargets = Annotated[
    list[str] | None,
    Field(
        min_length=1,
        description=(
            "Optional target set to start playback on immediately after "
            "building the playlist — same contract as playlist_play's "
            "`speakers` (see `detach`): by default the targets are "
            "detached from any existing groups and grouped only with each "
            "other, and any bystander is stopped. Omit (the default) to "
            "only build the playlist; start it later with playlist_play. "
            "An explicit empty list is rejected, like every other "
            "target-set tool."
        ),
    ),
]


def register_tools(mcp: FastMCP, controller: SonosController) -> None:
    """Register every MCP tool as a closure bound to the supplied controller.

    Called from `main()` after constructing the controller so module import
    has no side effects (no TCP bind, no SSDP discovery thread).
    """

    # ---- queries ------------------------------------------------------------

    @mcp.tool
    def list_speakers() -> list[dict]:
        """List every visible Sonos speaker with its IP, group, volume, and mute state.

        Raises an explanatory error (naming what was tried and what env
        vars to set) if no speakers can be found on the LAN. A speaker that
        goes unreachable mid-list (dropped off LAN, transient network error)
        does not fail the whole call — its entry comes back degraded, with
        only `name`, `ip`, and an `error` string instead of the full fields.
        """
        return controller.list_speakers()

    @mcp.tool
    def list_groups() -> list[dict]:
        """List current group topology: each coordinator with its members."""
        return controller.list_groups()

    @mcp.tool
    def refresh_speakers() -> list[dict]:
        """Force a fresh discovery, bypassing all caches (use if speakers were added/renamed)."""
        return controller.refresh()

    @mcp.tool
    def now_playing(speaker: SpeakerName) -> dict:
        """Current track, state, and group info for the speaker's group."""
        return controller.now_playing(speaker)

    # ---- transport ----------------------------------------------------------

    @mcp.tool
    def play_url(
        speakers: SpeakerTargets,
        url: Annotated[
            str,
            AfterValidator(validate_http_url),
            Field(description="HTTP(S) URL the target group should play. Must be reachable from the Sonos LAN."),
        ],
        title: Annotated[str | None, Field(description="Optional title shown on the Sonos display.")] = None,
        detach: DetachFlag = True,
    ) -> dict:
        """Play an arbitrary HTTP URL on a target set of speakers, grouped together.

        For a finite clip (an .mp3 file). BLOCKS until the clip finishes. Do
        NOT use this for a never-ending radio stream — it will hang. Use
        `play_stream` for live radio. See `speakers` / `detach` for the
        target-set contract shared by every audio-sending tool.
        """
        return controller.play_url(speakers, url, title=title, detach=detach)

    @mcp.tool
    def play_stream(
        speakers: SpeakerTargets,
        url: Annotated[
            str,
            AfterValidator(validate_http_url),
            Field(description="HTTP(S) URL of a live radio stream (e.g. an Icecast .mp3 stream)."),
        ],
        title: Annotated[str | None, Field(description="Optional station name shown on the Sonos display.")] = None,
        detach: DetachFlag = True,
    ) -> dict:
        """Play a live, never-ending radio stream on a target set — returns immediately.

        Use this (not `play_url`) for radio streams. Handles the speaker-model
        differences in how live streams must be started, and confirms the
        stream actually began playing before returning. The result includes
        `state` (should be 'PLAYING') and which `scheme` worked. See
        `speakers` / `detach` for the target-set contract shared by every
        audio-sending tool.
        """
        return controller.play_stream(speakers, url, title=title, detach=detach)

    @mcp.tool
    def play_file(
        speakers: SpeakerTargets,
        path: Annotated[str, Field(description="Absolute path to an audio file on the MCP host. It will be staged and served over HTTP.")],
        title: Annotated[str | None, Field(description="Optional title shown on the Sonos display.")] = None,
        detach: DetachFlag = True,
    ) -> dict:
        """Play a local audio file on a target set, staging it onto the MCP host's audio server.

        See `speakers` / `detach` for the target-set contract shared by
        every audio-sending tool.
        """
        return controller.play_file(speakers, path, title=title, detach=detach)

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
        speakers: Annotated[
            list[str],
            Field(
                min_length=1,
                description=(
                    "One or more speaker display names (case-insensitive), or "
                    "the single-item list ['all'] to broadcast in sync across "
                    "every speaker (dissolves all groups, plays, then "
                    "dissolves again — `detach` is ignored for ['all']). "
                    "'all' cannot be combined with other names. For a normal "
                    "target set, see `detach` for the grouping contract "
                    "shared by every audio-sending tool."
                ),
            ),
        ],
        text: Annotated[str, Field(description="What to say. Plain text; synthesized via Piper neural TTS.")],
        volume: Annotated[int | None, Field(ge=0, le=100, description="Optional volume for the announcement (applied to every speaker that ends up playing).")] = None,
        lang: Annotated[str, Field(description="Deprecated. Ignored. Voice selection is set process-wide via the PIPER_VOICE env var.")] = "en",
        detach: DetachFlag = True,
    ) -> dict:
        """Speak text on a target set of speakers, or on ['all'] for a synced whole-house broadcast.

        Blocks until playback finishes. Returned dict includes which
        speakers were actually affected.
        """
        return controller.say(speakers, text, volume=volume, lang=lang, detach=detach)

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
        speakers: OptionalSpeakerTargets = None,
        detach: DetachFlag = True,
    ) -> dict:
        """Build a playlist from .mp3 links found on a web page (and optionally play it).

        Use this to play a music blog (e.g. Said the Gramophone) when you only
        have the page URL, not the individual track URLs. Creates the playlist
        (or replaces it if the name exists). By default takes the first `limit`
        tracks; use `offset` to page deeper or `shuffle=true` for a random
        selection. **Pass `speakers` to build AND start playback in this single
        call** — then you are done, no separate playlist_play needed. See
        `speakers` / `detach` for the target-set contract shared by every
        audio-sending tool. Raises an error if the page has no direct audio
        links.
        """
        return controller.playlist_from_page(
            name, page_url, limit, offset=offset, shuffle=shuffle,
            speakers=speakers, detach=detach,
        )

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
        speakers: SpeakerTargets,
        name: PlaylistName,
        shuffle: Annotated[bool, Field(description="Randomize order. Starts with the item at `start_index`, then shuffles the rest.")] = False,
        start_index: Annotated[int, Field(ge=0, description="0-based index of the first item to play.")] = 0,
        detach: DetachFlag = True,
    ) -> dict:
        """Start continuous background playback of a playlist on a target set.

        Forms the target group first — see `speakers` / `detach` for the
        contract shared by every audio-sending tool — then plays items
        back-to-back on the resulting `coordinator` until the playlist ends
        or playback is preempted (by another `say`, `play_url`, or `stop`).
        External interruptions cleanly end the session. Returns immediately
        with session info; control tools (`playlist_next`, `previous`,
        `stop`, `status`) accept any member of the resulting group, not
        just `coordinator`.
        """
        return controller.playlist_play(
            speakers, name, shuffle=shuffle, start_index=start_index, detach=detach
        )

    @mcp.tool
    def playlist_next(speaker: SpeakerName) -> dict:
        """Skip to the next item in the currently-playing playlist.

        `speaker` can be any member of the group `playlist_play` formed,
        not just its `coordinator` — the session is found either way.
        """
        return controller.playlists.next_track(speaker)

    @mcp.tool
    def playlist_previous(speaker: SpeakerName) -> dict:
        """Go back to the previous item in the currently-playing playlist.

        `speaker` can be any member of the group `playlist_play` formed,
        not just its `coordinator` — the session is found either way.
        """
        return controller.playlists.previous_track(speaker)

    @mcp.tool
    def playlist_stop(speaker: SpeakerName) -> dict:
        """Stop the currently-playing playlist and halt playback.

        `speaker` can be any member of the group `playlist_play` formed,
        not just its `coordinator` — the session is found either way.
        """
        return controller.playlists.stop(speaker)

    @mcp.tool
    def playlist_status(speaker: SpeakerName) -> dict:
        """Return the status of the currently-playing playlist.

        `speaker` can be any member of the group `playlist_play` formed,
        not just its `coordinator` — the session is found either way.
        """
        return controller.playlists.status(speaker)


def main() -> None:
    # One controller per process. Audio HTTP server starts on instantiation.
    controller = SonosController()
    register_tools(mcp, controller)
    mcp.run()  # stdio transport by default


if __name__ == "__main__":
    main()
