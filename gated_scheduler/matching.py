"""The deterministic matching core: contiguity + slot selection over an intersection.

PSI returns free *points*. "Are there N consecutive free slots?" is a separate check applied
to that result -- this module. It is pure and deterministic: no calendars, no crypto, no I/O.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from gated_scheduler.grid import Slot


@dataclass(frozen=True)
class Meeting:
    """A chosen meeting: a tuple of contiguous slots that works for everyone."""

    slots: tuple[Slot, ...]

    @property
    def start(self) -> datetime:
        return self.slots[0].start

    @property
    def end(self) -> datetime:
        return self.slots[-1].end


def contiguous_runs(free_slots: Iterable[Slot]) -> list[list[Slot]]:
    """Group free slots into maximal runs that are adjacent in *real time*.

    Index-adjacency is not enough: across an overnight or working-hours gap two slots can be
    consecutive in the grid yet not contiguous in time. We split on the time gap.
    """
    ordered = sorted(set(free_slots), key=lambda s: s.start)
    runs: list[list[Slot]] = []
    for slot in ordered:
        if runs and runs[-1][-1].end == slot.start:
            runs[-1].append(slot)
        else:
            runs.append([slot])
    return runs


Strategy = Callable[[list[list[Slot]], int], "Meeting | None"]


def earliest_block(runs: list[list[Slot]], slots_needed: int) -> Meeting | None:
    """Default selection rule: the earliest run long enough, taking its first N slots."""
    for run in runs:
        if len(run) >= slots_needed:
            return Meeting(slots=tuple(run[:slots_needed]))
    return None


def find_meeting(
    free_slots: Iterable[Slot],
    slots_needed: int = 1,
    *,
    strategy: Strategy = earliest_block,
) -> Meeting | None:
    """Find a meeting of ``slots_needed`` contiguous free slots, or ``None`` if impossible.

    ``slots_needed`` is a slot count (the duration->slots conversion lives upstream). The
    selection rule is pluggable; the default picks the earliest qualifying block.
    """
    if slots_needed < 1:
        raise ValueError("slots_needed must be >= 1")
    return strategy(contiguous_runs(free_slots), slots_needed)
