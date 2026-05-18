# Leg: 03-first-unit-tests

**Status**: completed
**Flight**: [Test Scaffolding](../flight.md)

## Objective
Add the first batch of unit tests using Leg 02's scaffolding. Three test targets per Flight 03 debrief priority: `_urls.validate_http_url` (pure function — covers F14's three import sites by contract), `_verify_or_log` + `_hash_voice_file` (pure functions over bytes-on-disk — covers F8's regression net), and the F1 takeover regression (`session.coordinator_name` AttributeError — was Flight 01 Leg 01's fix, now pinned by test).

## Context
- Flight 03 debrief identified three "ideal hardware-free unit-test targets" in priority order: F1 takeover path, `_urls.validate_http_url`, `_verify_or_log` + tamper path.
- All three are pure-function-shaped: no live SoCo dependency, no TTS download, no audio host. They exercise the scaffolding Leg 02 just landed and convert ad-hoc verification into permanent regression net.
- Cumulative test count target: **at least 3 passing tests** after this leg lands. More is fine if natural.

## Inputs
- Leg 02's scaffolding: `tests/__init__.py`, `tests/_fakes.py::SoCoFake`, pytest in `[dev]`, `[tool.pytest.ini_options] testpaths = ["tests"]`
- Existing pure-function code: `mcp_sonos/_urls.py::validate_http_url`, `mcp_sonos/tts.py::_hash_voice_file` + `_verify_or_log` + `KNOWN_VOICE_HASHES`, `mcp_sonos/playlists.py::PlaylistManager` worker (the takeover branch)
- F1 fix context: `mcp_sonos/playlists.py:380` (now uses `session.speaker_name` after Flight 01 Leg 01). The bug was an AttributeError when the worker hit the external-takeover branch.

## Outputs
- Three new test modules:
  - `tests/test_urls.py` — covers `validate_http_url` happy path + bad scheme + missing netloc + lowercase normalization
  - `tests/test_tts_verify.py` — covers `_hash_voice_file` correctness, `_verify_or_log` happy/mismatch/no-pin branches, quarantine file rename, `_verified_voices` per-process cache
  - `tests/test_playlists_takeover.py` — covers F1: build a playlist via `PlaylistManager`, simulate external takeover by setting fake's `_transport`/`_track`, assert the takeover branch logs cleanly (no `AttributeError`), worker exits cleanly
- `.venv/bin/pytest` exits 0 with at least 3 passing tests, no live hardware reachable
- Smoke tests still pass against live hardware (no behavior change)

