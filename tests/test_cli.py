import json
from pathlib import Path

from gated_scheduler.cli import main


def write_fixtures(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data))


def busy(s: int, e: int) -> dict[str, str]:
    return {"start": f"2026-06-15T{s:02d}:00:00+00:00", "end": f"2026-06-15T{e:02d}:00:00+00:00"}


def movable(s: int, e: int, tier: str, title: str = "") -> dict[str, str]:
    return {**busy(s, e), "reschedule": tier, "title": title}


def test_run_finds_and_reports_a_meeting(tmp_path, capsys) -> None:
    fixtures = tmp_path / "cal.json"
    write_fixtures(
        fixtures,
        {
            "Alice": {"events": [busy(11, 12)]},  # free 09, 10
            "Bob": {"events": [busy(9, 10)]},  # free 10, 11
            "Carol": {"events": [busy(9, 10), busy(11, 12)]},  # free 10
        },
    )
    out = tmp_path / "demo.html"
    code = main(
        [
            "run",
            "--fixtures",
            str(fixtures),
            "--window",
            "2026-06-15..2026-06-16",
            "--hours",
            "9-12",
            "--slot-minutes",
            "60",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "10:00" in printed
    assert "blinded" in printed  # the trace shows opaque payloads
    assert "CLEARTEXT" in printed  # ...and the single cleartext reveal
    assert out.exists()
    assert out.read_text().lstrip().startswith("<!DOCTYPE html>")


def test_run_reports_no_common_slot(tmp_path, capsys) -> None:
    fixtures = tmp_path / "cal.json"
    write_fixtures(
        fixtures,
        {
            "Alice": {"events": [busy(10, 12)]},  # free 09
            "Bob": {"events": [busy(9, 11)]},  # free 11
        },
    )
    code = main(
        [
            "run",
            "--fixtures",
            str(fixtures),
            "--window",
            "2026-06-15..2026-06-16",
            "--hours",
            "9-12",
            "--slot-minutes",
            "60",
        ]
    )
    assert code == 0
    assert "no common slot" in capsys.readouterr().out.lower()


def test_run_multi_slot_duration(tmp_path, capsys) -> None:
    fixtures = tmp_path / "cal.json"
    write_fixtures(
        fixtures,
        {
            "Alice": {"events": [busy(12, 13)]},  # free 09,10,11
            "Bob": {"events": [busy(9, 10)]},  # free 10,11,12
        },
    )
    code = main(
        [
            "run",
            "--fixtures",
            str(fixtures),
            "--window",
            "2026-06-15..2026-06-16",
            "--hours",
            "9-13",
            "--slot-minutes",
            "60",
            "--duration",
            "120",
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "10:00" in printed
    assert "12:00" in printed


def test_run_is_reproducible_with_seed(tmp_path, capsys) -> None:
    fixtures = tmp_path / "cal.json"
    write_fixtures(
        fixtures, {"Alice": {"events": [busy(11, 12)]}, "Bob": {"events": [busy(9, 10)]}}
    )
    args = [
        "run",
        "--fixtures",
        str(fixtures),
        "--window",
        "2026-06-15..2026-06-16",
        "--hours",
        "9-12",
        "--slot-minutes",
        "60",
        "--seed",
        "7",
    ]
    assert main(args) == 0
    first = capsys.readouterr().out
    assert main(args) == 0
    second = capsys.readouterr().out
    assert first == second


def test_missing_fixtures_file_fails_cleanly(tmp_path, capsys) -> None:
    code = main(
        [
            "run",
            "--fixtures",
            str(tmp_path / "nope.json"),
            "--window",
            "2026-06-15..2026-06-16",
        ]
    )
    assert code != 0
    assert "not found" in (capsys.readouterr().err.lower())


def test_run_tiered_escalates_and_reports_who_moves(tmp_path, capsys) -> None:
    fixtures = tmp_path / "cal.json"
    write_fixtures(
        fixtures,
        {
            "Alice": {"events": [movable(10, 11, "easy", "1:1 with Dana")]},
            "Bob": {"events": [busy(9, 10), busy(11, 12)]},
            "Carol": {"events": [busy(9, 10), busy(11, 12)]},
        },
    )
    out = tmp_path / "demo.html"
    code = main(
        [
            "run",
            "--fixtures",
            str(fixtures),
            "--window",
            "2026-06-15..2026-06-16",
            "--hours",
            "9-12",
            "--slot-minutes",
            "60",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "Round 1" in printed and "Round 2" in printed  # the escalation is shown
    assert "10:00" in printed  # the chosen slot
    assert "easy" in printed.lower()  # the flexibility level reached
    assert "1:1 with Dana" in printed  # the per-party "what must be moved"
    assert "blinded" in printed and "CLEARTEXT" in printed  # trace still proves privacy
    assert out.exists()
    assert out.read_text().lstrip().startswith("<!DOCTYPE html>")


def test_run_tiered_reports_impossible(tmp_path, capsys) -> None:
    fixtures = tmp_path / "cal.json"
    write_fixtures(
        fixtures,
        {
            "Alice": {"events": [busy(9, 12)]},  # booked solid, immovable
            "Bob": {"events": [movable(9, 12, "easy", "Deep work")]},  # tagged -> tiered path
        },
    )
    code = main(
        [
            "run",
            "--fixtures",
            str(fixtures),
            "--window",
            "2026-06-15..2026-06-16",
            "--hours",
            "9-12",
            "--slot-minutes",
            "60",
        ]
    )
    assert code == 0
    assert "no meeting possible" in capsys.readouterr().out.lower()
