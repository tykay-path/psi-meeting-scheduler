"""The calendar seam.

A ``CalendarSource`` has exactly one job: produce a party's set of free slot ids on the shared
grid. Everything downstream (PSI, matching) takes sets and knows nothing about where they came
from -- so a hand-written source, a fixture file, and Google Calendar are interchangeable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from gated_scheduler.grid import TimeGrid


class CalendarSource(ABC):
    @abstractmethod
    def party_ids(self) -> list[str]:
        """The parties this source can provide calendars for."""

    @abstractmethod
    def free_slots(self, party_id: str, grid: TimeGrid) -> set[str]:
        """The slot ids in which ``party_id`` is free, derived from its own calendar only."""
