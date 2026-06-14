# Gated-Access Meeting Scheduling via Private Set Intersection

Find a meeting time that works for everyone **without any single entity ever seeing all the
calendars**. Each party reads only its *own* calendar; a genuine multi-party **Private Set
Intersection (PSI)** protocol computes the slots in which everyone is free, revealing nothing
beyond that intersection.

```
[ CalendarSource ] -> free-slot set on shared grid -> [ PSI core ] -> [ matching ] -> meeting
   (swappable)              (the seam)              (privacy-preserving)  (deterministic)
```

## The idea

Scheduling is trivial when one entity can see every calendar. It gets interesting when access is
*gated*: each party sees only its own calendar, yet a meeting must fit everyone's availability —
and **no single entity ever holds the full picture**. That constraint *is* the problem. Any
design where some component aggregates all calendars has quietly reverted to the easy,
already-solved version.

Finding a common slot under gated access is fundamentally an **algorithm**, not an agent system —
just comparing availability under a privacy constraint. The right tool is a well-studied
cryptographic primitive: PSI lets several parties compute the intersection of their private sets
while revealing nothing but the intersection itself.

This project is **Part A** of that vision (availability matching). Preferences, natural-language
requests, rescheduling, and learning behaviour over time are *Part B* — explicitly out of scope.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"        # or: uv pip install -e ".[dev]"

pytest                          # 93 tests
schedule run --help
```

## Demo

A pre-generated report is included: **[demo.html](https://tykay-path.github.io/psi-meeting-scheduler/demo.html)** — click to open it in your browser and see the timeline and full PSI protocol trace.

Three colleagues, all in Tel Aviv, want a **45-minute** meeting during Monday business hours:

```bash
schedule run --fixtures fixtures/three_people.json \
  --window 2026-06-15..2026-06-16 --hours 9-17 --slot-minutes 15 \
  --tz Asia/Jerusalem --duration 45 --out demo.html
```

```
Protocol trace (only blinded points travel until the final result):
  #00  Alice -> ring        Alice blinds its 16 free slots with its own key   [16 blinded point(s)]
  #01  Bob   -> ring        Bob re-blinds Alice's set with its key            [16 blinded point(s)]
  ...
  #12  Combiner -> Output   Combiner finds 8 blinded point(s) common to all  [8 blinded point(s)]
  #13  ring  -> Output      Parties hand the Output a blinded table of slots  [32 blinded point(s)]
  #14  Output -> everyone   Output reveals the 8 common slot(s) to everyone   [8 slot(s) - CLEARTEXT]

