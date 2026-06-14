from hypothesis import given, settings
from hypothesis import strategies as st

from gated_scheduler.psi.primitives import random_scalar
from gated_scheduler.psi.protocol import (
    KIND_INTERSECTION,
    KIND_RESULT,
    KIND_SUBMIT,
    Party,
    run_psi,
)


def make_parties(sets: dict[str, set[str]]) -> list[Party]:
    return [Party(name=n, key=random_scalar(), free_slot_ids=frozenset(s)) for n, s in sets.items()]


def test_two_party_intersection() -> None:
    universe = [f"slot-{i}" for i in range(6)]
    parties = make_parties(
        {"Alice": {"slot-1", "slot-2", "slot-3"}, "Bob": {"slot-2", "slot-3", "slot-4"}}
    )
    outcome = run_psi(parties, universe)
    assert outcome.common_slot_ids == {"slot-2", "slot-3"}


def test_three_party_intersection() -> None:
    universe = [f"slot-{i}" for i in range(6)]
    parties = make_parties(
        {
            "Alice": {"slot-1", "slot-2", "slot-3"},
            "Bob": {"slot-2", "slot-3", "slot-4"},
            "Carol": {"slot-3", "slot-2", "slot-5"},
        }
    )
    outcome = run_psi(parties, universe)
    assert outcome.common_slot_ids == {"slot-2", "slot-3"}


def test_empty_intersection() -> None:
    universe = [f"slot-{i}" for i in range(6)]
    parties = make_parties({"Alice": {"slot-1"}, "Bob": {"slot-2"}})
    outcome = run_psi(parties, universe)
    assert outcome.common_slot_ids == set()


def test_all_identical_sets() -> None:
    universe = [f"slot-{i}" for i in range(6)]
    common = {"slot-1", "slot-3", "slot-5"}
    parties = make_parties({"Alice": set(common), "Bob": set(common), "Carol": set(common)})
    outcome = run_psi(parties, universe)
    assert outcome.common_slot_ids == common


def test_one_party_free_everywhere() -> None:
    universe = [f"slot-{i}" for i in range(6)]
    parties = make_parties(
        {
            "Alice": set(universe),  # free in every slot
            "Bob": {"slot-2", "slot-4"},
            "Carol": {"slot-2", "slot-4", "slot-5"},
        }
    )
    outcome = run_psi(parties, universe)
    assert outcome.common_slot_ids == {"slot-2", "slot-4"}


def test_single_common_slot() -> None:
    universe = [f"slot-{i}" for i in range(8)]
    parties = make_parties(
        {"Alice": {"slot-1", "slot-7"}, "Bob": {"slot-7", "slot-3"}, "Carol": {"slot-7", "slot-5"}}
    )
    outcome = run_psi(parties, universe)
    assert outcome.common_slot_ids == {"slot-7"}


def test_result_independent_of_party_order() -> None:
    universe = [f"slot-{i}" for i in range(6)]
    sets = {
        "Alice": {"slot-1", "slot-2"},
        "Bob": {"slot-2", "slot-3"},
        "Carol": {"slot-2", "slot-5"},
    }
    forward = run_psi(make_parties(sets), universe).common_slot_ids
    backward = run_psi(list(reversed(make_parties(sets))), universe).common_slot_ids
    assert forward == backward == {"slot-2"}


def test_reports_party_set_sizes() -> None:
    universe = [f"slot-{i}" for i in range(6)]
    parties = make_parties({"Alice": {"slot-1", "slot-2", "slot-3"}, "Bob": {"slot-2"}})
    outcome = run_psi(parties, universe)
    assert outcome.party_set_sizes == {"Alice": 3, "Bob": 1}


# --- privacy guarantees ---


def test_only_the_final_result_travels_in_cleartext() -> None:
    universe = [f"slot-{i}" for i in range(6)]
    parties = make_parties(
        {"Alice": {"slot-1", "slot-2", "slot-3"}, "Bob": {"slot-2", "slot-3", "slot-4"}}
    )
    outcome = run_psi(parties, universe)
    cleartext = outcome.transcript.cleartext_messages()
    assert len(cleartext) == 1
    assert cleartext[0].kind == KIND_RESULT
    assert set(cleartext[0].payload_slots) == outcome.common_slot_ids
    # every other message carries only opaque blinded points
    for message in outcome.transcript.messages:
        if message.kind != KIND_RESULT:
            assert message.payload_slots == ()


def test_output_role_only_receives_the_intersection_not_full_sets() -> None:
    universe = [f"slot-{i}" for i in range(8)]
    parties = make_parties(
        {
            "Alice": {"slot-1", "slot-2", "slot-3", "slot-6"},
            "Bob": {"slot-2", "slot-3", "slot-6", "slot-7"},
            "Carol": {"slot-3", "slot-6", "slot-2", "slot-5"},
        }
    )
    outcome = run_psi(parties, universe)
    intersection_msgs = [m for m in outcome.transcript.messages if m.kind == KIND_INTERSECTION]
    assert len(intersection_msgs) == 1
    # the Combiner forwards only the common points to the Output -- not any full party set
    assert len(intersection_msgs[0].payload_points) == len(outcome.common_slot_ids)
    # fully-blinded party sets are only ever submitted to the Combiner, never the Output
    submit_msgs = [m for m in outcome.transcript.messages if m.kind == KIND_SUBMIT]
    assert submit_msgs
    assert all(m.receiver == "Combiner" for m in submit_msgs)


# --- property-based correctness ---


@settings(max_examples=60, deadline=None)
@given(
    subsets=st.lists(
        st.sets(st.integers(min_value=0, max_value=15)),
        min_size=2,
        max_size=4,
    )
)
def test_psi_equals_plain_intersection(subsets: list[set[int]]) -> None:
    universe = [f"slot-{i:02d}" for i in range(16)]
    parties = [
        Party(name=f"P{j}", key=random_scalar(), free_slot_ids=frozenset(universe[i] for i in s))
        for j, s in enumerate(subsets)
    ]
    outcome = run_psi(parties, universe)
    expected = set.intersection(*({universe[i] for i in s} for s in subsets))
    assert outcome.common_slot_ids == expected
