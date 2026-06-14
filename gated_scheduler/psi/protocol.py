"""Multi-party Private Set Intersection via commutative (ECDH) encryption.

The protocol, semi-honest with no collusion:

1. Every party blinds its own free-slot set with its secret key and shuffles it, then the set
   is relayed through every other party, each applying its key. Because blinding commutes, an
   element ``x`` ends up as ``K*H(x)`` (``K`` = product of all keys) regardless of path, so
   equal slots collide -- and ``x`` stays hidden under DDH from everyone else.
2. The fully-blinded sets go to the **Combiner**, which intersects them as opaque points. It
   holds no key and no de-blinding table, so it cannot map points back to slots.
3. The parties also ring-blind the *public* universe (in order) into a table ``K*H(u) -> u``,
   given only to the **Output** role.
4. The Output receives only the common points from the Combiner and uses the table to recover
   the cleartext intersection -- and nothing else.

No entity ever holds all calendars in the clear: parties see only their own; the Combiner sees
only opaque points (plus set sizes, the documented leak); the Output learns only the
intersection. The guarantee rests on the Combiner and Output not colluding.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from gated_scheduler.psi.channel import Channel, Transcript
from gated_scheduler.psi.primitives import blind, hash_to_group

KIND_BLIND_OWN = "blind_own"
KIND_RELAY = "relay"
KIND_SUBMIT = "submit"
KIND_TABLE = "table"
KIND_INTERSECTION = "intersection"
KIND_RESULT = "result"

_RING = "ring"


@dataclass
class Party:
    """A participant: its own secret key and the slots it is free for. Reads no one else."""

    name: str
    key: bytes
    free_slot_ids: frozenset[str]

    def blinded_own_set(self, rng: random.Random) -> list[bytes]:
        """H(id) blinded by this party's key, shuffled to hide the party's own ordering."""
        points = [blind(self.key, hash_to_group(sid.encode())) for sid in self.free_slot_ids]
        rng.shuffle(points)
        return points

    def relay(self, points: list[bytes]) -> list[bytes]:
        """Apply this party's key to points passing through the ring (order-preserving)."""
        return [blind(self.key, p) for p in points]


@dataclass
class Combiner:
    """Computes the intersection of fully-blinded sets. Holds no key and no table."""

    name: str = "Combiner"

    def intersect(self, blinded_sets: list[list[bytes]]) -> list[bytes]:
        if not blinded_sets:
            return []
        common = set(blinded_sets[0])
        for other in blinded_sets[1:]:
            common &= set(other)
        return list(common)


@dataclass
class Output:
    """Recovers cleartext slots from common points using the public-universe table.

    Receives only the intersection, so it learns only the intersection."""

    name: str = "Output"

    def recover(self, common_points: list[bytes], table: dict[bytes, str]) -> set[str]:
        return {table[p] for p in common_points if p in table}


@dataclass
class PsiOutcome:
    common_slot_ids: frozenset[str]
    transcript: Transcript
    party_set_sizes: dict[str, int] = field(default_factory=dict)


def run_psi(
    parties: list[Party],
    universe_slot_ids: list[str],
    *,
    combiner: Combiner | None = None,
    output: Output | None = None,
    channel: Channel | None = None,
    rng: random.Random | None = None,
) -> PsiOutcome:
    """Run the multi-party PSI and return the common slots plus a full message transcript."""
    if len(parties) < 2:
        raise ValueError("PSI needs at least two parties")
    combiner = combiner or Combiner()
    output = output or Output()
    channel = channel or Channel()
    rng = rng or random.SystemRandom()

    # 1. Each party's set is blinded by its owner, then relayed through every other party.
    fully_blinded: list[list[bytes]] = []
    for owner in parties:
        points = owner.blinded_own_set(rng)
        channel.send(
            owner.name,
            _RING,
            KIND_BLIND_OWN,
            f"{owner.name} blinds its {len(points)} free slots with its own key",
            payload_points=tuple(points),
        )
        for other in parties:
            if other is owner:
                continue
            points = other.relay(points)
            channel.send(
                other.name,
                _RING,
                KIND_RELAY,
                f"{other.name} re-blinds {owner.name}'s set with its key",
                payload_points=tuple(points),
            )
        channel.send(
            owner.name,
            combiner.name,
            KIND_SUBMIT,
            f"{owner.name} submits its fully-blinded set to the Combiner",
            payload_points=tuple(points),
        )
        fully_blinded.append(points)

    # 2. Combiner intersects the opaque sets.
    common = combiner.intersect(fully_blinded)
    channel.send(
        combiner.name,
        output.name,
        KIND_INTERSECTION,
        f"Combiner finds {len(common)} blinded point(s) common to all parties",
        payload_points=tuple(common),
    )

    # 3. Parties ring-blind the public universe (in order) into the Output's de-blinding table.
    universe_points = [hash_to_group(u.encode()) for u in universe_slot_ids]
    for party in parties:
        universe_points = party.relay(universe_points)
    table = dict(zip(universe_points, universe_slot_ids, strict=True))
    channel.send(
        _RING,
        output.name,
        KIND_TABLE,
        f"Parties hand the Output a blinded table of the {len(table)} public slots",
        payload_points=tuple(universe_points),
    )

    # 4. Output recovers only the intersection.
    common_ids = output.recover(common, table)
    channel.send(
        output.name,
        "everyone",
        KIND_RESULT,
        f"Output reveals the {len(common_ids)} common slot(s) to everyone",
        payload_slots=tuple(sorted(common_ids)),
    )

    return PsiOutcome(
        common_slot_ids=frozenset(common_ids),
        transcript=channel.transcript,
        party_set_sizes={p.name: len(p.free_slot_ids) for p in parties},
    )
