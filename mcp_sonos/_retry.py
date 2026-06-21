"""Shared stale-coordinator retry helper.

Extracted so both `controller.py` and `playlists.py` can use it without
creating a circular import (controller imports playlists; neither imports
this module until now).
"""

from __future__ import annotations

from typing import Callable, TypeVar

from soco import SoCo

_T = TypeVar("_T")


def with_stale_coord_retry(
    coord: SoCo,
    action: Callable[[SoCo], _T],
    invalidate: Callable[[], None],
    resolve: Callable[[], SoCo],
) -> SoCo:
    """Call ``action(coord)``, recovering once from a stale-coordinator view.

    On ``SoCoSlaveException``:
    1. Call ``invalidate()`` to flush the speakers cache (bypasses TTL so the
       next resolution forces a fresh discovery).
    2. Call ``resolve()`` to obtain a fresh coordinator.
    3. Call ``action(fresh_coord)`` once more; if it still raises, propagate.

    Returns the coordinator that succeeded (either the original ``coord`` or
    the fresh one from ``resolve()``).  Callers that need the coordinator for
    follow-up calls (e.g. ``_wait_until_stopped``) use the return value;
    callers that don't need it may ignore it.

    The ``action`` callable's own return value is intentionally discarded —
    the only useful post-retry datum is which coordinator succeeded.
    """
    # Imported lazily so test fakes don't have to satisfy the full SoCo type
    # hierarchy on the happy path (mirrors the original per-site lazy imports).
    from soco.exceptions import SoCoSlaveException

    try:
        action(coord)
        return coord
    except SoCoSlaveException:
        invalidate()
        fresh_coord = resolve()
        action(fresh_coord)
        return fresh_coord
