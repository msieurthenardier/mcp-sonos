# Leg: 03-first-unit-tests

**Status**: ready
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
- [ ] `tests/test_urls.py` exists; contains ≥3 tests covering `validate_http_url`: happy path (`http://example.com/x.mp3`, `https://...`), bad scheme (`file://`, `gopher://`), missing netloc (`http:`, empty string)
- [ ] `tests/test_tts_verify.py` exists; contains ≥3 tests covering `_hash_voice_file` (known content → known hash), `_verify_or_log` happy (pin matches), `_verify_or_log` mismatch (raises RuntimeError + quarantine file gets created), `_verify_or_log` no-pin (logs warning, doesn't raise)
- [ ] `tests/test_playlists_takeover.py` exists; contains ≥1 test that exercises the F1 takeover branch with `SoCoFake` and asserts no `AttributeError` is raised + log message mentions the speaker name
- [ ] `.venv/bin/pytest` exits 0 with no live Sonos reachable
- [ ] At least 3 tests pass (any reasonable count above that is fine)
- [ ] All tests use `pytest` idioms (test functions, `caplog`, `tmp_path`, etc.) — no `unittest.TestCase` boilerplate unless there's a strong reason
- [ ] If any test fails or surfaces a real bug in the code under test, **fix the code in this leg if the fix is small and obvious** (e.g. a stricter validator); otherwise note the bug and add a `pytest.xfail` marker (don't ship broken tests)

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
   import pytest
   from mcp_sonos.playlists import PlaylistManager
   from tests._fakes import SoCoFake

   def test_takeover_logs_cleanly_no_attributeerror(caplog):
       speaker = SoCoFake(player_name="Kitchen", uid="RINCON_TEST001")

       # PlaylistManager constructor takes resolve_coordinator: Callable[[str], tuple[SoCo, SoCo]]
       def resolve_coordinator(name):
           assert name == "Kitchen"
           return speaker, speaker

       manager = PlaylistManager(resolve_coordinator=resolve_coordinator)
       manager.create("morning")
       manager.add_many("morning", [{"url": "http://test/a.mp3", "title": "A"}])

       with caplog.at_level(logging.INFO):
           manager.play("Kitchen", "morning")

           # Wait for the worker to start polling
           assert manager._iteration_event.wait(timeout=2.0), "worker never started polling"
           manager._iteration_event.clear()

           # Simulate external takeover: a different URI is now playing
           speaker._track = {"uri": "http://other/takeover.mp3", "title": ""}
           speaker._transport = {"current_transport_state": "PLAYING"}

           # Wait for the next iteration to observe the takeover
           assert manager._iteration_event.wait(timeout=2.0), "worker never observed takeover"

       # The bug under regression: takeover detection should NOT raise AttributeError
       assert "AttributeError" not in caplog.text
       # The log should mention the speaker name (post-Flight-01 fix)
       assert "Kitchen" in caplog.text
       # And mention "preempted" or "stopping"
       assert "preempted" in caplog.text.lower() or "stopping" in caplog.text.lower()

       # Cleanup: stop the worker thread
       manager.stop("Kitchen")
   ```
   - Uses Leg 02's `_iteration_event` for deterministic worker synchronization (replaces sleep-based polling). No flakiness on slow runners.
   - `PlaylistManager` constructor signature confirmed at design review (`mcp_sonos/playlists.py:98`).

4. **Optional**: add `conftest.py` if pytest needs `tests` on the import path. With `testpaths = ["tests"]` it should pick up automatically; if `from tests._fakes import SoCoFake` fails, add `conftest.py` or `pytest.ini` tweaks as needed.

## Files Affected
- `tests/test_urls.py` — new, ~25 lines
- `tests/test_tts_verify.py` — new, ~50 lines
- `tests/test_playlists_takeover.py` — new, ~40 lines
- Possibly `tests/conftest.py` — only if pytest's import discovery needs help

## Edge Cases
- **`KNOWN_VOICE_HASHES` mutation in tests**: tests modify the module-level dict for setup. Use `try/finally` to restore state (shown in snippets above). A future cleanup could refactor to dependency-inject the pin map, but that's out of scope.
- **`_verified_voices` cache pollution**: tests that touch `_ensure_voice` (none in this leg) would share the cache across tests. None of this leg's tests do — but Leg 04's investigation test may. Note in Leg 04's edge cases.
- **`caplog` log level**: pytest's `caplog` defaults to `WARNING` — use `caplog.at_level("INFO")` for tests that need lower-level logs (the playlist test).
- **Worker thread cleanup**: `manager.stop("Kitchen")` at the end of the takeover test ensures the daemon thread exits. If it leaks, subsequent tests may see odd state. Use `pytest --forked` or explicit cleanup if flakiness emerges.
- **`_iteration_event` is module-shared across PlaylistManagers**: it's an instance attribute, so distinct managers have distinct events. But within a single test, multiple `wait()`/`clear()` cycles are sequential and safe. Don't rely on the event being set "exactly once" — the worker may set it multiple times before a test gets back to `wait()`. The `clear()` between waits handles this.

---

## Post-Completion Checklist

- [ ] All acceptance criteria verified
- [ ] `pytest` passes with no live hardware
- [ ] Smoke tests still pass against live hardware
- [ ] Update `../flight-log.md` with leg progress entry (include test counts)
- [ ] Set this leg's status to `completed`
- [ ] Check off this leg in `../flight.md`
