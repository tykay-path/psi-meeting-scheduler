import random
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gated_scheduler.grid import TimeGrid
from gated_scheduler.matching import find_meeting
from gated_scheduler.scheduler import schedule_meeting, schedule_tiered, slots_for_duration
from gated_scheduler.sources.fixtures import FixtureCalendarSource

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def busy(start_h: int, end_h: int) -> dict[str, str]:
    return {
        "start": f"2026-06-15T{start_h:02d}:00:00+00:00",
        "end": f"2026-06-15T{end_h:02d}:00:00+00:00",
    }


def movable(start_h: int, end_h: int, tier: str, title: str = "") -> dict[str, str]:
    return {**busy(start_h, end_h), "reschedule": tier, "title": title}


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


# --- Part B: tiered relaxation in rounds ---------------------------------------------------


def test_tiered_match_in_round_one_needs_no_rescheduling() -> None:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {
            "Alice": {"events": [busy(11, 12)]},  # free 09, 10
            "Bob": {"events": [busy(9, 10)]},  # free 10, 11
            "Carol": {"events": [busy(9, 10), busy(11, 12)]},  # free 10
        }
    )
    result = schedule_tiered(source, grid, slots_needed=1)
    assert result.winning_index == 0
    assert result.relaxation_used == "no rescheduling"
    assert result.meeting is not None
    assert result.meeting.start == datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
    assert result.displaced_by_party == {}


def test_tiered_match_in_round_two_when_easy_meeting_is_freed() -> None:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {
            "Alice": {"events": [movable(10, 11, "easy", "1:1 with Dana")]},  # free 09,11 -> +10
            "Bob": {"events": [busy(9, 10), busy(11, 12)]},  # free 10
            "Carol": {"events": [busy(9, 10), busy(11, 12)]},  # free 10
        }
    )
    result = schedule_tiered(source, grid, slots_needed=1)
    assert result.winning_index == 1
    assert result.relaxation_used == "easy reschedules"
    assert result.meeting is not None
    assert result.meeting.start == datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
    # only Alice moves; Bob and Carol were already free at 10:00
    assert set(result.displaced_by_party) == {"Alice"}
    assert result.displaced_by_party["Alice"][0].title == "1:1 with Dana"


def test_tiered_match_in_round_three_needs_medium() -> None:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {
            "Alice": {"events": [movable(10, 11, "medium", "Team sync")]},
            "Bob": {"events": [busy(9, 10), busy(11, 12)]},
            "Carol": {"events": [busy(9, 10), busy(11, 12)]},
        }
    )
    result = schedule_tiered(source, grid, slots_needed=1)
    assert result.winning_index == 2
    assert result.relaxation_used == "easy + medium reschedules"
    assert result.meeting is not None
    assert result.meeting.start == datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
    assert set(result.displaced_by_party) == {"Alice"}


def test_tiered_impossible_when_even_medium_relaxation_fails() -> None:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {
            "Alice": {"events": [busy(10, 12)]},  # free 09 (hard)
            "Bob": {"events": [busy(9, 11)]},  # free 11 (hard)
        }
    )
    result = schedule_tiered(source, grid, slots_needed=1)
    assert result.winning_index is None
    assert result.meeting is None
    assert result.relaxation_used is None
    assert result.displaced_by_party == {}
    assert len(result.rounds) == 3  # all three rounds were attempted


def test_tiered_multiple_matches_in_a_round_pick_earliest() -> None:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {
            "Alice": {"events": [busy(11, 12)]},  # free 09, 10
            "Bob": {"events": [busy(11, 12)]},  # free 09, 10
        }
    )
    # common in round 1 = {09, 10}; earliest single slot wins
    result = schedule_tiered(source, grid, slots_needed=1)
    assert result.winning_index == 0
    assert result.meeting is not None
    assert result.meeting.start == datetime(2026, 6, 15, 9, 0, tzinfo=UTC)


def test_tiered_multi_person_sacrifice_in_round_two() -> None:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {
            "Alice": {"events": [movable(10, 11, "easy", "Alice 1:1")]},
            "Bob": {"events": [movable(10, 11, "easy", "Bob 1:1")]},
            "Carol": {"events": [busy(9, 10), busy(11, 12)]},  # free 10 already
        }
    )
    result = schedule_tiered(source, grid, slots_needed=1)
    assert result.winning_index == 1
    assert result.meeting is not None
    assert result.meeting.start == datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
    # both Alice and Bob give up an easy meeting; Carol moves nothing
    assert set(result.displaced_by_party) == {"Alice", "Bob"}
    assert result.displaced_by_party["Alice"][0].title == "Alice 1:1"
    assert result.displaced_by_party["Bob"][0].title == "Bob 1:1"


