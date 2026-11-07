"""Caller identity: the browser session's Supabase JWT, verified by Supabase Auth (not just decoded)."""

from dataclasses import dataclass

import httpx
from fastapi import Header, HTTPException

from zt_core.settings import env


@dataclass(frozen=True)
class User:
    id: str
    email: str
    role: str

    @property
    def actor(self) -> str:
        return f"user:{self.id}"


async def current_user(authorization: str = Header(default="")) -> User:
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "missing bearer token")
    async with httpx.AsyncClient(timeout=5) as http:
        r = await http.get(f"{env('SUPABASE_URL')}/auth/v1/user",
                           headers={"Authorization": f"Bearer {token}", "apikey": env("PUBLIC_SUPABASE_ANON_KEY")})
    if r.status_code != 200:
        raise HTTPException(401, "invalid session")
    body = r.json()
    return User(body["id"], body.get("email", ""), (body.get("app_metadata") or {}).get("role", ""))


def require(user: User, *roles: str) -> None:
    if user.role not in roles and user.role != "admin":
        raise HTTPException(403, f"role {user.role or 'none'} cannot do this")
