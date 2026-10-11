# Flight Debrief: DJ Voice Segments in Playlists

**Date**: 2026-10-11
**Flight**: [DJ Voice Segments in Playlists](flight.md)
**Status**: landed
**Duration**: 2026-10-10 (chartered, designed, and flown in one autonomous overnight run) → 2026-10-11 (operator acceptance)
**Legs Completed**: 2 of 2
**Plugin version**: 1.2.0

## Outcome Assessment

### Objectives Achieved
Playlists have a voice item kind. `playlist_add` and `playlist_add_many`
accept `text` in place of `url`. The text is synthesized with Piper when it
is added and stored as an MCP-hosted URL. The existing routing sends a mixed
playlist to the worker engine, which plays songs and voice segments in order.

The same pass fixed three things:
- **Live append:** the worker now plays items appended during playback. It
  schedules item *objects*, so each appended item plays exactly once and
  removed items are skipped.
- **Shuffled status:** `playlist_status` reported the wrong `current_item`
  for shuffled playlists.
- **Previous at the start:** `previous` at the first item moved forward.

Released as **v0.6.0** (PR #16, squash-merged as `f97a301`; tag `v0.6.0`;
GitHub release). This was the repo's first tag and GitHub release.

### Charter Success Criteria
| Criterion | Status | Notes |
|-----------|--------|-------|
| One `playlist_add_many` call mixes URL and text items; text items keep their position and show as voice items in `playlist_get` | **Met** | `kind`/`text` in `to_dict()`; unit-tested. |
| `playlist_play` on a mixed playlist plays every item in order on real hardware, with voice audible between songs | **Met** | `playlist_smoke.py dj` PASS on Kitchen on the first attempt. `now_playing` showed PLAYING at each voice item's hosted URI, including one appended live. Operator confirmed it audibly on 2026-10-11 ("its working"). |
| `playlist_next` / `previous` / `stop` / `status` behave the same across voice items as song items | **Met** | No kind-specific paths. The `status` and `previous` defects were fixed (DD-9, DD-10). |
| Unit tests cover the new item type; the README agent prompt documents the DJ pattern | **Met** | 36 new tests. README rule 11 was corrected and a new rule 13 describes DJ segments. |

Constraints held:
- No new dependencies.
- Track-only, all-external playlists still route to the native queue
  (unit-tested).
- Voice playlists use the worker engine, as accepted.

All checkpoints were met, and no adaptation (divert) criterion fired.

## What Went Well
- **Design reviews caught a real concurrency bug before any code
  existed.** The leg-1 design review found that the index plus
  `scheduled_count` live-append design would double-play an item appended
  after a `remove`. The fix was a switch to identity-based scheduling. The
  result is simpler: `remove` and `clear` need no bookkeeping, and the
  pre-existing index-shift hazard is gone. The flight-end Reviewer and the
  hardware run then found nothing.
- **The routing premise held, with no new playback machinery.** Voice items
  become hosted URLs, and the existing `any_mcp_hosted` routing and worker
  loop did the rest. DD-3 needed zero change to `play()`.
- **Deterministic concurrency tests.** A test-local gated fake (hold or
  release per `play_uri`, a gated `stop()`) and `SoCoFake.play_uri_log`
  made the live-append, skip-race, remove, clear and previous scenarios
  deterministic. Results so far:
  - 0 flakes across 5+ runs of the new file and 3+ full-suite runs;
  - every `finally` releases the gates and asserts the worker thread is
    dead.
- **The unattended hardware leg was safe and passed first time.** It ran on
  a standalone speaker at volume 10, saved the speaker's volume beforehand
  and restored it afterwards (22 → 10 → 22), and was capped at 3 attempts.
  It needed one attempt and no code changes.
- **Smaller design patterns that worked:**
  - Synthesis is injected into `PlaylistManager` (`synthesize_voice`,
    default `None` with a named error), which kept `playlists.py` free of
    `tts` and `audio_host` imports.
  - `add_many` validates every item, then synthesizes outside the lock,
    then commits under the lock, so it is all-or-nothing.

