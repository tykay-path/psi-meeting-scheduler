"""A calendar source backed by local JSON -- the offline, deterministic implementation.

JSON shape::

    {
      "Alice": {
        "timezone": "Asia/Jerusalem",            # optional; default UTC. Applies to naive times.
        "events": [
          {"start": "2026-06-15T10:00:00", "end": "2026-06-15T11:00:00"},
          {"start": "...", "end": "...", "status": "tentative"},
          {"start": "...", "end": "...", "transparent": true},
          {"date": "2026-06-16", "all_day": true}
        ]
      },
      "Bob": { ... }
    }

This source owns only parsing; the event semantics live in ``freebusy``.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from gated_scheduler.freebusy import Event, EventStatus
from gated_scheduler.freebusy import free_slots as derive_free_slots
from gated_scheduler.grid import TimeGrid
from gated_scheduler.sources.base import CalendarSource


class FixtureCalendarSource(CalendarSource):
    def __init__(self, data: dict[str, Any], *, tentative_is_busy: bool = True) -> None:
        self._data = data
        self._tentative_is_busy = tentative_is_busy

    @classmethod
    def from_file(
        cls, path: str | Path, *, tentative_is_busy: bool = True
    ) -> FixtureCalendarSource:
        data = json.loads(Path(path).read_text())
        return cls(data, tentative_is_busy=tentative_is_busy)

    def party_ids(self) -> list[str]:
        return sorted(self._data)

    def free_slots(self, party_id: str, grid: TimeGrid) -> set[str]:
        if party_id not in self._data:
            raise KeyError(party_id)
        entry = self._data[party_id]
        tz: tzinfo = ZoneInfo(entry["timezone"]) if entry.get("timezone") else UTC
        events = [_parse_event(raw, tz) for raw in entry.get("events", [])]
        return derive_free_slots(events, grid, tentative_is_busy=self._tentative_is_busy)


def _parse_event(raw: dict[str, Any], tz: tzinfo) -> Event:
    status = EventStatus(raw.get("status", "confirmed"))
    transparent = bool(raw.get("transparent", False))
    if raw.get("all_day"):
        day = date.fromisoformat(raw["date"])
        start = datetime(day.year, day.month, day.day, tzinfo=tz)
        return Event(
            start=start,
            end=start + timedelta(days=1),
            status=status,
            transparent=transparent,
            all_day=True,
        )
    start = datetime.fromisoformat(raw["start"])
    end = datetime.fromisoformat(raw["end"])
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)
    return Event(start=start, end=end, status=status, transparent=transparent)
