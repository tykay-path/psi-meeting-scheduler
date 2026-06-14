from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from gated_scheduler.freebusy import (
    EASY,
    HARD,
    MEDIUM,
    Event,
    EventStatus,
    displaced_meetings,
    free_slots,
)
from gated_scheduler.grid import TimeGrid


def day_grid() -> TimeGrid:
    # 09:00, 10:00, 11:00 on Mon 2026-06-15
    return TimeGrid(
        start=datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
        slot_minutes=60,
    )


def ids(grid: TimeGrid, indices: list[int]) -> set[str]:
    return {grid.slots[i].slot_id for i in indices}


def test_no_events_means_all_slots_free() -> None:
    grid = day_grid()
    assert free_slots([], grid) == set(grid.slot_ids())


def test_confirmed_event_blocks_its_slots() -> None:
    grid = day_grid()
    event = Event(
        start=datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 11, 0, tzinfo=UTC),
    )
    assert free_slots([event], grid) == ids(grid, [2])


def test_tentative_is_busy_by_default_but_configurable() -> None:
    grid = day_grid()
    event = Event(
        start=datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
        status=EventStatus.TENTATIVE,
    )
    assert free_slots([event], grid) == ids(grid, [1, 2])
    assert free_slots([event], grid, tentative_is_busy=False) == set(grid.slot_ids())


def test_cancelled_event_is_ignored() -> None:
    grid = day_grid()
    event = Event(
        start=datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
        status=EventStatus.CANCELLED,
    )
    assert free_slots([event], grid) == set(grid.slot_ids())


def test_transparent_event_does_not_block() -> None:
    grid = day_grid()
    event = Event(
        start=datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
        transparent=True,
    )
    assert free_slots([event], grid) == set(grid.slot_ids())


def test_five_minute_event_makes_its_whole_slot_busy() -> None:
    grid = day_grid()
    event = Event(
        start=datetime(2026, 6, 15, 9, 5, tzinfo=UTC),
        end=datetime(2026, 6, 15, 9, 10, tzinfo=UTC),
    )
    assert free_slots([event], grid) == ids(grid, [1, 2])


def test_multiple_events_union() -> None:
    grid = day_grid()
    events = [
        Event(datetime(2026, 6, 15, 9, 0, tzinfo=UTC), datetime(2026, 6, 15, 10, 0, tzinfo=UTC)),
        Event(datetime(2026, 6, 15, 11, 0, tzinfo=UTC), datetime(2026, 6, 15, 12, 0, tzinfo=UTC)),
    ]
    assert free_slots(events, grid) == ids(grid, [1])


def test_event_outside_window_has_no_effect() -> None:
    grid = day_grid()
    event = Event(
        start=datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 14, 0, tzinfo=UTC),
    )
    assert free_slots([event], grid) == set(grid.slot_ids())


def test_non_utc_event_is_normalized() -> None:
    grid = day_grid()
    tz = ZoneInfo("Asia/Jerusalem")  # UTC+3 in June
    event = Event(
        start=datetime(2026, 6, 15, 12, 0, tzinfo=tz),  # 09:00 UTC
        end=datetime(2026, 6, 15, 13, 0, tzinfo=tz),  # 10:00 UTC
    )
    assert free_slots([event], grid) == ids(grid, [1, 2])


def test_all_day_event_blocks_the_whole_day() -> None:
    grid = TimeGrid(
        start=datetime(2026, 6, 15, 0, 0, tzinfo=UTC),
        end=datetime(2026, 6, 17, 0, 0, tzinfo=UTC),
        slot_minutes=60,
        working_hours=(9, 12),
    )
    # day 1 = indices 0,1,2 ; day 2 = indices 3,4,5
    event = Event(
        start=datetime(2026, 6, 15, 0, 0, tzinfo=UTC),
        end=datetime(2026, 6, 16, 0, 0, tzinfo=UTC),
        all_day=True,
    )
    assert free_slots([event], grid) == ids(grid, [3, 4, 5])


