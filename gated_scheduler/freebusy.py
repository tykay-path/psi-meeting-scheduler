"""Turn a pile of calendar events into a clean free-slot set on the grid.

This is where most real-world bugs live -- not in the PSI, but in the messy mapping from
events to free/busy: time zones, all-day events, tentative vs. accepted, events that only
partially cover a slot, and events crossing grid boundaries. The actual interval->slot overlap
(and tz normalization) is handled by ``TimeGrid``; this module owns the *event semantics*.

Policy (configurable where noted): a slot is busy if *any* blocking event overlaps it at all
(conservative); tentative events are busy by default; cancelled and free/transparent events
never block; all-day events block their whole day.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from gated_scheduler.grid import TimeGrid


class EventStatus(StrEnum):
    CONFIRMED = "confirmed"
    TENTATIVE = "tentative"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Event:
    """A normalized calendar event. ``transparent`` mirrors Google's "shows me as free"."""

    start: datetime
    end: datetime
    status: EventStatus = EventStatus.CONFIRMED
    transparent: bool = False
    all_day: bool = False


def _is_blocking(event: Event, tentative_is_busy: bool) -> bool:
    if event.status == EventStatus.CANCELLED or event.transparent:
        return False
    if event.status == EventStatus.TENTATIVE:
        return tentative_is_busy
    return True


def _busy_interval(event: Event) -> tuple[datetime, datetime]:
    if event.all_day and event.end <= event.start:
        return event.start, event.start + timedelta(days=1)
    return event.start, event.end


def free_slots(
    events: Iterable[Event],
    grid: TimeGrid,
    *,
    tentative_is_busy: bool = True,
) -> set[str]:
    """The set of grid slot ids in which the owner is free, given its events."""
    busy: set[int] = set()
    for event in events:
        if not _is_blocking(event, tentative_is_busy):
            continue
        start, end = _busy_interval(event)
        busy |= grid.slots_covering(start, end)
    return {slot.slot_id for slot in grid.slots if slot.index not in busy}
