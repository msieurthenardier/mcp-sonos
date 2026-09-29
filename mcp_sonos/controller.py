"""SonosController — all business logic, MCP-agnostic.

The FastMCP tool layer is a thin wrapper that validates inputs and
calls these methods. Keeping things here means we can unit-test the
behavior without the MCP transport.
"""

from __future__ import annotations

import os
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Callable

from soco import SoCo

from . import speakers as sp
from . import targeting
from ._extract import extract_audio_urls
from ._retry import with_stale_coord_retry
from ._urls import validate_http_url
from .audio_host import AudioHost
from .playlists import PlaylistManager
from .tts import synthesize


# Confirmation-poll cap for target-group formation (see `_confirm_final_membership`).
# Kept small and separate from TTS_TIMEOUT_SECONDS/PLAY_URL_RESUME_TIMEOUT_SECONDS —
# grouping settles in well under a second on real hardware (measured 2026-09-29:
# 0.16-0.32s), so 5s is a generous cap, not a tuning knob.
GROUP_CONFIRM_TIMEOUT_SECONDS = 5.0
GROUP_CONFIRM_POLL_INTERVAL_SECONDS = 0.1


# How long a single TTS clip is allowed to play before we give up
# polling. Piper at the default rate is ~150 wpm, so even long messages
# finish well within this.
TTS_TIMEOUT_SECONDS = 30

# Maximum time play_url() will block waiting for a clip to finish before
# giving up and (best-effort) resuming the queue.  Generous default covers
# most long-form content; live streams that never stop simply won't auto-
# resume after this cap (best-effort, swallowed).  Override via env var.
PLAY_URL_RESUME_TIMEOUT_SECONDS = int(
    os.environ.get("PLAY_URL_RESUME_TIMEOUT_SECONDS", "3600")
)

# Sonos has no documented UPnP/SoCo reboot action. The firmware exposes an
# undocumented HTTP endpoint on the device control port (1400); hitting it
# triggers a reboot. The device tears down the connection as it goes down, so
# a dropped/reset/timed-out request is the EXPECTED success signal — only a
# clean refusal (nothing listening) or a DNS failure means the command never
# landed. Behaviour is firmware-dependent and not exercised by the unit suite;
# validate against hardware via a smoke test.
SONOS_CONTROL_PORT = 1400
REBOOT_TIMEOUT_SECONDS = 5


def _reboot_via_http(ip: str, timeout: float = REBOOT_TIMEOUT_SECONDS) -> None:
    """Issue the reboot request to a speaker's control port.

    Returns normally if the reboot command was (best-effort) delivered —
    including when the device drops the connection mid-flight. Raises
    RuntimeError only when we can tell the command did not land.
    """
    url = f"http://{ip}:{SONOS_CONTROL_PORT}/reboot"
    try:
        with urllib.request.urlopen(url, timeout=timeout):  # noqa: S310 (LAN device, fixed scheme)
            return
    except (RemoteDisconnected, ConnectionResetError, TimeoutError):
        # Device went down before/while answering — that's the reboot.
        return
    except urllib.error.HTTPError:
        # Reached the device and it answered (some firmware 3xx/4xx the page
        # but still reboots). Treat as delivered.
        return
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (RemoteDisconnected, ConnectionResetError, TimeoutError)):
            return
        raise RuntimeError(f"could not reach {url}: {reason}") from exc


def _track_state(speaker: SoCo) -> dict:
    """Return a JSON-safe snapshot of a speaker's playback state."""
    info = speaker.get_current_transport_info()
    track = speaker.get_current_track_info()
    return {
        "state": info.get("current_transport_state"),
        "title": track.get("title"),
        "artist": track.get("artist"),
        "album": track.get("album"),
        "position": track.get("position"),
        "duration": track.get("duration"),
        "uri": track.get("uri"),
    }


def _coordinator_of(speaker: SoCo) -> SoCo:
    """Return the coordinator for `speaker`, or `speaker` itself.

    SoCo briefly returns `group.coordinator = None` after rapid topology
    changes. In that state the speaker is effectively a coordinator-of-
    one, so we report it as such. This makes every downstream call
    (transport, now-playing, group lookups) robust against the lull.
    """
    try:
        if speaker.group:
            c = speaker.group.coordinator
            if c is not None:
                return c
    except Exception:
        pass
    return speaker


def _group_members_of(speaker: SoCo) -> list[str]:
    try:
        if speaker.group and speaker.group.members:
            return sorted(m.player_name for m in speaker.group.members)
    except Exception:
        pass
    return [speaker.player_name]


def _group_member_uids_of(speaker: SoCo) -> list[str]:
    """Same guarded shape as `_group_members_of`, but UIDs instead of names.

    Used by the target-group planner/executor, which needs stable
    identifiers rather than display names. Any new code that reads
    `speaker.group.members` must go through one of these two helpers, per
    the CLAUDE.md invariant — never `.group.members` directly.
    """
    try:
        if speaker.group and speaker.group.members:
            return sorted(m.uid for m in speaker.group.members)
    except Exception:
        pass
    return [speaker.uid]


class GroupingError(RuntimeError):
    """Raised when forming a target group fails mid-execution, or its
    resulting topology can't be confirmed within the poll cap.

    No rollback is attempted: because the executor stops bystanders before
    unjoining or joining anyone, a mid-sequence failure leaves at most
    silence and partial grouping — never a bystander left playing target
    audio. The message names the failing step, the requested target names,
    and a cache-cleared snapshot of the observed topology of every speaker
    the plan touched, so the caller (agent) can decide whether to retry.
    """


