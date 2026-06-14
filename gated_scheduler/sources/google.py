"""Google Calendar source -- a documented stub, deliberately the last thing to build.

By the time this matters, the deterministic core and the fixture pipeline already prove
everything except one narrow question: "does my fetch produce the same kind of free-slot set
the fixtures did?" The intended implementation uses Google's **free/busy query API**, which
returns busy intervals directly instead of full event details -- a better fit *and* a privacy
win (no titles or attendees, just busy/free), aligned with the minimal-disclosure spirit of the
whole design. Each busy interval becomes an ``Event`` and the existing ``freebusy`` logic is
reused unchanged, so this layer stays thin.

Note for Part B: free/busy returns no titles or reschedule hints, so a real implementation would
source tiers/titles elsewhere (the owner's own agent), keeping the relaxation decision local.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from gated_scheduler.grid import TimeGrid
from gated_scheduler.sources.base import CalendarSource, DisplacedMeeting

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

    def free_slots(self, party_id: str, grid: TimeGrid, *, relax_threshold: int = 0) -> set[str]:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def displaced_meetings(
        self,
        party_id: str,
        grid: TimeGrid,
        meeting_slot_ids: Iterable[str],
        *,
        relax_threshold: int,
    ) -> list[DisplacedMeeting]:
        raise NotImplementedError(_NOT_IMPLEMENTED)
