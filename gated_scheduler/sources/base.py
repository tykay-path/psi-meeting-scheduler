"""The calendar seam.

A ``CalendarSource`` has exactly one job: produce a party's set of free slot ids on the shared
grid. Everything downstream (PSI, matching) takes sets and knows nothing about where they came
from -- so a hand-written source, a fixture file, and Google Calendar are interchangeable.

Part B adds a second, equally local job: given a chosen meeting time, report which of *this*
party's own meetings it would have to reschedule. Both jobs read only one calendar, so no single
entity ever assembles the full picture.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from gated_scheduler.grid import TimeGrid


@dataclass(frozen=True)
class DisplacedMeeting:
    """A meeting the owner would reschedule to free a chosen slot (Part B).

    Computed locally from a single party's own calendar -- never aggregated across parties.
    """

    title: str
    start: datetime
    end: datetime
    tier: int


class CalendarSource(ABC):
    @abstractmethod
    def party_ids(self) -> list[str]:
        """The parties this source can provide calendars for."""

    @abstractmethod
    def free_slots(self, party_id: str, grid: TimeGrid, *, relax_threshold: int = 0) -> set[str]:
        """The slot ids in which ``party_id`` is free, derived from its own calendar only.

        ``relax_threshold`` (Part B) frees the meetings the party is willing to reschedule, by
        tier; ``0`` is true free/busy (Part A behaviour).
        """

    @abstractmethod
    def displaced_meetings(
        self,
        party_id: str,
        grid: TimeGrid,
        meeting_slot_ids: Iterable[str],
        *,
        relax_threshold: int,
    ) -> list[DisplacedMeeting]:
        """This party's own meetings that must move to hold a meeting on ``meeting_slot_ids``.

        Local to one calendar; under gated access a party never learns what anyone else moves.
        """
