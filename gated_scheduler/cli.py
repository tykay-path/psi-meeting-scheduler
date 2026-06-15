"""Command-line entry point: run the scheduler over fixture calendars and show the result.

Prints a readable protocol trace (proving only blinded points travel until the final reveal)
plus the chosen meeting, and optionally writes the self-contained HTML report.
"""

from __future__ import annotations

import argparse
import random
import sys
import webbrowser
from datetime import datetime, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from gated_scheduler.freebusy import EASY, HARD, MEDIUM
from gated_scheduler.grid import TimeGrid
from gated_scheduler.psi.channel import Transcript
from gated_scheduler.scheduler import (
    ScheduleResult,
    TieredScheduleResult,
    schedule_meeting,
    schedule_tiered,
    slots_for_duration,
)
from gated_scheduler.sources.base import CalendarSource
from gated_scheduler.sources.fixtures import FixtureCalendarSource
from gated_scheduler.sources.google import CalendarClient, GoogleCalendarSource, build_google_client
from gated_scheduler.viz.html import render_html

_TIER_LABELS = {EASY: "easy", MEDIUM: "medium", HARD: "hard"}


class _SourceError(Exception):
    """A user-facing problem building the calendar source (bad flags, missing file)."""


def _load_google_client(credentials: str) -> CalendarClient:
    """Load Google credentials from a JSON path and build a live client.

    Isolated behind one function so tests can monkeypatch it with a fake (no network, no creds),
    and so the optional ``google`` dependency is imported only when actually scheduling live.
    """
    try:
        from google.oauth2.service_account import (  # noqa: PLC0415  (lazy: optional dependency)
            Credentials,
        )
    except ImportError as error:  # pragma: no cover - exercised only without the extra installed
        raise _SourceError(
            "Google support requires the 'google' extra: pip install 'gated-scheduler[google]'"
        ) from error

    scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
    creds = Credentials.from_service_account_file(credentials, scopes=scopes)
    return build_google_client(creds)


def _build_source(args: argparse.Namespace) -> CalendarSource:
    if args.source == "google":
        if not args.calendars:
            raise _SourceError("--source google requires --calendars (comma-separated ids)")
        if not args.credentials:
            raise _SourceError("--source google requires --credentials (path to JSON)")
        calendar_ids = [c.strip() for c in args.calendars.split(",") if c.strip()]
        client = _load_google_client(args.credentials)
        return GoogleCalendarSource(
            client, calendar_ids, tentative_is_busy=not args.tentative_free
        )

    if not args.fixtures:
        raise _SourceError("--source fixtures requires --fixtures (path to JSON)")
    fixtures = Path(args.fixtures)
    if not fixtures.exists():
        raise _SourceError(f"fixtures file not found: {fixtures}")
    return FixtureCalendarSource.from_file(fixtures, tentative_is_busy=not args.tentative_free)


def _fmt(dt: datetime, tz: tzinfo) -> str:
    return dt.astimezone(tz).strftime("%a %b %d, %H:%M")


def _parse_window(value: str, tz: tzinfo) -> tuple[datetime, datetime]:
    if value.count("..") != 1:
        raise ValueError("--window must be START..END (e.g. 2026-06-15..2026-06-26)")
    start_s, end_s = value.split("..")
    start = datetime.fromisoformat(start_s)
    end = datetime.fromisoformat(end_s)
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)
    return start, end


def _parse_hours(value: str) -> tuple[int, int]:
    parts = value.split("-")
    if len(parts) != 2:
        raise ValueError("--hours must look like 9-18")
    return int(parts[0]), int(parts[1])


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="schedule",
        description="Find a meeting time everyone is free for, via multi-party PSI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Schedule over fixture or live Google calendars.")
    run.add_argument(
        "--source",
        choices=["fixtures", "google"],
        default="fixtures",
        help="calendar source (default: fixtures)",
    )
    run.add_argument("--fixtures", help="path to the calendars JSON file (--source fixtures)")
    run.add_argument(
        "--calendars", help="comma-separated calendar ids/emails (--source google)"
    )
    run.add_argument(
        "--credentials", help="path to Google credentials JSON (--source google)"
    )
    run.add_argument("--window", required=True, help="START..END, ISO date or datetime")
    run.add_argument("--slot-minutes", type=int, default=15, help="grid granularity (default 15)")
    run.add_argument("--hours", default=None, help="working hours, e.g. 9-18 (optional)")
    run.add_argument("--weekdays", action="store_true", help="restrict to weekdays")
    run.add_argument("--tz", default="UTC", help="IANA timezone for window/hours/display")
    run.add_argument(
        "--duration", type=int, default=None, help="meeting minutes (default: one slot)"
    )
    run.add_argument("--out", default=None, help="write the HTML report to this path")
    run.add_argument("--open", action="store_true", dest="open_browser", help="open the report")
    run.add_argument("--seed", type=int, default=None, help="seed the shuffle for reproducibility")
    run.add_argument("--tentative-free", action="store_true", help="treat tentative events as free")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return _run(args)
    return 1


