"""Zentry API: health, transaction ingest, case investigation and decisions."""

from contextlib import asynccontextmanager
from typing import Literal

import nats
import psycopg
from fastapi import FastAPI, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt

from zt_core.events import NatsEventBus
from zt_core.ingest import ingest_transactions
from zt_core.settings import env

from .cases import router as cases_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.bus = await NatsEventBus.connect(env("NATS_URL"), "zt-api")
    yield
    await app.state.bus.close()


app = FastAPI(title="Zentry API", version="0.1.0", lifespan=lifespan)
app.include_router(cases_router)


@app.get("/healthz")
async def healthz(response: Response) -> dict:
    checks: dict[str, str] = {}
    try:
        async with await psycopg.AsyncConnection.connect(env("DATABASE_URL"), connect_timeout=3) as conn:
            await conn.execute("select 1")
        checks["db"] = "ok"
    except Exception as e:  # noqa: BLE001 — report any failure as unhealthy
        checks["db"] = f"error: {e.__class__.__name__}"
    try:
        nc = await nats.connect(env("NATS_URL"), connect_timeout=3, max_reconnect_attempts=0)
        await nc.close()
        checks["nats"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["nats"] = f"error: {e.__class__.__name__}"
    if any(v != "ok" for v in checks.values()):
        response.status_code = 503
    return checks


class TransactionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    from_account: str
    to_account: str
    amount_satang: StrictInt = Field(gt=0, description="integer satang; floats are rejected")
    channel: Literal["promptpay", "transfer", "qr"]
    ref_no: str
    ts: AwareDatetime
    device_id: str | None = None


class IngestRequest(BaseModel):
    transactions: list[TransactionIn] = Field(min_length=1, max_length=5000)


@app.post("/ingest/transactions")
def ingest(req: IngestRequest) -> dict:
    """Ledger insert + outbox event in one DB transaction. Re-sending an id is a no-op."""
    with psycopg.connect(env("DATABASE_URL")) as conn:
        inserted = ingest_transactions(conn, [t.model_dump() for t in req.transactions])
    return {"received": len(req.transactions), "inserted": len(inserted),
            "duplicates": len(req.transactions) - len(inserted)}
