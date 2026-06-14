"""The communication seam between parties.

Parties never call each other directly; they exchange serialized messages through a
``Channel``. The ``Channel`` records every message on a shared ``Transcript`` -- the single
point where data crosses a trust boundary. That makes two things possible: a faithful demo of
the message flow, and an automated audit that nothing but the final result ever travels in the
clear. This implementation is in-process, but the interface is exactly what a real socket
transport would expose.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Message:
    """One message between roles. Blinded data travels as ``payload_points`` (opaque group
    elements); only the final result is allowed to carry cleartext ``payload_slots``."""

    step: int
    sender: str
    receiver: str
    kind: str
    summary: str
    payload_points: tuple[bytes, ...] = ()
    payload_slots: tuple[str, ...] = ()

    @property
    def reveals_cleartext(self) -> bool:
        return len(self.payload_slots) > 0

    @property
    def size(self) -> int:
        return len(self.payload_points) + len(self.payload_slots)


class Transcript:
    """An ordered log of every message exchanged during a protocol run."""

    def __init__(self) -> None:
        self._messages: list[Message] = []

    def record(
        self,
        sender: str,
        receiver: str,
        kind: str,
        summary: str,
        *,
        payload_points: tuple[bytes, ...] = (),
        payload_slots: tuple[str, ...] = (),
    ) -> Message:
        message = Message(
            step=len(self._messages),
            sender=sender,
            receiver=receiver,
            kind=kind,
            summary=summary,
            payload_points=tuple(payload_points),
            payload_slots=tuple(payload_slots),
        )
        self._messages.append(message)
        return message

    @property
    def messages(self) -> list[Message]:
        return list(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def cleartext_messages(self) -> list[Message]:
        """Every message that carried any cleartext slot -- should only ever be the result."""
        return [m for m in self._messages if m.reveals_cleartext]


@dataclass
class Channel:
    """In-process transport backed by a shared transcript."""

    transcript: Transcript = field(default_factory=Transcript)

    def send(
        self,
        sender: str,
        receiver: str,
        kind: str,
        summary: str,
        *,
        payload_points: tuple[bytes, ...] = (),
        payload_slots: tuple[str, ...] = (),
    ) -> Message:
        return self.transcript.record(
            sender,
            receiver,
            kind,
            summary,
            payload_points=payload_points,
            payload_slots=payload_slots,
        )
