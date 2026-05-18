# Flight Log: Test Scaffolding

**Flight**: [Test Scaffolding](flight.md)

## Summary
(Filled in during execution.)

---

### Flight Director Notes

**2026-05-18 — Flight start**

- Mission stayed `active`. Flight flipped: `ready` → `in-flight`.
- Feature branch: `flight/04-test-scaffolding` created off `flight/03-supply-chain-hardening` at `0724234` (which includes the Flight 04 planning commit).
- Crew loaded from `.flightops/agent-crews/leg-execution.md` (Developer + Reviewer, both Sonnet).
- Agent pattern per Flight 02 rule of thumb:
  - Leg 01: consolidated review+implement (text/config cleanups, runtime-inert)
  - Leg 02: split — DI refactor has runtime semantics (module import side effects, FastMCP integration); load-bearing leg
  - Leg 03: split — unit-test content benefits from review (assertion shape, fake usage, regression-pin correctness)
  - Leg 04: split — investigative; fix-or-xfail decision benefits from review
- Commit cadence: per-leg commits, matching Flights 01-03 convention.
- **Final flight of the mission.** Successful execution closes 14/14 criteria (F7) + 3 carry-forward Action Items + either resolves or `xfail`s the `say()` coordinator bug Known Issue.

---

## Reconnaissance Report

Verified each scope item against current code at flight planning time (2026-05-18, after Flights 01-03 landed; current HEAD on `flight/03-supply-chain-hardening` at `989c171`). Source artifacts: [`maintenance/2026-05-18.md`](../../../../maintenance/2026-05-18.md) for F7, plus carry-forward Action Items from Flight 02 and Flight 03 debriefs.

| Item | Classification | Evidence | Recommendation |
|------|----------------|----------|----------------|
| F7 — Module-level `controller = SonosController()` in `server.py` | `confirmed-live` | `mcp_sonos/server.py:34` — `controller = SonosController()` at module top-level (line 33 has it commented above). Importing the module starts the audio host. | Defer via `register_tools(mcp, controller)` called from `main()`. |
| F7 — `tests/` directory + pytest config | `confirmed-live` | No `tests/` directory exists. `pyproject.toml` has no `[tool.pytest.ini_options]` block. `[dev]` optional-deps contains only `pip-audit`. | Create `tests/__init__.py`, `tests/_fakes.py::SoCoFake`, add pytest config + pytest to `[dev]`. |
| F7 — SoCoFake | `confirmed-live` | No fake exists. Reference for needed surface: `mcp_sonos/controller.py` and `mcp_sonos/playlists.py` SoCo call sites. | Per flight design — minimal surface in `tests/_fakes.py`. |
| Flight 02 debrief AI — SSDP-deterministic smoke scripts | `confirmed-live` | `grep -n "SONOS_IPS" smoke_test.py playlist_smoke.py` returns zero hits. Both scripts rely on SSDP discovery, which can race. | Set `os.environ.setdefault("SONOS_IPS", "192.168.1.51,...")` at the top of both scripts. |
| Flight 02 debrief AI — `controller.py:86` class docstring drift | `confirmed-live` | `mcp_sonos/controller.py:85` reads `"""Stateful controller: speakers cache + audio host + lock."""`. The `self._lock` it referred to was removed in Flight 02 Leg 02. | Drop `+ lock` from the docstring. |
| Flight 03 debrief AI — first unit-test targets (validate_http_url, _verify_or_log, F1 takeover) | `confirmed-live` (target code exists, no tests) | `mcp_sonos/_urls.py::validate_http_url` exists; `mcp_sonos/tts.py::_verify_or_log` + `_hash_voice_file` exist; `mcp_sonos/playlists.py:380` F1 takeover branch correctly references `session.speaker_name` (Flight 01 fix). All three are ideal pure-function unit-test targets. No tests exist yet. | Three test modules in Leg 03 covering these targets. |
| Flight 03 debrief AI — say() coordinator bug investigation | `confirmed-live` (open Known Issue) | Mission Known Issues entry: `say()` fails with `play_uri can only be called/used on the coordinator in a group` even when target speaker is its own singleton coordinator. Reproduced in 2 of 3 prior debrief smoke runs. Pre-debrief "Sonos topology" hypothesis was refuted in Flight 03 debrief. | Reproduce as SoCoFake-driven failing pytest test in Leg 04; fix-or-xfail per scope guard. |

