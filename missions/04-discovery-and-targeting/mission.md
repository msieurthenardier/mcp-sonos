# Mission: Zero-Config Discovery & Deterministic Speaker Targeting

**Status**: completed

## Outcome
An agent can drive the whole Sonos household without anyone configuring
speaker IPs, and when it asks for audio on a set of speakers, exactly those
speakers make sound — every time, regardless of how the household happened to
be grouped beforehand. "Play this on Kitchen and Patio" means Kitchen and Patio
play it and nothing else does, in one tool call, with no look-up-the-groups-
then-ungroup routine. Callers who want today's "play on the speaker's whole
group" behavior can still ask for it explicitly.

## Context
Two gaps surfaced on 2026-09-27 while running the Mission 03 hardware smoke
tests:

- **Discovery.** The operator's `SONOS_IPS` pin listed four speakers; the
  household has five. Patio (192.168.86.49) was invisible to every tool
  because a pinned list is exhaustive — nothing beyond it is ever discovered.
  Unpinned discovery isn't a usable alternative today: on this WSL2 host SSDP
  multicast found nothing in 3/3 runs (5 s timeout each), while a direct
  subnet scan found all five speakers in ~0.5 s. The current discovery path
  tries SSDP first and scans only as a fallback, so going unpinned costs
  ~5.5 s per discovery on a 30 s cache TTL. The docs (README config table,
  CLAUDE.md operating constraints) tell operators to pin IPs, and
  `refresh_speakers` claims to do "fresh SSDP discovery" when with a pin it
  does neither.
- **Targeting.** A smoke test aimed at "Kitchen" played on all five speakers:
  Kitchen was the coordinator of a whole-house group, and every audio tool
  plays on the named speaker's entire current group. To play on one speaker,
  an agent must first list groups, ungroup, then play — multi-step, racy
  under group churn, and easy to forget.

The five audio-sending tools are `play_url`, `play_file`, `play_stream`,
`playlist_play`, and `say`; each takes a single `speaker` today. Grouping is
only reachable through separate tools (`group`, `ungroup`, `partymode`,
`dissolve_all_groups`).

## Success Criteria
- [x] With no speaker IPs configured, discovery finds every visible speaker in the household on the operator's LAN (all five, including Patio), across repeated runs *(behavior-test-backed — real LAN)*
- [x] When IPs are configured, they still work as a way in on networks where automatic discovery fails, and no longer hide household members that weren't listed *(behavior-test-backed)*
- [x] When discovery finds no speakers, the tool error explains why and what the operator can set, rather than failing with an empty or generic result
- [x] Every audio-sending tool (clip/file playback, stream playback, playlist playback, announcements) accepts a set of one or more target speakers
- [x] By default, audio plays on exactly the requested target set: targets are detached from any existing groups and grouped only with each other *(behavior-test-backed — real speakers)*
- [x] By default, speakers that were grouped with a target but aren't targets end up stopped and separated from the targets, so only the targets make sound *(behavior-test-backed)*
- [x] Speakers in groups that contained no target are untouched *(behavior-test-backed)*
- [x] A caller can opt out of detaching and get today's behavior: each target's existing group plays as-is
- [x] The all-speakers announcement keeps its existing broadcast behavior *(behavior-test-backed)*
- [x] Tool schemas, README (configuration table, agent system prompt), and CLAUDE.md describe the new discovery and targeting behavior accurately; no tool description claims behavior it doesn't have *(partially: squawk 0005 open; see mission debrief)*
- [x] The unit suite covers discovery selection and target-set grouping without hardware, and passes

## Stakeholders
Maintainer (msieurthenardier) — self-hosted on a home LAN, drives the server
from an agent. The agent is the direct consumer of the tool schemas. No
external users.

## Constraints
- **Breaking tool-schema change is accepted.** Audio-sending tools move from
  a single `speaker` to a list of speakers (maintainer decision; pre-1.0,
  agent-driven). Bump the minor version and update the README agent system
  prompt in the same flight.
- **Detach is the default**; opting out restores today's semantics exactly.
- **Transport/control tools stay single-speaker** (pause, resume, stop,
  next/previous, playlist_next/previous/stop/status, volume/mute). After a
  detached play, the named speaker's group *is* the target set, so they
  already act on it. Out of scope.
- **`say("all")` behavior is preserved.**
- Anything touching groups goes through `_coordinator_of` /
  `_group_members_of` (CLAUDE.md invariant). Grouping logic lives in the
  controller; `server.py` stays a thin wrapper.