def _run(args: argparse.Namespace) -> int:
    try:
        tz: tzinfo = ZoneInfo(args.tz)
    except (ZoneInfoNotFoundError, ValueError):
        print(f"error: unknown timezone {args.tz!r}", file=sys.stderr)
        return 2

    try:
        start, end = _parse_window(args.window, tz)
        working_hours = _parse_hours(args.hours) if args.hours else None
        grid = TimeGrid(
            start,
            end,
            args.slot_minutes,
            working_hours=working_hours,
            weekdays_only=args.weekdays,
            tz=tz,
        )
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    try:
        source = _build_source(args)
    except _SourceError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    duration = args.duration if args.duration is not None else args.slot_minutes
    try:
        slots_needed = slots_for_duration(duration, grid)
        rng = random.Random(args.seed) if args.seed is not None else None
        report: ScheduleResult | TieredScheduleResult
        # Fixtures know whether any meeting is reschedulable (selects the single-round fast path);
        # Google calendars don't expose that cheaply, so they always take the tiered path (which
        # subsumes round 1 -- it just stops there when round 1 already matches).
        tiered = (
            not isinstance(source, FixtureCalendarSource)
            or source.has_reschedulable_meetings()
        )
        if tiered:
            report = schedule_tiered(source, grid, slots_needed=slots_needed, rng=rng)
            _print_tiered_report(report, tz)
        else:
            report = schedule_meeting(source, grid, slots_needed=slots_needed, rng=rng)
            _print_report(report, tz)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.out:
        out = Path(args.out)
        out.write_text(render_html(report))
        print(f"\nWrote {out}")
        if args.open_browser:
            webbrowser.open(out.resolve().as_uri())
    return 0


def _print_trace(transcript: Transcript) -> None:
    print("Protocol trace (only blinded points travel until the final result):")
    for message in transcript.messages:
        payload = (
            f"{message.size} slot(s) - CLEARTEXT"
            if message.reveals_cleartext
            else f"{message.size} blinded point(s)"
        )
        arrow = f"{message.sender} -> {message.receiver}"
        print(f"  #{message.step:02d}  {arrow:<26}  {message.summary}  [{payload}]")


def _print_revealed(grid: TimeGrid, common_slot_ids: frozenset[str], tz: tzinfo) -> None:
    common_slots = sorted(
        (grid.slots[i] for sid in common_slot_ids if (i := grid.index_of(sid)) is not None),
        key=lambda s: s.start,
    )
    if common_slots:
        labels = ", ".join(_fmt(s.start, tz) for s in common_slots)
        print(f"Revealed: {len(common_slots)} common slot(s): {labels}")
    else:
        print("Revealed: 0 common slots")


def _print_report(result: ScheduleResult, tz: tzinfo) -> None:
    grid = result.grid
    names = ", ".join(sorted(result.free_by_party))
    window = f"{_fmt(grid.start, tz)} -> {_fmt(grid.end, tz)}"
    print("Gated-Access Meeting Scheduling - multi-party PSI")
    print(f"Parties : {names}")
    print(f"Grid    : {window} | {grid.slot_minutes}-min slots | {len(grid)} slots | {tz}")
    print()
    _print_trace(result.psi.transcript)
    print()

    party_count = len(result.free_by_party)
    if result.meeting is not None:
        meeting = result.meeting
        end_label = meeting.end.astimezone(tz).strftime("%H:%M")
        print(
            f"Result  : {_fmt(meeting.start, tz)} -> {end_label}  "
            f"({len(meeting.slots)} contiguous slot(s) free for all {party_count} parties)"
        )
    else:
        print(f"Result  : No common slot found for all {party_count} parties.")
    _print_revealed(grid, result.common_slot_ids, tz)


def _print_tiered_report(result: TieredScheduleResult, tz: tzinfo) -> None:
    grid = result.grid
    names = ", ".join(sorted(result.free_by_party))
    window = f"{_fmt(grid.start, tz)} -> {_fmt(grid.end, tz)}"
    print("Gated-Access Meeting Scheduling - tiered relaxation (Part B)")
    print(f"Parties : {names}")
    print(f"Grid    : {window} | {grid.slot_minutes}-min slots | {len(grid)} slots | {tz}")
    print()
    print("Escalating rounds (each reruns the PSI with more meetings freed):")
    for n, rnd in enumerate(result.rounds, start=1):
        verdict = "match" if rnd.result.meeting is not None else "no common slot"
        print(f"  Round {n}  {rnd.label:<26}  -> {verdict}")
    print()
    _print_trace(result.psi.transcript)
    print()

    if result.meeting is not None:
        meeting = result.meeting
        end_label = meeting.end.astimezone(tz).strftime("%H:%M")
        print(
            f"Result  : {_fmt(meeting.start, tz)} -> {end_label}  "
            f"({len(meeting.slots)} contiguous slot(s)), required: {result.relaxation_used}"
        )
        _print_revealed(grid, result.common_slot_ids, tz)
        _print_displaced(result, tz)
    else:
        print("Result  : No meeting possible, even after freeing medium-cost meetings.")
        _print_revealed(grid, result.common_slot_ids, tz)


def _print_displaced(result: TieredScheduleResult, tz: tzinfo) -> None:
    if not result.displaced_by_party:
        print("Reschedules: none -- everyone was already free at the chosen time.")
        return
    print("Reschedules (each computed locally; no party sees another's):")
    for name in sorted(result.displaced_by_party):
        moved = result.displaced_by_party[name]
        items = "; ".join(
            f'"{m.title or "(untitled)"}" ({_TIER_LABELS.get(m.tier, str(m.tier))}, '
            f"{_fmt(m.start, tz)})"
            for m in moved
        )
        print(f"  {name:<8} moves {len(moved)} meeting(s): {items}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
