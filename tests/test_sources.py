import json
from datetime import UTC, datetime

import pytest

from gated_scheduler.freebusy import EASY, HARD, MEDIUM, EventStatus
from gated_scheduler.freebusy import free_slots as derive_free_slots
from gated_scheduler.grid import TimeGrid
from gated_scheduler.sources.base import CalendarSource, DisplacedMeeting
from gated_scheduler.sources.fixtures import FixtureCalendarSource
from gated_scheduler.sources.google import GoogleCalendarSource, _event_from_google


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


# --- Google Calendar source -----------------------------------------------------------------


class FakeCalendarClient:
    """A stand-in for the Google API client: returns hand-built Google-shaped dicts.

    Mirrors the ``CalendarClient`` protocol (``freebusy`` / ``list_events``) without any network,
    so the source's mapping logic is exercised directly.
    """

    def __init__(
        self,
        *,
        freebusy_by_cal: dict[str, list[dict]] | None = None,
        events_by_cal: dict[str, list[dict]] | None = None,
    ) -> None:
        self._freebusy = freebusy_by_cal or {}
        self._events = events_by_cal or {}
        self.freebusy_calls: list[str] = []
        self.events_calls: list[str] = []

    def freebusy(self, calendar_id: str, time_min: datetime, time_max: datetime) -> list[dict]:
        self.freebusy_calls.append(calendar_id)
        return self._freebusy.get(calendar_id, [])

    def list_events(self, calendar_id: str, time_min: datetime, time_max: datetime) -> list[dict]:
        self.events_calls.append(calendar_id)
        return self._events.get(calendar_id, [])


def _timed_event(start: str, end: str, **extra: object) -> dict:
    return {"start": {"dateTime": start}, "end": {"dateTime": end}, **extra}


def _easy_events_client() -> FakeCalendarClient:
    """One easy-tier 09:00-10:00 meeting, exposed both as free/busy and as event detail."""
    busy = [{"start": "2026-06-15T09:00:00Z", "end": "2026-06-15T10:00:00Z"}]
    event = _timed_event(
        "2026-06-15T09:00:00+00:00",
        "2026-06-15T10:00:00+00:00",
        summary="1:1 with Dana",
        extendedProperties={"private": {"reschedule": "easy"}},
    )
    return FakeCalendarClient(
        freebusy_by_cal={"alice@x.com": busy}, events_by_cal={"alice@x.com": [event]}
    )


def test_google_source_is_a_calendar_source() -> None:
    assert isinstance(GoogleCalendarSource(FakeCalendarClient(), []), CalendarSource)


def test_google_party_ids_are_sorted_calendar_ids() -> None:
    src = GoogleCalendarSource(FakeCalendarClient(), ["bob@x.com", "alice@x.com"])
    assert src.party_ids() == ["alice@x.com", "bob@x.com"]


def test_google_free_slots_uses_freebusy_for_round_one() -> None:
    grid = day_grid()
    client = FakeCalendarClient(
        freebusy_by_cal={
            "alice@x.com": [{"start": "2026-06-15T09:00:00Z", "end": "2026-06-15T10:00:00Z"}]
        }
    )
    src = GoogleCalendarSource(client, ["alice@x.com"])
    assert src.free_slots("alice@x.com", grid) == ids(grid, [1, 2])
    assert client.freebusy_calls == ["alice@x.com"]
    assert client.events_calls == []  # round 1 never reads event detail


def test_google_free_slots_uses_events_when_relaxing() -> None:
    grid = day_grid()
    client = _easy_events_client()
    src = GoogleCalendarSource(client, ["alice@x.com"])
    # relaxing easy meetings frees the 09:00 slot via the events path
    assert src.free_slots("alice@x.com", grid, relax_threshold=EASY) == set(grid.slot_ids())
    assert client.events_calls == ["alice@x.com"]  # relaxation reads own-calendar detail


