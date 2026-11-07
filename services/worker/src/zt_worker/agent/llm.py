"""Small helper for the recon and follow-up agents: one JSON-returning chat call on Vultr Serverless
Inference, or None when no key is set (callers then use their deterministic templates)."""

from __future__ import annotations

import json
import os
import re

ID_RE = re.compile(r"\b(?:TX[A-Z0-9]{8,}|ST\d{7}|UP[A-Z0-9-]{6,}|A\d{7}|PP\d{8,}|GW\d{6}A\d{7})\b")


def configured() -> bool:
    return bool(os.environ.get("VULTR_INFERENCE_API_KEY") and os.environ.get("LLM_MODEL"))


def model_name() -> str:
    return os.environ.get("LLM_MODEL", "") if configured() else "offline"


def chat_json(system: str, user: str, temperature: float = 0.2) -> dict | None:
    if not configured():
        return None
    from openai import OpenAI

    client = OpenAI(base_url=os.environ.get("VULTR_INFERENCE_BASE_URL", "https://api.vultrinference.com/v1"),
                    api_key=os.environ["VULTR_INFERENCE_API_KEY"], timeout=90)
    resp = client.chat.completions.create(model=os.environ["LLM_MODEL"], temperature=temperature,
                                          messages=[{"role": "system", "content": system},
                                                    {"role": "user", "content": user}])
    text = resp.choices[0].message.content or ""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def grounded(text: str, allowed: set[str]) -> bool:
    """The text may only cite ids that were in the facts it was given."""
    return set(ID_RE.findall(text)) <= allowed
