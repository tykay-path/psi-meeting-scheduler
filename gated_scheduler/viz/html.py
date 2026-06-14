"""Render a self-contained HTML report of a scheduling run.

The page makes the privacy property *visible*: it shows each party's ground-truth calendar
(clearly labelled illustration-only -- the protocol never reveals it), the computed
intersection, the chosen meeting, and the full message trace demonstrating that only opaque
blinded points travel until the final result. The output is a single file with inline CSS and
no external resources, so it can be opened or shared anywhere.

For a Part B tiered result it additionally shows the *escalation*: one mini-timeline per round as
availability is relaxed, the winning round highlighted, and -- computed locally per party -- which
meetings each person must move.
"""

from __future__ import annotations

from datetime import datetime, tzinfo

from jinja2 import Environment

from gated_scheduler.freebusy import EASY, HARD, MEDIUM
from gated_scheduler.psi.channel import Transcript
from gated_scheduler.scheduler import ScheduleResult, TieredScheduleResult

_Result = ScheduleResult | TieredScheduleResult
_TIER_LABELS = {EASY: "easy", MEDIUM: "medium", HARD: "hard"}


def _fmt(dt: datetime, tz: tzinfo) -> str:
    return dt.astimezone(tz).strftime("%a %b %d, %H:%M")


def _trace_view(transcript: Transcript) -> list[dict[str, object]]:
    return [
        {
            "step": m.step,
            "sender": m.sender,
            "receiver": m.receiver,
            "summary": m.summary,
            "size": m.size,
            "cleartext": m.reveals_cleartext,
        }
        for m in transcript.messages
    ]


def _chosen_view(result: _Result, tz: tzinfo) -> tuple[set[str], dict[str, object] | None]:
    if result.meeting is None:
        return set(), None
    chosen_ids = {slot.slot_id for slot in result.meeting.slots}
    chosen = {
        "start": _fmt(result.meeting.start, tz),
        "end": _fmt(result.meeting.end, tz),
        "slots": len(result.meeting.slots),
    }
    return chosen_ids, chosen


def _grid_view(
    result: _Result, chosen_ids: set[str], tz: tzinfo
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str]]:
    """Build the per-slot, per-party, and revealed-slot view models for one round of data."""
    grid = result.grid
    common = result.common_slot_ids
    slots_vm: list[dict[str, object]] = []
    prev_day = None
    for slot in grid.slots:
        local = slot.start.astimezone(tz)
        day = local.strftime("%a %b %d")
        slots_vm.append(
            {
                "time": local.strftime("%H:%M"),
                "day": day,
                "first_of_day": day != prev_day,
                "is_common": slot.slot_id in common,
                "is_chosen": slot.slot_id in chosen_ids,
            }
        )
        prev_day = day

    parties_vm: list[dict[str, object]] = []
    for name in sorted(result.free_by_party):
        free = result.free_by_party[name]
        cells = [
            {
                "free": slot.slot_id in free,
                "is_chosen": slot.slot_id in chosen_ids,
                "label": slot.start.astimezone(tz).strftime("%a %H:%M"),
            }
            for slot in grid.slots
        ]
        parties_vm.append({"name": name, "cells": cells})

    common_slots = sorted(
        (grid.slots[i] for sid in common if (i := grid.index_of(sid)) is not None),
        key=lambda s: s.start,
    )
    common_labels = [_fmt(s.start, tz) for s in common_slots]
    return slots_vm, parties_vm, common_labels