def test_google_free_slots_monotonic_across_thresholds() -> None:
    grid = day_grid()
    src = GoogleCalendarSource(_easy_events_client(), ["alice@x.com"])
    round0 = src.free_slots("alice@x.com", grid, relax_threshold=0)
    round_easy = src.free_slots("alice@x.com", grid, relax_threshold=EASY)
    assert round0 == ids(grid, [1, 2])  # easy meeting still blocks at threshold 0
    assert round0 <= round_easy  # availability only grows


def test_google_freebusy_and_events_agree_at_threshold_zero() -> None:
    """The hybrid seam: the same meeting must yield the same free set either way at threshold 0.

    The free/busy path (round 1) and the events path (relaxation rounds) describe the same
    calendar; if they disagreed at threshold 0, monotonicity across rounds would break.
    """
    grid = day_grid()
    client = _easy_events_client()
    # free/busy path (what round 1 uses)
    via_freebusy = GoogleCalendarSource(client, ["alice@x.com"]).free_slots(
        "alice@x.com", grid, relax_threshold=0
    )
    # events path at threshold 0: derive directly from the mapped events
    raw_events = client.list_events("alice@x.com", grid.start, grid.end)
    events = [_event_from_google(raw) for raw in raw_events]
    via_events = derive_free_slots(events, grid, relax_threshold=0)
    assert via_freebusy == via_events


def test_google_displaced_meetings_reports_title_and_tier() -> None:
    grid = day_grid()
    src = GoogleCalendarSource(_easy_events_client(), ["alice@x.com"])
    chosen = ids(grid, [0])  # the 09:00 slot
    displaced = src.displaced_meetings("alice@x.com", grid, chosen, relax_threshold=EASY)
    assert len(displaced) == 1
    moved = displaced[0]
    assert isinstance(moved, DisplacedMeeting)
    assert moved.title == "1:1 with Dana"
    assert moved.tier == EASY
    assert moved.start == datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
    # relaxing nothing displaces nothing
    assert src.displaced_meetings("alice@x.com", grid, chosen, relax_threshold=0) == []


def test_google_unknown_reschedule_tier_raises() -> None:
    grid = day_grid()
    client = FakeCalendarClient(
        events_by_cal={
            "alice@x.com": [
                _timed_event(
                    "2026-06-15T09:00:00+00:00",
                    "2026-06-15T10:00:00+00:00",
                    extendedProperties={"private": {"reschedule": "sometimes"}},
                )
            ]
        }
    )
    src = GoogleCalendarSource(client, ["alice@x.com"])
    with pytest.raises(ValueError):
        src.free_slots("alice@x.com", grid, relax_threshold=EASY)


# --- Google event mapping (_event_from_google) ----------------------------------------------
# The source's only real job is mapping a Google event resource to a freebusy.Event; the event
# *semantics* (blocking, relaxation) are already proven by freebusy's own tests.


def test_map_timed_event_with_tier_and_title() -> None:
    event = _event_from_google(
        _timed_event(
            "2026-06-15T09:00:00+00:00",
            "2026-06-15T10:00:00+00:00",
            summary="1:1 with Dana",
            extendedProperties={"private": {"reschedule": "medium"}},
        )
    )
    assert event.start == datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
    assert event.end == datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
    assert event.tier == MEDIUM
    assert event.title == "1:1 with Dana"


def test_map_untagged_event_defaults_to_hard() -> None:
    event = _event_from_google(
        _timed_event("2026-06-15T09:00:00+00:00", "2026-06-15T10:00:00+00:00")
    )
    assert event.tier == HARD
    assert event.title == ""


def test_map_cancelled_status() -> None:
    event = _event_from_google(
        _timed_event("2026-06-15T09:00:00+00:00", "2026-06-15T10:00:00+00:00", status="cancelled")
    )
    assert event.status == EventStatus.CANCELLED


def test_map_tentative_status() -> None:
    event = _event_from_google(
        _timed_event("2026-06-15T09:00:00+00:00", "2026-06-15T10:00:00+00:00", status="tentative")
    )
    assert event.status == EventStatus.TENTATIVE