**No items retired or scoped down — all 7 confirmed-live.** This is the largest scope reconciliation of any flight in this mission: 1 mission criterion (F7) + 2 Flight 02 debrief AIs + 4 Flight 03 debrief AIs.

### Additional Observations

1. **Flight 04 is the final flight of the mission.** Successful execution lands F7 (the last open mission criterion); closes either as resolution or `xfail` the `say()` coordinator bug; and consolidates 3 carry-forward Action Items that have been open across multiple debriefs.

2. **Leg 04 is the only investigative leg in the mission.** All prior legs were "implement per spec." Leg 04 has explicit fix-or-xfail decision tree with a scope-guard (>30 lines → xfail). Good methodology test for how `/agentic-workflow` handles open-ended investigation.

3. **`_verified_voices` thread-safety invariant** (from Flight 03 debrief) is NOT addressed in this flight — it requires the test scaffolding from Leg 02 to be exercised before any structural change to `_VoiceCache`. Carry-forward for a future micro-flight.

4. **Methodology heuristics** identified by Flight 03 debrief ("hardware-free verifiability" + "split-vs-consolidate" as `/flight` skill design heuristics) are mission-control improvements, not mcp-sonos changes. Out of scope for Flight 04.

5. **CLAUDE.md update** to mention `pytest` as a regression net (no longer "smoke tests only" per the existing claim at line 34) is in Leg 02's Outputs but worth flagging here: it's a documentation surface change in the flight, not just a code change.

---

---

## Leg Progress

**2026-05-18 — Leg 05 (`05-fix-smoke-scripts-after-di-refactor`) landed**

- Mid-flight scope expansion. Closes the smoke-script regression Leg 04 surfaced and logged as a new mission Known Issue. Both smoke scripts now construct a `SonosController` and call `register_tools(mcp, controller)` before opening `Client(mcp)` — restoring the pre-Leg-02 functional shape with the DI factory pattern preserved.
- **`smoke_test.py`**: added `from mcp_sonos.controller import SonosController` import and extended the existing server import to `from mcp_sonos.server import mcp, register_tools`. Placed `controller = SonosController()` + `register_tools(mcp, controller)` at the top of `async def main()`, immediately before `async with Client(mcp) as client:`. Keeps the construction side-effects (TCP bind, SSDP/SONOS_IPS discovery) scoped to the `main()` execution path, matching `mcp_sonos/server.py::main()`'s own pattern.
- **`playlist_smoke.py`**: changed `from mcp_sonos.server import mcp, controller` → `from mcp_sonos.server import mcp, register_tools`, added `from mcp_sonos.controller import SonosController`. `controller` construction and `register_tools(mcp, controller)` placed at **module top level** (after the imports, before any function definition) — required because `build_playlist()` references `controller.cache_dir` and `controller.audio.url_for(...)` as free variables; making `controller` a function-local in `main()` would not satisfy those closures. This matches the script's original module-level `controller` shape (just locally constructed instead of imported from `mcp_sonos.server`). Placement is after the SONOS_IPS setdefault block from Leg 01, so discovery uses the deterministic IPs.
- Verification (all hardware-independent):
  1. `.venv/bin/python -m py_compile smoke_test.py playlist_smoke.py` — clean.
  2. `grep -n "register_tools" smoke_test.py playlist_smoke.py` — `smoke_test.py:23` (import), `smoke_test.py:35` (call); `playlist_smoke.py:36` (import), `playlist_smoke.py:40` (call). Both files have the import + the call.
  3. `grep -n "from mcp_sonos.server import" smoke_test.py playlist_smoke.py` — both files import `mcp, register_tools` only. `controller` is no longer imported from `mcp_sonos.server` (which is the correct shape, since Leg 02 removed the module-level symbol).
