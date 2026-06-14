"""The orchestrator: wire the calendar seam to the PSI core to the matching core.

    [ CalendarSource ] -> free-slot sets -> [ PSI ] -> common slots -> [ matching ] -> meeting

Each party's free set is read only via the source (standing in for "that party's own agent
reads that party's own calendar"). In a real deployment each ``Party`` would live in its
owner's process; here a single process simulates them, and the PSI transcript -- not this
wiring -- is what proves no calendar is ever shared in the clear.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from gated_scheduler.grid import TimeGrid
from gated_scheduler.matching import Meeting, find_meeting
from gated_scheduler.psi.primitives import random_scalar
from gated_scheduler.psi.protocol import Party, PsiOutcome, run_psi
from gated_scheduler.sources.base import CalendarSource


@dataclass
class ScheduleResult:
    meeting: Meeting | None
    grid: TimeGrid
    psi: PsiOutcome
    free_by_party: dict[str, frozenset[str]]  # ground truth, for illustration in the viz only

    @property
    def common_slot_ids(self) -> frozenset[str]:
        return self.psi.common_slot_ids


def slots_for_duration(duration_minutes: int, grid: TimeGrid) -> int:
    """How many grid slots a meeting of ``duration_minutes`` needs (rounded up)."""
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive")
    return math.ceil(duration_minutes / grid.slot_minutes)


def schedule_meeting(
    source: CalendarSource,
    grid: TimeGrid,
    *,
    slots_needed: int = 1,
    rng: random.Random | None = None,
) -> ScheduleResult:
    """Find a meeting time everyone is free for, via multi-party PSI over the shared grid."""
    party_ids = source.party_ids()
    if len(party_ids) < 2:
        raise ValueError("scheduling needs at least two parties")

    free_by_party = {pid: frozenset(source.free_slots(pid, grid)) for pid in party_ids}
    parties = [
        Party(name=pid, key=random_scalar(), free_slot_ids=free_by_party[pid]) for pid in party_ids
    ]

    outcome = run_psi(parties, grid.slot_ids(), rng=rng)

    common_slots = sorted(
        (
            grid.slots[index]
            for sid in outcome.common_slot_ids
            if (index := grid.index_of(sid)) is not None
        ),
        key=lambda slot: slot.start,
    )
    meeting = find_meeting(common_slots, slots_needed=slots_needed)

    return ScheduleResult(
        meeting=meeting,
        grid=grid,
        psi=outcome,
        free_by_party=free_by_party,
    )