def test_map_transparent_event() -> None:
    event = _event_from_google(
        _timed_event(
            "2026-06-15T09:00:00+00:00", "2026-06-15T10:00:00+00:00", transparency="transparent"
        )
    )
    assert event.transparent is True


def test_map_opaque_event_is_not_transparent() -> None:
    event = _event_from_google(
        _timed_event(
            "2026-06-15T09:00:00+00:00", "2026-06-15T10:00:00+00:00", transparency="opaque"
        )
    )
    assert event.transparent is False


def test_map_all_day_event() -> None:
    event = _event_from_google({"start": {"date": "2026-06-15"}, "end": {"date": "2026-06-16"}})
    assert event.all_day is True
    assert event.start == datetime(2026, 6, 15, 0, 0, tzinfo=UTC)
    assert event.end == datetime(2026, 6, 16, 0, 0, tzinfo=UTC)


def test_map_unknown_tier_raises() -> None:
    with pytest.raises(ValueError):
        _event_from_google(
            _timed_event(
                "2026-06-15T09:00:00+00:00",
                "2026-06-15T10:00:00+00:00",
                extendedProperties={"private": {"reschedule": "sometimes"}},
            )
        )



# --- Part B: tier parsing, relaxation, and displaced meetings ------------------------------


def _easy_meeting_source() -> FixtureCalendarSource:
    return FixtureCalendarSource(
        {
            "Alice": {
                "events": [
                    {
                        "start": "2026-06-15T09:00:00+00:00",
                        "end": "2026-06-15T10:00:00+00:00",
                        "reschedule": "easy",
                        "title": "1:1 with Dana",
                    }
                ]
            }
        }
    )


def test_free_slots_honors_relax_threshold() -> None:
    grid = day_grid()
    src = _easy_meeting_source()
    assert src.free_slots("Alice", grid) == ids(grid, [1, 2])  # round 1: easy meeting still blocks
    assert src.free_slots("Alice", grid, relax_threshold=EASY) == set(grid.slot_ids())  # freed


def test_untagged_event_defaults_to_hard_in_fixtures() -> None:
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
    assert src.free_slots("Alice", grid, relax_threshold=MEDIUM) == ids(grid, [1, 2])


def test_displaced_meetings_reports_moved_meeting_with_title_and_tier() -> None:
    grid = day_grid()
    src = _easy_meeting_source()
    chosen = ids(grid, [0])  # the 09:00 slot
    displaced = src.displaced_meetings("Alice", grid, chosen, relax_threshold=EASY)
    assert len(displaced) == 1
    moved = displaced[0]
    assert isinstance(moved, DisplacedMeeting)
    assert moved.title == "1:1 with Dana"
    assert moved.tier == EASY
    assert moved.start == datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
    # nothing is displaced when we relax nothing
    assert src.displaced_meetings("Alice", grid, chosen, relax_threshold=0) == []


def test_unknown_reschedule_tier_raises() -> None:
    grid = day_grid()
    src = FixtureCalendarSource(
        {
            "Alice": {
                "events": [
                    {
                        "start": "2026-06-15T09:00:00+00:00",
                        "end": "2026-06-15T10:00:00+00:00",
                        "reschedule": "sometimes",
                    }
                ]
            }
        }
    )
    with pytest.raises(ValueError):
        src.free_slots("Alice", grid)


def test_has_reschedulable_meetings_reflects_tags() -> None:
    untagged = FixtureCalendarSource(
        {
            "Alice": {
                "events": [
                    {"start": "2026-06-15T09:00:00+00:00", "end": "2026-06-15T10:00:00+00:00"}
                ]
            }
        }
    )
    tagged = FixtureCalendarSource(
        {
            "Alice": {
                "events": [
                    {
                        "start": "2026-06-15T09:00:00+00:00",
                        "end": "2026-06-15T10:00:00+00:00",
                        "reschedule": "easy",
                    }
                ]
            }
        }
    )
    assert untagged.has_reschedulable_meetings() is False
    assert tagged.has_reschedulable_meetings() is True
