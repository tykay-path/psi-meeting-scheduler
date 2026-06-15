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

**Part A** of that vision is privacy-preserving *availability matching* (the core below). **Part B**
adds *preferences* — when no slot works for everyone, it finds the least-disruptive time by letting
people reschedule the meetings they don't mind moving (see **Part B** below). Learning those
preferences over time, natural-language requests, and a malicious-security model remain future work.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"        # or: uv pip install -e ".[dev]"

pytest                          # 125 tests
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

## Part B — preferences via tiered relaxation

The hard case is when **no time works for everyone**: every slot collides with someone's existing
commitment. Part B finds the *least-disruptive* meeting anyway, mirroring how people really
schedule — *"I'll move an internal 1:1 to make room for a customer call."*

The trick is to **encode cost structurally, through the order in which meetings are freed** — no
explicit cost numbers, and **no new cryptography**. Each meeting is tagged with how willing its
owner is to move it (`easy` / `medium` / `hard`; untagged = `hard`). We then run the *same PSI* in
**rounds**, relaxing more each time, and the **first round that finds a slot wins**:

1. **Round 1** — true free/busy only.
2. **Round 2** — also free the slots taken only by `easy` meetings.
3. **Round 3** — also free `medium` ones.

Availability only grows between rounds, so the first match disturbs only the cheapest tier that was
necessary. Each round is an independent PSI run with **fresh blinding keys**, and — faithful to gated
access — each party computes **locally** which of *its own* meetings it would move; no one ever
learns what anyone else gives up.

```bash
schedule run --fixtures fixtures/reschedule_easy.json \
  --window 2026-06-15..2026-06-16 --hours 9-17 --slot-minutes 60 \
  --tz Asia/Jerusalem --duration 60 --out demo_partb.html
```

```
Escalating rounds (each reruns the PSI with more meetings freed):
  Round 1  no rescheduling             -> no common slot
  Round 2  easy reschedules            -> match

Result  : Mon Jun 15, 14:00 -> 15:00  (1 contiguous slot(s)), required: easy reschedules
Revealed: 1 common slot(s): Mon Jun 15, 14:00
Reschedules (each computed locally; no party sees another's):
  Alice    moves 1 meeting(s): "1:1 with Ben" (easy, Mon Jun 15, 14:00)
```

No common slot exists until Alice's *easy* 1:1 is freed in round 2 — so the tool proposes 14:00 and
tells Alice (and only Alice) what she'd move. The HTML report shows one mini-timeline per round with
the winning round highlighted, plus the per-party "what must move" list. Other fixtures exercise the
rest: `reschedule_medium.json` (needs round 3), `multi_person_sacrifice.json` (two people each free
an easy meeting), and `reschedule_impossible.json` (no slot even at round 3).

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
| `freebusy.py` | Event semantics → free-slot set (timezones, all-day, tentative, transparency, partial overlap); **reschedule tiers** + relaxation (Part B) |
| `matching.py` | Deterministic core: earliest run of *N contiguous* free slots; pluggable selection |
| `psi/primitives.py` | Thin wrapper over libsodium ed25519 (`hash_to_group`, `random_scalar`, `blind`) |
| `psi/channel.py` | `Channel` + `Transcript`: the seam where messages cross, recorded for audit & viz |
| `psi/protocol.py` | The multi-party commutative-ECDH PSI (Party / Combiner / Output roles) |
| `sources/` | The calendar seam: `CalendarSource` (free slots + per-party *displaced-meeting* reporting), a fixtures implementation, and a hybrid Google Calendar implementation (free/busy + own-calendar event detail) |
| `scheduler.py` | Orchestrates source → PSI → matching; **tiered relaxation rounds** (Part B) |
| `viz/html.py` | Self-contained HTML report |
| `cli.py` | `schedule run …` |

## Privacy model & honest caveats

- **Threat model:** semi-honest, no collusion. Parties follow the protocol; the guarantee holds as
  long as the Combiner and the Output role don't collude. Defending against parties that *lie about
  their availability* or *deviate from the protocol* is a separate axis (malicious-model PSI) — still future.
- **Documented leak:** the Combiner learns each party's free-slot *count* (set sizes). A standard
  mitigation is to pad every set to the universe size; left out of v1 for clarity.
