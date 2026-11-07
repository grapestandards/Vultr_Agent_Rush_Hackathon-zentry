"""EventBus: the only way services publish/consume events, so NATS JetStream can be swapped for
Vultr Managed Kafka without touching business logic."""

from __future__ import annotations

import json
import zlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

import nats
from nats.js.api import RetentionPolicy, StorageType, StreamConfig

N_SHARDS = 8
TXN_STREAM = "TXN"
DEDUP_WINDOW_S = 2 * 60 * 60
MAX_DELIVER = 5

STREAMS = [
    StreamConfig(name=TXN_STREAM, subjects=["txn.raw.*", "txn.dlq"], storage=StorageType.FILE,
                 retention=RetentionPolicy.LIMITS, max_age=7 * 24 * 3600, duplicate_window=DEDUP_WINDOW_S),
    StreamConfig(name="EVENTS", subjects=["txn.scored", "alerts.new", "recon.files", "jobs.>", "train.logs.>"],
                 storage=StorageType.FILE, max_age=7 * 24 * 3600, duplicate_window=DEDUP_WINDOW_S),
]


def shard_of(account_id: str) -> int:
    """Stable across processes (unlike hash())."""
    return zlib.crc32(account_id.encode()) % N_SHARDS


def txn_subject(account_id: str) -> str:
    return f"txn.raw.{shard_of(account_id)}"


@dataclass
class Message:
    subject: str
    data: dict[str, Any]
    msg_id: str | None
    deliveries: int
    _raw: Any

    async def ack(self) -> None:
        await self._raw.ack()

    async def nak(self, delay_s: float = 1.0) -> None:
        await self._raw.nak(delay=delay_s)


class EventBus(Protocol):
    async def publish(self, subject: str, data: dict[str, Any], msg_id: str | None = None) -> bool:
        """Returns False when the broker dropped it as a duplicate of msg_id."""

    def consume(self, subject: str, durable: str, batch: int = 500) -> AsyncIterator[list[Message]]: ...

    async def close(self) -> None: ...


class NatsEventBus:
    def __init__(self, nc: nats.NATS) -> None:
        self.nc = nc
        self.js = nc.jetstream()

    @classmethod
    async def connect(cls, url: str, name: str, creds: str | None = None) -> NatsEventBus:
        nc = await nats.connect(url, name=name, user_credentials=creds or None)
        bus = cls(nc)
        await bus.ensure_streams()
        return bus

    async def ensure_streams(self) -> None:
        for cfg in STREAMS:
            try:
                await self.js.add_stream(cfg)
            except nats.js.errors.BadRequestError:
                await self.js.update_stream(cfg)

    async def publish(self, subject: str, data: dict[str, Any], msg_id: str | None = None) -> bool:
        headers = {"Nats-Msg-Id": msg_id} if msg_id else None
        ack = await self.js.publish(subject, json.dumps(data, default=str).encode(), headers=headers)
        return not ack.duplicate

    async def consume(self, subject: str, durable: str, batch: int = 500) -> AsyncIterator[list[Message]]:
        from nats.js.api import ConsumerConfig

        sub = await self.js.pull_subscribe(subject, durable=durable,
                                           config=ConsumerConfig(max_deliver=MAX_DELIVER, ack_wait=60))
        while True:
            try:
                raw = await sub.fetch(batch, timeout=1)
            except nats.errors.TimeoutError:
                continue
            yield [
                Message(m.subject, json.loads(m.data), (m.headers or {}).get("Nats-Msg-Id"),
                        m.metadata.num_delivered, m)
                for m in raw
            ]

    async def close(self) -> None:
        await self.nc.drain()
