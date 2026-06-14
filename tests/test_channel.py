from gated_scheduler.psi.channel import Channel, Message, Transcript


def test_transcript_records_messages_with_sequential_steps() -> None:
    t = Transcript()
    m0 = t.record("Alice", "Bob", "relay", "passed blinded set", payload_points=(b"x" * 32,))
    m1 = t.record("Bob", "Carol", "relay", "passed blinded set", payload_points=(b"y" * 32,))
    assert m0.step == 0
    assert m1.step == 1
    assert [m.step for m in t.messages] == [0, 1]
    assert len(t) == 2


def test_message_reveals_cleartext_only_when_carrying_slots() -> None:
    blinded = Message(0, "Alice", "Bob", "relay", "", payload_points=(b"z" * 32,))
    result = Message(1, "Out", "all", "result", "", payload_slots=("2026-06-15T14:00:00Z",))
    assert not blinded.reveals_cleartext
    assert result.reveals_cleartext


def test_message_size_counts_payload() -> None:
    m = Message(0, "A", "B", "relay", "", payload_points=(b"a" * 32, b"b" * 32))
    assert m.size == 2


def test_transcript_cleartext_messages_filters_to_results() -> None:
    t = Transcript()
    t.record("Alice", "Combiner", "submit", "", payload_points=(b"x" * 32,))
    t.record("Out", "all", "result", "", payload_slots=("slot-1",))
    cleartext = t.cleartext_messages()
    assert len(cleartext) == 1
    assert cleartext[0].kind == "result"


def test_channel_send_records_on_shared_transcript() -> None:
    t = Transcript()
    channel = Channel(t)
    msg = channel.send("Alice", "Bob", "relay", "blinded hop", payload_points=(b"x" * 32,))
    assert t.messages == [msg]
    assert msg.sender == "Alice"
    assert msg.receiver == "Bob"
    assert msg.summary == "blinded hop"
