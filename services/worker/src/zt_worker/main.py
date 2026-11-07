"""Zentry worker. M1: connects to NATS JetStream and stays up; consumers arrive in M2."""

import asyncio
import logging
import signal

import nats

from zt_core.settings import env

log = logging.getLogger("zt_worker")


async def run() -> None:
    nc = await nats.connect(env("NATS_URL"), name="zt-worker")
    js = nc.jetstream()
    info = await js.account_info()
    log.info("connected to NATS JetStream (streams=%s)", info.streams)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await nc.drain()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
