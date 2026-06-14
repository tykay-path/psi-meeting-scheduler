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

from gated_scheduler.grid import TimeGrid
from gated_scheduler.scheduler import ScheduleResult, schedule_meeting, slots_for_duration
from gated_scheduler.sources.fixtures import FixtureCalendarSource
from gated_scheduler.viz.html import render_html


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
    run = sub.add_parser("run", help="Schedule over a JSON fixtures file.")
    run.add_argument("--fixtures", required=True, help="path to the calendars JSON file")
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

    fixtures = Path(args.fixtures)
    if not fixtures.exists():
        print(f"error: fixtures file not found: {fixtures}", file=sys.stderr)
        return 2
    source = FixtureCalendarSource.from_file(fixtures, tentative_is_busy=not args.tentative_free)

    duration = args.duration if args.duration is not None else args.slot_minutes
    try:
        slots_needed = slots_for_duration(duration, grid)
        rng = random.Random(args.seed) if args.seed is not None else None
        result = schedule_meeting(source, grid, slots_needed=slots_needed, rng=rng)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    _print_report(result, tz)

    if args.out:
        out = Path(args.out)
        out.write_text(render_html(result))
        print(f"\nWrote {out}")
        if args.open_browser:
            webbrowser.open(out.resolve().as_uri())
    return 0


def _print_report(result: ScheduleResult, tz: tzinfo) -> None:
    grid = result.grid
    names = ", ".join(sorted(result.free_by_party))
    window = f"{_fmt(grid.start, tz)} -> {_fmt(grid.end, tz)}"
    print("Gated-Access Meeting Scheduling - multi-party PSI")
    print(f"Parties : {names}")
    print(f"Grid    : {window} | {grid.slot_minutes}-min slots | {len(grid)} slots | {tz}")
    print()
    print("Protocol trace (only blinded points travel until the final result):")
    for message in result.psi.transcript.messages:
        payload = (
            f"{message.size} slot(s) - CLEARTEXT"
            if message.reveals_cleartext
            else f"{message.size} blinded point(s)"
        )
        arrow = f"{message.sender} -> {message.receiver}"
        print(f"  #{message.step:02d}  {arrow:<26}  {message.summary}  [{payload}]")
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

    common_slots = sorted(
        (
            grid.slots[index]
            for sid in result.common_slot_ids
            if (index := grid.index_of(sid)) is not None
        ),
        key=lambda s: s.start,
    )
    if common_slots:
        labels = ", ".join(_fmt(s.start, tz) for s in common_slots)
        print(f"Revealed: {len(common_slots)} common slot(s): {labels}")
    else:
        print("Revealed: 0 common slots")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
