"""Grounding check for agent output: every transaction or account id the agent cites must exist in
the database AND must have been returned by one of its tool calls in this run."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import psycopg

from .tools import ACCT_RE, TXN_RE


@dataclass
class Validation:
    ok: bool
    cited: list[str] = field(default_factory=list)
    missing_in_db: list[str] = field(default_factory=list)
    not_from_tools: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def cited_ids(report: dict) -> set[str]:
    text = json.dumps(report, ensure_ascii=False)
    return set(TXN_RE.findall(text)) | set(ACCT_RE.findall(text))


def validate(conn: psycopg.Connection, report: dict, seen_ids: set[str]) -> Validation:
    ids = cited_ids(report)
    txns = [i for i in ids if i.startswith("TX")]
    accts = [i for i in ids if i.startswith("A")]
    found: set[str] = set()
    if txns:
        found |= {r[0] for r in conn.execute("select id from public.transactions where id = any(%s)", (txns,))}
    if accts:
        found |= {r[0] for r in conn.execute("select id from public.accounts where id = any(%s)", (accts,))}
    missing = sorted(ids - found)
    ungrounded = sorted(ids - seen_ids)
    return Validation(not missing and not ungrounded, sorted(ids), missing, ungrounded)
