"""Short-lived bearer tokens for training jobs: HMAC over (run id, expiry). A Training VM gets only
this token, never database or storage credentials."""

from __future__ import annotations

import hashlib
import hmac
import os
import time


def _secret() -> bytes:
    explicit = os.environ.get("TRAIN_JOB_SECRET")
    if explicit:
        return explicit.encode()
    # api and worker share .env, so the service key is a stable fallback; it never leaves the server
    return hashlib.sha256(b"zentry-train:" + os.environ["SUPABASE_SERVICE_ROLE_KEY"].encode()).digest()


def sign(run_id: str, ttl_s: int = 45 * 60) -> str:
    exp = int(time.time()) + ttl_s
    mac = hmac.new(_secret(), f"{run_id}.{exp}".encode(), hashlib.sha256).hexdigest()
    return f"{run_id}.{exp}.{mac}"


def verify(token: str, run_id: str) -> bool:
    try:
        rid, exp, mac = token.rsplit(".", 2)
    except ValueError:
        return False
    good = hmac.new(_secret(), f"{rid}.{exp}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, good) and rid == run_id and int(exp) > time.time()