def render_html(result: _Result, *, title: str = "Gated-Access Meeting Scheduling") -> str:
    tz = result.grid.tz
    chosen_ids, chosen = _chosen_view(result, tz)

    rounds_vm: list[dict[str, object]] = []
    displaced_vm: list[dict[str, object]] = []
    relaxation: str | None = None
    if isinstance(result, TieredScheduleResult):
        relaxation = result.relaxation_used
        for idx, rnd in enumerate(result.rounds):
            highlight = chosen_ids if idx == result.winning_index else set()
            r_slots, r_parties, r_common = _grid_view(rnd.result, highlight, tz)
            rounds_vm.append(
                {
                    "number": idx + 1,
                    "label": rnd.label,
                    "matched": rnd.result.meeting is not None,
                    "is_winner": idx == result.winning_index,
                    "set_sizes": rnd.result.psi.party_set_sizes,
                    "slots": r_slots,
                    "parties": r_parties,
                    "common": r_common,
                }
            )
        displaced_vm = [
            {
                "name": name,
                "moves": [
                    {
                        "title": m.title or "(untitled)",
                        "tier": _TIER_LABELS.get(m.tier, str(m.tier)),
                        "time": _fmt(m.start, tz),
                    }
                    for m in result.displaced_by_party[name]
                ],
            }
            for name in sorted(result.displaced_by_party)
        ]

    slots_vm, parties_vm, common_labels = _grid_view(result, chosen_ids, tz)
    env = Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)
    return env.from_string(_TEMPLATE).render(
        title=title,
        chosen=chosen,
        relaxation=relaxation,
        common=common_labels,
        slots=slots_vm,
        parties=parties_vm,
        rounds=rounds_vm,
        displaced=displaced_vm,
        trace=_trace_view(result.psi.transcript),
        party_count=len(result.free_by_party),
        set_sizes=result.psi.party_set_sizes,
    )


