"""Unit tests for `mcp_sonos.tts._hash_voice_file` and `_verify_or_log`.

These are the F8 regression net: they cover the supply-chain pin
verification flow without touching the network or PiperVoice.load. Tests
mutate the module-level `KNOWN_VOICE_HASHES` dict and restore it via
`try/finally` so failures don't leak setup state into other tests.

NOTE: this mutation pattern is NOT safe under `pytest-xdist` parallel
runs — it assumes single-process pytest. If parallel runs land later,
refactor to `monkeypatch.setitem(KNOWN_VOICE_HASHES, ...)`.
"""

from __future__ import annotations

import hashlib

import pytest

from mcp_sonos.tts import KNOWN_VOICE_HASHES, _hash_voice_file, _verify_or_log


def test_hash_voice_file_known_content(tmp_path):
    p = tmp_path / "test.bin"
    content = b"hello world"
    p.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()
    assert _hash_voice_file(p) == expected


def test_verify_or_log_happy(tmp_path):
    p = tmp_path / "voice.onnx"
    p.write_bytes(b"x")
    observed = _hash_voice_file(p)
    KNOWN_VOICE_HASHES["test_voice"] = observed
    try:
        # Pin matches → returns None, no raise, no file mutation.
        assert _verify_or_log("test_voice", observed, p) is None
        assert p.exists(), "happy path must leave the file in place"
    finally:
        del KNOWN_VOICE_HASHES["test_voice"]


def test_verify_or_log_mismatch_quarantines(tmp_path):
    p = tmp_path / "voice.onnx"
    p.write_bytes(b"original")
    KNOWN_VOICE_HASHES["test_voice"] = "0" * 64  # wrong hash
    try:
        with pytest.raises(RuntimeError, match="hash mismatch"):
            _verify_or_log("test_voice", _hash_voice_file(p), p)
        # File got renamed with .suspect suffix (not deleted — operator
        # can inspect).
        assert not p.exists()
        assert p.with_suffix(p.suffix + ".suspect").exists()
    finally:
        del KNOWN_VOICE_HASHES["test_voice"]


def test_verify_or_log_no_pin_warns(tmp_path, caplog):
    p = tmp_path / "voice.onnx"
    p.write_bytes(b"x")
    observed = _hash_voice_file(p)
    # Voice not in KNOWN_VOICE_HASHES → trust-on-first-use warning path.
    with caplog.at_level("WARNING"):
        assert _verify_or_log("nonexistent_voice", observed, p) is None
    assert "no pinned hash" in caplog.text.lower()
    # Observed hash is logged so the operator can pin it.
    assert observed in caplog.text
