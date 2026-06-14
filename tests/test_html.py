from datetime import UTC, datetime

from gated_scheduler.grid import TimeGrid
from gated_scheduler.scheduler import schedule_meeting
from gated_scheduler.sources.fixtures import FixtureCalendarSource
from gated_scheduler.viz.html import render_html


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
