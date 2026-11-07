"""Delete the JetStream streams so a fresh replay isn't swallowed by the dedup window
(transaction ids are deterministic). The worker recreates them on start."""

import asyncio
import os

import nats

from zt_core.events import STREAMS


async def main() -> None:
    nc = await nats.connect(os.environ.get("NATS_URL", "nats://127.0.0.1:4222"))
    js = nc.jetstream()
    for cfg in STREAMS:
        try:
            await js.delete_stream(cfg.name)
            print(f"deleted stream {cfg.name}")
        except nats.js.errors.NotFoundError:
            pass
    await nc.close()


asyncio.run(main())
