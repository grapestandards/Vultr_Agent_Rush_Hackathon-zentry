"""Zentry API. M1: health only; case, decision, train and recon routes arrive in later milestones."""

import nats
import psycopg
from fastapi import FastAPI, Response

from zt_core.settings import env

app = FastAPI(title="Zentry API", version="0.1.0")


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
