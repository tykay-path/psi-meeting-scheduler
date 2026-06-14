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


# Reschedulability tiers (Part B): how willing the owner is to move a meeting -- higher is harder.
# Relaxation runs in rounds with a threshold T; an event stops blocking once ``tier <= T``. An
# untagged event defaults to HARD, so it never moves unless explicitly marked easier.
EASY = 1
MEDIUM = 2
HARD = 3


@dataclass(frozen=True)
class Event:
    """A normalized calendar event. ``transparent`` mirrors Google's "shows me as free"."""

    start: datetime
    end: datetime
    status: EventStatus = EventStatus.CONFIRMED
    transparent: bool = False
    all_day: bool = False
    tier: int = HARD
    title: str = ""


def _is_blocking(event: Event, tentative_is_busy: bool, relax_threshold: int = 0) -> bool:
    if event.status == EventStatus.CANCELLED or event.transparent:
        return False
    if event.tier <= relax_threshold:  # the owner is willing to reschedule this one
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
    relax_threshold: int = 0,
) -> set[str]:
    """The set of grid slot ids in which the owner is free, given its events.

    ``relax_threshold`` frees the meetings the owner is willing to reschedule: any event whose
    reschedule ``tier`` is ``<= relax_threshold`` stops blocking. Because ``busy`` is a *union*
    over blocking events, a slot is free only when *every* event covering it has been relaxed --
    so availability grows monotonically with the threshold (round 1 ⊆ round 2 ⊆ round 3).
    """
    busy: set[int] = set()
    for event in events:
        if not _is_blocking(event, tentative_is_busy, relax_threshold):
            continue
        start, end = _busy_interval(event)
        busy |= grid.slots_covering(start, end)
    return {slot.slot_id for slot in grid.slots if slot.index not in busy}


def displaced_meetings(
    events: Iterable[Event],
    grid: TimeGrid,
    meeting_slot_ids: Iterable[str],
    *,
    relax_threshold: int,
    tentative_is_busy: bool = True,
) -> list[Event]:
    """The owner's own meetings that must move to hold a meeting on ``meeting_slot_ids``.

    A meeting is displaced when it is within the relaxed tier (``tier <= relax_threshold``), would
    otherwise block (it really occupied the slot), and overlaps the chosen meeting. Purely local to
    one calendar: no other party's data is ever involved, preserving the gated-access property.
    """
    target = set(meeting_slot_ids)
    displaced: list[Event] = []
    for event in events:
        if event.tier > relax_threshold:
            continue  # not something the owner offered to move this round
        if not _is_blocking(event, tentative_is_busy, relax_threshold=0):
            continue  # transparent/cancelled: never occupied the slot, so nothing to move
        start, end = _busy_interval(event)
        covered = {grid.slots[i].slot_id for i in grid.slots_covering(start, end)}
        if covered & target:
            displaced.append(event)
    return displaced
