"""Play "Hello, this is Sonos speaker <name>" on each speaker individually.

    python -m poc.greet_each

Dissolves all current groups so every speaker plays solo, sets volume
to 40% on each, then speaks the greeting one at a time. Leaves the
speakers ungrouped at the end.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from .audio_server import AudioServer
from .speakers import discover_speakers, lan_host_ip, safe_filename
from .tts import synthesize


VOLUME = 40
MAX_PLAYBACK_SECONDS = 15


def wait_until_stopped(speaker, timeout: float = MAX_PLAYBACK_SECONDS) -> None:
    """Block until speaker reports STOPPED (TTS finished). Polls 4Hz."""
    deadline = time.monotonic() + timeout
    time.sleep(0.4)  # let playback actually start before we poll for STOPPED
    while time.monotonic() < deadline:
        state = speaker.get_current_transport_info().get("current_transport_state")
        if state in ("STOPPED", "PAUSED_PLAYBACK"):
            return
        time.sleep(0.25)


def main() -> int:
    speakers = discover_speakers()
    if not speakers:
        print("No speakers found. See `python -m poc.discover` for diagnostics.")
        return 1

    host_ip = lan_host_ip()
    print(f"Found {len(speakers)} speakers. Serving audio from {host_ip}.\n")

    # Dissolve every existing group so each speaker is a coordinator-of-one.
    print("Dissolving existing groups...")
    for s in speakers:
        try:
            s.unjoin()  # no-op if already a coordinator-of-one
        except Exception as e:
            print(f"  [!] unjoin {s.player_name}: {e}")
    time.sleep(0.7)

    # Volume to 40% on each speaker.
    for s in speakers:
        s.volume = VOLUME

    with tempfile.TemporaryDirectory(prefix="sonos-tts-") as tmp:
        tmp_path = Path(tmp)

        files: dict[str, str] = {}
        for s in speakers:
            phrase = f"Hello, this is Sonos speaker {s.player_name}."
            fname = f"greet_{safe_filename(s.player_name)}.mp3"
            synthesize(phrase, tmp_path / fname)
            files[s.player_name] = fname
            print(f"  TTS: {phrase!r} -> {fname}")

        with AudioServer(tmp_path, host_ip=host_ip) as srv:
            for s in speakers:
                url = srv.url_for(files[s.player_name])
                print(f"\n-> Playing on {s.player_name} ({s.ip_address})")
                s.play_uri(url, title=f"Greeting: {s.player_name}")
                wait_until_stopped(s)

    print("\nDone (speakers left ungrouped).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