- Preserve the worker-engine **speaker-UID session keying** invariant and the
  queue-resume behavior of `say` / `play_url`.
- Existing env-var contracts keep working: an operator with a working
  `SONOS_IPS` must not be broken by the upgrade.
- The audio HTTP port range (8000–8999) and firewall assumptions are
  unchanged.

## Environment Requirements
- Existing local Python venv at `<repo-root>/.venv` (`pip install -e '.[dev]'`)
- Live Sonos hardware on the LAN for behavior verification: the operator's
  household (5 speakers — Dining Room .50, Fireplace Room .51, Lounge .52,
  Kitchen .53, Patio .49 — plus a Boost bridge at .48, which must be excluded)
- WSL2 mirrored networking + the `WSL-Sonos-Audio` firewall rule (in place)
- No CI to satisfy

## Open Questions
- **Subnet-scan scope.** The scan covers the host's local subnet(s). How it
  behaves on multi-NIC / VPN / large subnets, and whether it needs a bound or
  an interface override, is for Flight 1 to establish.
- **Discovery cost vs. cache TTL.** Scan-first is ~0.5 s here; decide whether
  steady-state calls should ever pay it synchronously (background refresh,
  longer TTL, invalidate-on-miss). Not a success criterion (maintainer did not
  select it), but must not regress to multi-second stalls.
- **Seed expansion.** Configured IPs becoming "a way in" implies expanding
  from them to the full household (e.g. via the household topology any one
  speaker reports). Confirm this also handles invisible devices (Boost,
  bonded satellites) correctly.
- **Detach mechanics & timing.** Order of operations for detach → stop
  bystanders → group targets → play, settle delays, and interaction with
  SoCo's transient `coordinator=None` state and stale-coordinator retry.
- **Coordinator choice** for a multi-target set (first listed? current
  coordinator if already a target?) and how that interacts with worker-engine
  session keying and queue resume (which speaker's queue gets snapshotted and
  resumed when the group changes under it).
- **Opt-out with multiple targets** in different existing groups: "each
  target's existing group plays as-is" — confirm whether that means playing on
  each group independently or is only meaningful for one target.
- **Parameter naming** for the opt-out (e.g. a boolean vs. a mode enum) —
  flight design.

- **Say-all under a list signature — decided.** The `"all"` sentinel is kept:
  `say` with a speaker list of exactly `["all"]` triggers today's synchronized
  broadcast path (dissolve → party → dissolve); mixing `"all"` with speaker
  names is a validation error. The broadcast path stays separate from the new
  detach-and-group path (maintainer decision, 2026-09-27).
- **Partial failure.** Detach → stop bystanders → group targets → play is a
  multi-step sequence across several groups with no rollback today. Flight 2
  must define (and test) the state left behind and the error reported when a
  step fails midway.
- **Resume snapshot timing.** Queue-resume must snapshot the pre-detach
  coordinator's state before any regrouping, and decide where it resumes.
  Split-off bystanders' queues are not resumed (they end stopped).
- **Playlist sessions after target-group formation.** The worker engine
  re-resolves the coordinator by one speaker name on every track. With a
  target set, fix the coordinator identity at formation and follow it; confirm
  grouping is not re-imposed mid-playlist if someone regroups by hand.
- **Configured-IP fallback.** Expanding from configured IPs must try each
  until one answers (a speaker may be rebooting), not assume the first is up.
- **Scan bound (from validation).** SoCo's scan merges every private network
  on every adapter; this WSL2 host is multi-adapter. Flight 1 should land a
  concrete bound (e.g. derived from the advertised host IP's subnet, reusing
  the existing `HOST_IP` override) rather than the library default.

## Known Issues
N/A — none open at mission start.

## Flights

> **Note:** These are tentative suggestions, not commitments. Flights are planned and created one at a time as work progresses. This list will evolve based on discoveries during implementation.

- [x] Flight 1: Zero-config discovery — scan-first discovery with no configuration, configured IPs as a way in that expands to the full household, clear failure diagnostics, and corrected docs/tool descriptions. First because targeting work and its hardware verification need every speaker (Patio) discoverable.
- [x] Flight 2: Deterministic target-set playback — list-of-speakers targets on all audio-sending tools, detach-by-default grouping (stop bystanders), explicit opt-out, both playlist engines and queue-resume preserved, schema + README system prompt + version bump. Its own flight: a breaking interface change with the hardware-dependent grouping behavior as its risk.