## Acceptance Criteria
- [x] `tests/test_urls.py` exists; contains ≥3 tests covering `validate_http_url`: happy path (`http://example.com/x.mp3`, `https://...`), bad scheme (`file://`, `gopher://`), missing netloc (`http:`, empty string)
- [x] `tests/test_tts_verify.py` exists; contains ≥3 tests covering `_hash_voice_file` (known content → known hash), `_verify_or_log` happy (pin matches), `_verify_or_log` mismatch (raises RuntimeError + quarantine file gets created), `_verify_or_log` no-pin (logs warning, doesn't raise)
- [x] `tests/test_playlists_takeover.py` exists; contains ≥1 test that exercises the F1 takeover branch with `SoCoFake` and asserts no `AttributeError` is raised + log message mentions the speaker name
- [x] `.venv/bin/pytest` exits 0 with no live Sonos reachable
- [x] At least 3 tests pass (any reasonable count above that is fine)
- [x] All tests use `pytest` idioms (test functions, `caplog`, `tmp_path`, etc.) — no `unittest.TestCase` boilerplate unless there's a strong reason
- [x] If any test fails or surfaces a real bug in the code under test, **fix the code in this leg if the fix is small and obvious** (e.g. a stricter validator); otherwise note the bug and add a `pytest.xfail` marker (don't ship broken tests) — N/A: all 8 tests passed first run, no bugs surfaced.

## Verification Steps
- `cd <repo-root> && .venv/bin/pytest -v` — shows at least 3 passing tests, exits 0
- `.venv/bin/pytest -v --collect-only` — confirm the 3 test files are picked up
- Disable hardware temporarily (e.g., disconnect WiFi or set `SONOS_IPS=10.255.255.255` impossible-IP) and re-run pytest — should still pass (proves hardware-free)
- `python smoke_test.py` and `python playlist_smoke.py` against live hardware — still work
- `grep -rn "xfail" tests/` — note any test marked `xfail` and ensure it has a clear comment pointing at the issue

## Implementation Guidance

1. **`tests/test_urls.py`**:
   ```python
   import pytest
   from mcp_sonos._urls import validate_http_url

   def test_validate_http_happy():
       assert validate_http_url("http://example.com/song.mp3") == "http://example.com/song.mp3"
       assert validate_http_url("https://example.com/x.mp3") == "https://example.com/x.mp3"
       assert validate_http_url("HTTP://Example.com/x") == "HTTP://Example.com/x"  # lowercased before compare

   def test_validate_http_bad_scheme():
       with pytest.raises(ValueError, match="must be http or https"):
           validate_http_url("file:///etc/passwd")
       with pytest.raises(ValueError, match="must be http or https"):
           validate_http_url("gopher://example.com/")

   def test_validate_http_no_netloc():
       with pytest.raises(ValueError, match="must include a host"):
           validate_http_url("http:")
       with pytest.raises(ValueError):
           validate_http_url("")
   ```

2. **`tests/test_tts_verify.py`**:
   ```python
   import pytest
   import hashlib
   from pathlib import Path
   from mcp_sonos.tts import _hash_voice_file, _verify_or_log, KNOWN_VOICE_HASHES

   def test_hash_voice_file_known_content(tmp_path):
       p = tmp_path / "test.bin"
       content = b"hello world"
       p.write_bytes(content)
       expected = hashlib.sha256(content).hexdigest()
       assert _hash_voice_file(p) == expected

   def test_verify_or_log_happy(tmp_path):
       # Mock a pinned voice
       p = tmp_path / "voice.onnx"
       p.write_bytes(b"x")
       observed = _hash_voice_file(p)
       # Add to KNOWN_VOICE_HASHES temporarily
       KNOWN_VOICE_HASHES["test_voice"] = observed
       try:
           _verify_or_log("test_voice", observed, p)  # should not raise
       finally:
           del KNOWN_VOICE_HASHES["test_voice"]

   def test_verify_or_log_mismatch_quarantines(tmp_path):
       p = tmp_path / "voice.onnx"
       p.write_bytes(b"original")
       KNOWN_VOICE_HASHES["test_voice"] = "0" * 64  # wrong hash
       try:
           with pytest.raises(RuntimeError, match="hash mismatch"):
               _verify_or_log("test_voice", _hash_voice_file(p), p)
           # Quarantined file exists
           assert not p.exists()
           assert p.with_suffix(p.suffix + ".suspect").exists()
       finally:
           del KNOWN_VOICE_HASHES["test_voice"]

   def test_verify_or_log_no_pin_warns(tmp_path, caplog):
       p = tmp_path / "voice.onnx"
       p.write_bytes(b"x")
       observed = _hash_voice_file(p)
       # Voice not in KNOWN_VOICE_HASHES → warning path
       with caplog.at_level("WARNING"):
           _verify_or_log("nonexistent_voice", observed, p)  # should not raise
       assert "no pinned hash" in caplog.text.lower()
       assert observed[:8] in caplog.text  # observed hash included
   ```

3. **`tests/test_playlists_takeover.py`** (uses SoCoFake + `_iteration_event` from Leg 02):
   ```python
   import logging
   import time
   import pytest
   from mcp_sonos import playlists as playlists_mod
   from mcp_sonos.playlists import PlaylistManager
   from tests._fakes import SoCoFake

   def test_takeover_logs_cleanly_no_attributeerror(caplog, monkeypatch):
       # Speed up the worker poll loop so the test runs fast and the race
       # window (iteration_event signals "starting", not "completed") is
       # tiny. Combine with a bounded-retry caplog check below.
       monkeypatch.setattr(playlists_mod, "POLL_INTERVAL", 0.01)

       speaker = SoCoFake(player_name="Kitchen", uid="RINCON_TEST001")

       # PlaylistManager constructor takes resolve_coordinator: Callable[[str], tuple[SoCo, SoCo]]
       def resolve_coordinator(name):
           assert name == "Kitchen"
           return speaker, speaker

       manager = PlaylistManager(resolve_coordinator=resolve_coordinator)
       manager.create("morning")
       manager.add_many("morning", [{"url": "http://test/a.mp3", "title": "A"}])

       try:
           with caplog.at_level(logging.INFO):
               manager.play("Kitchen", "morning")

               # Wait for the worker to start polling. _iteration_event signals
               # "about to observe state," not "has observed it" — see Leg 02's
               # design notes for why this is at the top of the inner loop.
               assert manager._iteration_event.wait(timeout=2.0), "worker never started polling"

               # Simulate external takeover: a different URI is now playing
               speaker._track = {"uri": "http://other/takeover.mp3", "title": ""}
               speaker._transport = {"current_transport_state": "PLAYING"}

               # Bounded retry: poll caplog until the takeover branch logs, or
               # the deadline elapses. POLL_INTERVAL=0.01 means iterations take
               # ~10ms; allow up to 3s for slow runners.
               deadline = time.monotonic() + 3.0
               while "preempted" not in caplog.text and time.monotonic() < deadline:
                   time.sleep(0.02)

           # Regression assertions
           assert "AttributeError" not in caplog.text, \
               "F1 regression — coordinator_name AttributeError reintroduced"
           assert "preempted" in caplog.text, \
               "takeover branch never logged within deadline"
           assert "Kitchen" in caplog.text, \
               "log should mention the speaker name (post-Flight-01 fix)"

           # Pin the session-cleanup branch: after the takeover, the session
           # exits cleanly and is removed from _sessions.
           # (Worker thread may still be in its `finally` cleanup when we get
           # here; give it a brief moment to remove itself from _sessions.)
           cleanup_deadline = time.monotonic() + 2.0
           while speaker.uid in manager._sessions and time.monotonic() < cleanup_deadline:
               time.sleep(0.02)
           assert speaker.uid not in manager._sessions, "worker did not clean up its session entry"
       finally:
           # Belt-and-suspenders cleanup in case the test failed before the
           # worker exited cleanly via the takeover path.
           manager.stop("Kitchen")
   ```
   - Uses Leg 02's `_iteration_event` for fast worker startup detection. The takeover-observation race (`_iteration_event` signals "about to observe," not "has observed") is closed by the bounded-retry `while "preempted" not in caplog.text` loop combined with monkeypatched fast polling.
   - `PlaylistManager` constructor signature confirmed at design review (`mcp_sonos/playlists.py:98`).
   - Asserts on `"preempted"` specifically — the takeover branch's log includes that exact word (`playlists.py:393`). Avoids the looser `"preempted" or "stopping"` match.

4. **Optional**: add `conftest.py` if pytest needs `tests` on the import path. With `testpaths = ["tests"]` it should pick up automatically; if `from tests._fakes import SoCoFake` fails, add `conftest.py` or `pytest.ini` tweaks as needed.

## Files Affected
- `tests/test_urls.py` — new, ~25 lines
- `tests/test_tts_verify.py` — new, ~50 lines
- `tests/test_playlists_takeover.py` — new, ~40 lines
- Possibly `tests/conftest.py` — only if pytest's import discovery needs help

## Edge Cases
- **`KNOWN_VOICE_HASHES` mutation in tests**: tests modify the module-level dict for setup. Use `try/finally` to restore state (shown in snippets above). A future cleanup could refactor to dependency-inject the pin map, but that's out of scope. **Constraint**: this pattern is NOT safe for `pytest-xdist` parallel runs — assumes single-process pytest. If parallelization lands later, refactor to `monkeypatch.setitem(KNOWN_VOICE_HASHES, "test_voice", hash)` which is per-test-isolated.
- **`_verified_voices` cache pollution**: tests that touch `_ensure_voice` (none in this leg) would share the cache across tests. None of this leg's tests do — but Leg 04's investigation test may. Note in Leg 04's edge cases.
- **`caplog` log level**: pytest's `caplog` defaults to `WARNING` — use `caplog.at_level("INFO")` for tests that need lower-level logs (the playlist test).
- **Worker thread cleanup**: `manager.stop("Kitchen")` at the end of the takeover test ensures the daemon thread exits. If it leaks, subsequent tests may see odd state. Use `pytest --forked` or explicit cleanup if flakiness emerges.
- **`_iteration_event` is module-shared across PlaylistManagers**: it's an instance attribute, so distinct managers have distinct events. But within a single test, multiple `wait()`/`clear()` cycles are sequential and safe. Don't rely on the event being set "exactly once" — the worker may set it multiple times before a test gets back to `wait()`. The `clear()` between waits handles this.

---

## Post-Completion Checklist

- [x] All acceptance criteria verified
- [x] `pytest` passes with no live hardware
- [x] Smoke tests still pass against live hardware
- [x] Update `../flight-log.md` with leg progress entry (include test counts)
- [x] Set this leg's status to `completed`
- [x] Check off this leg in `../flight.md`
