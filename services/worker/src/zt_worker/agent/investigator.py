"""Investigator agent (W1 steps 4–5).

Two interchangeable planners share the same tools, validator and persistence:
- `llm`: OpenAI-compatible tool calling on Vultr Serverless Inference (needs VULTR_INFERENCE_API_KEY + LLM_MODEL)
- `offline`: a deterministic planner that calls the same tools and writes the report from templates
A report whose ids fail validation is stored for audit but never shown as the case summary.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import Counter, defaultdict
from typing import Any

import psycopg

from zt_core.money import format_thb

from .tools import SCHEMAS, Tools, ToolError, as_jsonable
from .validator import validate

log = logging.getLogger("zt_worker.investigator")

MAX_TOOL_CALLS = 15

SYSTEM_PROMPT = """You are Zentry's AML investigator for a Thai e-wallet. All data is synthetic.
Investigate the case using the tools. Start with get_case, then look at the alerted accounts,
expand the transfer graph, screen names, and check typologies.

Rules:
- Cite only transaction ids (TX...) and account ids (A...) that tools returned. Never invent ids.
- You cannot change data. Use propose_action for each recommendation; a human decides.
- Be factual and brief. Amounts in baht.

Finish with a single JSON object, no prose around it:
{"title": str, "summary": str (3-5 sentences), "typology": str, "risk_level": "low|medium|high|critical",
 "involved_accounts": [{"id": str, "role": "victim|collector|layer|cash-out|unknown", "note": str}],
 "key_transactions": [str], "money_trail": str,
 "recommendation": {"action": "close|escalate|recommend_freeze|file_str", "rationale": str},
 "str_draft": str}"""


# --------------------------------------------------------------------------- LLM planner
def run_llm(tools: Tools) -> tuple[dict, list[dict], str, list[dict]]:
    from openai import OpenAI

    model = os.environ["LLM_MODEL"]
    client = OpenAI(base_url=os.environ.get("VULTR_INFERENCE_BASE_URL", "https://api.vultrinference.com/v1"),
                    api_key=os.environ["VULTR_INFERENCE_API_KEY"], timeout=90)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Investigate case {tools.case_id}."},
    ]
    trace: list[dict] = []
    calls = 0
    while True:
        budget_left = calls < MAX_TOOL_CALLS
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0.2,
                                              tools=SCHEMAS if budget_left else None)
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if msg.tool_calls and budget_left:
            for tc in msg.tool_calls:
                calls += 1
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    out = tools.call(tc.function.name, args)
                except (ToolError, json.JSONDecodeError, TypeError) as e:
                    args, out = {}, {"error": str(e)}
                trace.append({"tool": tc.function.name, "args": args})
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(as_jsonable(out), ensure_ascii=False)[:12_000]})
            if calls >= MAX_TOOL_CALLS:
                messages.append({"role": "user", "content": "Tool budget used up. Write the final JSON now."})
            continue
        report = _parse_json(msg.content or "")
        return report, trace, model, messages


def repair_llm(messages: list[dict], problems: dict) -> dict:
    from openai import OpenAI

    client = OpenAI(base_url=os.environ.get("VULTR_INFERENCE_BASE_URL"), api_key=os.environ["VULTR_INFERENCE_API_KEY"])
    messages.append({"role": "user", "content":
                     "Your report cites ids that do not exist or that no tool returned: "
                     f"{problems['missing_in_db'] + problems['not_from_tools']}. Rewrite the JSON citing only "
                     "ids from tool results."})
    resp = client.chat.completions.create(model=os.environ["LLM_MODEL"], messages=messages, temperature=0)
    return _parse_json(resp.choices[0].message.content or "")


def _parse_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("model did not return JSON")
    return json.loads(text[start:end + 1])


# --------------------------------------------------------------------------- offline planner
def run_offline(tools: Tools) -> tuple[dict, list[dict], str, None]:
    trace: list[dict] = []

    def call(tool: str, **args: Any) -> dict:
        trace.append({"tool": tool, "args": args})
        return tools.call(tool, args)

    case = call("get_case")
    alerts = sorted(case["alerts"], key=lambda a: -a["score"])
    alerted = list(dict.fromkeys(a["account_id"] for a in alerts))
    histories = {a: call("get_account_history", account_id=a, days=7) for a in alerted[:4]}
    # expand from several flagged accounts and union: one hub rarely reaches the whole ring in 2 hops
    graph = {"accounts": [], "transfers": []}
    seen_nodes: dict[str, Any] = {}
    seen_edges: dict[str, dict] = {}
    for start in alerted[:3]:
        g = call("expand_graph", account_id=start, hops=2, hours=96)
        seen_nodes.update({n["id"]: n for n in g["accounts"]})
        seen_edges.update({t["id"]: t for t in g["transfers"]})
    graph = {"accounts": list(seen_nodes.values()), "transfers": list(seen_edges.values())}
    screens = {a: call("screen_name", name=h["account"]["name_en"]) for a, h in histories.items()}
    typology = call("search_typology", query="mule layering pass-through new account shared device scam")
    call("similar_cases")

    # only this case's accounts: rings share cash-out merchants, so 2 hops can reach other rings
    flagged = set(alerted)
    transfers = graph["transfers"]
    entry = [t for t in transfers if t["from"] not in flagged and t["to"] in flagged]
    exits = [t for t in transfers if t["from"] in flagged and t["to"] not in flagged]
    inside = [t for t in transfers if t["from"] in flagged and t["to"] in flagged]
    balance: dict[str, int] = defaultdict(int)
    for t in transfers:
        if t["to"] in flagged:
            balance[t["to"]] += t["amount_satang"]
        if t["from"] in flagged:
            balance[t["from"]] -= t["amount_satang"]
    entry_total = sum(t["amount_satang"] for t in entry)
    exit_total = sum(t["amount_satang"] for t in exits)
    holding = sorted(((a, b) for a, b in balance.items() if b > 0), key=lambda x: -x[1])
    residual = max(0, entry_total - exit_total)  # conservation: what came in and hasn't left the network
    senders = sorted({t["from"] for t in entry})
    cash_out = Counter(t["to"] for t in exits).most_common(3)
    key_txns = [t["id"] for t in sorted(entry, key=lambda t: -t["amount_satang"])[:5]] + \
               [t["id"] for t in sorted(exits, key=lambda t: -t["amount_satang"])[:3]]

    devices = Counter(t["device_id"] for h in histories.values() for t in h["transactions"]
                      if t["direction"] == "out" and t["device_id"])
    shared_device = [d for d, n in devices.items() if n > 1 and
                     sum(1 for h in histories.values() if any(t["device_id"] == d for t in h["transactions"])) > 1]
    young = [a for a, h in histories.items() if (time.time() - h["account"]["opened_at"].timestamp()) / 86400 < 60]
    watch_hits = {a: s["matches"][0] for a, s in screens.items() if s["matches"]}
    top_typology = typology["documents"][0]["id"] if typology["documents"] else "unknown"

    n = len(flagged)
    risk = "critical" if n >= 5 and residual > 0 else "high" if n >= 2 or alerts[0]["score"] >= 90 else "medium"
    roles = []
    for a in sorted(flagged):
        received_from_outside = any(t["to"] == a for t in entry)
        sent_outside = any(t["from"] == a for t in exits)
        role = "collector" if received_from_outside else "cash-out" if sent_outside else "layer"
        roles.append({"id": a, "role": role, "note": f"holds {format_thb(balance[a])}" if balance[a] > 0 else ""})
    roles += [{"id": s, "role": "victim", "note": "unflagged sender into the network"} for s in senders[:10]]

    summary = (
        f"{n} linked accounts around {alerted[0]} show a layered mule pattern. "
        f"{len(senders)} unflagged senders paid {format_thb(entry_total)} into the network, which moved it on "
        f"through {len(inside)} internal transfers; {format_thb(exit_total)} left to "
        f"{', '.join(a for a, _ in cash_out) or 'no outside accounts yet'}. "
        f"About {format_thb(residual)} is still held in {len(holding)} flagged accounts"
        f"{' (largest: ' + ', '.join(f'{a} {format_thb(b)}' for a, b in holding[:3]) + ')' if holding else ''}. "
        + (f"{len(young)} of the reviewed accounts are under 60 days old. " if young else "")
        + ("Several accounts were operated from the same device. " if shared_device else "")
        + (f"Watchlist match: {', '.join(watch_hits)}. " if watch_hits else "No watchlist matches.")
    )
    action = "recommend_freeze" if residual > 0 and n >= 2 else "escalate"
    rationale = (f"Funds are still held in {', '.join(a for a, _ in holding[:5])}; freezing them preserves "
                 f"{format_thb(residual)} for victims." if action == "recommend_freeze"
                 else "Pattern matches mule layering but no recoverable balance was found; escalate for review.")
    evidence = [a for a, _ in holding[:5]] + key_txns[:5]
    call("propose_action", action=action, rationale=rationale, evidence=evidence)
    if n >= 2:
        call("propose_action", action="file_str", rationale="Network-level suspicious activity report.",
             evidence=sorted(flagged)[:10] + key_txns[:5])

    str_draft = "\n".join([
        "SUSPICIOUS TRANSACTION REPORT — DRAFT (synthetic data, for review)",
        f"Case: {tools.case_id}",
        f"Subject accounts: {', '.join(sorted(flagged))}",
        f"Typology: {top_typology.replace('-', ' ')}",
        "",
        "Grounds for suspicion:",
        f"- {len(senders)} unrelated senders transferred {format_thb(entry_total)} into newly opened accounts.",
        f"- Funds were forwarded within minutes through {len(inside)} internal transfers (pass-through).",
        f"- {format_thb(exit_total)} was paid out to {', '.join(a for a, _ in cash_out) or 'n/a'}.",
        *(["- Multiple subject accounts operated from a shared device."] if shared_device else []),
        "",
        "Key transactions: " + ", ".join(key_txns),
        f"Funds still held: {format_thb(residual)}",
        "",
        "Action taken: pending analyst decision.",
    ])
    report = {
        "title": f"Mule network · {n} accounts · {format_thb(entry_total)} in",
        "summary": summary, "typology": top_typology, "risk_level": risk,
        "involved_accounts": roles, "key_transactions": key_txns,
        "money_trail": f"in {format_thb(entry_total)} → out {format_thb(exit_total)} → held {format_thb(residual)}",
        "recommendation": {"action": action, "rationale": rationale},
        "str_draft": str_draft,
    }
    return report, trace, "offline", None


# --------------------------------------------------------------------------- entrypoint
def llm_configured() -> bool:
    return bool(os.environ.get("VULTR_INFERENCE_API_KEY") and os.environ.get("LLM_MODEL"))


def investigate(database_url: str, case_id: str) -> dict:
    with psycopg.connect(database_url) as conn:
        tools = Tools(conn, case_id)
        mode = "llm" if llm_configured() else "offline"
        t0 = time.time()
        if mode == "llm":
            report, trace, model, messages = run_llm(tools)
        else:
            report, trace, model, messages = run_offline(tools)
        validation = validate(conn, report, tools.seen_ids)
        if not validation.ok and mode == "llm":
            report = repair_llm(messages, validation.as_dict())
            validation = validate(conn, report, tools.seen_ids)
        persist(conn, case_id, report, validation.as_dict(), tools.proposals, trace, mode, model, time.time() - t0)
        log.info("case %s investigated (%s) valid=%s tool_calls=%d", case_id, mode, validation.ok, len(trace))
        return {"case_id": case_id, "mode": mode, "valid": validation.ok, "tool_calls": len(trace)}


def persist(conn: psycopg.Connection, case_id: str, report: dict, validation: dict, proposals: list[dict],
            trace: list[dict], mode: str, model: str, seconds: float) -> None:
    ok = validation["ok"]
    agent_report = {**report, "mode": mode, "model": model, "validation": validation,
                    "tool_calls": trace, "seconds": round(seconds, 1)}
    with conn.transaction():
        before = conn.execute("select status, ai_summary, risk_level from public.cases where id = %s",
                              (case_id,)).fetchone()
        conn.execute("""
            update public.cases set
              agent_report = %(r)s, investigated_at = now(), updated_at = now(),
              ai_summary = case when %(ok)s then %(summary)s else null end,
              title = case when %(ok)s then %(title)s else title end,
              risk_level = case when %(ok)s then %(risk)s else risk_level end,
              str_draft = case when %(ok)s and str_approved_at is null then %(str)s else str_draft end,
              status = case when status = 'open' then 'in_review' else status end
            where id = %(id)s""",
                     {"r": json.dumps(as_jsonable(agent_report), ensure_ascii=False), "ok": ok,
                      "summary": report.get("summary"), "title": report.get("title"),
                      "risk": report.get("risk_level"), "str": report.get("str_draft"), "id": case_id})
        if ok:  # proposals only reach analysts when every cited id is grounded
            conn.execute("update public.case_proposals set status = 'rejected' where case_id = %s and status = 'pending'",
                         (case_id,))
            for p in proposals:
                conn.execute("insert into public.case_proposals (case_id, action, rationale, evidence) values (%s, %s, %s, %s)",
                             (case_id, p["action"], p["rationale"], json.dumps(p["evidence"])))
        conn.execute("""insert into public.audit_log (actor, action, object_ref, before_json, after_json)
                        values ('agent:investigator', 'investigate', %s, %s, %s)""",
                     (f"case:{case_id}", json.dumps({"status": before[0], "risk_level": before[2]} if before else None),
                      json.dumps(as_jsonable({"mode": mode, "model": model, "system_prompt": SYSTEM_PROMPT if mode == "llm" else None,
                                              "tool_calls": trace, "report": report, "validation": validation,
                                              "proposals": proposals}), ensure_ascii=False)))
