"""A calendar source backed by local JSON -- the offline, deterministic implementation.

JSON shape::

    {
      "Alice": {
        "timezone": "Asia/Jerusalem",            # optional; default UTC. Applies to naive times.
        "events": [
          {"start": "2026-06-15T10:00:00", "end": "2026-06-15T11:00:00"},
          {"start": "...", "end": "...", "status": "tentative"},
          {"start": "...", "end": "...", "transparent": true},
          {"date": "2026-06-16", "all_day": true},
          {"start": "...", "end": "...", "reschedule": "easy", "title": "1:1 with Dana"}
        ]
      },
      "Bob": { ... }
    }

``reschedule`` (Part B) tags how willing the owner is to move a meeting: ``easy`` / ``medium`` /
``hard``; absent means ``hard`` (never moved). ``title`` names the meeting for the "what must be
moved" report. This source owns only parsing; the event semantics live in ``freebusy``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from gated_scheduler.freebusy import EASY, HARD, MEDIUM, Event, EventStatus
from gated_scheduler.freebusy import displaced_meetings as derive_displaced
from gated_scheduler.freebusy import free_slots as derive_free_slots
from gated_scheduler.grid import TimeGrid
from gated_scheduler.sources.base import CalendarSource, DisplacedMeeting

_TIERS = {"easy": EASY, "medium": MEDIUM, "hard": HARD}


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

    def has_reschedulable_meetings(self) -> bool:
        """Whether any event carries a Part B ``reschedule`` tag (selects the tiered CLI path)."""
        return any(
            "reschedule" in raw
            for entry in self._data.values()
            for raw in entry.get("events", [])
        )

    def _events(self, party_id: str) -> list[Event]:
        if party_id not in self._data:
            raise KeyError(party_id)
        entry = self._data[party_id]
        tz: tzinfo = ZoneInfo(entry["timezone"]) if entry.get("timezone") else UTC
        return [_parse_event(raw, tz) for raw in entry.get("events", [])]

    def free_slots(self, party_id: str, grid: TimeGrid, *, relax_threshold: int = 0) -> set[str]:
        return derive_free_slots(
            self._events(party_id),
            grid,
            tentative_is_busy=self._tentative_is_busy,
            relax_threshold=relax_threshold,
        )

    def displaced_meetings(
        self,
        party_id: str,
        grid: TimeGrid,
        meeting_slot_ids: Iterable[str],
        *,
        relax_threshold: int,
    ) -> list[DisplacedMeeting]:
        moved = derive_displaced(
            self._events(party_id),
            grid,
            meeting_slot_ids,
            relax_threshold=relax_threshold,
            tentative_is_busy=self._tentative_is_busy,
        )
        return [
            DisplacedMeeting(title=e.title, start=e.start, end=e.end, tier=e.tier) for e in moved
        ]


def _parse_tier(raw: dict[str, Any]) -> int:
    value = raw.get("reschedule")
    if value is None:
        return HARD
    try:
        return _TIERS[str(value).lower()]
    except KeyError:
        raise ValueError(f"unknown reschedule tier: {value!r}") from None


def _parse_event(raw: dict[str, Any], tz: tzinfo) -> Event:
    status = EventStatus(raw.get("status", "confirmed"))
    transparent = bool(raw.get("transparent", False))
    tier = _parse_tier(raw)
    title = str(raw.get("title", ""))
    if raw.get("all_day"):
        day = date.fromisoformat(raw["date"])
        start = datetime(day.year, day.month, day.day, tzinfo=tz)
        return Event(
            start=start,
            end=start + timedelta(days=1),
            status=status,
            transparent=transparent,
            all_day=True,
            tier=tier,
            title=title,
        )
    start = datetime.fromisoformat(raw["start"])
    end = datetime.fromisoformat(raw["end"])
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)
    return Event(
        start=start,
        end=end,
        status=status,
        transparent=transparent,
        tier=tier,
        title=title,
    )
