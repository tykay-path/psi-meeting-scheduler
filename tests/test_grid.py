from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from gated_scheduler.grid import TimeGrid


def test_hour_window_15min_yields_four_slots() -> None:
    grid = TimeGrid(
        start=datetime(2026, 6, 15, 14, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 15, 0, tzinfo=UTC),
        slot_minutes=15,
    )
    slots = grid.slots
    assert len(slots) == 4
    assert grid.slot_minutes == 15
    assert slots[0].start == datetime(2026, 6, 15, 14, 0, tzinfo=UTC)
    assert slots[0].end == datetime(2026, 6, 15, 14, 15, tzinfo=UTC)
    assert slots[3].start == datetime(2026, 6, 15, 14, 45, tzinfo=UTC)
    assert slots[3].end == datetime(2026, 6, 15, 15, 0, tzinfo=UTC)
    assert [s.index for s in slots] == [0, 1, 2, 3]


def test_partial_trailing_window_is_truncated() -> None:
    # 50 minutes at 15-min granularity -> 3 whole slots, trailing 5 min dropped
    grid = TimeGrid(
        start=datetime(2026, 6, 15, 14, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 14, 50, tzinfo=UTC),
        slot_minutes=15,
    )
    assert len(grid) == 3
    assert grid.slots[-1].end == datetime(2026, 6, 15, 14, 45, tzinfo=UTC)


def test_slot_ids_are_canonical_utc_strings() -> None:
    grid = TimeGrid(
        start=datetime(2026, 6, 15, 14, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 14, 30, tzinfo=UTC),
        slot_minutes=15,
    )
    assert grid.slot_ids() == ["2026-06-15T14:00:00Z", "2026-06-15T14:15:00Z"]


def test_index_of_round_trips_slot_id() -> None:
    grid = TimeGrid(
        start=datetime(2026, 6, 15, 14, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 15, 0, tzinfo=UTC),
        slot_minutes=15,
    )
    for i, sid in enumerate(grid.slot_ids()):
        assert grid.index_of(sid) == i


def test_index_of_unknown_id_returns_none() -> None:
    grid = TimeGrid(
        start=datetime(2026, 6, 15, 14, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 15, 0, tzinfo=UTC),
        slot_minutes=15,
    )
    assert grid.index_of("1999-01-01T00:00:00Z") is None


def test_slots_covering_full_overlap_spans_multiple_slots() -> None:
    grid = TimeGrid(
        start=datetime(2026, 6, 15, 14, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 15, 0, tzinfo=UTC),
        slot_minutes=15,
    )
    covered = grid.slots_covering(
        datetime(2026, 6, 15, 14, 10, tzinfo=UTC),
        datetime(2026, 6, 15, 14, 40, tzinfo=UTC),
    )
    # touches [14:00-14:15], [14:15-14:30], [14:30-14:45]
    assert covered == {0, 1, 2}


def test_slots_covering_partial_overlap_marks_slot() -> None:
    # a 5-minute event inside one slot still makes that slot busy (conservative policy)
    grid = TimeGrid(
        start=datetime(2026, 6, 15, 14, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 15, 0, tzinfo=UTC),
        slot_minutes=15,
    )
    covered = grid.slots_covering(
        datetime(2026, 6, 15, 14, 5, tzinfo=UTC),
        datetime(2026, 6, 15, 14, 10, tzinfo=UTC),
    )
    assert covered == {0}


def test_slots_covering_is_half_open_at_boundary() -> None:
    # an event ending exactly at a slot boundary does not cover the next slot
    grid = TimeGrid(
        start=datetime(2026, 6, 15, 14, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 15, 0, tzinfo=UTC),
        slot_minutes=15,
    )
    covered = grid.slots_covering(
        datetime(2026, 6, 15, 14, 0, tzinfo=UTC),
        datetime(2026, 6, 15, 14, 15, tzinfo=UTC),
    )
    assert covered == {0}


def test_slots_covering_accepts_naive_and_nonutc_intervals() -> None:
    grid = TimeGrid(
        start=datetime(2026, 6, 15, 14, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 15, 0, tzinfo=UTC),
        slot_minutes=15,
    )
    # 17:20-17:25 in Asia/Jerusalem (UTC+3 in June) == 14:20-14:25 UTC -> slot 1
    tz = ZoneInfo("Asia/Jerusalem")
    covered = grid.slots_covering(
        datetime(2026, 6, 15, 17, 20, tzinfo=tz),
        datetime(2026, 6, 15, 17, 25, tzinfo=tz),
    )
    assert covered == {1}


def test_working_hours_mask_limits_slots_per_day() -> None:
    # 2026-06-15 is a Monday; window covers Mon + Tue, 09:00-12:00 -> 3 slots/day
    grid = TimeGrid(
        start=datetime(2026, 6, 15, 0, 0, tzinfo=UTC),
        end=datetime(2026, 6, 17, 0, 0, tzinfo=UTC),
        slot_minutes=60,
        working_hours=(9, 12),
    )
    assert len(grid) == 6
    assert grid.slots[0].start == datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
    assert grid.slots[2].end == datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    assert grid.slots[3].start == datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    assert grid.slots[5].end == datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    # indices stay sequential after masking
    assert [s.index for s in grid.slots] == [0, 1, 2, 3, 4, 5]


def test_weekends_excluded_when_weekdays_only() -> None:
    # Fri 06-19 through Mon 06-22; 09:00-10:00 -> one slot per weekday
    grid = TimeGrid(
        start=datetime(2026, 6, 19, 0, 0, tzinfo=UTC),
        end=datetime(2026, 6, 23, 0, 0, tzinfo=UTC),
        slot_minutes=60,
        working_hours=(9, 10),
        weekdays_only=True,
    )
    assert [s.start.date() for s in grid.slots] == [date(2026, 6, 19), date(2026, 6, 22)]


def test_working_hours_creates_time_gap_across_day_boundary() -> None:
    grid = TimeGrid(
        start=datetime(2026, 6, 15, 0, 0, tzinfo=UTC),
        end=datetime(2026, 6, 17, 0, 0, tzinfo=UTC),
        slot_minutes=60,
        working_hours=(9, 12),
    )
    # within a day, slots are time-contiguous
    assert grid.slots[0].end == grid.slots[1].start
    # across the overnight gap, consecutive slots are NOT time-contiguous
    assert grid.slots[2].end != grid.slots[3].start


def test_working_hours_respects_timezone() -> None:
    tz = ZoneInfo("Asia/Jerusalem")  # UTC+3 in June
    grid = TimeGrid(
        start=datetime(2026, 6, 15, 0, 0, tzinfo=UTC),
        end=datetime(2026, 6, 16, 0, 0, tzinfo=UTC),
        slot_minutes=60,
        working_hours=(9, 10),
        tz=tz,
    )
    assert len(grid) == 1
    # 09:00 in UTC+3 == 06:00 UTC
    assert grid.slots[0].start == datetime(2026, 6, 15, 6, 0, tzinfo=UTC)