## What Could Be Improved

### Process
- **Mutable shared state was designed index-first and reviewed twice
  before anyone questioned it.** The flight text itself named the hazard
  ("remove shifts indices"). Flight review cycle 2 then *refined* the
  `scheduled_count` bookkeeping, spreading it into `remove` and `clear`,
  instead of challenging it. The leg review caught it, at the cost of
  rewriting DD-5/DD-9 in flight and a second leg-review cycle.
  - The general signal: bookkeeping that spreads into other mutators means
    you should look for a stable identity instead.
  - Enumerating every mutator against the scheduling state at flight
    design would have caught it one gate earlier.
- **The DD-10 off-by-one was "fixed" twice.** Cycle 1 handled index 0;
  cycle 2 found index 1 was also wrong. Arithmetic claims about index fixes
  should come with a small case table (index 0, 1, N, removed neighbour) at
  design time.
- **Two premise-audit misses in leg 1.** The leg assumed
  `playlist_smoke.py`'s `build_playlist` uses `select_track_pool` (it
  doesn't), and it omitted `tests/test_version.py` from Files Affected (the
  test hardcodes the version). Both were logged as deviations and cost
  nothing, but they were facts the leg author asserted without opening the
  files.
- **When the operator reversed DD-6, the decisions depending on it were
  not re-traced at that moment.** The cycle-1 Architect found the fallout
  instead: DD-9 became blocking only because shuffle with voice became a
  supported combination.

### Technical
- **`_worker` is now the densest code in the repo.** It has a
  `while True` inside `with self._lock` inside the outer loop, plus a
  separate locked backward scan in the back handler. The rule that nothing
  inside the block may take the non-reentrant `self._lock` lives only in
  comments and CLAUDE.md. Candidate refactor: extract
  `_next_item_locked(session, playlist)` so the invariant has one home and
  can be unit-tested directly.
- **Two index notions.** `current_index` (play-order position) and
  `current_playlist_index` (position in the playlist) are both on the
  status surface. Both are documented, but they invite confusion.
- **The TTS cache grows without limit.** Every distinct text writes a WAV
  to tempdir, with no eviction. This is pre-existing (`say` does the same),
  but DJ sets make it grow faster. Separately, a tempdir cleanup between add
  and play makes that item skip silently.
- **First-use latency.** The first voice item in a process can trigger the
  ~60 MB Piper voice download inside a `playlist_add_many` call. On the
  stdio-serialized server that blocks every other tool until it finishes.
  This is documented only implicitly, through README's "first `say` is
  slow".
- **Accepted, permanent:** voice playlists don't survive a reap. Appends to
  a native-queue playlist that is already playing, or to a worker playlist
  that has finished, are inert until the next `playlist_play`.

### Documentation
- The README tool descriptions don't mention that a native-queue playlist
  already playing never picks up appends (README rule 11 and the
  `server.py` comment do).
- Shuffle plus live append ordering is not documented: appended items go
  to the tail of the order in insertion order, not shuffled in.

## Test Metrics
| | M03 F01 | M04 F01 | M04 F02 | Squawks 0004–0007 | **Sortie 01** |
|---|---|---|---|---|---|
| Tests | 78 | 118 | 172 | 177 | **213** |
| Wall-clock (pytest) | ~1.4 s | 1.85–1.95 s | 2.80–2.95 s | — | **~2.8 s** |
| Fail / skip / flake | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 | **0/0/0** |

- **Where the time goes:** `tests/test_playlist_voice_items.py` is 36
  tests and about 1.4 s, roughly 40 ms per test. The other 177 tests run in
  about 1.4 s, roughly 8 ms per test.
- **Why:** the new file uses real worker threads with Event-gated fakes,
  plus in-process FastMCP `Client` round-trips, and it is the repo's first
  concurrency-driven test file. Its slowest test is
  `test_server_playlist_add_many_bad_scheme_rejected` at 0.15 s.
