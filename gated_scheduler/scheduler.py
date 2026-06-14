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

from gated_scheduler.freebusy import EASY, MEDIUM
from gated_scheduler.grid import TimeGrid
from gated_scheduler.matching import Meeting, find_meeting
from gated_scheduler.psi.primitives import random_scalar
from gated_scheduler.psi.protocol import Party, PsiOutcome, run_psi
from gated_scheduler.sources.base import CalendarSource, DisplacedMeeting


@dataclass
class ScheduleResult:
    meeting: Meeting | None
    grid: TimeGrid
    psi: PsiOutcome
    free_by_party: dict[str, frozenset[str]]  # ground truth, for illustration in the viz only

    @property
    def common_slot_ids(self) -> frozenset[str]:
        return self.psi.common_slot_ids


@dataclass
class RoundResult:
    """One relaxation round: the threshold used, a human label, and the round's PSI/match result."""

    relax_threshold: int
    label: str
    result: ScheduleResult


@dataclass
class TieredScheduleResult:
    """The outcome of escalating relaxation across rounds (Part B).

    ``rounds`` records every attempt in order; ``winning_index`` is the first that matched (or
    ``None`` if even the most-relaxed round failed). ``displaced_by_party`` maps each party that
    must reschedule to its own displaced meetings -- computed locally, never aggregated. The
    ``meeting``/``grid``/``psi``/``free_by_party`` shims point at the winning (or final) round so
    the CLI and viz can consume a tiered result wherever a single round used to flow.
    """

    rounds: list[RoundResult]
    winning_index: int | None
    displaced_by_party: dict[str, list[DisplacedMeeting]]

    @property
    def winning_round(self) -> RoundResult | None:
        return self.rounds[self.winning_index] if self.winning_index is not None else None

    @property
    def _shown(self) -> RoundResult:
        idx = self.winning_index if self.winning_index is not None else len(self.rounds) - 1
        return self.rounds[idx]

    @property
    def meeting(self) -> Meeting | None:
        return self._shown.result.meeting

    @property
    def grid(self) -> TimeGrid:
        return self._shown.result.grid

    @property
    def psi(self) -> PsiOutcome:
        return self._shown.result.psi

    @property
    def free_by_party(self) -> dict[str, frozenset[str]]:
        return self._shown.result.free_by_party

    @property
    def common_slot_ids(self) -> frozenset[str]:
        return self._shown.result.common_slot_ids

    @property
    def relaxation_used(self) -> str | None:
        return self.winning_round.label if self.winning_round is not None else None


def slots_for_duration(duration_minutes: int, grid: TimeGrid) -> int:
    """How many grid slots a meeting of ``duration_minutes`` needs (rounded up)."""
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive")
    return math.ceil(duration_minutes / grid.slot_minutes)


def _run_round(
    source: CalendarSource,
    grid: TimeGrid,
    party_ids: list[str],
    slots_needed: int,
    relax_threshold: int,
    rng: random.Random | None,
) -> ScheduleResult:
    """One PSI round at a fixed relaxation threshold -- the single-pass Part A flow."""
    free_by_party = {
        pid: frozenset(source.free_slots(pid, grid, relax_threshold=relax_threshold))
        for pid in party_ids
    }
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

    return ScheduleResult(meeting=meeting, grid=grid, psi=outcome, free_by_party=free_by_party)


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
    return _run_round(source, grid, party_ids, slots_needed, 0, rng)


_ROUNDS: tuple[tuple[int, str], ...] = (
    (0, "no rescheduling"),
    (EASY, "easy reschedules"),
    (MEDIUM, "easy + medium reschedules"),
)


def schedule_tiered(
    source: CalendarSource,
    grid: TimeGrid,
    *,
    slots_needed: int = 1,
    rng: random.Random | None = None,
) -> TieredScheduleResult:
    """Find a meeting by escalating relaxation in rounds; the first round that matches wins.

    Round 1 uses true free/busy; round 2 additionally frees ``easy`` meetings; round 3 also frees
    ``medium`` ones. Availability only grows, so the first match sacrifices only the cheapest tier
    that was necessary. Each round is an independent PSI run with fresh blinding keys -- the Part A
    core is reused unchanged.
    """
    party_ids = source.party_ids()
    if len(party_ids) < 2:
        raise ValueError("scheduling needs at least two parties")

    rounds: list[RoundResult] = []
    for threshold, label in _ROUNDS:
        result = _run_round(source, grid, party_ids, slots_needed, threshold, rng)
        rounds.append(RoundResult(relax_threshold=threshold, label=label, result=result))
        if result.meeting is not None:
            displaced = _displaced_by_party(source, grid, party_ids, result.meeting, threshold)
            return TieredScheduleResult(
                rounds=rounds, winning_index=len(rounds) - 1, displaced_by_party=displaced
            )
    return TieredScheduleResult(rounds=rounds, winning_index=None, displaced_by_party={})


def _displaced_by_party(
    source: CalendarSource,
    grid: TimeGrid,
    party_ids: list[str],
    meeting: Meeting,
    relax_threshold: int,
) -> dict[str, list[DisplacedMeeting]]:
    """What each party must move for ``meeting`` -- computed locally from its own calendar."""
    meeting_ids = {slot.slot_id for slot in meeting.slots}
    displaced: dict[str, list[DisplacedMeeting]] = {}
    for pid in party_ids:
        moved = source.displaced_meetings(pid, grid, meeting_ids, relax_threshold=relax_threshold)
        if moved:
            displaced[pid] = moved
    return displaced
