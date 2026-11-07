"""Record the product demo video: a scripted tour of the app with on-screen captions.

    uv run --with playwright python scripts/record_demo.py [base_url]   (default http://localhost:3000)

Signs in as the compliance manager demo user (DEMO_PASSWORD from .env) and writes
apps/web/static/demo/zentry-demo.mp4 + poster.jpg (needs ffmpeg). Run after `make reset && make replay`."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import psycopg
from playwright.sync_api import Page, sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000").rstrip("/")
OUT = Path(__file__).resolve().parents[1] / "apps/web/static/demo"
SIZE = {"width": 1440, "height": 900}

CAPTION_JS = """(t) => {
  let el = document.getElementById('__cap');
  if (!el) {
    el = document.createElement('div'); el.id = '__cap';
    el.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:99999;' +
      'background:rgba(5,6,11,.88);color:#fff;font:600 17px Inter,system-ui,sans-serif;padding:12px 22px;' +
      'border-radius:999px;box-shadow:0 12px 40px rgba(0,0,0,.25);transition:opacity .3s;max-width:80vw;text-align:center';
    document.body.appendChild(el);
  }
  el.textContent = t; el.style.opacity = t ? '1' : '0';
}"""


def caption(page: Page, text: str, hold: float = 0) -> None:
    page.evaluate(CAPTION_JS, text)
    if hold:
        page.wait_for_timeout(int(hold * 1000))


def glide(page: Page, selector: str, px: int, steps: int = 12) -> None:
    """Smoothly scroll an inner scroll container (pages scroll inside <main>, not the window)."""
    for _ in range(steps):
        page.evaluate("([s, d]) => document.querySelector(s)?.scrollBy({top: d, behavior: 'smooth'})", [selector, px // steps])
        page.wait_for_timeout(120)


def demo_ids() -> tuple[str, str]:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        case_id, = conn.execute("""
            select c.id::text from public.cases c where c.agent_report is not null
            order by (select count(*) from public.case_links l where l.case_id = c.id) desc limit 1""").fetchone()
        account, = conn.execute("""
            select l.account_id from public.case_links l join public.alerts a on a.account_id = l.account_id
            where l.case_id = %s order by a.score desc limit 1""", (case_id,)).fetchone()
    return case_id, account


def main() -> None:
    case_id, account = demo_ids()
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_raw"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # sign in off camera; the recording starts on the Command Center
        login = browser.new_context(viewport=SIZE)
        lp = login.new_page()
        lp.goto(f"{BASE}/login")
        lp.fill("input[name=email]", "compliance_manager@demo.zentry.local")
        lp.fill("input[name=password]", os.environ["DEMO_PASSWORD"])
        lp.click("form button[type=submit], form button:not([type=button])")
        lp.wait_for_url(f"{BASE}/")
        state = login.storage_state()
        login.close()

        ctx = browser.new_context(viewport=SIZE, record_video_dir=str(tmp), record_video_size=SIZE,
                                  device_scale_factor=1, storage_state=state)
        page = ctx.new_page()

        page.goto(f"{BASE}/")
        page.wait_for_load_state("networkidle")
        caption(page, "Zentry: one AI desk for financial crime and payment ops", 3)
        caption(page, "Every transfer is scored by our AI the moment it happens", 3.5)

        page.goto(f"{BASE}/alerts")
        page.wait_for_load_state("networkidle")
        caption(page, "Alert queue: every flag comes with its reasons", 4)

        page.goto(f"{BASE}/cases/{case_id}")
        page.wait_for_load_state("networkidle")
        caption(page, "A whole mule ring lands in one case, investigated by an AI agent", 4)
        glide(page, "main", 900)
        caption(page, "Every claim cites a real transaction, checked before anyone sees it", 4)
        glide(page, "main", 900)
        page.wait_for_timeout(1500)

        page.goto(f"{BASE}/graph?account={account}")
        page.wait_for_timeout(4500)
        caption(page, "Follow the money in and out of the ring", 5)

        page.goto(f"{BASE}/accounts/{account}")
        page.wait_for_load_state("networkidle")
        caption(page, "Names stay masked; revealing one needs a reason and is recorded", 5)

        page.goto(f"{BASE}/recon")
        page.wait_for_load_state("networkidle")
        caption(page, "Reconciliation: the ledger against bank and gateway files", 2)
        rows = page.locator("main table tbody tr")
        if not rows.count():
            page.get_by_role("button", name="Run reconciliation").click()
            caption(page, "Matching every transfer…")
            rows.first.wait_for(timeout=60_000)
            page.wait_for_timeout(1000)
        caption(page, "Every mismatch found and sorted by type", 3)
        if rows.count():
            rows.first.click()
            page.wait_for_timeout(800)
        caption(page, "AI explains each one and drafts the journal entry for finance to approve", 5)

        page.goto(f"{BASE}/follow-ups")
        page.wait_for_load_state("networkidle")
        caption(page, "Payment reminders in Thai and English, drafted by AI and sent only after approval", 5)
        caption(page, "Zentry · built on Vultr · synthetic data only", 3)

        video = page.video
        ctx.close()
        browser.close()
        raw = Path(video.path())
    # -ss 1 drops the blank frames before the first page paints
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1", "-i", raw, "-c:v", "libx264", "-preset", "slow", "-crf", "24",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", OUT / "zentry-demo.mp4"], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "12", "-i", raw, "-frames:v", "1", "-q:v", "3",
                    "-pix_fmt", "yuvj420p", OUT / "poster.jpg"], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(OUT / "zentry-demo.mp4")


if __name__ == "__main__":
    main()
