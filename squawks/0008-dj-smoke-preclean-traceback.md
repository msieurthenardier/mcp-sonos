# Squawk 0008: `playlist_smoke.py dj` prints a traceback from its pre-clean delete

**Status**: open
**Type**: servicing
**Severity**: routine
**Reported**: 2026-10-11
**Completed**: —

## Report
Every `playlist_smoke.py dj` run starts with a rich-formatted
`PlaylistError: No playlist named 'smoke-dj'` traceback. The scenario
pre-cleans by deleting a playlist that usually doesn't exist. The run still
passes, but the noise looks like a failure in a hardware log. This was
logged as an anomaly in Sortie 01 leg 2 and listed as a debrief action item.

## Evidence
- `playlist_smoke.py:test_dj` — `await client.call_tool("playlist_delete", {"name": name})`
  is already wrapped in `try/except Exception: pass`. The traceback is
  therefore printed by the in-process FastMCP server's own tool-error
  logging, not by the client, so another try/except won't silence it.
- Sortie 01 flight log, Anomalies: "pre-clean `playlist_delete smoke-dj`
  logs a `PlaylistError` … traceback".

Likely fix: before deleting, check that `smoke-dj` appears in
`playlist_list`. Wrapping the call won't help.

## Corrective Action
*(written at completion)*

## Verification
A code read shows that `playlist_delete` is called only when the playlist
exists. A hardware `dj` run (optional) shows no traceback before
`###### DJ test`.

## Sign-Off
*(written at completion)*
