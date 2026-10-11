# Squawk 0009: playlist append caveats missing from the agent-facing tool descriptions

**Status**: open
**Type**: defect
**Severity**: routine
**Reported**: 2026-10-11
**Completed**: —

## Report
The agent reads tool descriptions, but the `playlist_add` and
`playlist_add_many` tool docstrings don't give the append caveats that
0.6.0 introduced:
- a playlist already playing on the **native queue** ignores appended
  items;
- appending to a **finished** worker playlist does nothing until the agent
  calls `playlist_play` again.

Separately, no document says that in a **shuffled** worker session,
appended items play at the tail in insertion order and are not shuffled
in. This came from a Sortie 01 debrief action item.

## Evidence
- `mcp_sonos/server.py:playlist_add` — docstring "Append one item to a
  playlist: a track (`url`) or a spoken voice segment (`text`)."; no append
  caveats.
- `mcp_sonos/server.py:playlist_add_many` — same.
- README system-prompt rule 11 covers native-queue and finished-playlist
  appends but not shuffle ordering. A grep for shuffle together with
  append/tail/insertion in `README.md`/`server.py` finds nothing.
- Behavior source: `mcp_sonos/playlists.py:_worker`, where the locked block
  appends unscheduled items to `session.order` in `playlist.items` order.

## Corrective Action
*(written at completion)*

## Verification
Docstrings and README rule 11 read correctly against
`playlists.py:_worker`. `.venv/bin/python -m pytest -q` is still green.

## Sign-Off
*(written at completion)*
