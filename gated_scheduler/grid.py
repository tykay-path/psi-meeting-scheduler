"""The shared time grid: the public element universe for PSI.

All parties agree on this discretized set of candidate slots up front. It is public
structure and leaks nothing about anyone's calendar. PSI matches elements *exactly*, so the
grid is what gives every party a common vocabulary of slot identifiers.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo

_SLOT_ID_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _to_utc(dt: datetime) -> datetime:
    """Normalize any datetime to UTC. Naive datetimes are assumed to already be UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass(frozen=True)
class Slot:
    """One candidate slot on the grid. Times are tz-aware UTC; ``[start, end)`` is half-open."""

    index: int
    start: datetime
    end: datetime

    @property
    def slot_id(self) -> str:
        """The canonical, public identifier hashed into the PSI (UTC start instant)."""
        return self.start.astimezone(UTC).strftime(_SLOT_ID_FORMAT)


class TimeGrid:
    """An ordered set of fixed-width candidate slots over a date window."""

    def __init__(
        self,
        start: datetime,
        end: datetime,
        slot_minutes: int = 15,
        *,
        working_hours: tuple[int, int] | None = None,
        weekdays_only: bool = False,
        tz: tzinfo = UTC,
    ) -> None:
        if slot_minutes <= 0:
            raise ValueError("slot_minutes must be positive")
        if working_hours is not None and not 0 <= working_hours[0] < working_hours[1] <= 24:
            raise ValueError("working_hours must be (start_hour, end_hour) with start < end")
        self.slot_minutes = slot_minutes
        self.start = _to_utc(start)
        self.end = _to_utc(end)
        if self.end <= self.start:
            raise ValueError("end must be after start")
        self.tz = tz
        self.working_hours = working_hours
        self.weekdays_only = weekdays_only

        step = timedelta(minutes=slot_minutes)
        slots: list[Slot] = []
        cur = self.start
        index = 0
        while cur + step <= self.end:
            slot_end = cur + step
            if self._in_schedule(cur, slot_end):
                slots.append(Slot(index=index, start=cur, end=slot_end))
                index += 1
            cur = slot_end
        self._slots: list[Slot] = slots
        self._id_to_index: dict[str, int] = {s.slot_id: s.index for s in slots}

    def _in_schedule(self, start_utc: datetime, end_utc: datetime) -> bool:
        """Whether a candidate slot survives the weekday/working-hours mask (in ``self.tz``)."""
        if self.working_hours is None and not self.weekdays_only:
            return True
        local_start = start_utc.astimezone(self.tz)
        if self.weekdays_only and local_start.weekday() >= 5:
            return False
        if self.working_hours is not None:
            local_end = end_utc.astimezone(self.tz)
            wh_start, wh_end = self.working_hours
            work_start = local_start.replace(hour=wh_start, minute=0, second=0, microsecond=0)
            work_end = local_start.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
                hours=wh_end
            )
            if not (local_start >= work_start and local_end <= work_end):
                return False
        return True

    @property
    def slots(self) -> list[Slot]:
        return self._slots

    def __len__(self) -> int:
        return len(self._slots)

    def __iter__(self) -> Iterator[Slot]:
        return iter(self._slots)

    def slot_ids(self) -> list[str]:
        """All slot identifiers, in chronological order (the public universe)."""
        return [s.slot_id for s in self._slots]

    def index_of(self, slot_id: str) -> int | None:
        return self._id_to_index.get(slot_id)

    def slots_covering(self, start: datetime, end: datetime) -> set[int]:
        """Indices of slots that the half-open interval ``[start, end)`` overlaps at all.

        Any positive overlap counts (a 5-minute event makes its whole slot busy); an interval
        touching only a slot boundary does not cover the adjacent slot.
        """
        start = _to_utc(start)
        end = _to_utc(end)
        return {s.index for s in self._slots if s.start < end and start < s.end}
