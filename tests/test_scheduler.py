from datetime import UTC, datetime

import pytest

from gated_scheduler.grid import TimeGrid
from gated_scheduler.scheduler import schedule_meeting, slots_for_duration
from gated_scheduler.sources.fixtures import FixtureCalendarSource


def busy(start_h: int, end_h: int) -> dict[str, str]:
    return {
        "start": f"2026-06-15T{start_h:02d}:00:00+00:00",
        "end": f"2026-06-15T{end_h:02d}:00:00+00:00",
    }


def grid_3_slots() -> TimeGrid:
    # 09:00, 10:00, 11:00
    return TimeGrid(
        start=datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
        slot_minutes=60,
    )


def grid_4_slots() -> TimeGrid:
    # 09:00, 10:00, 11:00, 12:00
    return TimeGrid(
        start=datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
        slot_minutes=60,
    )


def test_single_common_slot_is_scheduled() -> None:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {
            "Alice": {"events": [busy(11, 12)]},  # free 09, 10
            "Bob": {"events": [busy(9, 10)]},  # free 10, 11
            "Carol": {"events": [busy(9, 10), busy(11, 12)]},  # free 10
        }
    )
    result = schedule_meeting(source, grid, slots_needed=1)
    assert result.common_slot_ids == {grid.slots[1].slot_id}
    assert result.meeting is not None
    assert result.meeting.start == datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
    assert result.meeting.end == datetime(2026, 6, 15, 11, 0, tzinfo=UTC)


def test_multi_slot_meeting_needs_contiguous_common_slots() -> None:
    grid = grid_4_slots()
    source = FixtureCalendarSource(
        {
            "Alice": {"events": [busy(12, 13)]},  # free 09,10,11
            "Bob": {"events": [busy(9, 10)]},  # free 10,11,12
        }
    )
    # common = {10, 11}; a 2-slot meeting fits at 10:00-12:00
    result = schedule_meeting(source, grid, slots_needed=2)
    assert result.common_slot_ids == {grid.slots[1].slot_id, grid.slots[2].slot_id}
    assert result.meeting is not None
    assert result.meeting.start == datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
    assert result.meeting.end == datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def test_no_common_slot_yields_no_meeting() -> None:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {
            "Alice": {"events": [busy(10, 12)]},  # free 09
            "Bob": {"events": [busy(9, 11)]},  # free 11
        }
    )
    result = schedule_meeting(source, grid, slots_needed=1)
    assert result.common_slot_ids == set()
    assert result.meeting is None


def test_meeting_too_long_for_common_block_yields_no_meeting() -> None:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {
            "Alice": {"events": [busy(11, 12)]},  # free 09,10
            "Bob": {"events": [busy(9, 10)]},  # free 10,11
        }
    )
    # common = {10} only -> a 2-slot meeting cannot fit
    result = schedule_meeting(source, grid, slots_needed=2)
    assert result.common_slot_ids == {grid.slots[1].slot_id}
    assert result.meeting is None


def test_result_exposes_ground_truth_free_sets_for_the_viz() -> None:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {"Alice": {"events": [busy(11, 12)]}, "Bob": {"events": [busy(9, 10)]}}
    )
    result = schedule_meeting(source, grid, slots_needed=1)
    assert result.free_by_party["Alice"] == {grid.slots[0].slot_id, grid.slots[1].slot_id}
    assert result.free_by_party["Bob"] == {grid.slots[1].slot_id, grid.slots[2].slot_id}


def test_transcript_is_available_and_only_result_is_cleartext() -> None:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {"Alice": {"events": [busy(11, 12)]}, "Bob": {"events": [busy(9, 10)]}}
    )
    result = schedule_meeting(source, grid, slots_needed=1)
    assert len(result.psi.transcript) > 0
    cleartext = result.psi.transcript.cleartext_messages()
    assert len(cleartext) == 1


def test_requires_at_least_two_parties() -> None:
    grid = grid_3_slots()
    source = FixtureCalendarSource({"Alice": {"events": []}})
    with pytest.raises(ValueError):
        schedule_meeting(source, grid, slots_needed=1)


def test_slots_for_duration_rounds_up() -> None:
    grid = TimeGrid(
        start=datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 17, 0, tzinfo=UTC),
        slot_minutes=15,
    )
    assert slots_for_duration(45, grid) == 3
    assert slots_for_duration(50, grid) == 4  # rounds up
    assert slots_for_duration(15, grid) == 1
    with pytest.raises(ValueError):
        slots_for_duration(0, grid)
