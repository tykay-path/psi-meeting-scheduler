"""Google Calendar source -- a hybrid of free/busy and (own-calendar only) event detail.

Two reads, both local to a single party's calendar, so no entity ever assembles the full picture:

* **Availability (Part A)** uses Google's **free/busy query API**, which returns busy intervals
  only -- no titles or attendees. It is the right tool for round 1: minimal disclosure, and the
  only thing that flows downstream is opaque slot ids anyway.
* **Relaxation + "what must move" (Part B)** needs detail free/busy cannot express -- which busy
  blocks are reschedulable, and their titles. So when ``relax_threshold > 0`` (or when computing
  displaced meetings) the source reads the **events** of *that party's own* calendar and maps each
  to a ``freebusy.Event``. The reschedule tier comes from the event's private
  ``extendedProperties.private.reschedule`` (``easy``/``medium``/``hard``), a tag the owner's own
  agent sets; untagged defaults to ``HARD``, matching the fixture source.

The mapping is the only logic worth testing here; the event *semantics* (blocking, relaxation,
displacement) are reused unchanged from ``freebusy``. The Google API client is injected (see
``CalendarClient``), so the mapping is exercised with hand-built fixtures and ``googleapiclient``
is needed only for the live adapter, ``build_google_client``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from gated_scheduler.freebusy import EASY, HARD, MEDIUM, Event, EventStatus
from gated_scheduler.freebusy import displaced_meetings as derive_displaced
from gated_scheduler.freebusy import free_slots as derive_free_slots
from gated_scheduler.grid import TimeGrid
from gated_scheduler.sources.base import CalendarSource, DisplacedMeeting

_TIERS = {"easy": EASY, "medium": MEDIUM, "hard": HARD}


class CalendarClient(Protocol):
    """The injected seam to Google. Returns raw Google-shaped dicts; mapping happens here."""

    def freebusy(self, calendar_id: str, time_min: datetime, time_max: datetime) -> list[dict]:
        """The free/busy ``busy`` array: ``[{"start": rfc3339, "end": rfc3339}, ...]``."""
        ...

    def list_events(self, calendar_id: str, time_min: datetime, time_max: datetime) -> list[dict]:
        """Google event resources (raw dicts) overlapping ``[time_min, time_max)``."""
        ...


class GoogleCalendarSource(CalendarSource):
    """A ``CalendarSource`` backed by the Google Calendar API (via an injected client)."""

    def __init__(
        self,
        client: CalendarClient,
        calendar_ids: Iterable[str],
        *,
        tentative_is_busy: bool = True,
    ) -> None:
        self._client = client
        self._calendar_ids = list(calendar_ids)
        self._tentative_is_busy = tentative_is_busy

    def party_ids(self) -> list[str]:
        return sorted(self._calendar_ids)

    def free_slots(self, party_id: str, grid: TimeGrid, *, relax_threshold: int = 0) -> set[str]:
        if relax_threshold <= 0:
            # Round 1: free/busy only -- minimal disclosure, no event detail read.
            events = self._busy_as_events(party_id, grid)
        else:
            # Relaxation needs to know which busy blocks are reschedulable -> read own events.
            events = self._events(party_id, grid)
        return derive_free_slots(
            events,
            grid,
            tentative_is_busy=self._tentative_is_busy,
            relax_threshold=relax_threshold,
        )

    def displaced_meetings(
        self,
        party_id: str,
        grid: TimeGrid,
        meeting_slot_ids: Iterable[str],
        *,
        relax_threshold: int,
    ) -> list[DisplacedMeeting]:
        moved = derive_displaced(
            self._events(party_id, grid),
            grid,
            meeting_slot_ids,
            relax_threshold=relax_threshold,
            tentative_is_busy=self._tentative_is_busy,
        )
        return [
            DisplacedMeeting(title=e.title, start=e.start, end=e.end, tier=e.tier) for e in moved
        ]

    def _busy_as_events(self, party_id: str, grid: TimeGrid) -> list[Event]:
        """Free/busy intervals as opaque busy ``Event``s (no title, default HARD tier)."""
        intervals = self._client.freebusy(party_id, grid.start, grid.end)
        return [
            Event(start=_parse_dt(raw["start"]), end=_parse_dt(raw["end"])) for raw in intervals
        ]

    def _events(self, party_id: str, grid: TimeGrid) -> list[Event]:
        raw_events = self._client.list_events(party_id, grid.start, grid.end)
        return [_event_from_google(raw) for raw in raw_events]


def _parse_dt(value: str) -> datetime:
    """Parse an RFC3339 timestamp; Google's trailing ``Z`` is normalized to ``+00:00``."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_tier(raw: dict[str, Any]) -> int:
    private = (raw.get("extendedProperties") or {}).get("private") or {}
    value = private.get("reschedule")
    if value is None:
        return HARD
    try:
        return _TIERS[str(value).lower()]
    except KeyError:
        raise ValueError(f"unknown reschedule tier: {value!r}") from None


