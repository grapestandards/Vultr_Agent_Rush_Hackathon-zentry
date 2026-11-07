"""Zentry worker: outbox relay, scoring consumer, investigator (select with WORKER_TASKS)."""

import asyncio
import logging
import os
from pathlib import Path

from zt_core.events import NatsEventBus
from zt_core.settings import env

from .investigate_jobs import run_investigator
from .relay import run_relay
from .scorer import run_scorer

log = logging.getLogger("zt_worker")


async def run() -> None:
    tasks = {t.strip() for t in os.environ.get("WORKER_TASKS", "relay,scorer,investigator").split(",") if t.strip()}
    bus = await NatsEventBus.connect(env("NATS_URL"), "zt-worker", os.environ.get("NATS_CREDS"))
    database_url = env("DATABASE_URL")
    jobs = []
    if "relay" in tasks:
        jobs.append(run_relay(bus, database_url))
    if "scorer" in tasks:
        jobs.append(run_scorer(bus, database_url, Path(os.environ.get("MODEL_ROOT", "."))))
    if "investigator" in tasks:
        jobs.append(run_investigator(bus, database_url))
    log.info("worker started: %s", sorted(tasks))
    try:
        await asyncio.gather(*jobs)
    finally:
        await bus.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
