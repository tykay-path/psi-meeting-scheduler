"""Thin wrapper over libsodium's ed25519 group operations (via PyNaCl).

Only the cryptographic primitives the PSI protocol needs live here -- nothing about
calendars or the protocol itself. We use libsodium for every primitive and never implement
the math ourselves.

ristretto255 would be the textbook choice (prime-order, no cofactor), but PyNaCl's build does
not expose it. We use ed25519 instead, relying on two libsodium guarantees:

* ``crypto_core_ed25519_from_uniform`` clears the cofactor -- its output is in the
  prime-order subgroup (verified: multiplying it by the subgroup order yields the identity),
  so there are no small-subgroup pitfalls; and
* ``crypto_scalarmult_ed25519_noclamp`` does *unclamped* scalar multiplication. Clamping
  (the default) mangles scalar bits and would break the commutativity the protocol depends on
  (``k1*(k2*P) == k2*(k1*P)``).
"""

from __future__ import annotations

import hashlib
import os

from nacl import bindings as _b

POINT_BYTES: int = _b.crypto_core_ed25519_BYTES
SCALAR_BYTES: int = _b.crypto_core_ed25519_SCALARBYTES
_NONREDUCED_SCALAR_BYTES: int = _b.crypto_core_ed25519_NONREDUCEDSCALARBYTES


def random_scalar() -> bytes:
    """A uniformly random scalar in ``[0, L)`` -- a party's secret blinding key."""
    return _b.crypto_core_ed25519_scalar_reduce(os.urandom(_NONREDUCED_SCALAR_BYTES))


def hash_to_group(data: bytes) -> bytes:
    """Deterministically map bytes to a prime-order group element (hash-to-curve)."""
    uniform = hashlib.sha512(data).digest()[:32]
    return _b.crypto_core_ed25519_from_uniform(uniform)


def blind(scalar: bytes, point: bytes) -> bytes:
    """Multiply ``point`` by ``scalar`` -- the (commutative) blinding operation."""
    if len(scalar) != SCALAR_BYTES:
        raise ValueError(f"scalar must be {SCALAR_BYTES} bytes, got {len(scalar)}")
    if len(point) != POINT_BYTES:
        raise ValueError(f"point must be {POINT_BYTES} bytes, got {len(point)}")
    return _b.crypto_scalarmult_ed25519_noclamp(scalar, point)


def is_valid_point(point: bytes) -> bool:
    """Whether ``point`` is a canonical encoding of a prime-order group element."""
    if len(point) != POINT_BYTES:
        return False
    return bool(_b.crypto_core_ed25519_is_valid_point(point))
