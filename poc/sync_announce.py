"""Group all speakers and play one synchronized announcement.

    python -m poc.sync_announce

Dissolves any existing groups, sets volume to 40% on each speaker,
joins them all under one coordinator, plays the message, then
dissolves the group again. Speakers are left ungrouped at the end.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from .audio_server import AudioServer
from .speakers import discover_speakers, lan_host_ip
from .tts import synthesize


MESSAGE = "Welcome to being free of the Sonos app. It's a brave new world."
VOLUME = 40
MAX_PLAYBACK_SECONDS = 30


def wait_until_stopped(speaker, timeout: float = MAX_PLAYBACK_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    time.sleep(0.4)
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
    print(f"Found {len(speakers)} speakers. Serving audio from {host_ip}.")

    # Phase 1: dissolve any existing groups so we have a clean slate.
    print("Dissolving existing groups...")
    for s in speakers:
        try:
            s.unjoin()  # no-op if already a coordinator-of-one
        except Exception as e:
            print(f"  [!] unjoin {s.player_name}: {e}")
    time.sleep(0.7)

    # Volume to 40% across the board.
    for s in speakers:
        s.volume = VOLUME

    # Pick a stable coordinator (alphabetical). Now safe because every
    # speaker is a coordinator-of-one after the dissolve.
    coordinator = sorted(speakers, key=lambda s: s.player_name)[0]
    print(f"Coordinator: {coordinator.player_name}")

    with tempfile.TemporaryDirectory(prefix="sonos-tts-") as tmp:
        tmp_path = Path(tmp)
        synthesize(MESSAGE, tmp_path / "announce.mp3")
        print(f"TTS: {MESSAGE!r}")

        with AudioServer(tmp_path, host_ip=host_ip) as srv:
            print("Joining all speakers under coordinator (partymode)...")
            coordinator.partymode()
            time.sleep(1.0)  # group membership broadcasts asynchronously

            url = srv.url_for("announce.mp3")
            print("Playing synced announcement...")
            coordinator.play_uri(url, title="MCP Sonos announcement")
            wait_until_stopped(coordinator)

    # Phase 2: dissolve the announcement group so we end ungrouped.
    print("Dissolving announcement group...")
    for s in speakers:
        try:
            s.unjoin()
        except Exception as e:
            print(f"  [!] unjoin {s.player_name}: {e}")
    time.sleep(0.5)

    print("Done (speakers left ungrouped).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