- **Hardware-dependent verification deferred** — `ping -c1 -W1` against all five `192.168.1.51-55` IPs returned UNREACHABLE. Live smoke run of `smoke_test.py` (which would have been the mission's first chance at a green `say()` end-to-end thanks to Leg 04's fix) cannot be performed from this session. The static checks above confirm the import-time `ImportError` and the runtime `Unknown tool: 'list_speakers'` failure modes documented in the mission Known Issue are both addressed; live-hardware confirmation is a post-handoff verification step.
- Mission Known Issues updated: the "Smoke scripts no longer functional after Leg 02 DI refactor" entry now marked resolved by this leg (resolution note added; the live-hardware verification caveat preserved as a follow-up flag).
- Leg status: `ready` → `in-flight` → `landed`. Not committed (handoff to reviewer per `/agentic-workflow` Phase 2d).

**2026-05-18 — Leg 04 (`04-investigate-say-coordinator-bug`) landed**

- **Outcome: FIX** (not xfail). Mission Known Issue `say()` coordinator-routing bug resolved. **10 tests pass, 0 fail, 0 xfail** (8 prior + 2 new from this leg).
- **Phase A — bug reproduction (Path A succeeded on first try)**:
  - Created `tests/test_say_coordinator.py` with a `_SlaveOnPlayUriFake(SoCoFake)` subclass — overrides `play_uri` to raise `SoCoSlaveException` while inheriting the default `group.coordinator = self` view (i.e. SoCo's local cache reports the speaker as coordinator-of-one). This is Flight 03 debrief's predicted shape: `list_groups` says coordinator, `play_uri` says otherwise.
  - Imported `from soco.exceptions import SoCoSlaveException` IN THE TEST FILE; `tests/_fakes.py` is untouched (still zero `import soco` hits — fake stays SoCo-free per its docstring).
  - Stubbed `controller_mod.AudioHost.start`, `controller_mod.synthesize`, `controller_mod.AudioHost.url_for`, and `SonosController._wait_until_stopped` to keep the test hardware-free and fast (full file runs in 0.19s). Patched `controller_mod.sp.discover_speakers` per test to return the staged fakes.
- **Phase B — root-cause investigation**:
  - Added `print(..., file=sys.stderr)` instrumentation in `say()` per the leg's snippet (also `import sys` at module top).
  - Ran `pytest tests/test_say_coordinator.py -v -s` and observed: `target='Kitchen' s=Kitchen s.uid=RINCON_BUG0001 coord=Kitchen coord.uid=RINCON_BUG0001 coord.group.coordinator=Kitchen coord.group.coordinator.uid=RINCON_BUG0001`.
  - **Key finding**: `coord.uid == coord.group.coordinator.uid`. **No controller-visible divergence exists before the call.** The divergence is between SoCo's in-process cache and the Sonos firmware — invisible to `_coordinator_of` and `_resolve_coordinator` no matter how cleverly they're rewritten. Hypothesis #1 (stale-cached SoCo) confirmed in its strongest form: the cache lies in a way the controller can't detect without invoking `play_uri` and observing the rejection.
  - Implication: A "prefer `coord.group.coordinator` over `coord` when they differ" fix is impossible — they never differ in this state. The only fix shapes are (a) `SoCoSlaveException`-catching retry with forced re-discovery, or (b) blanket pre-emptive re-discovery before every `play_uri`. Option (a) is cheaper and more targeted.
  - **Removed all `print(..., file=sys.stderr)` lines AND the `import sys`** before proceeding to Phase C. Verified via `grep -n "print.*file=sys.stderr" mcp_sonos/controller.py` returning zero hits.
- **Phase C — fix decision (in-scope, FIX)**:
  - Surface-guard check: the fix touches `controller.py::say()` (~5 lines wrapper change) + adds `controller.py::_play_uri_with_stale_coord_retry` (~20 lines new helper). No `playlists.py` touched, no SoCo internals, no new cache layer beyond `_speakers_fresh` (the fix uses the EXISTING cache, just invalidates its timestamp). **In-scope per surface guard.**
  - Fix shape — `controller.py::_play_uri_with_stale_coord_retry(name, coord, url, *, title) -> SoCo`:
    1. Lazy-imports `SoCoSlaveException` (so test fakes don't have to satisfy the SoCo type hierarchy for the happy path).
    2. Calls `coord.play_uri(url, title=title)`; returns `coord` on success.
    3. On `SoCoSlaveException`: sets `self._speakers_ts = 0.0` to force re-discovery on the next `_speakers_fresh()`; calls `_resolve_coordinator(name)` to get a fresh `SoCo`; calls `fresh_coord.play_uri(url, title=title)` once; returns `fresh_coord` so `_wait_until_stopped` runs on the speaker that actually accepted the call.
  - `say()` reassigns its local `coord` to the helper's return value so the subsequent `_wait_until_stopped(coord)` runs against the right SoCo.
  - Two test cases pin the fix:
    1. `test_say_recovers_after_rediscover_returns_fresh_coordinator` — first discovery returns a `_SlaveOnPlayUriFake`; second returns a plain `SoCoFake`. Asserts `say()` returns normally, `result["spoken_on"] == "Kitchen"`, `fresh._track["uri"]` was set (proof `play_uri` reached the fresh fake), and exactly two discovery calls occurred.
    2. `test_say_propagates_when_rediscover_also_returns_stale_coordinator` — both discoveries return a `_SlaveOnPlayUriFake`. Asserts `pytest.raises(SoCoSlaveException)` and exactly two discovery calls (no infinite retry loop). Pins the single-retry contract.
- **Live-hardware verification deferred — blocked by NEW Leg 02 regression**:
  - Attempted `.venv/bin/python smoke_test.py` to verify the fix end-to-end against Sonos hardware. Failed at `Server exposes 0 tools:` with `fastmcp.exceptions.ToolError: Unknown tool: 'list_speakers'`. Cause: Leg 02's DI refactor moved tool registration into `register_tools(mcp, controller)` called from `main()`, but `smoke_test.py:22` imports `mcp` directly and never calls `main()` — so the imported `mcp` instance has zero tools. `playlist_smoke.py:35` is worse: it `from mcp_sonos.server import mcp, controller`, and `controller` no longer exists at module level — raises `ImportError` on import.
  - **This is a SECOND mission Known Issue surfaced by this leg, NOT a Leg 04 fix-or-xfail outcome.** Mission Known Issues updated with both items (say() bug resolved + new smoke-script regression to fix).
  - The pytest suite remains the regression net for the `say()` fix; it deterministically exercises both halves (recovery + worst-case bound) without live hardware.
- **Verification** (all hardware-independent):
  1. `.venv/bin/python -m py_compile tests/test_say_coordinator.py mcp_sonos/controller.py` — clean.
  2. `.venv/bin/pytest -v` — 10 passed in 0.26s, exit 0. The 8 prior tests + 2 new = no regressions in `validate_http_url`, `_verify_or_log`, or F1 takeover paths.
  3. `grep -n "print.*file=sys.stderr" mcp_sonos/controller.py` — zero hits.
  4. `grep -n "import soco\|from soco" tests/_fakes.py` — zero hits (fake stays SoCo-free).
  5. `grep -n "import soco" tests/test_say_coordinator.py` — 1 hit on `from soco.exceptions import SoCoSlaveException` (correct placement: in the test, not in the fake).
- **Hardware-dependent verification deferred**: `smoke_test.py` `say()` end-to-end verification blocked on the new Known Issue (smoke script wiring needs an update for the Leg 02 DI refactor — separate flight or post-mission maintenance).
- Leg status: `ready` → `in-flight` → `landed`. Not committed (handoff to reviewer per `/agentic-workflow` Phase 2d).

**2026-05-18 — Leg 03 (`03-first-unit-tests`) landed**

- First batch of unit tests using Leg 02's scaffolding. **8 tests pass, 0 fail, 0 xfail.** No live hardware required — `SoCoFake` is the only "Sonos" present.
- **`tests/test_urls.py`**: 3 tests covering `validate_http_url` per the leg snippet (happy path including case-insensitive scheme, bad scheme, missing netloc). Tightened the empty-string assertion to "raises ValueError" without pinning the message — empty string parses to no scheme, falls through to the bad-scheme branch first, so the precise message is not load-bearing.
- **`tests/test_tts_verify.py`**: 4 tests covering `_hash_voice_file` (known content → known hash) and the three `_verify_or_log` branches (pin matches, mismatch quarantines, no-pin warns). Mutates `KNOWN_VOICE_HASHES` via `try/finally` to restore state — single-process-pytest assumption documented in the module docstring. Strengthened the happy-path assertion to also confirm the file is left in place (only the mismatch branch should rename). Asserted on the full `observed` hash in `caplog.text` rather than a 8-char prefix.
- **`tests/test_playlists_takeover.py`**: 1 test pinning the F1 regression — `PlaylistManager` worker handles external takeover (different URI now playing) without raising `AttributeError`, names the speaker in the log, and cleanly exits its session. Uses `monkeypatch.setattr(playlists_mod, "POLL_INTERVAL", 0.01)` for ~10ms iterations + bounded-retry `while "preempted" not in caplog.text` loop (3s deadline) to close the `_iteration_event` "about-to-observe, not has-observed" race documented in Leg 02. Test passes deterministically — race closure works as designed.
- **No source-code changes**. Per AC #7, source fixes only happen if a test surfaces a bug; all 8 tests passed first run. `mcp_sonos/` is untouched in this leg.
- Verification (all hardware-independent):
  1. `.venv/bin/python -m py_compile tests/test_urls.py tests/test_tts_verify.py tests/test_playlists_takeover.py` — clean.
  2. `.venv/bin/pytest --collect-only` — 8 items collected across the 3 modules (also shows the existing zero-test layout from Leg 02 is now populated).
  3. `.venv/bin/pytest -v` — `8 passed in 0.21s`, exit 0.
  4. `grep -n "import soco\|from soco" tests/test_urls.py tests/test_tts_verify.py tests/test_playlists_takeover.py` — zero hits (exit 1). The takeover test reaches `playlists.py` which `from soco import SoCo`s for type hints, but `SoCo` is never instantiated by the test — `SoCoFake` covers the entire surface.
- **Hardware-dependent verification deferred**: live-disable pytest re-run (e.g. `SONOS_IPS=10.255.255.255`) and smoke-script runs (`smoke_test.py`, `playlist_smoke.py`) remain hardware-touching steps for the post-flight verification pass. The hardware-free property is established by the test sources themselves (no `import soco` outside type hints; no network calls; `SoCoFake` is the only speaker object touched).
- Leg status: `ready` → `in-flight` → `landed`. Not committed (handoff to reviewer per `/agentic-workflow` Phase 2d).

**2026-05-18 — Leg 02 (`02-test-scaffolding-and-di-refactor`) landed**

- Load-bearing architectural refactor. DI factory pattern introduced; SoCoFake scaffolding + pytest config landed alongside.
- **`mcp_sonos/server.py` DI refactor**: removed module-level `controller = SonosController()` (was line 34); kept module-level `mcp = FastMCP(...)` instance with the existing `name="sonos"` and `instructions=...` text byte-identical (diffed against `HEAD` over lines 21-31 — empty diff). All 32 `@mcp.tool`-decorated functions moved inside `def register_tools(mcp: FastMCP, controller: SonosController) -> None:` as closures over the `controller` parameter; signatures, `Annotated[..., Field(...)]` parameter annotations, and docstrings preserved verbatim. `SpeakerName` and `PlaylistName` type aliases stay module-level (controller-independent). `main()` now constructs the controller, calls `register_tools(mcp, controller)`, then `mcp.run()`. FastMCP 3.3.1 accepts late `@mcp.tool` registration with no API friction (no divert path needed — confirmed at design review held).
- **`mcp_sonos/playlists.py` test-observability hook**: added `self._iteration_event = threading.Event()` to `PlaylistManager.__init__` with the comment `# Test-observability hook — production code never waits on this.`. Added `self._iteration_event.set()` at the TOP of the inner poll loop (line 357, the wait-for-track-end loop — `while not session.stop_event.is_set()`), before the `skip_event` / `back_event` / poll / sleep paths. Placement is intentional per the leg spec: every iteration sets the event, including the break paths (skip, back, takeover) and the `continue` path on poll failure. Production code never reads it.
- **Test scaffolding**:
  - `tests/__init__.py` — created empty (package marker).
  - `tests/conftest.py` — created empty (pre-empts pytest import-discovery edge cases in Leg 03).
  - `tests/_fakes.py` — created with `SoCoFake` dataclass + `FakeGroup` dataclass, matching the leg's step 3 snippet. Uses string forward references (`"SoCoFake"`) for self-references. **No `import soco`**; the fake is independent of the real SoCo library. Surface: `player_name`, `uid`, `ip_address`, `is_visible()`, `group.coordinator`, `group.members`, `get_current_transport_info()`, `get_current_track_info()`, `play_uri`, `pause`, `stop`, `next`, `previous`, `volume` (property + setter), `mute` (property + setter), `unjoin`, `join`, `add_to_queue`, `clear_queue`. Module docstring originally referenced "no `import soco`" as a phrase; reworded to "this module never imports it" to avoid the literal substring confusing the `grep -n "import soco" tests/_fakes.py` verification step.
- **`pyproject.toml`**: extended `[project.optional-dependencies] dev` from `["pip-audit"]` to `["pip-audit", "pytest"]` (alphabetical order). Added `[tool.pytest.ini_options]` block with `testpaths = ["tests"]`. `.venv/bin/pip install -e ".[dev]"` succeeded; pytest 9.0.3 + pluggy 1.6.0 + iniconfig 2.3.0 installed alongside existing pip-audit 2.10.0.
- Verification (all hardware-independent):
  1. `.venv/bin/python -m py_compile mcp_sonos/server.py mcp_sonos/playlists.py tests/_fakes.py` — clean.
  2. `grep -n "^controller = SonosController" mcp_sonos/server.py` — zero hits (exit 1).
  3. `grep -n "def register_tools" mcp_sonos/server.py` — 1 hit at line 46.
  4. `grep -c "Use 'all' as the target" mcp_sonos/server.py` — returned `0`, **NOT 1 as the verification step predicted**. Cause: the substring straddles a line break in the `instructions=...` literal (line 27 ends `Use 'all' ` and line 28 starts `as the target of \`say\` ...`). The original `HEAD:mcp_sonos/server.py` ALSO returns 0 for this grep — the placement was identical before the refactor, so this is a stable property of the original source layout, not a regression from the refactor. Verbatim preservation was instead confirmed via `diff` of lines 21-31 against `HEAD` (empty diff). Flagging for future improvement to the verification step (e.g. `grep -A 2 ... | grep "as the target"` or a multi-line `pcregrep -M` form).
  5. `.venv/bin/python -c "import mcp_sonos.server; print('imports clean')"` — printed `imports clean`, exited 0, no port bind, no SSDP discovery, no audio host thread.
  6. `.venv/bin/python -c "from tests._fakes import SoCoFake; f = SoCoFake(player_name='Test'); print(f.player_name, f.group.coordinator.player_name)"` — printed `Test Test`, exit 0.
  7. `grep -n "import soco" tests/_fakes.py` — zero hits (exit 1) after the docstring reword.
  8. `.venv/bin/pytest` — runs, "collected 0 items / no tests ran in 0.00s", exit 0 (expected — tests land in Leg 03).
  9. `.venv/bin/pip-audit --version` → `2.10.0`; `.venv/bin/pytest --version` → `9.0.3`. Both work.
  10. Spot-check: `PlaylistManager(...)._iteration_event` is a `threading.Event`, unset on init.
- **Hardware-dependent verification deferred**: `.venv/bin/python -m mcp_sonos.server` end-to-end start and the smoke scripts (`.venv/bin/python smoke_test.py`, `.venv/bin/python playlist_smoke.py`) require live Sonos hardware. The functional path through `main()` → `SonosController()` → `register_tools(mcp, controller)` → `mcp.run()` is identical in shape to the prior module-level wiring; only the construction order changed.
- Leg status: `ready` → `in-flight` → `landed`. Not committed (handoff to reviewer per `/agentic-workflow` Phase 2d).

**2026-05-18 — Leg 01 (`01-flight-prereqs`) landed**

- Two bundled cleanups from prior debriefs, both runtime-inert (text/config only).
- **Smoke-script SSDP determinism** (Flight 02 debrief AI): added `import os` + `os.environ.setdefault("SONOS_IPS", "192.168.1.51,192.168.1.52,192.168.1.53,192.168.1.54,192.168.1.55")` block to both `smoke_test.py` and `playlist_smoke.py`, with the 3-line comment explaining the SSDP-race rationale + override path per the leg's prescriptive snippet. Placeholder IP list chosen: `192.168.1.51-55` — extends the `.51` start of the existing `HOST_IP=192.168.1.50` comment in `.env.example` upward (the `.env.example` `SONOS_IPS` example uses `.10/.11/.12`; opted for `.51-55` to stay close to the `HOST_IP` placeholder neighborhood Flight 02 Leg 03 established, and because the leg spec's Implementation Guidance explicitly lists `192.168.1.51,...,55`).
  - Placement nuance for `playlist_smoke.py`: the `setdefault` must precede `from mcp_sonos.server import mcp, controller` because `server.py` instantiates `SonosController()` at module top-level (the very thing Leg 02 will defer via `register_tools`). Set `SONOS_IPS` after `import os` but before `logging.basicConfig` to keep the env-mutation cluster tight and ahead of any side-effect-laden import. For `smoke_test.py`, placed between stdlib imports and the `from fastmcp import Client` block for the same reason.
- **`controller.py` class docstring** (Flight 02 debrief AI): `"""Stateful controller: speakers cache + audio host + lock."""` → `"""Stateful controller: speakers cache + audio host."""` at line 86. One-line edit, matches the leg spec's preferred replacement verbatim.
- Verification (all hardware-independent):
  1. `grep -n "SONOS_IPS" smoke_test.py playlist_smoke.py` — 3 hits per file (comment + comment + setdefault).
  2. `grep -A 1 "class SonosController" mcp_sonos/controller.py` — confirmed docstring is now `"""Stateful controller: speakers cache + audio host."""`.
  3. `git grep "+ lock" mcp_sonos/` — zero hits (exit 1).
  4. `git grep "speakers cache + audio host + lock"` — 0 hits in source code; remaining hits are in historical artifacts (Flight 02 debrief/log, Flight 04 recon table, this leg's own spec) that *quote* the old docstring as a reference. Annotated this scope clarification in the leg AC checkbox.
  5. `.venv/bin/python -m py_compile smoke_test.py playlist_smoke.py mcp_sonos/controller.py` — clean.
- Leg status: `ready` → `in-flight` → `landed`. Not committed (handoff to reviewer per `/agentic-workflow` Phase 2d).

---

## Decisions

**2026-05-18 — Leg 04: FIX (not xfail) on the `say()` coordinator bug**

- **Decision**: Implement a `SoCoSlaveException`-catching retry with forced re-discovery in `controller.py::say()`, rather than mark the test `xfail`.
- **Surface-guard evidence**: diff is contained to `controller.py` only — modifies `say()` (`mcp_sonos/controller.py:319-326`) and adds `_play_uri_with_stale_coord_retry` (new helper, ~20 lines, inserted after `say()`). No changes to `playlists.py`, `tts.py`, `_urls.py`, `server.py`, SoCo internals, or any new cache layer beyond the existing `_speakers_ts` invalidation. **In-scope per the leg's surface-area guard.**
- **Hypothesis confirmed**: Hypothesis #1 (stale-cached SoCo) in its strongest form — `coord.uid` and `coord.group.coordinator.uid` agree at the call site (instrumented via `print(..., file=sys.stderr)` during Phase B, then removed). The divergence lives between SoCo's in-process cache and Sonos firmware, invisible to controller-side inspection. Hypothesis #2 (lull-state) was NOT explored — Path A reproduced cleanly so Path B wasn't needed; the lull-state path is a subset of the same fix (the retry catches both since both manifest as `SoCoSlaveException`).
- **Rationale for FIX over xfail**: the leg's success criterion is "regression test scaffolding exists for this bug, fix if surface-guard-compliant." The retry pattern is the standard idiom for stale-cache recovery, fits cleanly in `say()`, and pins the single-retry contract via a worst-case test. Marking xfail would have left a real correctness bug unaddressed when the fix shape is well-understood and contained.
- **Trade-off accepted**: the fix doesn't fire for transports OTHER than `say()` (e.g. `play_url`, `play_file` via the same coordinator path). The mission Known Issue only documented `say()` failures, so we're matching the documented bug surface. If `play_url` smoke runs surface the same `SoCoSlaveException` later, the fix can be generalized by lifting `_play_uri_with_stale_coord_retry` into `play_url` as well — minimal additional surface. Documented here for a future debrief to pick up.

---

## Deviations

---

## Anomalies

**2026-05-18 — Leg 04: new mission Known Issue surfaced (Leg 02 DI-refactor regression in smoke scripts)**

- During Leg 04's attempt at live-hardware verification of the `say()` fix via `smoke_test.py`, both smoke scripts were found broken by the Leg 02 DI refactor:
  - `smoke_test.py` imports `mcp` from `mcp_sonos.server` and runs `Client(mcp)` without calling `main()` → 0 tools registered → `ToolError: Unknown tool: 'list_speakers'`.
  - `playlist_smoke.py` imports `mcp, controller` from `mcp_sonos.server` → `controller` no longer exists at module level → `ImportError`.
- **NOT a Leg 04 regression** — the cause is Leg 02's tool-registration relocation, but Leg 02's verification step `python -c "import mcp_sonos.server"` (correctly designed to confirm no TCP bind on import) did not exercise the FastMCP `Client(mcp)` path, so the symptom didn't surface until a smoke run was attempted.
- **Pre-flight check** had this risk on the radar (`flight.md` line 59: "pre-flight smoke baseline" item is unchecked). It was never recorded — running it after Leg 02 would have caught both smoke scripts before Leg 04.
- Logged as a new mission Known Issue; recommended next step is a small patch flight or post-mission maintenance run.
- **Methodology takeaway for debrief**: when a DI refactor moves registration into `main()`, the smoke scripts' "import the running configuration" pattern silently breaks. Flag this in the Architect's leg-design review for DI-style refactors going forward.

---

## Session Notes