- **Part B widens that leak slightly.** Run in rounds, the Combiner watches each party's free-slot
  count *grow* between rounds — roughly how many `easy`/`medium`-movable meetings it has. Fresh
  blinding keys each round hide *which* slots changed; the same padding would hide the counts too
  (left out, for parity with the set-size choice above).
- **"Free" needn't hide cost any more.** A plain free/busy set treats every open slot as equally
  available. Part B's tiers express "free, but I'd rather not move this" *structurally* — by the
  round in which a meeting is freed — so cost-awareness needs no explicit cost numbers and no new crypto.
- **Duration/contiguity** is logic over the PSI output, not part of the PSI.
- **Granularity is a dial.** Finer slots give more precision but enlarge the universe and make PSI
  heavier; 15-minute slots over a work-hour window stay small.

## Testing

142 tests, test-driven throughout (`pytest`, with `hypothesis` for properties):

- **Core:** known-answer + edge cases (empty intersection, single slot, all-identical, one party
  free everywhere, the isolated-vs-consecutive **contiguity** case, day-boundary gaps) plus a
  property test against a brute-force oracle.
- **PSI:** a property test asserting `PSI result == plain set intersection` over random N-party
  inputs, order-independence, and a **privacy assertion** — no message except the final result ever
  carries cleartext, and the Output role only ever receives the intersection.
- **Free/busy:** timezones, all-day, tentative vs. accepted, transparency, partial overlap.
- **Google source:** the free/busy → `Event` and event-resource → `Event` mappings (tier from
  extended properties, all-day, status, transparency, RFC3339), the free/busy↔events agreement at
  threshold 0, monotonic relaxation, and displaced-meeting reporting — all via an injected fake client.
- **Pipeline / CLI / HTML:** end-to-end on fixtures, including the no-common-slot path and
  self-containedness / escaping of the report.
- **Part B (tiered relaxation):** the seven documented cases — match in round 1/2/3, impossible,
  multiple-matches-earliest-wins, multi-person sacrifice, monotonicity — a brute-force oracle for the
  winning round, and a **per-round privacy assertion** (every round reveals only its intersection).

```bash
pytest            # tests
ruff check .      # lint
mypy gated_scheduler   # types
```

## Out of scope and future work

Part B v1 deliberately stops short of a few things. **Re-placing the displaced meetings** (where
does the moved 1:1 actually go? — the cascading-reschedule problem) is left to the humans. **How a
meeting gets its tier** is a hand-tagged black box here; the natural next step is an agent that
buckets a calendar into easy/medium/hard from its features and the owner's past behaviour. An
**exact-optimum** variant (explicit secure cost-aggregation for the true minimum total disruption)
is a possible v2 to test against this tiered baseline. **Input honesty / malicious & collusion
resistance**, set-size **padding**, and **natural-language requests** also remain future work.

**Live Google Calendar** is implemented in `sources/google.py` as a **hybrid** of two reads, both
local to a single party's calendar:

- **Availability (Part A)** uses Google's **free/busy API** — busy intervals only, no titles or
  attendees (a privacy win). Each interval becomes a `freebusy.Event` and everything downstream is
  reused unchanged.
- **Relaxation + "what must move" (Part B)** needs detail free/busy can't express, so when a round
  relaxes (`relax_threshold > 0`) the source reads that party's **own events** and maps each to a
  `freebusy.Event`. The reschedule tier comes from the event's private
  `extendedProperties.private.reschedule` (`easy`/`medium`/`hard`); untagged defaults to `hard`,
  exactly like the fixtures.

The Google API client is **injected** (`CalendarClient` protocol), so the mapping logic is fully
unit-tested with hand-built fixtures and no network. The live adapter and `google.oauth2`
credential loading are lazy-imported behind the optional `google` extra:

```bash
pip install 'gated-scheduler[google]'
schedule run --source google \
  --calendars alice@example.com,bob@example.com \
  --credentials service-account.json \
  --window 2026-06-15..2026-06-16 --hours 9-18
```

Because only blinded slot ids ever cross the PSI, swapping fixtures for Google changes nothing about
the privacy guarantee — titles and tiers are read and used **locally**, never aggregated.