- **Total wall-clock stayed flat:** about 2.8 s, against 2.80–2.95 s at
  M04 F02, despite +41 tests over that baseline.
- **Watch:** this file now accounts for about half the suite's time. If
  more thread-driven tests land, keep them gated, never sleep-based.
- **Flakes:** none observed across 5+ runs of the new file.

## Deviations and Lessons Learned

| Deviation | Reason | Standardize? |
|-----------|--------|--------------|
| DD-6 reversed (shuffle allowed with voice) | Operator: a voice item isn't necessarily DJ commentary; choosing is the agent's job | No (intent call) |
| DD-5/DD-9 rewritten in flight to identity-based scheduling | Index-based design double-plays after `remove` (leg-1 design review) | **Yes**: schedule by identity, not position, whenever the list can be mutated concurrently |
| Leg 1 got a binding "Design Review Addendum" rather than an in-place rewrite | Review cycle 2 detail (loop order, backward scan, test determinism) | Yes, when a leg is still `planning` and the changes are additive |
| FD made the flight commit directly (no Developer spawn) | Mechanical commit, tight usage window; logged | No. Note it only. |
| `tests/test_version.py` updated, though not listed in the leg | Hardcoded version | Yes: list `test_version.py` in any leg that bumps the version |
| Hardware leg ran unattended overnight at low volume | Operator authorized a fully autonomous run | Yes, as a pattern: standalone target, save and restore volume, attempt cap |

## Key Learnings
- **For mutable shared state with concurrent mutators, ask "what is an
  entry's stable identity?" before designing indices or counters.** In this
  codebase, `PlaylistItem` is a dataclass with value equality, so identity
  means `is` / `id()`, never `==` / `in`. The `id()` scheme is safe only
  because `order` keeps the objects alive. CLAUDE.md now records the
  identity rule.
- **Validate everything, then do slow I/O outside the lock, then commit
  under the lock.** This is the reusable shape for any add path that does
  I/O (`_build_items`).
- **An atomic extend-or-deregister check, under the same lock as appends,
  removes the "add succeeded but nothing will ever play it" window.**
- **A verify-only hardware leg is worth keeping separate for concurrency
  changes, even when it needs no code.** It gives an unattended gate with
  its own safety envelope.
- **"Sortie or not" is about where the review budget went.** Voice items
  were routine. Most of the review effort and both redesigns went to
  worker-loop correctness: live append, plus two pre-existing defects that
  the feature exposed. The work still fit one flight, but see the Sortie
  observation below.

## Methodology Observations

1. **Sortie gate re-check doesn't weigh *where the review effort went*.**
   - *Skill/phase*: sortie, step 5 (re-check the gate) and agentic-workflow
     2a ("out-of-scope defects found mid-flight").
   - *What happened*: The gate re-check asked whether a second, independent
     cluster of decisions had surfaced. It said no, because live append was
     coupled to the DJ outcome. Two pre-existing defects (shuffled status,
     previous at index 0/1) were pulled in because they sat on the same
     loop. In the end, worker concurrency consumed both redesigns and most
     of four review cycles, while the chartered feature (voice items) was
     routine.
   - *Expected*: The re-check should flag the case where pulled-in or
     coupled work dominates the review budget. It could suggest landing a
     hardening squawk or sortie first, so the feature sortie stays
     low-risk.
   - *Cost*: Higher-risk tiering for the whole leg, and two extra design
     cycles that a smaller pre-flight hardening change would have isolated.
     The work itself was right; the bundling made it harder to review.
   - *Plugin version*: 1.2.0.
