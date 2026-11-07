"""Create (or reset) the demo login for each role through the Supabase Auth admin API."""

from __future__ import annotations

import httpx

ROLES = ["analyst", "finance_ops", "collections", "compliance_manager"]


def demo_email(role: str) -> str:
    return f"{role}@demo.zentry.local"


def ensure_demo_users(supabase_url: str, service_key: str, password: str) -> list[str]:
    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    with httpx.Client(base_url=f"{supabase_url}/auth/v1", headers=headers, timeout=15) as http:
        existing = {u["email"]: u["id"] for u in http.get("/admin/users", params={"per_page": 1000}).json()["users"]}
        emails = []
        for role in ROLES:
            email = demo_email(role)
            body = {"email": email, "password": password, "email_confirm": True, "app_metadata": {"role": role}}
            if email in existing:
                resp = http.put(f"/admin/users/{existing[email]}", json=body)
            else:
                resp = http.post("/admin/users", json=body)
            resp.raise_for_status()
            emails.append(email)
        return emails
