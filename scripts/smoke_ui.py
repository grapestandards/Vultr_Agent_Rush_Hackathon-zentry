"""Browser smoke test: every page as every demo role, then the tuning form with every option.

    uv run --with playwright python scripts/smoke_ui.py [base_url] [--train]   (default http://localhost:3000)

Fails on HTTP 5xx, uncaught page errors or console errors. --train also starts a real training run
from the form and waits for it to finish (about 3 min locally, 10 min on the VM)."""

from __future__ import annotations

import os
import sys
import time

import psycopg
from playwright.sync_api import Page, sync_playwright

args = [a for a in sys.argv[1:] if not a.startswith("--")]
BASE = (args[0] if args else "http://localhost:3000").rstrip("/")
TRAIN = "--train" in sys.argv
ROLES = ["analyst", "finance_ops", "collections", "compliance_manager"]
PAGES = ["/", "/alerts", "/cases", "/graph", "/recon", "/follow-ups", "/tuning"]

failures: list[str] = []


def ok(cond: bool, what: str) -> None:
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        failures.append(what)


def watch(page: Page, role: str) -> list[str]:
    problems: list[str] = []
    page.on("pageerror", lambda e: problems.append(f"{role} page error: {e}"))
    page.on("console", lambda m: m.type == "error" and "favicon" not in m.text
            and problems.append(f"{role} console: {m.text[:160]}"))
    page.on("response", lambda r: r.status >= 500 and problems.append(f"{role} HTTP {r.status} {r.url}"))
    return problems


def login(page: Page, role: str) -> None:
    page.goto(f"{BASE}/login")
    page.fill("input[name=email]", f"{role}@demo.zentry.local")
    page.fill("input[name=password]", os.environ["DEMO_PASSWORD"])
    page.click("form button:not([type=button])")
    page.wait_for_url(f"{BASE}/")


def sample_ids() -> tuple[str, str]:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        case_id, = conn.execute("select id::text from public.cases order by created_at limit 1").fetchone()
        account, = conn.execute("select account_id from public.case_links where account_id is not null limit 1").fetchone()
    return case_id, account


def main() -> None:
    case_id, account = sample_ids()
    pages = PAGES + [f"/cases/{case_id}", f"/accounts/{account}", f"/graph?account={account}", "/welcome"]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for role in ROLES:
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            problems = watch(page, role)
            login(page, role)
            for path in pages:
                r = page.goto(f"{BASE}{path}")
                page.wait_for_timeout(1200)
                status = r.status if r else 0
                ok(status < 400, f"{role:<18} {path:<40} HTTP {status}")
            ok(not problems, f"{role}: no errors" + ("" if not problems else " — " + "; ".join(problems[:5])))
            ctx.close()

        # tuning form, as the model owner
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        problems = watch(page, "tuning")
        login(page, "compliance_manager")
        page.goto(f"{BASE}/tuning")
        boxes = page.locator("input[type=checkbox][name^=f_]")
        n = boxes.count()
        names = [boxes.nth(i).get_attribute("name") for i in range(n)]
        toggle = lambda name: page.locator(f"label:has(input[name={name}])").click()  # noqa: E731
        ok(n == 23, f"tuning: {n} feature toggles")

        # too few features -> readable error, no run
        for name in names[:-2]:
            toggle(name)
        page.get_by_role("button", name="Train").click()
        page.wait_for_timeout(1500)
        ok(page.get_by_text("choose at least 3").count() > 0, "tuning: fewer than 3 features explains why")
        problems.clear()  # the browser logs that deliberate 422

        # every option set
        page.reload()
        for name in names[4:6]:  # drop two features
            toggle(name)
        page.fill("input[name=learning_rate]", "0.08")
        page.fill("input[name=num_leaves]", "40")
        page.fill("input[name=scale_pos_weight]", "15")
        page.fill("input[name=trials]", "2")
        page.locator("input[name=use_analyst_labels]").uncheck()
        page.locator("input[name=use_analyst_labels]").check()
        if TRAIN:
            page.get_by_role("button", name="Train").click()
            page.wait_for_timeout(2500)
            ok(page.get_by_text("Training started").count() > 0 or page.get_by_text("in progress").count() > 0,
               "tuning: run starts from the form")
            t0 = time.time()
            with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
                while time.time() - t0 < 1200:
                    st = conn.execute("select status, error from public.train_runs order by created_at desc limit 1").fetchone()
                    if st[0] in ("succeeded", "failed"):
                        break
                    time.sleep(10)
            ok(st[0] == "succeeded", f"tuning: run {st[0]} in {time.time() - t0:.0f}s {st[1] or ''}")
            page.reload()
            page.wait_for_timeout(1500)
            ok(page.get_by_text("Champion vs Challenger").count() > 0, "tuning: challenger card shows")
        ok(not problems, "tuning: no errors" + ("" if not problems else " — " + "; ".join(problems[:5])))
        browser.close()

    print(f"\n{'ALL PASSED' if not failures else f'{len(failures)} FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