def _event_from_google(raw: dict[str, Any]) -> Event:
    """Map a single Google Calendar event resource to a ``freebusy.Event``.

    Handles timed (``start.dateTime``) and all-day (``start.date``) events, Google ``status`` and
    ``transparency``, the private reschedule tier, and the ``summary`` title.
    """
    status = EventStatus(raw.get("status", "confirmed"))
    transparent = raw.get("transparency") == "transparent"
    tier = _parse_tier(raw)
    title = str(raw.get("summary", ""))
    start_field = raw["start"]
    end_field = raw["end"]

    if "date" in start_field:  # all-day: [start.date, end.date) at midnight UTC
        start_day = date.fromisoformat(start_field["date"])
        start = datetime(start_day.year, start_day.month, start_day.day, tzinfo=UTC)
        if "date" in end_field:
            end_day = date.fromisoformat(end_field["date"])
            end = datetime(end_day.year, end_day.month, end_day.day, tzinfo=UTC)
        else:
            end = start + timedelta(days=1)
        return Event(
            start=start,
            end=end,
            status=status,
            transparent=transparent,
            all_day=True,
            tier=tier,
            title=title,
        )

    return Event(
        start=_parse_dt(start_field["dateTime"]),
        end=_parse_dt(end_field["dateTime"]),
        status=status,
        transparent=transparent,
        tier=tier,
        title=title,
    )


def build_google_client(credentials: Any) -> CalendarClient:
    """Build a live ``CalendarClient`` backed by ``googleapiclient`` (optional dependency).

    Install with ``pip install 'gated-scheduler[google]'``. ``credentials`` is a
    ``google.oauth2`` / service-account credentials object the caller has already obtained.
    """
    try:
        from googleapiclient.discovery import build  # noqa: PLC0415  (lazy: optional dependency)
    except ImportError as error:  # pragma: no cover - exercised only without the extra installed
        raise RuntimeError(
            "Google Calendar support requires the 'google' extra: pip install "
            "'gated-scheduler[google]'"
        ) from error

    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    return _GoogleApiClient(service)


def _rfc3339(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _GoogleApiClient:
    """Thin adapter wrapping a built Calendar ``service`` into the ``CalendarClient`` protocol."""

    def __init__(self, service: Any) -> None:
        self._service = service

    def freebusy(self, calendar_id: str, time_min: datetime, time_max: datetime) -> list[dict]:
        body = {
            "timeMin": _rfc3339(time_min),
            "timeMax": _rfc3339(time_max),
            "items": [{"id": calendar_id}],
        }
        response = self._service.freebusy().query(body=body).execute()
        return response.get("calendars", {}).get(calendar_id, {}).get("busy", [])

    def list_events(self, calendar_id: str, time_min: datetime, time_max: datetime) -> list[dict]:
        response = (
            self._service.events()
            .list(
                calendarId=calendar_id,
                timeMin=_rfc3339(time_min),
                timeMax=_rfc3339(time_max),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return response.get("items", [])
