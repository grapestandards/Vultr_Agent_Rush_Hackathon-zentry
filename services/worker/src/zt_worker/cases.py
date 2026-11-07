"""Case builder (W1 step 3): alerts on the same account — or on accounts that transacted with each
other in the last 72h — are grouped into one open mule case. When a new alert connects several
open cases (two collectors feeding the same layer-2 mule), those cases are merged into the oldest."""

from __future__ import annotations

import psycopg

LINK_WINDOW = "72 hours"


async def attach_to_cases(cur: psycopg.AsyncCursor, alert_ids: list[str]) -> list[str]:
    """Link new alerts to cases; returns ids of cases that changed (new, grown or merged)."""
    changed: list[str] = []
    await cur.execute("select id, account_id, txn_ts from public.alerts where id = any(%s) order by txn_ts", (alert_ids,))
    for alert_id, account, ts in await cur.fetchall():
        await cur.execute("""
            select distinct l.case_id, c.created_at from public.case_links l join public.cases c on c.id = l.case_id
            where c.type = 'mule' and c.status not in ('closed', 'escalated') and (l.account_id = %(a)s or l.account_id in (
                select to_account from public.transactions
                  where from_account = %(a)s and ts between %(ts)s - interval '72 hours' and %(ts)s
                union
                select from_account from public.transactions
                  where to_account = %(a)s and ts between %(ts)s - interval '72 hours' and %(ts)s))
            order by c.created_at""", {"a": account, "ts": ts})
        found = [r[0] for r in await cur.fetchall()]
        if found:
            case_id, others = found[0], found[1:]
            for other in others:  # merge into the oldest case
                await cur.execute("""insert into public.case_links (case_id, alert_id, account_id, transaction_id)
                                     select %s, alert_id, account_id, transaction_id from public.case_links
                                     where case_id = %s and (account_id is null or account_id not in
                                       (select account_id from public.case_links where case_id = %s and account_id is not null))""",
                                  (case_id, other, case_id))
                await cur.execute("delete from public.case_proposals where case_id = %s", (other,))
                await cur.execute("delete from public.cases where id = %s", (other,))
                await cur.execute("""insert into public.audit_log (actor, action, object_ref, after_json)
                                     values ('agent:case_builder', 'merge_case', %s, %s)""",
                                  (f"case:{case_id}", f'{{"merged": "{other}"}}'))
        else:
            await cur.execute("""insert into public.cases (type, status, title) values ('mule', 'open', %s)
                                 returning id""", (f"Possible mule activity around {account}",))
            case_id = (await cur.fetchone())[0]
        await cur.execute("insert into public.case_links (case_id, alert_id) values (%s, %s)", (case_id, alert_id))
        await cur.execute("""insert into public.case_links (case_id, account_id)
                             select %(c)s, %(a)s where not exists (select 1 from public.case_links
                             where case_id = %(c)s and account_id = %(a)s)""", {"c": case_id, "a": account})
        await cur.execute("update public.alerts set status = 'in_case' where id = %s", (alert_id,))
        await cur.execute("update public.cases set updated_at = now() where id = %s", (case_id,))
        changed.append(str(case_id))
    return list(dict.fromkeys(changed))
