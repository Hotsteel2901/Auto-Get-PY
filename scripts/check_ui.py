#!/usr/bin/env python3
"""Browser check for the web UI.

Drives the real single-page app in headless Chromium against a running server:
every page, both languages, both themes, and the main interactions. Fails on
any console error, page error or failed request.

    python app.py --port 8765 &
    python scripts/check_ui.py --base-url http://127.0.0.1:8765

Expected strings are read from the app's own `t()` so the check works whichever
locale is active.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

PAGES = [
    ("dashboard", "dashboard.title"),
    ("new-task", "newTask.title"),
    ("downloads", "downloads.title"),
    ("files", "files.title"),
    ("agents", "agents.title"),
    ("settings", "settings.title"),
]

failures: list[str] = []
checks = 0


def check(condition: bool, label: str) -> None:
    global checks
    checks += 1
    if condition:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}")


async def wait_for_count(page, selector: str, minimum: int, timeout: float = 25.0) -> int:
    """Poll a locator until it reaches ``minimum`` elements (or time out).

    Data-dependent assertions must not use a fixed sleep: the crawl may still
    be writing files when the page is opened.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    count = 0
    while asyncio.get_running_loop().time() < deadline:
        count = await page.locator(selector).count()
        if count >= minimum:
            return count
        await page.wait_for_timeout(400)
    return count


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--screenshot-dir", default=None,
                        help="Write one screenshot per page to this directory")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    console_errors: list[str] = []
    failed_requests: list[str] = []
    page_errors: list[str] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=not args.headed)
        context = await browser.new_context(viewport={"width": 1500, "height": 940})
        page = await context.new_page()

        page.on("console", lambda message: (
            console_errors.append(f"{message.type}: {message.text}")
            if message.type == "error" else None))
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("requestfailed", lambda request: failed_requests.append(
            f"{request.url} ({request.failure})"))

        async def tr(key: str) -> str:
            """Read a translation straight from the running app."""
            return await page.evaluate(
                "key => import('/webui/js/i18n.js').then(m => m.t(key))", key)

        print(f"\n── load {base}/ ─────────────────────────────────────────")
        response = await page.goto(f"{base}/", wait_until="networkidle", timeout=30_000)
        check(response is not None and response.ok, "the app shell loads")
        check(await page.title() == f"{await tr('dashboard.title')} · Auto-Get-PY",
              "the document title comes from the router")
        check(await page.locator(".nav-item").count() == 6,
              "six navigation entries are rendered")
        check(await page.locator("#conn-status").get_attribute("data-state") == "open",
              "the progress WebSocket reports 'open'")

        print("\n── theme ─────────────────────────────────────────────────")
        check(await page.evaluate("document.documentElement.dataset.theme") == "light",
              "the interface starts in light mode")
        check(await page.locator("#theme-toggle svg").count() == 1,
              "the theme button has an icon")

        await page.click("#theme-toggle")
        await page.wait_for_timeout(350)
        check(await page.evaluate("document.documentElement.dataset.theme") == "dark",
              "the theme button switches to dark")
        check(await page.evaluate("JSON.parse(localStorage.getItem('autoget:theme'))") == "dark",
              "the theme choice is persisted")

        # Re-loading must keep the theme without a flash of light.
        await page.reload(wait_until="networkidle")
        await page.wait_for_timeout(400)
        check(await page.evaluate("document.documentElement.dataset.theme") == "dark",
              "the dark theme survives a reload")

        if args.screenshot_dir:
            out = Path(args.screenshot_dir)
            out.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(out / "dashboard-dark.png"))

        await page.click("#theme-toggle")
        await page.wait_for_timeout(350)
        check(await page.evaluate("document.documentElement.dataset.theme") == "light",
              "and switches back to light")

        print("\n── pages ─────────────────────────────────────────────────")
        for page_id, title_key in PAGES:
            await page.click(f'.nav-item[data-page="{page_id}"]')
            await page.wait_for_timeout(650)

            heading = await page.locator("#page-title").inner_text()
            check(heading == await tr(title_key), f"#{page_id} renders ({heading})")

            body = await page.locator("#main").inner_text()
            check(len(body.strip()) > 0, f"#{page_id} has content")
            check("failed to load" not in body.lower(),
                  f"#{page_id} mounted without an error")

            if args.screenshot_dir:
                out = Path(args.screenshot_dir)
                out.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(out / f"{page_id}.png"), full_page=True)

        print("\n── language ──────────────────────────────────────────────")
        check(await page.evaluate(
            "import('/webui/js/i18n.js').then(m => m.getLocale())") == "zh",
            "the interface starts in Chinese")
        check(await page.locator("#lang-toggle").inner_text() == "EN",
              "the switcher offers the other language")

        await page.click(".nav-item[data-page='downloads']")
        await page.wait_for_timeout(500)
        check("下载" in (await page.locator("#page-title").inner_text())
              or "下载" in (await page.locator(".nav-item[data-page='downloads']").inner_text()),
              "nav labels are Chinese")

        await page.click("#lang-toggle")
        await page.wait_for_timeout(700)
        check(await page.evaluate(
            "import('/webui/js/i18n.js').then(m => m.getLocale())") == "en",
            "the switcher switches to English")
        check("Downloads" in await page.locator(".nav-item[data-page='downloads']").inner_text(),
              "nav labels switch to English")
        check(await page.locator("#page-title").inner_text() == "Downloads",
              "the page title switches too")
        check(await page.locator("#dl-body").count() == 1,
              "the page was re-mounted, not left blank")
        check(await page.evaluate(
            "JSON.parse(localStorage.getItem('autoget:locale'))") == "en",
            "the language choice is persisted")

        await page.click("#lang-toggle")
        await page.wait_for_timeout(700)
        check(await page.evaluate(
            "import('/webui/js/i18n.js').then(m => m.getLocale())") == "zh",
            "switching back returns to Chinese")

        print("\n── new task form ─────────────────────────────────────────")
        await page.click(".nav-item[data-page='new-task']")
        await page.wait_for_timeout(600)

        check(await page.locator(".recipe").count() == 5, "five recipe presets")
        check(await page.locator("[data-ext]").count() > 30, "extension chips built")
        check(await page.locator("[data-dec]").count() == 7, "seven decryptor toggles")

        await page.click('[data-preset="spa"]')
        await page.wait_for_timeout(300)
        check(await page.is_checked("#t-browser"),
              "the JavaScript-app recipe enables browser rendering")
        check(await page.locator("#browser-options").is_visible(),
              "the browser options panel becomes visible")

        await page.click('[data-preset="page"]')
        await page.wait_for_timeout(300)
        check(not await page.is_checked("#t-browser"),
              "the single-page recipe turns browser rendering back off")

        invalid = await page.evaluate("""() => {
            const form = document.getElementById('task-form');
            return [...form.elements]
                .filter(el => el.willValidate && !el.checkValidity())
                .map(el => el.id || el.name || el.type);
        }""")
        check(invalid == ["f-url"],
              f"only the empty required URL blocks submission (invalid: {invalid})")

        await page.fill("#f-url", "http://127.0.0.1:9911/")
        await page.fill("#f-name", "browser smoke test")
        await page.wait_for_timeout(300)
        check(await page.locator("#url-preview").inner_text() != "",
              "the URL preview fills in")
        check(await page.evaluate("document.getElementById('task-form').checkValidity()"),
              "the form is valid once the URL is filled")

        await page.click("#submit-btn")
        await page.wait_for_timeout(1800)
        check(await page.locator("#page-title").inner_text() == await tr("dashboard.title"),
              "submitting a task navigates to the dashboard")
        check(await wait_for_count(page, "#recent-rows tr", 1) >= 1,
              "the new task appears in the dashboard")

        print("\n── downloads ─────────────────────────────────────────────")
        await page.click(".nav-item[data-page='downloads']")
        rows = await wait_for_count(page, "#dl-body tbody tr", 1)
        check(rows > 0, f"the downloads page lists records ({rows})")
        check(await wait_for_count(page, "#dl-body tbody .badge-completed", 1) > 0,
              "downloads start completing")

        await page.fill("#dl-search", "hero")
        await page.wait_for_timeout(700)
        filtered = await page.locator("#dl-body tbody tr").count()
        check(0 < filtered < rows, f"search narrows the table ({rows} → {filtered})")
        await page.fill("#dl-search", "")
        await page.wait_for_timeout(500)

        print("\n── files ─────────────────────────────────────────────────")
        await page.click(".nav-item[data-page='files']")
        on_disk = await wait_for_count(page, "#files-body tbody tr", 1, timeout=45.0)
        if on_disk == 0:
            print("       debug: files page state -> "
                  f"summary={await page.locator('#files-summary').inner_text()!r} "
                  f"text={(await page.locator('#main').inner_text())[:150]!r}")
        check(on_disk > 0, f"the files page lists files on disk ({on_disk})")

        print("\n── agents ────────────────────────────────────────────────")
        await page.click(".nav-item[data-page='agents']")
        await page.wait_for_timeout(900)
        agent_rows = await page.locator("#agents-body tbody tr").count()
        check(agent_rows >= 17, f"the agents page lists every integration ({agent_rows})")
        check("/api/opencode" in await page.locator("#agents-body tbody").inner_text(),
              "each row shows its own alias")

        await page.locator("#agents-body tbody button").first.click()
        await page.wait_for_timeout(450)
        check(await page.locator(".modal").count() == 1, "the setup modal opens")
        modal_text = await page.locator(".modal").inner_text()
        check("/quick" in modal_text and "undefined" not in modal_text,
              "the modal shows a real alias-specific snippet")
        await page.click(".modal-head .icon-btn")
        await page.wait_for_timeout(300)
        check(await page.locator(".modal").count() == 0, "the setup modal closes")

        print("\n── settings & shortcuts ──────────────────────────────────")
        await page.click(".nav-item[data-page='settings']")
        await page.wait_for_timeout(800)
        check(await page.input_value("#s-concurrency") != "", "settings load from the server")
        check("9" in await page.locator("#runtime-card").inner_text()
              or "v" in await page.locator("#runtime-card").inner_text(),
              "the runtime card shows server facts")

        await page.keyboard.press("g")
        await page.keyboard.press("l")
        await page.wait_for_timeout(600)
        check(await page.locator("#page-title").inner_text() == await tr("downloads.title"),
              "the 'g l' keyboard shortcut navigates")

        await page.goto(f"{base}/webui/index.html#agents", wait_until="networkidle")
        await page.wait_for_timeout(800)
        check(await page.locator("#page-title").inner_text() == await tr("agents.title"),
              "a deep link opens the right page")

        await page.goto(f"{base}/webui/index.html?lang=en#agents", wait_until="networkidle")
        await page.wait_for_timeout(900)
        check(await page.locator("#page-title").inner_text() == "Agents",
              "?lang=en opens the interface in English")

        print("\n── responsive ────────────────────────────────────────────")
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.goto(f"{base}/webui/index.html", wait_until="networkidle")
        await page.wait_for_timeout(700)
        check(await page.locator("#menu-toggle").is_visible(),
              "the mobile menu button appears on a narrow viewport")
        await page.click("#menu-toggle")
        await page.wait_for_timeout(400)
        check(await page.evaluate("document.body.dataset.nav") == "open",
              "the mobile drawer opens")

        await browser.close()

    print("\n── diagnostics ───────────────────────────────────────────")
    for label, entries in (("console errors", console_errors),
                           ("page errors", page_errors),
                           ("failed requests", failed_requests)):
        real = [entry for entry in entries if "favicon" not in entry]
        if real:
            failures.append(f"{label}: {len(real)}")
            print(f"  {label}:")
            for entry in real[:8]:
                print(f"    - {entry}")
        else:
            print(f"  no {label}")

    print("\n──────────────────────────────────────────────────────────")
    if failures:
        print(f"\n{len(failures)} problem(s) out of {checks} checks:")
        for failure in failures:
            print(f"  ✗ {failure}")
        return 1
    print(f"\nAll {checks} browser checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
