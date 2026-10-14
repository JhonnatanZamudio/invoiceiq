"""Capture README screenshots from a running, seeded server.

Usage: python scripts/screenshots.py [base_url]
Set CHROMIUM_PATH to use a preinstalled Chromium instead of Playwright's managed one.
"""

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OUT = Path("docs/screenshots")
EMAIL, PASSWORD = "demo@invoiceiq.local", "demo-invoiceiq-2026"  # local demo seed only


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        page = browser.new_page(viewport={"width": 1280, "height": 860}, locale="es-CO")
        page.goto(BASE)
        page.fill("input[name=email]", EMAIL)
        page.fill("input[name=password]", PASSWORD)
        page.click("#auth-submit")
        page.wait_for_selector("#invoice-rows tr")
        page.screenshot(path=OUT / "invoice-list.png", full_page=True)

        # Open an invoice whose totals don't add up to show the review screen.
        page.click("#invoice-rows tr:has-text('CM-77')")
        page.wait_for_selector("#fields .field")
        page.screenshot(path=OUT / "review.png", full_page=True)
        browser.close()
    print(f"Saved screenshots to {OUT}/")


if __name__ == "__main__":
    main()