def test_tiered_stops_at_first_matching_round() -> None:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {
            "Alice": {"events": [movable(10, 11, "easy", "1:1")]},
            "Bob": {"events": [busy(9, 10), busy(11, 12)]},
            "Carol": {"events": [busy(9, 10), busy(11, 12)]},
        }
    )
    result = schedule_tiered(source, grid, slots_needed=1)
    assert result.winning_index == 1
    assert len(result.rounds) == 2  # round 3 never ran (no backtracking, stop at first match)
    assert result.rounds[0].result.meeting is None  # round 1 genuinely had no match


def test_every_round_keeps_only_the_intersection_in_cleartext() -> None:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {
            "Alice": {"events": [movable(10, 11, "medium", "Team sync")]},
            "Bob": {"events": [busy(9, 10), busy(11, 12)]},
            "Carol": {"events": [busy(9, 10), busy(11, 12)]},
        }
    )
    result = schedule_tiered(source, grid, slots_needed=1)
    assert result.winning_index == 2  # all three rounds ran
    for rnd in result.rounds:
        cleartext = rnd.result.psi.transcript.cleartext_messages()
        assert len(cleartext) <= 1  # at most the single final reveal
        for msg in cleartext:
            assert set(msg.payload_slots) == set(rnd.result.common_slot_ids)


def _random_event(h: int, tier: str) -> dict[str, str]:
    return {**busy(h, h + 1), "reschedule": tier}


_EVENTS = st.lists(
    st.builds(_random_event, st.integers(9, 12), st.sampled_from(["easy", "medium", "hard"])),
    max_size=3,
)


@settings(deadline=None, max_examples=50)
@given(a_events=_EVENTS, b_events=_EVENTS, slots_needed=st.integers(1, 2))
def test_tiered_psi_agrees_with_plain_intersection_oracle(
    a_events: list[dict[str, str]], b_events: list[dict[str, str]], slots_needed: int
) -> None:
    grid = grid_4_slots()
    source = FixtureCalendarSource({"Alice": {"events": a_events}, "Bob": {"events": b_events}})
    result = schedule_tiered(source, grid, slots_needed=slots_needed, rng=random.Random(0))

    # Oracle: the lowest round whose *plain* relaxed intersection yields a contiguous block.
    expected_idx = None
    expected_start = None
    for idx, threshold in enumerate([0, 1, 2]):
        common_ids = set(source.free_slots("Alice", grid, relax_threshold=threshold)) & set(
            source.free_slots("Bob", grid, relax_threshold=threshold)
        )
        common_slots = sorted(
            (grid.slots[i] for sid in common_ids if (i := grid.index_of(sid)) is not None),
            key=lambda s: s.start,
        )
        meeting = find_meeting(common_slots, slots_needed=slots_needed)
        if meeting is not None:
            expected_idx = idx
            expected_start = meeting.start
            break

    assert result.winning_index == expected_idx
    if expected_idx is not None:
        assert result.meeting is not None
        assert result.meeting.start == expected_start


# --- Part B: the shipped demo fixtures behave as documented ---------------------------------


def _workday_grid() -> TimeGrid:
    tz = ZoneInfo("Asia/Jerusalem")
    return TimeGrid(
        datetime(2026, 6, 15, 0, 0, tzinfo=tz),
        datetime(2026, 6, 16, 0, 0, tzinfo=tz),
        slot_minutes=60,
        working_hours=(9, 17),
        tz=tz,
    )


def _meeting_hour(result: object) -> int:
    return result.meeting.start.astimezone(ZoneInfo("Asia/Jerusalem")).hour  # type: ignore[attr-defined]


def test_reschedule_easy_fixture_matches_in_round_two() -> None:
    source = FixtureCalendarSource.from_file(FIXTURES_DIR / "reschedule_easy.json")
    result = schedule_tiered(source, _workday_grid(), slots_needed=1)
    assert result.winning_index == 1
    assert result.meeting is not None
    assert _meeting_hour(result) == 14
    assert set(result.displaced_by_party) == {"Alice"}


def test_reschedule_medium_fixture_matches_in_round_three() -> None:
    source = FixtureCalendarSource.from_file(FIXTURES_DIR / "reschedule_medium.json")
    result = schedule_tiered(source, _workday_grid(), slots_needed=1)
    assert result.winning_index == 2
    assert result.meeting is not None
    assert _meeting_hour(result) == 14
    assert set(result.displaced_by_party) == {"Alice"}


def test_multi_person_sacrifice_fixture_matches_in_round_two() -> None:
    source = FixtureCalendarSource.from_file(FIXTURES_DIR / "multi_person_sacrifice.json")
    result = schedule_tiered(source, _workday_grid(), slots_needed=1)
    assert result.winning_index == 1
    assert result.meeting is not None
    assert _meeting_hour(result) == 14
    assert set(result.displaced_by_party) == {"Alice", "Bob"}


def test_reschedule_impossible_fixture_finds_nothing() -> None:
    source = FixtureCalendarSource.from_file(FIXTURES_DIR / "reschedule_impossible.json")
    result = schedule_tiered(source, _workday_grid(), slots_needed=1)
    assert result.winning_index is None
    assert result.meeting is None
    assert result.displaced_by_party == {}