def test_all_day_event_with_degenerate_end_blocks_one_day() -> None:
    grid = TimeGrid(
        start=datetime(2026, 6, 15, 0, 0, tzinfo=UTC),
        end=datetime(2026, 6, 17, 0, 0, tzinfo=UTC),
        slot_minutes=60,
        working_hours=(9, 12),
    )
    event = Event(
        start=datetime(2026, 6, 15, 0, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 0, 0, tzinfo=UTC),  # same instant -> treat as one day
        all_day=True,
    )
    assert free_slots([event], grid) == ids(grid, [3, 4, 5])


# --- Part B: tiered relaxation -------------------------------------------------------------


def test_untagged_event_defaults_to_hard_and_never_frees() -> None:
    grid = day_grid()
    event = Event(
        start=datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
    )
    assert event.tier == HARD
    # even relaxing up to medium, an untagged (hard) meeting keeps its slot busy
    assert free_slots([event], grid, relax_threshold=MEDIUM) == ids(grid, [1, 2])


def test_easy_event_blocks_by_default_but_frees_when_relaxed() -> None:
    grid = day_grid()
    event = Event(
        start=datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
        tier=EASY,
        title="1:1 with Dana",
    )
    # round 1 (no relaxation): still busy
    assert free_slots([event], grid) == ids(grid, [1, 2])
    # round 2 (relax easy): the meeting is moved, slot frees
    assert free_slots([event], grid, relax_threshold=EASY) == set(grid.slot_ids())


def test_medium_event_frees_only_at_threshold_medium() -> None:
    grid = day_grid()
    event = Event(
        start=datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
        tier=MEDIUM,
    )
    assert free_slots([event], grid, relax_threshold=0) == ids(grid, [1, 2])
    assert free_slots([event], grid, relax_threshold=EASY) == ids(grid, [1, 2])
    assert free_slots([event], grid, relax_threshold=MEDIUM) == set(grid.slot_ids())


def test_slot_shared_by_easy_and_hard_stays_busy() -> None:
    grid = day_grid()
    # both events overlap the 09:00 slot (index 0)
    easy = Event(
        datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        datetime(2026, 6, 15, 9, 30, tzinfo=UTC),
        tier=EASY,
    )
    hard = Event(
        datetime(2026, 6, 15, 9, 30, tzinfo=UTC),
        datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
        tier=HARD,
    )
    # relaxing easy+medium still cannot free slot 0: the hard meeting never moves
    assert free_slots([easy, hard], grid, relax_threshold=MEDIUM) == ids(grid, [1, 2])


def test_relaxation_is_monotonic() -> None:
    grid = day_grid()
    events = [
        Event(
            datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
            datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
            tier=EASY,
        ),
        Event(
            datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
            datetime(2026, 6, 15, 11, 0, tzinfo=UTC),
            tier=MEDIUM,
        ),
        Event(
            datetime(2026, 6, 15, 11, 0, tzinfo=UTC),
            datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
            tier=HARD,
        ),
    ]
    f0 = free_slots(events, grid, relax_threshold=0)
    f1 = free_slots(events, grid, relax_threshold=EASY)
    f2 = free_slots(events, grid, relax_threshold=MEDIUM)
    assert f0 <= f1 <= f2  # availability only grows
    assert f0 == set()
    assert f1 == ids(grid, [0])
    assert f2 == ids(grid, [0, 1])  # hard event keeps slot 2 busy forever


def test_displaced_meetings_is_empty_when_nothing_is_relaxed() -> None:
    grid = day_grid()
    event = Event(
        datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
        tier=EASY,
        title="1:1",
    )
    assert displaced_meetings([event], grid, ids(grid, [0]), relax_threshold=0) == []


def test_displaced_meetings_returns_relaxed_events_overlapping_the_meeting() -> None:
    grid = day_grid()
    overlapping = Event(
        datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
        tier=EASY,
        title="1:1 with Dana",
    )
    elsewhere = Event(
        datetime(2026, 6, 15, 11, 0, tzinfo=UTC),
        datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
        tier=EASY,
        title="Gym",
    )
    hard_overlap = Event(
        datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
        tier=HARD,
        title="Board review",
    )
    displaced = displaced_meetings(
        [overlapping, elsewhere, hard_overlap], grid, ids(grid, [0]), relax_threshold=EASY
    )
    # only the easy meeting that actually overlaps the chosen slot is displaced
    assert displaced == [overlapping]
