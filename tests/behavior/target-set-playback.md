# Behavior Test: Target-Set Playback

**Slug**: `target-set-playback`
**Status**: draft
**Created**: 2026-09-29
**Last Run**: never

## Revision History
- **2026-09-29 (leg 4, coordinator-view hardening)**: repaired step 7's
  setup (it accidentally made Fireplace Room a `PLAYING` coordinator,
  which meant rule 2 always picked it as `c0`, so the intended "non-`c0`
  target coordinating bystanders" scenario never actually ran — see step
  7's note); moved the stream-reachability precondition's active check
  from step 3 to step 2 (that's actually where the first stream start
  happens); and corrected step 11's expected wording to match the real
  error message. Prompted by the leg 3 behavior-test run
  (`runs/2026-09-29-03-54-28.md`), which failed steps 7 and 11 against
  the spec as written even though the underlying product behavior was
  correct.

## Intent
This test verifies on the operator's real household that audio tools play on
*exactly* the requested speaker set. It checks four things:
- Speakers grouped with a target, but not targets themselves, end up stopped
  and separated.
- Groups with no target are untouched.
- `detach=false` preserves the old "play on the existing group" behavior.
- `say(["all"])` still broadcasts.

Unit tests cover the planner's logic. Only real speakers show whether SoCo's
`unjoin`, `join` and `stop` on this firmware produce the planned topology and
silence bystanders.

Every speaker is **muted** throughout. The observable is transport state read
through each group's coordinator, so nothing plays audibly in the house.

## Preconditions
- The flight's `targeting_smoke.py` exists at the repo root, and the venv has
  the flight branch installed.
- The household has five visible speakers: Dining Room, Fireplace Room,
  Kitchen, Lounge, Patio. *Active check*: step 1.
- The SomaFM stream `http://ice1.somafm.com/groovesalad-128-mp3` is
  reachable. *Active check*: step 2's first stream start.
- Every command runs from the repo root as a fresh process:
  `.venv/bin/python targeting_smoke.py <subcommand>`.
- The run's state file lives at `/tmp/behavior-tests/mcp-sonos/target-set-playback/state.json`.

## Observables Required
- shell: stdout JSON, stderr and exit code, measured via Bash. `topology`
  prints, for each group, its `coordinator`, its `members`, the coordinator's
  `state` and its `uri`.

## Steps

| # | Actions | Expected Results |
|---|---------|------------------|
| 1 | Run `save-state /tmp/behavior-tests/mcp-sonos/target-set-playback/state.json`, then `mute-all`, then `topology`. | Every command exits 0. The state file exists and names all five speakers with their volume, mute and group. `topology` lists the five speakers across its groups. |
| 2 | Run `group Kitchen "Dining Room" "Fireplace Room" Lounge Patio`, then `stream --speakers Kitchen --no-detach`, then `topology`. | The stream command exits 0, and its JSON shows `detached: false` and `stopped: []`. `topology` shows one group of all five, with coordinator Kitchen, state `PLAYING`, and a `uri` containing `groovesalad`. |
| 3 | Run `stream --speakers Kitchen Patio`, then `topology`. | The stream command exits 0. Its JSON shows `targets` [Kitchen, Patio], `detached: true`, and `stopped` containing Dining Room, Fireplace Room and Lounge. In `topology`, the group containing Kitchen has exactly the members {Kitchen, Patio} and state `PLAYING`. No group containing Dining Room, Fireplace Room or Lounge has state `PLAYING`. |
| 4 | Run `stop-all`. Then run `group "Fireplace Room" Lounge` and `stream --speakers "Fireplace Room" Lounge`. Then run `topology`, and record the Fireplace group's `uri`. | The group of exactly {Fireplace Room, Lounge} is `PLAYING`. *(Setup confirmation for step 5.)* |
| 5 | Run `stream --speakers Kitchen`, then `topology`. | The stream command exits 0, and its `stopped` does not include Fireplace Room or Lounge. In `topology`, the group of exactly {Fireplace Room, Lounge} is **still** `PLAYING` with the same `uri` as in step 4, meaning it was untouched. The group containing Kitchen is `PLAYING`, and Kitchen's group does not contain Fireplace Room or Lounge. |
| 6 | Run `stop-all`. Run `group "Dining Room" Patio`, then `stream --speakers "Dining Room" Patio`. Then run `stream --speakers Patio`, then `topology`. | The last stream command exits 0, with `targets` [Patio] and `stopped` containing Dining Room. In `topology`, Patio is the sole member of its group and is `PLAYING`. Dining Room's group does not contain Patio and is not `PLAYING`. *(The target was a follower of a bystander coordinator.)* |
| 7 | Run `stop-all`. Run `group "Fireplace Room" "Dining Room" Lounge Patio`. Then run `stream --speakers Kitchen "Fireplace Room"`, then `topology`. | The last stream command exits 0. Its `stopped` contains Dining Room, Lounge and Patio, and its `group_members` is exactly {Kitchen, Fireplace Room}. In `topology`, the group containing Kitchen is exactly {Kitchen, Fireplace Room} and `PLAYING`. Dining Room, Lounge and Patio are **still grouped together** under some coordinator, and that group is **not** `PLAYING`. *(A non-first target coordinated three bystanders; they stay grouped under a delegate, and silent. Note: the setup no longer starts a stream on Fireplace Room before this step — doing so made Fireplace Room a `PLAYING` coordinator, so coordinator rule 2 always picked it as `c0`, and the intended "non-`c0` target coordinates bystanders" scenario never actually ran — see the leg 3 run log. With no playback in the setup, rule 3 picks the standalone Kitchen as `c0` instead, and Fireplace Room is the non-`c0` target that coordinates the three bystanders, matching step 9's already-passing shape.)* |
| 8 | Run `stop-all`. Run `group Kitchen` (Kitchen alone) and `group "Fireplace Room" Lounge`. Then run `stream --speakers Kitchen "Fireplace Room" --no-detach`, then `topology`. | The stream command exits 0, with `detached: false` and `stopped: []`. `topology` shows one group containing Kitchen, Fireplace Room **and** Lounge, `PLAYING`. The opt-out merged each target's existing group, and nothing was stopped. |
| 9 | Run `stop-all`, then `say --speakers Kitchen Patio --text "target test"`, then `topology`. | `say` exits 0 after the clip finishes. Its JSON shows `targets` [Kitchen, Patio] and `group_members` exactly {Kitchen, Patio}. `topology` shows a group of exactly {Kitchen, Patio}. |
| 10 | Run `say --speakers all --text "broadcast test"`, then `topology`. | `say` exits 0, and its JSON shows `spoken_on: "all"` and a `speakers` list of all five. `topology` shows five single-speaker groups, because the broadcast still dissolves groups afterwards, exactly as before. |
| 11 | Run `say --speakers all Kitchen --text x`. | Exit code is non-zero. The error says `"all"` cannot be combined with other speaker names. |
| 12 | Run `stop-all`, then `restore-state /tmp/behavior-tests/mcp-sonos/target-set-playback/state.json`, then `topology`. | Every command exits 0. The group memberships match the groups saved in step 1, and no group is `PLAYING` that wasn't in step 1. The state file's volume and mute values are restored; `restore-state` reports each speaker's volume and mute as matching. |

## Out of Scope
- Audible verification. Every speaker is muted; loudness and sync quality
  are not judged.
- Playlist engines under target sets. The unit tests cover session keying and
  the lookup fallback. `playlist_play` shares the same target-group step
  exercised here.
- Queue resume after a clip. That needs a native queue playing, and the
  existing unit tests cover it (`tests/test_queue_resume.py`).
- Transport and control tools. They stay single-speaker, unchanged by this
  flight.
- Partial-failure paths. Unit tests cover them, since they can't be forced
  safely on hardware.

## Variants (optional)
None.
