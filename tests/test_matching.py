from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from gated_scheduler.grid import Slot, TimeGrid
from gated_scheduler.matching import Meeting, earliest_block, find_meeting


def make_grid(slots: int = 8, slot_minutes: int = 15) -> TimeGrid:
    start = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
    end = start + timedelta(minutes=slot_minutes * slots)
    return TimeGrid(start=start, end=end, slot_minutes=slot_minutes)


def pick(grid: TimeGrid, indices: list[int]) -> list[Slot]:
    return [grid.slots[i] for i in indices]


def test_empty_intersection_returns_none() -> None:
    assert find_meeting([], slots_needed=1) is None


def test_single_slot_meeting_returns_that_slot() -> None:
    grid = make_grid()
    result = find_meeting(pick(grid, [3]), slots_needed=1)
    assert result == Meeting(slots=(grid.slots[3],))
    assert result.start == grid.slots[3].start
    assert result.end == grid.slots[3].end


def test_picks_earliest_free_slot_for_single_slot_meeting() -> None:
    grid = make_grid()
    result = find_meeting(pick(grid, [5, 2, 7]), slots_needed=1)
    assert result is not None
    assert result.slots == (grid.slots[2],)


def test_three_isolated_slots_cannot_host_a_45_minute_meeting() -> None:
    # 0, 2, 4 are pairwise non-adjacent: no run of 3 contiguous slots exists
    grid = make_grid()
    assert find_meeting(pick(grid, [0, 2, 4]), slots_needed=3) is None


def test_three_consecutive_slots_host_a_45_minute_meeting() -> None:
    grid = make_grid()
    result = find_meeting(pick(grid, [0, 1, 2]), slots_needed=3)
    assert result is not None
    assert result.slots == (grid.slots[0], grid.slots[1], grid.slots[2])
    assert result.end - result.start == timedelta(minutes=45)


def test_picks_earliest_qualifying_run_skipping_too_short_one() -> None:
    grid = make_grid(slots=10)
    # run [1] is too short for a 2-slot meeting; run [4,5,6] qualifies
    result = find_meeting(pick(grid, [1, 4, 5, 6]), slots_needed=2)
    assert result is not None
    assert result.slots == (grid.slots[4], grid.slots[5])


def test_run_shorter_than_needed_returns_none() -> None:
    grid = make_grid()
    assert find_meeting(pick(grid, [2, 3]), slots_needed=3) is None


def test_accepts_unordered_input() -> None:
    grid = make_grid()
    result = find_meeting(pick(grid, [6, 5, 4]), slots_needed=3)
    assert result is not None
    assert result.slots == (grid.slots[4], grid.slots[5], grid.slots[6])


def test_day_boundary_gap_breaks_contiguity() -> None:
    # working-hours grid: last slot of day 1 and first of day 2 are index-consecutive
    # but NOT time-contiguous, so a 2-slot meeting cannot straddle the overnight gap
    grid = TimeGrid(
        start=datetime(2026, 6, 15, 0, 0, tzinfo=UTC),
        end=datetime(2026, 6, 17, 0, 0, tzinfo=UTC),
        slot_minutes=60,
        working_hours=(9, 11),  # 2 slots/day
    )
    # free: last slot of Mon (index 1) + first slot of Tue (index 2)
    assert find_meeting(pick(grid, [1, 2]), slots_needed=2) is None


def test_selection_strategy_is_pluggable() -> None:
    grid = make_grid(slots=10)
    free = pick(grid, [0, 1, 2, 6, 7, 8])

    def latest(runs: list[list[Slot]], n: int) -> Meeting | None:
        valid = [r for r in runs if len(r) >= n]
        return Meeting(slots=tuple(valid[-1][:n])) if valid else None

    assert find_meeting(free, slots_needed=2, strategy=earliest_block).slots == (
        grid.slots[0],
        grid.slots[1],
    )
    assert find_meeting(free, slots_needed=2, strategy=latest).slots == (
        grid.slots[6],
        grid.slots[7],
    )


# --- property-based testing ---


def _brute_force_earliest(free_slots: list[Slot], n: int) -> tuple[Slot, ...] | None:
    """Independent oracle: earliest maximal run with >= n slots, first n of it."""
    s = sorted(set(free_slots), key=lambda x: x.start)
    i = 0
    while i < len(s):
        run = [s[i]]
        j = i + 1
        while j < len(s) and s[j].start == run[-1].end:
            run.append(s[j])
            j += 1
        if len(run) >= n:
            return tuple(run[:n])
        i = j
    return None


@given(
    indices=st.sets(st.integers(min_value=0, max_value=31), min_size=0, max_size=32),
    n=st.integers(min_value=1, max_value=6),
)
def test_matches_brute_force_oracle(indices: set[int], n: int) -> None:
    grid = make_grid(slots=32)
    free = [grid.slots[i] for i in indices]
    result = find_meeting(free, slots_needed=n)
    expected = _brute_force_earliest(free, n)
    assert (result.slots if result else None) == expected


@given(
    indices=st.sets(st.integers(min_value=0, max_value=31), min_size=1, max_size=32),
    n=st.integers(min_value=1, max_value=6),
)
def test_result_invariants(indices: set[int], n: int) -> None:
    grid = make_grid(slots=32)
    free = [grid.slots[i] for i in indices]
    free_set = set(free)
    result = find_meeting(free, slots_needed=n)
    if result is None:
        return
    assert len(result.slots) == n
    assert all(s in free_set for s in result.slots)  # never schedules a busy slot
    for a, b in zip(result.slots, result.slots[1:], strict=False):  # contiguous in real time
        assert a.end == b.start
