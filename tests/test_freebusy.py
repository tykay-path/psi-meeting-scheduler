from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from gated_scheduler.freebusy import Event, EventStatus, free_slots
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