Result  : Mon Jun 15, 11:45 -> 12:30  (3 contiguous slot(s) free for all 3 parties)
Revealed: 8 common slot(s): 11:00, 11:15, 11:45, 12:00, 12:15, 14:00, 14:15, 14:30
```

Note the result is **11:45**, not the earlier 11:00 — the 11:00/11:15 pair is only two slots, too
short for 45 minutes. Contiguity is enforced *on top of* the intersection, exactly as it should be.
Open `demo.html` to see the timeline, the per-party calendars (illustration only), and the full
message flow. Every step before the last carries only opaque blinded points.

Three scenarios from the same tool:

| Command (abbreviated) | Result |
|---|---|
| `... three_people.json --duration 15` | earliest single slot: **11:00** |
| `... three_people.json --duration 45` | earliest 45-min block: **11:45–12:30** |
| `... three_people.json --duration 90` | **no slot** (8 common slots, but none give 6 in a row) |
| `... no_common_slot.json` | **no common slot** (0 in the intersection) |
| `... across_timezones.json --slot-minutes 60 --duration 60` | **12:00 Tel Aviv** |

The last one is three people in **three timezones** (Tel Aviv / New York / London), each with a
calendar in its own local time — the grid normalises everything to a shared instant and still
finds the one hour they share.

## How the PSI works

The protocol is multi-party PSI from **commutative (ECDH) encryption**, semi-honest:

1. Every party maps each free slot id to a curve point `H(slot)` and blinds it with its secret
   key, then **shuffles**. Each set is relayed around the ring; every other party applies its key
   too. Because blinding commutes, a slot `x` ends up as `K·H(x)` (where `K` = product of all
   keys) **regardless of path** — so equal slots collide, while `x` stays hidden under the
   Diffie-Hellman assumption.
2. The fully-blinded sets go to the **Combiner**, which intersects them as opaque points. It holds
   no key and no de-blinding table, so it can never map a point back to a slot.
3. The parties also ring-blind the *public* time grid into a table `K·H(u) -> u`, handed only to
   the **Output** role.
4. The Output receives **only** the common points from the Combiner and uses the table to recover
   the cleartext intersection — and nothing else.

No entity ever holds all calendars in the clear: parties see only their own; the Combiner sees
only opaque points; the Output learns only the result. The cryptographic primitives come from
**libsodium via PyNaCl** — we compose the protocol, we never implement the curve math.

> **Curve note.** ristretto255 would be the textbook choice (prime-order, no cofactor), but
> PyNaCl's build doesn't expose it, so we use **ed25519** with libsodium's cofactor-clearing
> `from_uniform` (its output is verified to be in the prime-order subgroup) and *unclamped*
> scalar multiplication (clamping would break the commutativity the protocol relies on).

## Architecture

A deliberately clean seam: the PSI core takes sets and knows nothing about calendars; the
calendar layer's only job is "produce this party's free-slot set on the grid."

| Module | Responsibility |
|---|---|
| `grid.py` | The public time grid (the element universe); UTC normalisation; working-hours mask; interval→slot coverage; temporal adjacency |
| `freebusy.py` | Event semantics → free-slot set (timezones, all-day, tentative, transparency, partial overlap) |
| `matching.py` | Deterministic core: earliest run of *N contiguous* free slots; pluggable selection |
| `psi/primitives.py` | Thin wrapper over libsodium ed25519 (`hash_to_group`, `random_scalar`, `blind`) |
| `psi/channel.py` | `Channel` + `Transcript`: the seam where messages cross, recorded for audit & viz |
| `psi/protocol.py` | The multi-party commutative-ECDH PSI (Party / Combiner / Output roles) |
| `sources/` | The calendar seam: `CalendarSource`, a fixtures implementation, a Google stub |
| `scheduler.py` | Orchestrates source → PSI → matching |
| `viz/html.py` | Self-contained HTML report |
| `cli.py` | `schedule run …` |

## Privacy model & honest caveats

- **Threat model:** semi-honest, no collusion. Parties follow the protocol; the guarantee holds as
  long as the Combiner and the Output role don't collude. Defending against parties that *lie about
  their availability* or *deviate from the protocol* is a separate axis (malicious-model PSI) — Part B.
- **Documented leak:** the Combiner learns each party's free-slot *count* (set sizes). A standard
  mitigation is to pad every set to the universe size; left out of v1 for clarity.
- **"Free" hides cost.** A plain free/busy set treats every open slot as equally available; it
  can't express "free, but I'd rather not move this." That's a *preference* — Part B.
- **Duration/contiguity** is logic over the PSI output, not part of the PSI.
- **Granularity is a dial.** Finer slots give more precision but enlarge the universe and make PSI
  heavier; 15-minute slots over a work-hour window stay small.

## Testing

93 tests, test-driven throughout (`pytest`, with `hypothesis` for properties):

- **Core:** known-answer + edge cases (empty intersection, single slot, all-identical, one party
  free everywhere, the isolated-vs-consecutive **contiguity** case, day-boundary gaps) plus a
  property test against a brute-force oracle.
- **PSI:** a property test asserting `PSI result == plain set intersection` over random N-party
  inputs, order-independence, and a **privacy assertion** — no message except the final result ever
  carries cleartext, and the Output role only ever receives the intersection.
- **Free/busy:** timezones, all-day, tentative vs. accepted, transparency, partial overlap.
- **Pipeline / CLI / HTML:** end-to-end on fixtures, including the no-common-slot path and
  self-containedness / escaping of the report.

```bash
pytest            # tests
ruff check .      # lint
mypy gated_scheduler   # types
```

## Out of scope (Part B) and future work

Preferences and cost-of-moving, input honesty / malicious & collusion resistance, rescheduling
when no slot exists, natural-language requests — and **live Google Calendar**. The Google source is
stubbed (`sources/google.py`) behind the same seam: its intended implementation uses Google's
**free/busy API** (busy intervals only — a privacy win), wraps each interval as a `freebusy.Event`,
and reuses everything downstream unchanged. By the time it matters, the only new thing under test is
"does my fetch produce the same kind of set the fixtures did."
