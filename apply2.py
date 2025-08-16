"""
Minimal form filler: open a URL and fill the First Name field with "Aziz".

Usage:
  pip install playwright
  python -m playwright install
  python apply2.py --url "<job url>" [--headless]
"""

import argparse
import os
import re
from typing import List

from playwright.sync_api import Page, TimeoutError as PWTimeout, Frame, sync_playwright


FIRST_NAME_VALUE = "Aziz"
LAST_NAME_VALUE = "Kanoun"
FIRST_NAME_SYNONYMS: List[str] = [
    "first name",
    "first",
    "given name",
    "prénom",
    "prenom",
]
INPUT_NAME_FIRSTNAME = ["first", "first_name", "given_name", "fname"]
LAST_NAME_SYNONYMS: List[str] = [
    "last name",
    "family name",
    "surname",
    "nom",
]
INPUT_NAME_LASTNAME = ["last", "last_name", "family_name", "lname"]

def _try_fill_in_context(ctx: Page | Frame, value: str, synonyms : List[str], input_names : List[str]) -> bool:
    # Try by accessible label
    for lt in synonyms:
        try:
            ctx.get_by_label(lt, exact=False).first.fill(value, timeout=1200)
            return True
        except Exception:
            pass

    # Try by placeholder substring
    for ph in synonyms:
        try:
            ctx.locator(f"input[placeholder*='{ph}']").first.fill(value, timeout=1000)
            return True
        except Exception:
            pass

    # Try by common name attribute substring
    for name_key in input_names:
        try:
            ctx.locator(f"input[name*='{name_key}']").first.fill(value, timeout=1000)
            return True
        except Exception:
            pass

    # Try by aria-label substring
    for aria in synonyms:
        try:
            ctx.locator(f"input[aria-label*='{aria}']").first.fill(value, timeout=1000)
            return True
        except Exception:
            pass

    # Try generic first text input as last resort (best-effort only)
    try:
        ctx.locator("input[type='text']").first.fill(value, timeout=1000)
        return True
    except Exception:
        return False

def try_fill_last_name_anywhere(page: Page, value: str) -> bool:
    # Try main page first
    if _try_fill_in_context(page, value, LAST_NAME_SYNONYMS, INPUT_NAME_LASTNAME):
        return True
    # Try inside iframes (e.g., Greenhouse/Lever embeds)
    for fr in page.frames:
        try:
            if fr == page.main_frame:
                continue
            if _try_fill_in_context(fr, value, LAST_NAME_SYNONYMS, INPUT_NAME_LASTNAME):
                return True
        except Exception:
            continue
    return False

def try_fill_first_name_anywhere(page: Page, value: str) -> bool:
    # Try main page first
    if _try_fill_in_context(page, value, FIRST_NAME_SYNONYMS, INPUT_NAME_FIRSTNAME):
        return True
    # Try inside iframes (e.g., Greenhouse/Lever embeds)
    for fr in page.frames:
        try:
            if fr == page.main_frame:
                continue
            if _try_fill_in_context(fr, value, FIRST_NAME_SYNONYMS, INPUT_NAME_FIRSTNAME):
                return True
        except Exception:
            continue
    return False


def dismiss_cookie_banners(page: Page) -> None:
    candidates = [
        "Accept",
        "Accept all",
        "I agree",
        "Agree",
        "Got it",
        "Accepter",
        "Tout accepter",
        "J'accepte",
        "J’accepte",
    ]
    for text in candidates:
        try:
            btn = page.get_by_role("button", name=re.compile(text, re.I)).first
            if btn.is_visible():
                btn.click(timeout=1000)
        except Exception:
            pass


def try_click_apply_buttons(page: Page) -> None:
    labels = ["Apply", "Apply now", "Postuler", "Soumettre"]
    for text in labels:
        try:
            btn = page.get_by_role("button", name=re.compile(text, re.I)).first
            if btn.is_visible():
                btn.click(timeout=1200)
                page.wait_for_timeout(500)
                return
        except Exception:
            pass


def run(url: str, headless: bool) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        print(f"Opening {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        dismiss_cookie_banners(page)
        try_click_apply_buttons(page)

        # Scroll progressively and attempt filling on page and iframes each step
        first_name_ok = False
        last_name_ok = False
        for _ in range(12):
            if not first_name_ok:
                first_name_ok = try_fill_first_name_anywhere(page, FIRST_NAME_VALUE)
            if not last_name_ok:
                last_name_ok = try_fill_last_name_anywhere(page, LAST_NAME_VALUE)
            if first_name_ok and last_name_ok:
                break
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(400)

        # Final attempt without scrolling
        if not first_name_ok:
            first_name_ok = try_fill_first_name_anywhere(page, FIRST_NAME_VALUE)
        if not last_name_ok:
            last_name_ok = try_fill_last_name_anywhere(page, LAST_NAME_VALUE)
        print(f"First name fill: {'OK' if first_name_ok else 'NOT FOUND'}")
        print(f"Last name fill: {'OK' if last_name_ok else 'NOT FOUND'}")

        os.makedirs("out", exist_ok=True)
        page.screenshot(path=os.path.join("out", "first_name_fill.png"), full_page=True)
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Open a URL and fill the First Name with 'Aziz'.")
    parser.add_argument("--url", required=True, help="Target URL with a form")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    args = parser.parse_args()

    run(url=args.url, headless=args.headless)


if __name__ == "__main__":
    main()
    #python apply2.py --url "https://careers.datadoghq.com/detail/6158712/?gh_jid=6158712&gh_src=8363eca61"
    #or python apply2.py --url "https://careers.datadoghq.com/detail/6158712/?gh_jid=6158712&gh_src=8363eca61" --headless