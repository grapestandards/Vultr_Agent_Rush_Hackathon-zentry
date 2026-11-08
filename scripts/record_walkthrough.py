"""Record the silent product walkthrough for voice-over.

    uv run --with playwright python scripts/record_walkthrough.py [base_url]   (default http://localhost:3000)

Run on fresh demo data (`make reset && make replay`, investigations finished) after one reconciliation
run and one training run, so those pages have results. Each scene signs in off camera as its role and
is recorded on its own; the scenes are joined into docs/demo/zentry-walkthrough.mp4 (needs ffmpeg).
A drawn cursor shows every move and click, since headless video has none."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psycopg
from playwright.sync_api import Browser, Locator, Page, sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000").rstrip("/")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/demo"
TMP = OUT / "_scenes"
SIZE = {"width": 1600, "height": 1000}

CURSOR_JS = """
(() => {
  if (window.__cursor) return;
  const c = document.createElement('div');
  c.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;z-index:2147483647;pointer-events:none;' +
    'transform:translate(-3px,-2px);transition:none';
  c.innerHTML = '<svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2 L3 18 L7.5 14 L10.5 20.5 L13 19.4 L10 13 L16 13 Z" fill="#111" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/></svg>';
  const ring = document.createElement('div');
  ring.style.cssText = 'position:fixed;width:36px;height:36px;margin:-18px 0 0 -18px;border-radius:50%;z-index:2147483646;' +
    'pointer-events:none;border:3px solid #5B4BE0;opacity:0;transform:scale(.4);transition:transform .35s ease, opacity .35s ease';
  const add = () => { document.body.appendChild(ring); document.body.appendChild(c); };
  document.body ? add() : addEventListener('DOMContentLoaded', add);
  addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
  addEventListener('mousedown', e => {
    ring.style.left = e.clientX + 'px'; ring.style.top = e.clientY + 'px';
    ring.style.transition = 'none'; ring.style.opacity = '1'; ring.style.transform = 'scale(.4)';
    requestAnimationFrame(() => { ring.style.transition = 'transform .45s ease, opacity .45s ease';
      ring.style.transform = 'scale(1.4)'; ring.style.opacity = '0'; });
  }, true);
  window.__cursor = true;
})();
"""

_pos = {"x": 800.0, "y": 500.0}


def pause(page: Page, seconds: float) -> None:
    page.wait_for_timeout(int(seconds * 1000))


def move(page: Page, x: float, y: float, steps: int = 30) -> None:
    page.mouse.move(x, y, steps=steps)
    _pos.update(x=x, y=y)


def hover(page: Page, target: Locator, dwell: float = 0.6) -> None:
    target.scroll_into_view_if_needed()
    box = target.bounding_box()
    move(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pause(page, dwell)


def click(page: Page, target: Locator, dwell: float = 0.4) -> None:
    hover(page, target, dwell)
    page.mouse.down()
    page.wait_for_timeout(90)
    page.mouse.up()


def glide(page: Page, px: int, seconds: float) -> None:
    """Scroll the page's inner scroll area (pages scroll inside <main>) smoothly."""
    steps = max(1, int(seconds * 10))
    for _ in range(steps):
        page.evaluate("d => document.querySelector('main')?.scrollBy(0, d)", px / steps)
        page.wait_for_timeout(100)


def wait_for(sql: str, params=(), timeout: float = 180) -> tuple:
    t0 = time.time()
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        while time.time() - t0 < timeout:
            row = conn.execute(sql, params).fetchone()
            if row and row[0]:
                return row
            time.sleep(3)
    raise TimeoutError(sql)


def sign_in(browser: Browser, role: str) -> dict:
    ctx = browser.new_context(viewport=SIZE)
    page = ctx.new_page()
    page.goto(f"{BASE}/login")
    page.fill("input[name=email]", f"{role}@demo.zentry.local")
    page.fill("input[name=password]", os.environ["DEMO_PASSWORD"])
    page.click("form button:not([type=button])")
    page.wait_for_url(f"{BASE}/")
    state = ctx.storage_state()
    ctx.close()
    return state


class Scene:
    def __init__(self, browser: Browser, state: dict, n: int):
        self.ctx = browser.new_context(viewport=SIZE, record_video_dir=str(TMP / f"s{n}"),
                                       record_video_size=SIZE, storage_state=state)
        self.ctx.add_init_script(CURSOR_JS)
        self.page = self.ctx.new_page()
        self.n = n

    def open(self, path: str, settle: float = 1.5) -> Page:
        self.page.goto(f"{BASE}{path}")
        self.page.wait_for_load_state("networkidle")
        self.page.mouse.move(_pos["x"], _pos["y"])
        pause(self.page, settle)
        return self.page

    def close(self) -> Path:
        video = self.page.video
        self.ctx.close()
        dst = TMP / f"scene{self.n}.webm"
        shutil.move(video.path(), dst)
        return dst


