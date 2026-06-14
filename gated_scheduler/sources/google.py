"""Google Calendar source -- a documented stub, deliberately the last thing to build.

By the time this matters, the deterministic core and the fixture pipeline already prove
everything except one narrow question: "does my fetch produce the same kind of free-slot set
the fixtures did?" The intended implementation uses Google's **free/busy query API**, which
returns busy intervals directly instead of full event details -- a better fit *and* a privacy
win (no titles or attendees, just busy/free), aligned with the minimal-disclosure spirit of the
whole design. Each busy interval becomes an ``Event`` and the existing ``freebusy`` logic is
reused unchanged, so this layer stays thin.
"""

from __future__ import annotations

from typing import Any

from gated_scheduler.grid import TimeGrid
from gated_scheduler.sources.base import CalendarSource

_NOT_IMPLEMENTED = (
    "GoogleCalendarSource is a stub for v1 (which runs on fixtures). To implement: authenticate "
    "with OAuth, call the free/busy API for the grid window, wrap each returned busy interval as "
    "a freebusy.Event, and reuse freebusy.free_slots -- the seam stays identical to fixtures."
)


class GoogleCalendarSource(CalendarSource):
    def __init__(self, credentials: Any = None) -> None:
        self._credentials = credentials

    def party_ids(self) -> list[str]:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def free_slots(self, party_id: str, grid: TimeGrid) -> set[str]:
        raise NotImplementedError(_NOT_IMPLEMENTED)