@dataclass
class TargetGroup:
    """Result of executing a `targeting.TargetPlan`."""

    coordinator: str
    members: list[str]
    stopped: list[str]
    detached: bool


@dataclass
class _TargetPlanContext:
    """Everything `_execute_plan` needs, produced by `_plan_targets`.

    Read-only from the caller's perspective (nothing here has been mutated
    on the household yet) — `_execute_plan` is the only place that issues
    stop/unjoin/join calls.
    """

    plan: targeting.TargetPlan
    speakers_by_uid: dict[str, SoCo]
    target_names: list[str]
    c0: SoCo
    detach: bool


def _speaker_dict(speaker: SoCo) -> dict:
    coord = _coordinator_of(speaker)
    return {
        "name": speaker.player_name,
        "ip": speaker.ip_address,
        "uid": speaker.uid,
        "is_coordinator": coord.uid == speaker.uid,
        "coordinator_name": coord.player_name,
        "volume": speaker.volume,
        "muted": speaker.mute,
    }


class SonosController:
    """Stateful controller: speakers cache + audio host."""

    def __init__(self, cache_dir: Path | None = None, audio_port: int | None = None):
        self.cache_dir = Path(cache_dir or tempfile.gettempdir()) / "mcp-sonos-audio"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._host_ip = sp.lan_host_ip()
        self.audio = AudioHost(self.cache_dir, host_ip=self._host_ip, port=audio_port)
        self.audio.start()
        _mr = os.environ.get("AUDIO_MEDIA_ROOT", "").strip()
        self.media_root: Path | None = Path(_mr).expanduser().resolve() if _mr else None
        self._speakers: list[SoCo] = []
        self._speakers_ts: float = 0.0
        self.playlists = PlaylistManager(
            resolve_coordinator=self._resolve_coordinator,
            host_ip=self._host_ip,
            audio_port=self.audio.port,
            invalidate_speakers_cache=self._invalidate_speakers,
        )
        # Injectable sleep for _say_all topology-settle; defaults to the real
        # time.sleep so production behavior is unchanged.  Tests patch this to
        # a no-op so the 1.0s settle doesn't dominate the suite wall-clock.
        self._sleep = time.sleep

    # ---- discovery / lookup -------------------------------------------------

    def _speakers_fresh(self, max_age: float = 30.0) -> list[SoCo]:
        if not self._speakers or (time.monotonic() - self._speakers_ts) > max_age:
            self._speakers = sp.discover_speakers()
            self._speakers_ts = time.monotonic()
        return self._speakers

    def _invalidate_speakers(self) -> None:
        """Force the next speaker access to bypass both cache layers.

        Zeroes our own 30s TTL (`_speakers_ts`) AND clears SoCo's own
        per-household `ZoneGroupState` cache (`POLLING_CACHE_TIMEOUT` =
        5s) — otherwise a re-discovery that lands within 5s of the last
        poll would return the same stale topology even though our app
        cache was reset. `ZoneGroupState` is shared process-wide per
        household, so clearing it via one cached speaker per household is
        enough.

        This method never discovers anything itself — it only clears
        state so the *next* `_speakers_fresh()` / `refresh()` call is
        forced to. Swallows per-speaker exceptions (e.g. a fake or a
        speaker that went unreachable has no usable `household_id`), and
        is a no-op when the cache is empty.

        Used by every forced-refresh path: `refresh()`, the `_resolve()`
        name-miss retry, `reboot()`, the `PlaylistManager` invalidation
        callback, and `say()`'s inline stale-coordinator retry. Any new
        forced-refresh path must route through this too, or it will
        intermittently see stale topology.
        """
        self._speakers_ts = 0.0
        self._clear_socos_zgs_cache(self._speakers)

    @staticmethod
    def _clear_socos_zgs_cache(speakers: list[SoCo]) -> None:
        """Clear SoCo's per-household `ZoneGroupState` cache, once per
        household, for every speaker in `speakers`.

        Extracted from `_invalidate_speakers` so `_plan_targets` can clear
        SoCo's topology cache before every snapshot WITHOUT also zeroing
        our own 30s discovery TTL (`_speakers_ts`) — the target-group
        planner needs a guaranteed-fresh `ZoneGroupState` read on every
        call, not a forced re-discovery.
        """
        seen_households: set[str] = set()
        for s in speakers:
            try:
                household = s.household_id
            except Exception:
                continue
            if household in seen_households:
                continue
            seen_households.add(household)
            try:
                s.zone_group_state.clear_cache()
            except Exception:
                continue

    def refresh(self) -> list[dict]:
        """Force a fresh discovery, bypassing both cache layers.

        Clears SoCo's own topology cache (via `_invalidate_speakers`) in
        addition to resetting our TTL, then re-discovers immediately via
        the seeds -> bounded-scan -> SSDP pipeline (`speakers.discover_speakers`).
        Use this after adding, renaming, or rebooting a speaker if you
        don't want to wait out the 30s TTL.
        """
        self._invalidate_speakers()
        self._speakers = sp.discover_speakers()
        self._speakers_ts = time.monotonic()
        return [_speaker_dict(s) for s in self._speakers]

    def list_speakers(self) -> list[dict]:
        return [_speaker_dict(s) for s in self._speakers_fresh()]

    def _resolve(self, name: str) -> SoCo:
        try:
            return sp.resolve_name(self._speakers_fresh(), name)
        except sp.SpeakerNotFound:
            # The cached list may be stale (speaker just added, renamed, or
            # rebooted). Force exactly one fresh discovery — bypassing
            # SoCo's own topology cache too — and retry once before giving
            # up. A NoSpeakersFound raised during this re-discovery
            # propagates as-is (not wrapped as SpeakerNotFound).
            self._invalidate_speakers()
            return sp.resolve_name(self._speakers_fresh(), name)

    def _resolve_coordinator(self, name: str) -> tuple[SoCo, SoCo]:
        """Return (named_speaker, its_coordinator).

        Transport commands (play_uri, pause, etc.) must run on the
        coordinator. Falls back to the speaker itself when SoCo
        reports `coordinator=None` (transient post-dissolve state).
        """
        s = self._resolve(name)
        return s, _coordinator_of(s)

    # ---- target-group planning / execution -----------------------------------
    #
    # The pure planning logic lives in `targeting.py` (`plan_target_group`);
    # everything here is the I/O half — name resolution, topology snapshot,
    # and issuing/confirming the mutations. See flight 2's design decisions
    # ("Detach algorithm", "Coordinator choice", "Plan / execute split
    # around queue resume", "Topology confirmation", "Partial failure").

    def _snapshot_topology(
        self, speakers_now: list[SoCo]
    ) -> tuple[list[targeting.GroupInfo], dict[str, SoCo]]:
        """Build a `targeting.GroupInfo` list plus a uid->SoCo map from the
        CURRENT live topology. Always goes through `_coordinator_of` /
        `_group_member_uids_of`, per the CLAUDE.md invariant."""
        groups: dict[str, targeting.GroupInfo] = {}
        speakers_by_uid: dict[str, SoCo] = {}
        for s in speakers_now:
            speakers_by_uid[s.uid] = s
            coord = _coordinator_of(s)
            speakers_by_uid.setdefault(coord.uid, coord)
            if coord.uid not in groups:
                try:
                    state = coord.get_current_transport_info().get("current_transport_state")
                except Exception:
                    state = None
                member_uids = tuple(_group_member_uids_of(coord))
                groups[coord.uid] = targeting.GroupInfo(coord.uid, member_uids, state)
        return list(groups.values()), speakers_by_uid

    def _plan_targets(self, names: list[str], *, detach: bool) -> _TargetPlanContext:
        """Resolve `names`, snapshot the live topology, and plan a target
        group. Read-only — no stop/unjoin/join is issued here.

        Raises `ValueError` for an empty or "all"-containing `names` list
        (only `say()` special-cases the `["all"]` sentinel, before ever
        calling this), `SpeakerNotFound` for an unresolvable name (no side
        effects), and lets `NoSpeakersFound` propagate unwrapped.
        """
        if not names:
            raise ValueError("at least one speaker is required")
        if any(n.strip().casefold() == "all" for n in names):
            raise ValueError(
                "'all' is only supported by say(); pass explicit speaker "
                "names to this tool, or call list_speakers to enumerate them."
            )

        resolved: list[SoCo] = []
        seen_uids: set[str] = set()
        for n in names:
            s = self._resolve(n)
            if s.uid not in seen_uids:
                seen_uids.add(s.uid)
                resolved.append(s)

        # Unconditionally clear SoCo's own ZGS cache before snapshotting —
        # see `_clear_socos_zgs_cache`'s docstring. A regroup made moments
        # ago (Sonos app, another call) must never feed the planner stale
        # topology.
        self._clear_socos_zgs_cache(self._speakers)
        speakers_now = self._speakers_fresh()
        topology, speakers_by_uid = self._snapshot_topology(speakers_now)
        for s in resolved:
            speakers_by_uid.setdefault(s.uid, s)

        target_uids = [s.uid for s in resolved]
        plan = targeting.plan_target_group(topology, target_uids, detach=detach)
        c0 = speakers_by_uid[plan.coordinator_uid]
        return _TargetPlanContext(
            plan=plan,
            speakers_by_uid=speakers_by_uid,
            target_names=[s.player_name for s in resolved],
            c0=c0,
            detach=detach,
        )

    def _execute_plan(self, ctx: _TargetPlanContext) -> TargetGroup:
        """Issue `ctx.plan`'s stops, then unjoins, then joins, then confirm.

        Raises `GroupingError` on a mid-execution exception or a
        confirmation timeout. No rollback (see `GroupingError`'s docstring).
        """
        plan = ctx.plan
        by_uid = ctx.speakers_by_uid
        try:
            for uid in plan.stop:
                by_uid[uid].stop()
            for uid in plan.unjoin:
                by_uid[uid].unjoin()
            c0 = by_uid[plan.coordinator_uid]
            for uid in plan.join:
                by_uid[uid].join(c0)
        except Exception as e:
            raise self._grouping_error("mutation", ctx, str(e)) from e

        if not plan.fast_path:
            self._confirm_final_membership(ctx)
        self._confirm_bystanders_stopped(ctx)

        c0 = by_uid[plan.coordinator_uid]
        stopped_names = [
            by_uid[uid].player_name for uid in plan.bystanders if uid in by_uid
        ]
        return TargetGroup(
            coordinator=c0.player_name,
            members=_group_members_of(c0),
            stopped=stopped_names,
            detached=ctx.detach,
        )

    def _confirm_final_membership(self, ctx: _TargetPlanContext) -> None:
        """Poll (never sleep-and-hope) until `ctx.c0`'s group equals
        `plan.final_members` — the flight's "planned membership", which for
        a `detach=False` merge is a superset of the target set. Clears
        SoCo's ZGS cache before every read (its own 5s cache would
        otherwise mask a just-issued join/unjoin)."""
        plan = ctx.plan
        c0 = ctx.speakers_by_uid[plan.coordinator_uid]
        expected = set(plan.final_members)
        deadline = time.monotonic() + GROUP_CONFIRM_TIMEOUT_SECONDS
        while True:
            self._clear_socos_zgs_cache(self._speakers)
            current = set(_group_member_uids_of(c0))
            if current == expected:
                return
            if time.monotonic() >= deadline:
                raise self._grouping_error(
                    "confirmation",
                    ctx,
                    f"timed out waiting for group membership {sorted(expected)}; "
                    f"last observed {sorted(current)}",
                )
            self._sleep(GROUP_CONFIRM_POLL_INTERVAL_SECONDS)

    def _confirm_bystanders_stopped(self, ctx: _TargetPlanContext) -> None:
        """Cheap insurance against a delegate handoff resuming playback: read
        each bystander's CURRENT coordinator transport state once
        (cache-cleared) and raise if any is PLAYING."""
        plan = ctx.plan
        if not plan.bystanders:
            return
        self._clear_socos_zgs_cache(self._speakers)
        for uid in plan.bystanders:
            s = ctx.speakers_by_uid.get(uid)
            if s is None:
                continue
            coord = _coordinator_of(s)
            try:
                state = coord.get_current_transport_info().get("current_transport_state")
            except Exception:
                state = None
            if state == "PLAYING":
                raise self._grouping_error(
                    "bystander-confirmation",
                    ctx,
                    f"bystander {s.player_name!r}'s coordinator "
                    f"{coord.player_name!r} is still PLAYING",
                )

    def _grouping_error(self, step: str, ctx: _TargetPlanContext, detail: str) -> GroupingError:
        self._clear_socos_zgs_cache(self._speakers)
        involved_uids = (
            list(ctx.plan.stop)
            + list(ctx.plan.unjoin)
            + list(ctx.plan.join)
            + list(ctx.plan.bystanders)
            + [ctx.plan.coordinator_uid]
        )
        seen: set[str] = set()
        observed: list[dict] = []
        for uid in involved_uids:
            if uid in seen:
                continue
            seen.add(uid)
            s = ctx.speakers_by_uid.get(uid)
            if s is None:
                continue
            try:
                coord = _coordinator_of(s)
                observed.append(
                    {
                        "speaker": s.player_name,
                        "coordinator": coord.player_name,
                        "group_members": _group_members_of(coord),
                    }
                )
            except Exception:
                continue
        return GroupingError(
            f"target-group {step} failed for targets {ctx.target_names}: {detail}. "
            f"Observed topology: {observed}"
        )

    # ---- queries ------------------------------------------------------------

    def now_playing(self, name: str) -> dict:
        s, coord = self._resolve_coordinator(name)
        return {
            "speaker": s.player_name,
            "coordinator": coord.player_name,
            "group_members": _group_members_of(coord),
            **_track_state(coord),
        }

    def list_groups(self) -> list[dict]:
        out: dict[str, dict] = {}
        for s in self._speakers_fresh():
            coord = _coordinator_of(s)
            if coord.uid not in out:
                out[coord.uid] = {
                    "coordinator": coord.player_name,
                    "members": [],
                }
            out[coord.uid]["members"].append(s.player_name)
        for g in out.values():
            g["members"].sort()
        return sorted(out.values(), key=lambda g: g["coordinator"])

    # ---- transport ----------------------------------------------------------

    def play_url(
        self,
        speakers: list[str],
        url: str,
        title: str | None = None,
        *,
        detach: bool = True,
    ) -> dict:
        """Play any HTTP URL on a target set of speakers, grouped together.

        By default (``detach=True``) the targets are detached from any
        existing groups and grouped only with each other; bystanders left
        behind are stopped. Pass ``detach=False`` to keep today's per-group
        behavior instead (each target's existing group plays, merged
        together if the targets span more than one group). See the flight's
        "Detach algorithm" / "Opt-out semantics" design decisions.

        Blocking contract (changed in Leg 4): this method BLOCKS until the
        clip finishes (or PLAY_URL_RESUME_TIMEOUT_SECONDS elapses), then
        attempts to resume a native-queue session that was active on the
        chosen coordinator before the clip started (best-effort; see
        `_with_queue_resume`). Return value reflects the post-resume state.

        play_file() inherits this behaviour because it calls play_url().
        """
        # Defence in depth: the MCP tool surface already validates, but
        # direct/test callers reach this method without that gate.
        validate_http_url(url)
        ctx = self._plan_targets(speakers, detach=detach)
        c0 = ctx.c0
        result_box: list[TargetGroup] = []

        def _run() -> None:
            result_box.append(self._execute_plan(ctx))
            by_uid = ctx.speakers_by_uid
            by_uid[ctx.plan.coordinator_uid].play_uri(url, title=title or "MCP playback")

        self._with_queue_resume(
            c0,
            c0.uid,
            _run,
            timeout=PLAY_URL_RESUME_TIMEOUT_SECONDS,
        )
        group = result_box[0]
        coord = ctx.speakers_by_uid[ctx.plan.coordinator_uid]
        return {
            "targets": ctx.target_names,
            "coordinator": group.coordinator,
            "group_members": group.members,
            "stopped": group.stopped,
            "detached": group.detached,
            "url": url,
            **_track_state(coord),
        }

    def play_stream(
        self,
        speakers: list[str],
        url: str,
        title: str | None = None,
        *,
        detach: bool = True,
    ) -> dict:
        """Play a live radio stream (endless) on a target set — non-blocking.

        Forms the target group first (see `play_url`'s `detach` semantics —
        identical here), then starts the stream on the chosen coordinator.

        Unlike ``play_url`` (which is for finite clips and BLOCKS until the
        clip ends), this is for never-ending Icecast/Shoutcast-style streams.
        It returns as soon as the stream is confirmed started.

        Sonos models disagree on how to start a live stream: newer zones take
        a plain ``http://…`` URI, while others (e.g. older Connect/Amp) reject
        it with a 714 ``Illegal MIME-Type`` or stall to STOPPED and only play
        the same URL wrapped in the ``x-rincon-mp3radio://`` scheme. We try
        plain first, confirm the transport actually reaches PLAYING, and fall
        back to the radio scheme (with a short retry for the transient
        701 ``Transition not available``) otherwise. Raises RuntimeError if
        neither scheme sustains playback.
        """
        validate_http_url(url)
        ctx = self._plan_targets(speakers, detach=detach)
        group = self._execute_plan(ctx)
        coord = ctx.speakers_by_uid[ctx.plan.coordinator_uid]
        attempts = (("plain", url), ("radio", "x-rincon-mp3radio://" + url))
        last_reason = ""
        for label, uri in attempts:
            # A clean transport state matters: a 701 "transition not available"
            # is almost always residual state from a just-prior stop/play. Give
            # the coordinator a moment to settle before driving it.
            try:
                coord.stop()
            except Exception:
                pass
            self._sleep(1.5)
            started = False
            for _ in range(3):  # transient 701 retry (radio scheme esp.)
                try:
                    coord.play_uri(uri, title=title or "Live stream")
                    started = True
                    break
                except Exception as e:
                    last_reason = str(e)
                    if "701" in last_reason:
                        self._sleep(1.2)
                        continue
                    break  # non-transient (e.g. 714) → try next scheme
            if not started:
                continue
            # Confirm it actually sustains, not just TRANSITIONING→STOPPED.
            for _ in range(12):
                self._sleep(0.5)
                state = coord.get_current_transport_info().get(
                    "current_transport_state"
                )
                if state == "PLAYING":
                    return {
                        "targets": ctx.target_names,
                        "coordinator": group.coordinator,
                        "group_members": group.members,
                        "stopped": group.stopped,
                        "detached": group.detached,
                        "url": url,
                        "scheme": label,
                        **_track_state(coord),
                    }
                if state == "STOPPED":
                    last_reason = f"{label} scheme stalled to STOPPED"
                    break
        raise RuntimeError(
            f"Could not start stream {url} on {group.coordinator}: {last_reason}. "
            "The stream may be incompatible with this speaker model."
        )

    def playlist_from_page(
        self,
        playlist: str,
        page_url: str,
        limit: int = 5,
        offset: int = 0,
        shuffle: bool = False,
        speakers: list[str] | None = None,
        *,
        detach: bool = True,
    ) -> dict:
        """Build a named playlist from audio links found on a web page.

        Fetches ``page_url`` server-side, extracts up to ``limit`` direct
        ``.mp3`` links, and loads them into the named playlist (creating it
        if absent, replacing its contents if it already exists). The audio
        URLs never pass through the calling model — only a compact summary
        (playlist name, source, count, titles) is returned.

        ``offset`` pages through the page's links (skip the first ``offset``
        matches, then take ``limit``). ``shuffle=True`` instead loads a random
        sample of ``limit`` links from anywhere on the page (``offset`` ignored).

        If ``speakers`` is given, playback is started on that target set
        right away — equivalent to a follow-up ``playlist_play`` — through
        the exact same target-group path (see ``playlist_play`` for the
        ``detach`` contract). The response gains the target-set keys
        (``targets``, ``coordinator``, ``group_members``, ``stopped``,
        ``detached``) plus ``engine`` in that case. When ``speakers`` is
        omitted (``None``) the playlist is only built, as before; start it
        later with ``playlist_play``.

        An explicit ``speakers=[]`` is NOT treated the same as omitted — it
        is rejected with the same ``ValueError`` every other target-set
        tool raises for an empty target list (via ``_plan_targets``,
        through ``playlist_play``), for consistency with ``play_url`` /
        ``play_stream`` / ``say``. The playlist itself is still built
        before that error is raised (creation is unconditional; only the
        optional play step can fail this way).

        Raises RuntimeError if no audio links are found (or ``offset`` is past
        the last link).
        """
        validate_http_url(page_url)
        items = extract_audio_urls(page_url, limit, offset=offset, shuffle=shuffle)
        if not items:
            raise RuntimeError(
                f"No audio (.mp3) links found at {page_url} "
                f"(limit={limit}, offset={offset}). The page may not list "
                "direct audio files, or offset is past the last link."
            )
        # Create-or-replace: idempotent across re-runs with the same name.
        try:
            self.playlists.create(playlist)
        except Exception:
            self.playlists.clear(playlist)
        self.playlists.add_many(playlist, items)
        result = {
            "playlist": playlist,
            "source": page_url,
            "count": len(items),
            "selection": "random" if shuffle else f"page-order[{offset}:{offset + limit}]",
            "titles": [it["title"] for it in items],
        }
        if speakers is not None:
            play = self.playlist_play(speakers, playlist, detach=detach)
            result["playing"] = True
            result.update(play)
        else:
            result["playing"] = False
        return result

    def playlist_play(
        self,
        speakers: list[str],
        name: str,
        *,
        shuffle: bool = False,
        start_index: int = 0,
        detach: bool = True,
    ) -> dict:
        """Start continuous playback of a named playlist on a target set.

        Forms the target group first — same ``detach`` contract as
        ``play_url``/``say``: by default the targets are detached from any
        existing groups and grouped only with each other, and any
        bystander left behind is stopped. See ``play_url``'s docstring and
        the flight's "Detach algorithm" / "Opt-out semantics" design
        decisions for the full algorithm; ``"all"`` is rejected here too
        (only ``say`` accepts it).

        Unlike ``play_url``/``say``, this calls ``_plan_targets`` then
        ``_execute_plan`` directly — no queue-resume wrapper. A playlist
        call always starts a NEW playback session rather than resuming an
        old one, so there is nothing to snapshot (flight 2's "Playlist
        sessions" design decision).

        The playlist engine is started on ``c0`` (the chosen coordinator),
        via ``self.playlists.play(c0.player_name, ...)``. Passing ``c0``'s
        own player name makes it the playlist engine's "named speaker",
        which keys the worker session on ``c0``'s UID — preserving the
        speaker-UID session-keying invariant (see CLAUDE.md's "Session
        keying" section) now that the "named speaker" may be a coordinator
        chosen from among several targets rather than the sole speaker the
        agent asked for.

        Response shape: the engine's own dict — which includes ``engine``
        and, per-engine, a ``speaker`` key — merged with the target-set
        keys ``targets``, ``coordinator``, ``group_members``, ``stopped``,
        ``detached``. ``speaker`` and ``coordinator`` end up holding the
        SAME value here (``c0``'s player name) precisely because ``c0`` is
        both the resolved target-group coordinator and the playlist
        engine's named speaker — both keys are kept rather than merged,
        since ``speaker`` is the engine response's own established key
        (also used by ``playlist_next``/``previous``/``stop``/``status``)
        and ``coordinator`` is the target-set contract's key shared by
        every audio tool.
        """
        ctx = self._plan_targets(speakers, detach=detach)
        group = self._execute_plan(ctx)
        c0 = ctx.speakers_by_uid[ctx.plan.coordinator_uid]
        engine_result = self.playlists.play(
            c0.player_name, name, shuffle=shuffle, start_index=start_index
        )
        return {
            **engine_result,
            "targets": ctx.target_names,
            "coordinator": group.coordinator,
            "group_members": group.members,
            "stopped": group.stopped,
            "detached": group.detached,
        }

    def play_file(
        self,
        speakers: list[str],
        path: str,
        title: str | None = None,
        *,
        detach: bool = True,
    ) -> dict:
        """Play a local file (path on the MCP host) by staging it to audio host.

        Delegates to `play_url`, so the target-set/`detach` contract and
        queue-resume behavior are identical — see `play_url`.
        """
        if self.media_root is None:
            raise ValueError("play_file is disabled; set AUDIO_MEDIA_ROOT to enable")
        if not self.media_root.is_dir():
            raise ValueError(f"AUDIO_MEDIA_ROOT={self.media_root} does not exist or is not a directory")
        target = Path(path).expanduser().resolve()
        if not target.is_relative_to(self.media_root):
            raise ValueError(f"path {target} is outside AUDIO_MEDIA_ROOT={self.media_root}")
        if not target.is_file():
            raise FileNotFoundError(target)
        if target.suffix.lower() not in {".mp3", ".wav", ".flac", ".m4a", ".ogg"}:
            raise ValueError(f"unsupported extension {target.suffix!r}; allowed: mp3/wav/flac/m4a/ogg")
        url = self.audio.stage(target)
        result = self.play_url(speakers, url, title=title or target.name, detach=detach)
        result["staged_file"] = str(target)
        return result

    def pause(self, name: str) -> dict:
        _, coord = self._resolve_coordinator(name)
        try:
            coord.pause()
        except Exception:
            # Already paused/stopped; idempotent for the agent.
            pass
        return {"coordinator": coord.player_name, **_track_state(coord)}

    def resume(self, name: str) -> dict:
        _, coord = self._resolve_coordinator(name)
        coord.play()
        return {"coordinator": coord.player_name, **_track_state(coord)}

    def stop(self, name: str) -> dict:
        _, coord = self._resolve_coordinator(name)
        try:
            coord.stop()
        except Exception:
            pass
        return {"coordinator": coord.player_name, **_track_state(coord)}

    def next_track(self, name: str) -> dict:
        _, coord = self._resolve_coordinator(name)
        coord.next()
        return {"coordinator": coord.player_name, **_track_state(coord)}

    def previous_track(self, name: str) -> dict:
        _, coord = self._resolve_coordinator(name)
        coord.previous()
        return {"coordinator": coord.player_name, **_track_state(coord)}

    # ---- volume -------------------------------------------------------------

    def set_volume(self, name: str, level: int) -> dict:
        if not 0 <= level <= 100:
            raise ValueError("volume must be 0..100")
        s = self._resolve(name)
        s.volume = level
        return {"speaker": s.player_name, "volume": s.volume, "muted": s.mute}

    def mute(self, name: str) -> dict:
        s = self._resolve(name)
        s.mute = True
        return {"speaker": s.player_name, "muted": s.mute}

    def unmute(self, name: str) -> dict:
        s = self._resolve(name)
        s.mute = False
        return {"speaker": s.player_name, "muted": s.mute}

    # ---- maintenance --------------------------------------------------------

    def reboot(self, name: str) -> dict:
        """Reboot a single speaker via its firmware HTTP control port.

        Per-speaker (not group-wide): only the named speaker restarts. The
        speaker drops off the LAN for ~30-60s while it boots; callers should
        refresh the speaker cache afterwards before driving it again. Best
        effort — see `_reboot_via_http` for the delivery semantics.
        """
        s = self._resolve(name)
        _reboot_via_http(s.ip_address)
        # The cached SoCo for this speaker is about to become unreachable;
        # force a fresh discovery (bypassing SoCo's topology cache too) on
        # the next access.
        self._invalidate_speakers()
        return {"speaker": s.player_name, "ip": s.ip_address, "rebooting": True}

    # ---- grouping -----------------------------------------------------------

    def group(self, coordinator: str, members: list[str]) -> dict:
        coord = self._resolve(coordinator)
        # Coordinator must be a coordinator-of-one or already a coordinator.
        if _coordinator_of(coord).uid != coord.uid:
            coord.unjoin()
            time.sleep(0.3)
        joined: list[str] = []
        for m_name in members:
            if m_name.casefold() == coord.player_name.casefold():
                continue
            m = self._resolve(m_name)
            m.join(coord)
            joined.append(m.player_name)
        time.sleep(0.5)  # let topology broadcast settle
        return {
            "coordinator": coord.player_name,
            "joined": joined,
            "group_members": _group_members_of(coord),
        }

    def ungroup(self, name: str) -> dict:
        s = self._resolve(name)
        try:
            s.unjoin()
        except Exception:
            pass
        return {"speaker": s.player_name, "is_coordinator": True}

    def partymode(self, coordinator: str) -> dict:
        coord = self._resolve(coordinator)
        # Dissolve everything first so partymode has a clean slate.
        for s in self._speakers_fresh():
            if s.uid != coord.uid:
                try:
                    s.unjoin()
                except Exception:
                    pass
        time.sleep(0.5)
        coord.partymode()
        time.sleep(0.7)
        return {
            "coordinator": coord.player_name,
            "group_members": _group_members_of(coord),
        }

    def dissolve_all_groups(self) -> dict:
        for s in self._speakers_fresh():
            try:
                s.unjoin()
            except Exception:
                pass
        time.sleep(0.5)
        return {"dissolved": True, "count": len(self._speakers)}

    # ---- TTS ----------------------------------------------------------------

    def say(
        self,
        speakers: list[str],
        text: str,
        *,
        volume: int | None = None,
        lang: str = "en",
        detach: bool = True,
    ) -> dict:
        """Speak `text` on a target set of speakers, or on ["all"] for a
        synchronized whole-house broadcast (unchanged from before).

        By default (`detach=True`) the targets are detached from any
        existing groups and grouped only with each other; bystanders left
        behind are stopped. Pass `detach=False` to keep each target's
        existing group instead (merged together if the targets span more
        than one group). `detach` is ignored for `speakers=["all"]` — that
        broadcast is already whole-house. `speakers=["all"]` mixed with any
        other name raises `ValueError`; `"all"` is not accepted by any
        other audio tool.

        Blocks until playback finishes (or hits TTS_TIMEOUT_SECONDS).
        """
        if not text.strip():
            raise ValueError("text is empty")
        if not speakers:
            raise ValueError("at least one speaker is required")

        if len(speakers) == 1 and speakers[0].strip().casefold() == "all":
            mp3 = synthesize(text, self.cache_dir, lang=lang)
            url = self.audio.url_for(mp3.name)
            return self._say_all(text, url, volume=volume)
        if any(name.strip().casefold() == "all" for name in speakers):
            raise ValueError(
                "'all' cannot be combined with other speaker names; call "
                "say(['all'], ...) alone for a whole-house announcement."
            )

        mp3 = synthesize(text, self.cache_dir, lang=lang)
        url = self.audio.url_for(mp3.name)

        ctx = self._plan_targets(speakers, detach=detach)
        c0 = ctx.c0
        # Captured before any mutation, per the flight's spec: the
        # stale-coordinator retry re-resolves the PLANNED coordinator by its
        # player name, not the caller's original target list.
        planned_coord_name = c0.player_name

        if volume is not None:
            # Exactly `final_members`: pulled-in non-targets (detach=False
            # merges) get it because they're playing; stopped bystanders
            # never do.
            for uid in ctx.plan.final_members:
                m = ctx.speakers_by_uid.get(uid)
                if m is not None:
                    m.volume = volume

        result_box: list[TargetGroup] = []

        def _play_clip() -> None:
            result_box.append(self._execute_plan(ctx))
            current_c0 = ctx.speakers_by_uid[ctx.plan.coordinator_uid]
            with_stale_coord_retry(
                coord=current_c0,
                action=lambda c: c.play_uri(url, title=f"Say: {text[:40]}"),
                invalidate=self._invalidate_speakers,
                resolve=lambda: self._resolve_coordinator(planned_coord_name)[1],
            )

        self._with_queue_resume(
            c0,
            c0.uid,
            _play_clip,
            timeout=TTS_TIMEOUT_SECONDS,
        )
        group = result_box[0]
        return {
            "targets": ctx.target_names,
            "coordinator": group.coordinator,
            "group_members": group.members,
            "stopped": group.stopped,
            "detached": group.detached,
            "text": text,
        }

    def _with_queue_resume(
        self,
        coord: SoCo,
        speaker_uid: str,
        run_clip: Callable[[], None],
        *,
        timeout: float,
    ) -> None:
        """Snapshot the native queue state, run a clip, then resume playback.

        Snapshot is taken ONLY when all four conditions hold:
          1. No active worker session for `speaker_uid` (worker owns its lifecycle).
          2. coord.queue_size > 0  (there is a queue to resume).
          3. Transport state is PLAYING (something was actually playing).
          4. int(playlist_position) > 0  (position is meaningful; "0" means no
             track is selected in the queue).

        If any condition fails, run_clip() is still called but no resume is
        attempted afterwards.

        Resume (play_from_queue + play_mode restore) is best-effort: any
        exception is swallowed so a failed restore never surfaces to the caller.

        Limitations documented at the design level:
        - say("all") / _say_all: group is dissolved before the clip; no resume
          attempted (caller does not go through _with_queue_resume at all).
        - Grouping: resume targets the coordinator at snapshot time; if
          grouping changed while the clip played the resume may land on a
          different device.  Best-effort.
        - MCP reaped mid-clip (long play_url): resume is lost; best-effort.
        """
        snapshotted = False
        saved_index: int = 0
        saved_play_mode: str = "NORMAL"
        saved_position: str | None = None

        # --- snapshot phase ---
        if not self.playlists.has_active_session(speaker_uid):
            try:
                queue_size = coord.queue_size
                transport_info = coord.get_current_transport_info()
                track_info = coord.get_current_track_info()
                state = transport_info.get("current_transport_state")
                playlist_pos_str = track_info.get("playlist_position", "0")
                playlist_pos = int(playlist_pos_str)
            except Exception:
                queue_size = 0
                state = "STOPPED"
                playlist_pos = 0
                track_info = {}

            if queue_size > 0 and state == "PLAYING" and playlist_pos > 0:
                saved_index = playlist_pos - 1  # 1-based → 0-based
                saved_play_mode = coord.play_mode
                saved_position = track_info.get("position")
                snapshotted = True

        # --- clip phase ---
        run_clip()

        # --- wait phase ---
        self._wait_until_stopped(coord, timeout=timeout)

        # --- resume phase (best-effort) ---
        if snapshotted:
            try:
                coord.play_from_queue(saved_index)
                # Mid-track resume: seek to the position captured at snapshot time.
                # Wrapped in its own try/except so hosts without HTTP range support
                # fall back to start-of-track silently (best-effort).
                if saved_position and saved_position not in (None, "0:00:00"):
                    try:
                        coord.seek(saved_position)
                    except Exception:
                        pass  # start-of-track fallback: swallow seek failures
                # NOTE: play_mode is not restored if play_from_queue itself
                # fails — intentional. If we can't resume the queue position
                # there is no queue track to restore play_mode onto, so
                # restoring it would set mode on whatever happens to be
                # playing (potentially someone else's content). The outer
                # try/except swallows the entire resume failure as best-effort.
                coord.play_mode = saved_play_mode
            except Exception:
                pass  # best-effort: swallow resume failures

    def _say_all(self, text: str, url: str, volume: int | None) -> dict:
        # Dissolve, partymode, play, dissolve. _speakers_fresh() raises
        # NoSpeakersFound (never returns empty) when discovery finds
        # nothing, so no empty-list guard is needed here.
        speakers = self._speakers_fresh()
        for s in speakers:
            try:
                s.unjoin()
            except Exception:
                pass
        self._sleep(0.5)
        if volume is not None:
            for s in speakers:
                s.volume = volume
        coord = sorted(speakers, key=lambda s: s.player_name)[0]
        coord.partymode()
        self._sleep(1.0)
        coord.play_uri(url, title=f"Say-all: {text[:40]}")
        self._wait_until_stopped(coord)
        # Leave them ungrouped after the announcement.
        for s in speakers:
            try:
                s.unjoin()
            except Exception:
                pass
        return {
            "spoken_on": "all",
            "coordinator_used": coord.player_name,
            "speakers": [s.player_name for s in speakers],
            "text": text,
        }

    @staticmethod
    def _wait_until_stopped(speaker: SoCo, timeout: float = TTS_TIMEOUT_SECONDS) -> None:
        deadline = time.monotonic() + timeout
        time.sleep(0.4)  # let playback actually start
        while time.monotonic() < deadline:
            state = speaker.get_current_transport_info().get("current_transport_state")
            if state in ("STOPPED", "PAUSED_PLAYBACK"):
                return
            time.sleep(0.25)
