from datetime import UTC, datetime

from gated_scheduler.grid import TimeGrid
from gated_scheduler.scheduler import schedule_meeting, schedule_tiered
from gated_scheduler.sources.fixtures import FixtureCalendarSource
from gated_scheduler.viz.html import render_html


def _ev(s: int, e: int, **extra: object) -> dict[str, object]:
    return {
        "start": f"2026-06-15T{s:02d}:00:00+00:00",
        "end": f"2026-06-15T{e:02d}:00:00+00:00",
        **extra,
    }


def tiered_easy() -> object:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {
            "Alice": {"events": [_ev(10, 11, reschedule="easy", title="1:1 with Ben")]},
            "Bob": {"events": [_ev(9, 10), _ev(11, 12)]},
            "Carol": {"events": [_ev(9, 10), _ev(11, 12)]},
        }
    )
    return schedule_tiered(source, grid, slots_needed=1)


def grid_3_slots() -> TimeGrid:
    return TimeGrid(
        start=datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        end=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
        slot_minutes=60,
    )


def scheduled() -> object:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {
            "Alice": {
                "events": [
                    {"start": "2026-06-15T11:00:00+00:00", "end": "2026-06-15T12:00:00+00:00"}
                ]
            },
            "Bob": {
                "events": [
                    {"start": "2026-06-15T09:00:00+00:00", "end": "2026-06-15T10:00:00+00:00"}
                ]
            },
        }
    )
    return schedule_meeting(source, grid, slots_needed=1)


def test_render_returns_full_html_document() -> None:
    html = render_html(scheduled())
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "</html>" in html


def test_html_lists_each_party() -> None:
    html = render_html(scheduled())
    assert "Alice" in html
    assert "Bob" in html


def test_html_shows_the_chosen_meeting() -> None:
    html = render_html(scheduled())
    assert "10:00" in html  # the common slot


def test_html_reports_when_no_slot_exists() -> None:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {
            "Alice": {
                "events": [
                    {"start": "2026-06-15T10:00:00+00:00", "end": "2026-06-15T12:00:00+00:00"}
                ]
            },
            "Bob": {
                "events": [
                    {"start": "2026-06-15T09:00:00+00:00", "end": "2026-06-15T11:00:00+00:00"}
                ]
            },
        }
    )
    html = render_html(schedule_meeting(source, grid, slots_needed=1))
    assert "no common" in html.lower()


def test_html_includes_the_protocol_trace() -> None:
    html = render_html(scheduled())
    assert "Combiner" in html
    assert "Output" in html


def test_html_labels_ground_truth_as_illustration_only() -> None:
    html = render_html(scheduled())
    assert "illustration" in html.lower()


def test_html_is_self_contained_no_external_resources() -> None:
    html = render_html(scheduled())
    assert "http://" not in html
    assert "https://" not in html


def test_html_escapes_party_names() -> None:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {
            "<script>evil</script>": {"events": []},
            "Bob": {"events": []},
        }
    )
    html = render_html(schedule_meeting(source, grid, slots_needed=1))
    assert "<script>evil</script>" not in html
    assert "&lt;script&gt;" in html


def test_tiered_html_is_full_document_with_rounds_and_winner() -> None:
    html = render_html(tiered_easy())
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "</html>" in html
    assert "Round 1" in html and "Round 2" in html
    assert "10:00" in html  # the chosen slot
    assert "easy" in html.lower()  # the flexibility level reached


def test_tiered_html_lists_displaced_meetings() -> None:
    html = render_html(tiered_easy())
    assert "1:1 with Ben" in html
    assert "Alice" in html
    assert "illustration" in html.lower()


def test_tiered_html_includes_trace_and_is_self_contained() -> None:
    html = render_html(tiered_easy())
    assert "Combiner" in html and "Output" in html
    assert "http://" not in html and "https://" not in html


def test_tiered_html_reports_impossible() -> None:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {
            "Alice": {"events": [_ev(9, 12)]},  # booked solid, immovable
            "Bob": {"events": [_ev(9, 12, reschedule="easy", title="Focus")]},
        }
    )
    html = render_html(schedule_tiered(source, grid, slots_needed=1))
    assert "no meeting" in html.lower()


def test_tiered_html_escapes_party_names() -> None:
    grid = grid_3_slots()
    source = FixtureCalendarSource(
        {
            "<script>evil</script>": {"events": [_ev(10, 11, reschedule="easy", title="x")]},
            "Bob": {"events": []},
        }
    )
    html = render_html(schedule_tiered(source, grid, slots_needed=1))
    assert "<script>evil</script>" not in html
