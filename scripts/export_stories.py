"""Export every story slide from /owner/stories as a 1080 × 1920 PNG, ready to post.

    python scripts/export_stories.py http://127.0.0.1:8765 <owner password> out/stories

Needs Playwright with Chromium (pip install playwright && playwright install chromium). The founder's own server
works too: pass its https address. Case slides are exported for every real business that has numbers.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from joop.stories import all_slides


def main(base: str, password: str, out: str) -> None:
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
        page = ctx.new_page()
        page.goto(f"{base}/owner/login")
        page.fill("input[name=password]", password)
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")
        for slide in all_slides():
            page.goto(f"{base}/owner/stories/{slide['name']}")
            page.wait_for_load_state("networkidle")
            page.screenshot(path=str(folder / f"{slide['n']:02d}-{slide['name']}.png"))
            print(slide["name"])
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3])
