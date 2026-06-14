import pytest

from gated_scheduler.psi.primitives import (
    POINT_BYTES,
    SCALAR_BYTES,
    blind,
    hash_to_group,
    is_valid_point,
    random_scalar,
)


def test_hash_to_group_is_deterministic() -> None:
    assert hash_to_group(b"2026-06-15T14:00:00Z") == hash_to_group(b"2026-06-15T14:00:00Z")


def test_hash_to_group_returns_valid_point_of_expected_size() -> None:
    p = hash_to_group(b"2026-06-15T14:00:00Z")
    assert len(p) == POINT_BYTES == 32
    assert is_valid_point(p)


def test_distinct_inputs_map_to_distinct_points() -> None:
    assert hash_to_group(b"slot-A") != hash_to_group(b"slot-B")


def test_random_scalar_size_and_randomness() -> None:
    s = random_scalar()
    assert len(s) == SCALAR_BYTES == 32
    assert random_scalar() != random_scalar()


def test_blinding_commutes() -> None:
    p = hash_to_group(b"slot-A")
    k1, k2 = random_scalar(), random_scalar()
    assert blind(k2, blind(k1, p)) == blind(k1, blind(k2, p))


def test_blinding_is_deterministic_and_collision_free_under_a_fixed_key() -> None:
    p = hash_to_group(b"slot-A")
    q = hash_to_group(b"slot-B")
    k = random_scalar()
    assert blind(k, p) == blind(k, p)  # deterministic
    assert blind(k, p) != blind(k, q)  # distinct inputs stay distinct
    assert blind(k, p) != p  # it actually hides the input


def test_blinded_point_is_a_valid_point() -> None:
    p = hash_to_group(b"slot-A")
    assert is_valid_point(blind(random_scalar(), p))


def test_is_valid_point_rejects_garbage() -> None:
    assert not is_valid_point(b"\xff" * 32)


def test_blind_rejects_wrong_sized_scalar() -> None:
    with pytest.raises(ValueError):
        blind(b"too-short", hash_to_group(b"slot-A"))


def test_blind_rejects_wrong_sized_point() -> None:
    with pytest.raises(ValueError):
        blind(random_scalar(), b"too-short")