2. **Design-review prompts don't ask the reviewer to enumerate mutators
   against shared state.**
   - *Skill/phase*: flight, Phase 5b (Architect review) and the
     flight-design crew prompt's "cache freshness / state-machine" items.
   - *What happened*: Two Architect cycles reviewed an index-based
     live-append design. Cycle 1 proposed spreading bookkeeping into
     `remove`/`clear`, and cycle 2 refined it. The double-play flaw was
     found only at leg-design review.
   - *Expected*: A prompt item like: "for each piece of shared mutable
     state, list every mutator and every reader. If the design needs other
     mutators to do bookkeeping, look for an identity- or generation-based
     alternative."
   - *Cost*: DD-5/DD-9 rewritten in flight, plus one extra leg-design
     review cycle.
   - *Plugin version*: 1.2.0.
   - *Recurrence*: Related to the M04 F02 observation 1 ("whose view does a
     shared cache hold?"). Both are cases of the reviewer checking a
     state-consistency property *within* a component but not across the
     paths that mutate it. **Second occurrence across missions and
     sorties.**
3. **The flight-log template's `## Decisions` section went unused.**
   - *Skill/phase*: agentic-workflow, Flight Director decision log;
     ARTIFACTS.md flight-log format.
   - *What happened*: Planning and runtime decisions (DD-6 reversal,
     identity rework, skipped spawn for the commit) were all written under
     Session Notes / Flight Director Notes. The template's `## Decisions`
     section stayed empty, because the skill says to log decisions under
     "Flight Director Notes", which the template doesn't contain.
   - *Expected*: Make the template and the skill agree on one place for
     decisions.
   - *Cost*: Cosmetic. A reader may look in the wrong section.
   - *Plugin version*: 1.2.0.
4. **The design-review cycle cap was hit on both the flight and leg 1, and
   the run proceeded under autonomous authorization.**
   - *Skill/phase*: flight Phase 5b; agentic-workflow 2a step 4.
   - *What happened*: Both artifacts used their two cycles. The FD resolved
     the remaining medium and low items itself, under the operator's
     autonomous-run authorization, instead of escalating.
   - *Expected / Cost*: Same as M04 F02 observation 3: the skills don't say
     how the cap interacts with explicit autonomous authorization. No harm
     was observed, and downstream gates found nothing.
   - *Plugin version*: 1.2.0.
   - *Recurrence*: **Second occurrence** (M04 F02 obs. 3).

## Recommendations
1. **Extract the worker's locked scheduling step** into
   `_next_item_locked(session, playlist)` with direct unit tests, so the
   non-reentrant-lock rule and the identity invariant have one home. This is
   a refactor with design implications, so it belongs in the next
   maintenance flight, not a squawk.
2. **Bound the TTS cache** (size- or age-based eviction) and document
   first-use Piper download latency for `playlist_add_many` with voice
   items. This is design work (an eviction policy) for the next playlist or
   maintenance flight.
3. **At flight design, enumerate mutators against shared state**, and for
   index fixes include a case table. Carry this into the next flight that
   touches `playlists.py` or the grouping executor.
4. **Document the two remaining sharp edges in the README tool
   descriptions:** native-queue playlists ignore appends, and shuffled
   sessions append to the tail in insertion order.
5. **Consider a reap-survival story for voice playlists** (a pinned audio
   port plus a persistent TTS directory) only if the operator wants DJ sets
   to survive restarts. It was explicitly deferred by the charter.

## Action Items
- [ ] [Squawk 0008](../../squawks/0008-dj-smoke-preclean-traceback.md):
      silence the `playlist_smoke.py dj` pre-clean traceback (it comes from
      server-side tool-error logging, so check `playlist_list` before
      deleting rather than wrapping the call).
- [ ] Next maintenance flight: Recommendation 1 (worker extraction), plus
      Recommendation 2 (TTS cache bound).
- [ ] [Squawk 0009](../../squawks/0009-playlist-append-docs-gaps.md):
      Recommendation 4, scoped to the agent-facing `playlist_add` /
      `playlist_add_many` docstrings plus the undocumented shuffle-append
      ordering. README rule 11 already covered native-queue appends.
- [x] Operator audible confirmation — 2026-10-11.
- Accepted, no action: the `dj` smoke harness could falsely time out on a
  voice clip shorter than its 0.2 s poll. It is harness-only and did not
  occur.