_TEMPLATE = """{% macro timeline(slots, parties) %}
<div class="scroll">
  <table class="timeline">
    <thead>
      <tr>
        <th class="rowhead"></th>
        {% for s in slots %}
        <th class="{{ 'firstofday' if s.first_of_day else '' }} {{ 'chosen' if s.is_chosen else '' }}">
          {% if s.first_of_day %}<div class="day">{{ s.day }}</div>{% endif %}
          <div class="time">{{ s.time }}</div>
        </th>
        {% endfor %}
      </tr>
    </thead>
    <tbody>
      {% for p in parties %}
      <tr>
        <th class="rowhead">{{ p.name }}</th>
        {% for cell in p.cells %}
        <td class="{{ 'free' if cell.free else 'busy' }} {{ 'chosen' if cell.is_chosen else '' }}" title="{{ cell.label }}">{{ '·' if cell.free else '×' }}</td>
        {% endfor %}
      </tr>
      {% endfor %}
      <tr class="interrow">
        <th class="rowhead">Everyone free?</th>
        {% for s in slots %}
        <td class="{{ 'common' if s.is_common else 'nocommon' }} {{ 'chosen' if s.is_chosen else '' }}">{{ '✓' if s.is_common else '' }}</td>
        {% endfor %}
      </tr>
    </tbody>
  </table>
</div>
{% endmacro %}
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<style>
  :root { --free:#1f9d55; --busy:#cbd5e0; --chosen:#f6c343; --ink:#1a202c; --muted:#718096; }
  * { box-sizing: border-box; }
  body { margin:0; background:#f7fafc; color:var(--ink);
         font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
  main { max-width: 980px; margin: 0 auto; padding: 32px 20px 64px; }
  h1 { margin:0 0 4px; font-size: 1.7rem; }
  .sub { color:var(--muted); margin:0 0 24px; }
  h2 { font-size: 1.15rem; margin: 32px 0 8px; }
  h3 { font-size: 1rem; margin: 0 0 8px; }
  .tag { font-weight:400; font-size:.72rem; color:var(--muted); border:1px solid #e2e8f0;
         padding:2px 8px; border-radius:999px; margin-left:8px; }
  .banner { border-radius:12px; padding:18px 20px; margin:8px 0 8px; }
  .banner.ok { background:#e6fffa; border:1px solid #38b2ac; }
  .banner.none { background:#fff5f5; border:1px solid #fc8181; color:#9b2c2c; font-weight:600; }
  .banner-label { text-transform:uppercase; letter-spacing:.08em; font-size:.7rem; color:var(--muted); }
  .banner-time { font-size:1.5rem; font-weight:700; margin:2px 0; }
  .banner-note { color:var(--muted); font-size:.9rem; }
  .revealed { display:flex; flex-wrap:wrap; gap:8px; list-style:none; padding:0; }
  .revealed li { background:#fffbea; border:1px solid var(--chosen); border-radius:8px; padding:6px 10px; font-variant-numeric:tabular-nums; }
  .revealed li.muted { background:#edf2f7; border-color:#e2e8f0; color:var(--muted); }
  .round { margin:10px 0 16px; padding:12px 14px; border:1px solid #e2e8f0; border-radius:12px; background:#fff; }
  .round.winner { border-color:var(--chosen); background:#fffdf5; }
  .round .meta { font-size:.78rem; color:var(--muted); margin:8px 0 0; }
  .scroll { overflow-x:auto; border:1px solid #e2e8f0; border-radius:10px; }
  table.timeline { border-collapse:collapse; font-size:.8rem; }
  table.timeline th, table.timeline td { border:1px solid #edf2f7; text-align:center; padding:6px 8px; min-width:46px; }
  table.timeline th.rowhead { text-align:right; position:sticky; left:0; background:#fff; font-weight:600; min-width:120px; }
  table.timeline th.firstofday { border-left:2px solid #cbd5e0; }
  td.firstofday, td.free.firstofday, td.busy.firstofday { border-left:2px solid #cbd5e0; }
  .day { font-size:.65rem; color:var(--muted); }
  .time { font-variant-numeric:tabular-nums; }
  td.free { background:#e9f8ef; color:var(--free); font-weight:700; }
  td.busy { background:#f2f4f7; color:#a0aec0; }
  td.common { background:#e9f8ef; color:var(--free); font-weight:700; }
  td.nocommon { background:#fff; color:#cbd5e0; }
  .interrow th, .interrow td { border-top:2px solid #cbd5e0; }
  th.chosen, td.chosen { outline:3px solid var(--chosen); outline-offset:-3px; }
  .legend { font-size:.8rem; color:var(--muted); margin-top:8px; }
  .swatch { display:inline-block; width:12px; height:12px; border-radius:3px; vertical-align:middle; }
  .swatch.free { background:#e9f8ef; border:1px solid var(--free); }
  .swatch.busy { background:#f2f4f7; border:1px solid #cbd5e0; }
  .swatch.chosen { background:#fffbea; border:2px solid var(--chosen); }
  table.trace { border-collapse:collapse; width:100%; font-size:.82rem; }
  table.trace th, table.trace td { border-bottom:1px solid #edf2f7; padding:7px 8px; text-align:left; vertical-align:top; }
  table.trace th { color:var(--muted); font-weight:600; }
  tr.cleartext { background:#fffbea; }
  .badge { font-size:.72rem; padding:2px 8px; border-radius:999px; white-space:nowrap; }
  .badge.opaque { background:#edf2f7; color:#4a5568; }
  .badge.reveal { background:#fffbea; color:#975a16; border:1px solid var(--chosen); }
  .notes { background:#fff; border:1px solid #e2e8f0; border-radius:10px; padding:8px 20px; }
  .notes li { margin:6px 0; }
  .muted { color:var(--muted); }
</style>
</head>
<body>
<main>
  <h1>{{ title }}</h1>
  <p class="sub">Privacy-preserving scheduling via multi-party Private Set Intersection</p>

  {% if chosen %}
  <div class="banner ok">
    <div class="banner-label">Proposed meeting</div>
    <div class="banner-time">{{ chosen.start }} &rarr; {{ chosen.end }}</div>
    <div class="banner-note">{{ chosen.slots }} contiguous slot(s), free for all {{ party_count }} parties{% if relaxation %} &mdash; required flexibility: <strong>{{ relaxation }}</strong>{% endif %}</div>
  </div>
  {% else %}
  <div class="banner none">{% if rounds %}No meeting possible, even after freeing medium-cost meetings.{% else %}No common slot found for all {{ party_count }} parties.{% endif %}</div>
  {% endif %}

  <section>
    <h2>What the protocol revealed</h2>
    <p>{% if rounds %}Each round discloses only its own intersection; the winning round revealed{% else %}The <strong>only</strong> thing disclosed is{% endif %} the {{ common|length }} slot(s) everyone is free for:</p>
    <ul class="revealed">
      {% for c in common %}<li>{{ c }}</li>{% endfor %}
      {% if not common %}<li class="muted">(none)</li>{% endif %}
    </ul>
  </section>

  {% if rounds %}
  <section>
    <h2>Escalating rounds <span class="tag">ground truth &mdash; illustration only; the protocol never reveals this</span></h2>
    <p>Each round re-runs the PSI with more meetings freed. The first round that finds a slot wins, so only the cheapest meetings that were necessary get disturbed.</p>
    {% for r in rounds %}
    <div class="round {{ 'winner' if r.is_winner else '' }}">
      <h3>Round {{ r.number }} &mdash; {{ r.label }}
        <span class="badge {{ 'reveal' if r.matched else 'opaque' }}">{{ 'match' if r.matched else 'no common slot' }}{{ ' &mdash; winner' if r.is_winner else '' }}</span>
      </h3>
      {{ timeline(r.slots, r.parties) }}
      <p class="meta">Free-slot counts the Combiner sees this round &mdash; {% for name, size in r.set_sizes.items() %}{{ name }}: {{ size }}{{ ", " if not loop.last else "" }}{% endfor %}.</p>
    </div>
    {% endfor %}
    <p class="legend">
      <span class="swatch free"></span> free &nbsp;
      <span class="swatch busy"></span> busy &nbsp;
      <span class="swatch chosen"></span> chosen meeting
    </p>
  </section>
  {% else %}
  <section>
    <h2>Timeline <span class="tag">ground truth &mdash; shown for illustration only; the protocol never reveals this</span></h2>
    {{ timeline(slots, parties) }}
    <p class="legend">
      <span class="swatch free"></span> free &nbsp;
      <span class="swatch busy"></span> busy &nbsp;
      <span class="swatch chosen"></span> chosen meeting
    </p>
  </section>
  {% endif %}

  {% if displaced %}
  <section>
    <h2>What must move <span class="tag">each party computes its own &mdash; no one sees another's</span></h2>
    <ul class="notes">
      {% for d in displaced %}
      <li><strong>{{ d.name }}</strong> reschedules: {% for it in d.moves %}&ldquo;{{ it.title }}&rdquo; ({{ it.tier }}, {{ it.time }}){{ "; " if not loop.last else "" }}{% endfor %}</li>
      {% endfor %}
    </ul>
  </section>
  {% endif %}

  <section>
    <h2>Protocol trace</h2>
    <p>{% if rounds %}The winning round's messages. {% endif %}Only opaque blinded points cross the wire until the very last step &mdash; no party's calendar is ever sent in the clear.</p>
    <table class="trace">
      <thead><tr><th>#</th><th>From</th><th>To</th><th>Step</th><th>Payload</th></tr></thead>
      <tbody>
        {% for m in trace %}
        <tr class="{{ 'cleartext' if m.cleartext else '' }}">
          <td>{{ m.step }}</td>
          <td>{{ m.sender }}</td>
          <td>{{ m.receiver }}</td>
          <td>{{ m.summary }}</td>
          <td>
            {% if m.cleartext %}<span class="badge reveal">{{ m.size }} slot(s) &middot; cleartext</span>
            {% else %}<span class="badge opaque">{{ m.size }} blinded point(s)</span>{% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </section>

  <section class="notes">
    <h2>Privacy model</h2>
    <ul>
      <li>Each party reads only its own calendar; no entity ever holds all calendars in the clear.</li>
      <li>The <strong>Combiner</strong> sees only opaque points: it computes the intersection but cannot map points back to slots.</li>
      <li>The <strong>Output</strong> holds the de-blinding table but receives only the intersection, so it learns only the result.</li>
      <li>Threat model: semi-honest, no collusion (the guarantee holds as long as Combiner and Output do not collude).</li>
      <li>Documented leak: the Combiner learns each party's free-slot count &mdash;
        {% for name, size in set_sizes.items() %}{{ name }}: {{ size }}{{ ", " if not loop.last else "" }}{% endfor %}.</li>
      {% if rounds %}<li>Because the rounds re-run the PSI on progressively relaxed availability, the Combiner also watches each party's free-slot count <em>grow</em> across rounds &mdash; roughly how many easy/medium-movable meetings it has. Fresh blinding keys each round hide <em>which</em> slots changed; padding every set to the universe size would hide the counts too (left out for clarity, as in Part A).</li>{% endif %}
    </ul>
  </section>
</main>
</body>
</html>
"""
