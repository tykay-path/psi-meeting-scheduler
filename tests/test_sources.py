import json
from datetime import UTC, datetime

import pytest

from gated_scheduler.grid import TimeGrid
from gated_scheduler.sources.base import CalendarSource
from gated_scheduler.sources.fixtures import FixtureCalendarSource
from gated_scheduler.sources.google import GoogleCalendarSource


def day_grid() -> TimeGrid:
    return TimeGrid(
        start=datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
        slot_minutes=60,
    )


def ids(grid: TimeGrid, indices: list[int]) -> set[str]:
    return {grid.slots[i].slot_id for i in indices}


def test_fixture_source_is_a_calendar_source() -> None:
    assert isinstance(FixtureCalendarSource({}), CalendarSource)


def test_party_ids_are_sorted() -> None:
    src = FixtureCalendarSource({"Bob": {"events": []}, "Alice": {"events": []}})
    assert src.party_ids() == ["Alice", "Bob"]


def test_free_slots_with_explicit_offset_event() -> None:
    grid = day_grid()
    src = FixtureCalendarSource(
        {
            "Alice": {
                "events": [
                    {"start": "2026-06-15T09:00:00+00:00", "end": "2026-06-15T10:00:00+00:00"}
                ]
            }
        }
    )
    assert src.free_slots("Alice", grid) == ids(grid, [1, 2])


def test_naive_datetimes_use_party_timezone() -> None:
    grid = day_grid()
    src = FixtureCalendarSource(
        {
            "Carol": {
                "timezone": "Asia/Jerusalem",  # UTC+3 in June
                # 12:00-13:00 local == 09:00-10:00 UTC -> blocks the 09:00 slot
                "events": [{"start": "2026-06-15T12:00:00", "end": "2026-06-15T13:00:00"}],
            }
        }
    )
    assert src.free_slots("Carol", grid) == ids(grid, [1, 2])


def test_tentative_event_busy_by_default_and_configurable() -> None:
    grid = day_grid()
    data = {
        "Eve": {
            "events": [
                {
                    "start": "2026-06-15T09:00:00+00:00",
                    "end": "2026-06-15T10:00:00+00:00",
                    "status": "tentative",
                }
            ]
        }
    }
    assert FixtureCalendarSource(data).free_slots("Eve", grid) == ids(grid, [1, 2])
    assert FixtureCalendarSource(data, tentative_is_busy=False).free_slots("Eve", grid) == set(
        grid.slot_ids()
    )


def test_transparent_event_does_not_block() -> None:
    grid = day_grid()
    src = FixtureCalendarSource(
        {
            "Frank": {
                "events": [
                    {
                        "start": "2026-06-15T09:00:00+00:00",
                        "end": "2026-06-15T12:00:00+00:00",
                        "transparent": True,
                    }
                ]
            }
        }
    )
    assert src.free_slots("Frank", grid) == set(grid.slot_ids())


def test_all_day_event_via_date_field_blocks_the_day() -> None:
    grid = TimeGrid(
        start=datetime(2026, 6, 15, 0, 0, tzinfo=UTC),
        end=datetime(2026, 6, 17, 0, 0, tzinfo=UTC),
        slot_minutes=60,
        working_hours=(9, 12),
    )
    src = FixtureCalendarSource({"Dan": {"events": [{"date": "2026-06-15", "all_day": True}]}})
    assert src.free_slots("Dan", grid) == ids(grid, [3, 4, 5])


def test_from_file_loads_json(tmp_path) -> None:
    data = {
        "Alice": {
            "events": [{"start": "2026-06-15T09:00:00+00:00", "end": "2026-06-15T10:00:00+00:00"}]
        }
    }
    path = tmp_path / "calendars.json"
    path.write_text(json.dumps(data))
    src = FixtureCalendarSource.from_file(path)
    assert src.party_ids() == ["Alice"]
    assert src.free_slots("Alice", day_grid()) == ids(day_grid(), [1, 2])


def test_unknown_party_raises() -> None:
    src = FixtureCalendarSource({"Alice": {"events": []}})
    with pytest.raises(KeyError):
        src.free_slots("Nobody", day_grid())


def test_google_source_is_a_documented_stub() -> None:
    src = GoogleCalendarSource()
    assert isinstance(src, CalendarSource)
    with pytest.raises(NotImplementedError):
        src.party_ids()
    with pytest.raises(NotImplementedError):
        src.free_slots("Alice", day_grid())
