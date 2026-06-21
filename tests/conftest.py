"""Shared pytest configuration.

Pin HOST_IP so constructing a SonosController never performs the
`speakers.lan_host_ip()` UDP route probe (a `connect()` toward 8.8.8.8).
That probe is non-deterministic in sandboxed/offline CI and intermittently
raises `RuntimeError("Could not determine LAN host IP")`, which surfaces as a
flaky fixture-setup error under randomized test ordering.

Controller-level tests don't depend on the real LAN IP: playlist URL
classification (worker-vs-native routing) is exercised through PlaylistManager
with an explicitly injected host_ip, never the controller's discovered value.
A fixed loopback address is therefore semantically inert here.

`setdefault` so a real HOST_IP in the environment (e.g. a hardware smoke run)
still wins.
"""

import os

os.environ.setdefault("HOST_IP", "127.0.0.1")