def main() -> None:
    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        case_id, = conn.execute("""
            select c.id::text from public.cases c where c.agent_report is not null and c.status <> 'closed'
            order by (select count(*) from public.case_links l where l.case_id = c.id) desc limit 1""").fetchone()
    scenes: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        states = {r: sign_in(browser, r) for r in ("analyst", "finance_ops", "collections", "compliance_manager")}

        # 1 · Alert queue (≈15 s)
        s = Scene(browser, states["analyst"], 1)
        page = s.open("/alerts", 2)
        cards = page.locator("main a[href^='/cases/']")
        for i in range(3):
            hover(page, cards.nth(i), 1.4)
        glide(page, 500, 3)
        pause(page, 2)
        scenes.append(s.close())

        # 2 · Case + AI report (≈30 s)
        s = Scene(browser, states["analyst"], 2)
        page = s.open("/cases", 1.5)
        click(page, page.locator(f"main a[href='/cases/{case_id}']").first)
        page.wait_for_url(f"**/cases/{case_id}")
        page.wait_for_load_state("networkidle")
        pause(page, 3)
        glide(page, 450, 5)
        pause(page, 3)
        chips = page.locator("main code, main [class*='font-mono']")
        for i in range(min(3, chips.count())):
            hover(page, chips.nth(i), 1.2)
        glide(page, 500, 5)
        pause(page, 4)
        scenes.append(s.close())

        # 3 · Follow the money (≈20 s)
        s = Scene(browser, states["analyst"], 3)
        page = s.open(f"/cases/{case_id}", 1)
        click(page, page.locator(f"main a[href='/graph?case={case_id}']").first)
        page.wait_for_url("**/graph?case=*")
        pause(page, 5)
        click(page, page.locator("button[title*='money flo'], button[title='Pause']").first)
        pause(page, 12)
        scenes.append(s.close())

        # 4 · Decision: freeze + STR (≈20 s)
        s = Scene(browser, states["analyst"], 4)
        page = s.open(f"/cases/{case_id}", 1)
        form = page.locator("form[action='?/decide']")
        form.scroll_into_view_if_needed()
        pause(page, 2)
        hover(page, page.locator("#str"), 2)
        click(page, form.locator("input[name=approve_str]"))
        note = form.locator("input[name=note]")
        click(page, note)
        page.keyboard.type("Mule ring confirmed: freeze and file STR", delay=45)
        pause(page, 1)
        click(page, form.locator("button[value=freeze]"), 0.8)
        page.wait_for_load_state("networkidle")
        pause(page, 5)
        scenes.append(s.close())

        # 5 · Reconciliation (≈30 s)
        s = Scene(browser, states["finance_ops"], 5)
        page = s.open("/recon", 3)
        rows = page.locator("main table tbody tr")
        hover(page, page.locator("main").get_by_text("Auto-match rate").first, 2)
        click(page, rows.nth(0), 0.6)
        pause(page, 5)
        click(page, rows.nth(3), 0.6)
        pause(page, 5)
        click(page, page.locator("button[value=confirm]").first, 0.8)
        page.wait_for_load_state("networkidle")
        pause(page, 4)
        scenes.append(s.close())

        # the agent drafts the refund / fee messages on its next tick
        wait_for("select count(*) from public.messages where status = 'draft'")

        # 6 · Follow-ups (≈30 s)
        s = Scene(browser, states["collections"], 6)
        page = s.open("/follow-ups", 3)
        click(page, page.locator("main button:has-text('Victim refund')").first, 0.6)
        pause(page, 4)
        draft = page.locator("main textarea").first
        hover(page, draft, 4)
        page.evaluate("() => document.querySelector('main textarea')?.scrollBy(0, 220)")
        pause(page, 4)
        click(page, page.get_by_role("button", name="Approve & send").first, 0.8)
        page.wait_for_load_state("networkidle")
        pause(page, 5)
        scenes.append(s.close())

        # 7 · Model tuning (≈35 s)
        s = Scene(browser, states["compliance_manager"], 7)
        page = s.open("/tuning", 3)
        hover(page, page.locator("main").get_by_text("Train a challenger").first, 2)
        hover(page, page.get_by_role("button", name="Train").first, 2)
        card = page.locator("main").get_by_text("Champion vs Challenger").first
        hover(page, card, 3)
        slider = page.locator("main input[type=range]").first
        if slider.count():
            box = slider.bounding_box()
            y = box["y"] + box["height"] / 2
            move(page, box["x"] + box["width"] * 0.68, y)
            page.mouse.down()
            for f in (0.6, 0.5, 0.55, 0.68, 0.75, 0.68):
                move(page, box["x"] + box["width"] * f, y, steps=12)
                pause(page, 0.5)
            page.mouse.up()
        pause(page, 3)
        hover(page, page.get_by_role("button", name="Promote").first, 3)
        glide(page, 400, 4)
        pause(page, 3)
        scenes.append(s.close())

        # 8 · Each role sees only its own work (≈15 s)
        s = Scene(browser, states["finance_ops"], 8)
        page = s.open("/recon", 2)
        click(page, page.locator("nav a[href='/cases']"), 0.8)
        page.wait_for_load_state("networkidle")
        pause(page, 4)
        hover(page, page.locator("main").get_by_text("Switch role"), 3)
        pause(page, 2)
        scenes.append(s.close())
        browser.close()

    # trim each scene's blank first frames, then join
    parts = []
    for i, src in enumerate(scenes, 1):
        dst = TMP / f"part{i}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.8", "-i", src, "-vf", "fps=30,format=yuv420p",
                        "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-an", dst], check=True)
        parts.append(dst)
    listing = TMP / "list.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in parts))
    out = OUT / "zentry-walkthrough.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing,
                    "-c", "copy", "-movflags", "+faststart", out], check=True)
    for i, part in enumerate(parts, 1):
        d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", part],
                           capture_output=True, text=True).stdout.strip()
        print(f"scene {i}: {float(d):.1f}s")
    shutil.rmtree(TMP, ignore_errors=True)
    print(out)


if __name__ == "__main__":
    main()
