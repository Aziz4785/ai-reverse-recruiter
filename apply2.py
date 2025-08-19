"""
Minimal form filler: open a URL and fill the First Name field with "Aziz".

Usage:
  pip install playwright
  python -m playwright install
  python apply2.py --url "<job url>" [--headless]
"""

import argparse
import re
from typing import List, NamedTuple
from user_data import *
from playwright.sync_api import Page, TimeoutError as PWTimeout, Frame, sync_playwright
from function_utils import *
from function_utils import _attempt_on_locator, find_field_locator_anywhere
from take_screenshot import capture_full_page_stitched


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

def _try_fill_in_context_status(ctx: Page | Frame, value: str,
                                synonyms: List[str], input_names: List[str]) -> FillResult:
    # 1) Accessible label
    for lt in synonyms:
        res = _attempt_on_locator(ctx.get_by_label(lt, exact=False), value)
        if res.present:
            return res

    # 2) Placeholder
    for ph in synonyms:
        res = _attempt_on_locator(ctx.locator(f"input[placeholder*='{ph}']"), value)
        if res.present:
            return res

    # 3) name=
    for name_key in input_names:
        res = _attempt_on_locator(ctx.locator(f"input[name*='{name_key}']"), value)
        if res.present:
            return res

    # 4) aria-label
    for aria in synonyms:
        res = _attempt_on_locator(ctx.locator(f"input[aria-label*='{aria}']"), value)
        if res.present:
            return res

    # 5) Last resort (generic text input). Comment out if you prefer strict matching only.
    res = _attempt_on_locator(ctx.locator("input[type='text']"), value)
    if res.present:
        return res

    return FillResult(False, False, False)

def try_fill_field_anywhere(page: Page, value: str,
                          synonyms: List[str], input_names: List[str]) -> FillResult:
    # Try main document
    res = _try_fill_in_context_status(page, value, synonyms, input_names)
    if res.present:
        return res
    # Try iframes
    for fr in page.frames:
        if fr == page.main_frame:
            continue
        try:
            res = _try_fill_in_context_status(fr, value, synonyms, input_names)
            if res.present:
                return res
        except Exception:
            continue
    return FillResult(False, False, False)

def try_fill_field_anywhere2(page: Page, value: str, synonyms: List[str], input_names: List[str]) -> bool:
    # Try main page first
    if _try_fill_in_context(page, value, synonyms, input_names):
        return True
    # Try inside iframes (e.g., Greenhouse/Lever embeds)
    for fr in page.frames:
        try:
            if fr == page.main_frame:
                continue
            if _try_fill_in_context(fr, value, synonyms, input_names):
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
        preferred_name_ok = False
        phone_number_ok = False

        fields = [
            ("first_name",     FIRST_NAME_VALUE,     FIRST_NAME_SYNONYMS,     INPUT_NAME_FIRSTNAME),
            ("last_name",      LAST_NAME_VALUE,      LAST_NAME_SYNONYMS,      INPUT_NAME_LASTNAME),
            ("preferred_name", PREFERED_NAME_VALUE,  PREFERED_NAME_SYNONYMS,  INPUT_NAME_PREFEREDNAME),
            ("phone_number",   PHONE_NUMBER_VALUE,   PHONE_NUMBER_SYNONYMS,   INPUT_NAME_PHONENUMBER),
        ]

        done = {key: False for key, *_ in fields} #this  code to be removed
        scroll_number = 0

        # Scroll progressively and attempt filling on page and iframes each step
        # first_name_ok = False
        # last_name_ok = False
        # for _ in range(12):
        #     if not first_name_ok:
        #         first_name_ok = try_fill_field_anywhere2(page, FIRST_NAME_VALUE, FIRST_NAME_SYNONYMS, INPUT_NAME_FIRSTNAME)
        #     if not last_name_ok:
        #         last_name_ok = try_fill_field_anywhere2(page, LAST_NAME_VALUE, LAST_NAME_SYNONYMS, INPUT_NAME_LASTNAME)
        #     if first_name_ok and last_name_ok:
        #         break
        #     page.mouse.wheel(0, 1200)
        #     page.wait_for_timeout(400)

        # # Final attempt without scrolling
        # if not first_name_ok:
        #     first_name_ok = try_fill_field_anywhere2(page, FIRST_NAME_VALUE, FIRST_NAME_SYNONYMS, INPUT_NAME_FIRSTNAME)
        # if not last_name_ok:
        #     last_name_ok = try_fill_field_anywhere2(page, LAST_NAME_VALUE, LAST_NAME_SYNONYMS, INPUT_NAME_LASTNAME)

        # #assert page.locator("#first_name").input_value(timeout=2000) == "Aziz"
        # print(f"First name fill: {'OK' if first_name_ok else 'NOT FOUND'}")
        # print(f"Last name fill: {'OK' if last_name_ok else 'NOT FOUND'}")

        for _ in range(12):
            scroll_number += 1
            at_least_one_existing_field_is_empty= False

            for key, value, syns, names in fields:
                if done[key]:
                    continue
                present, filled, already = try_fill_field_anywhere(page, value, syns, names)
                if filled or already:
                    done[key] = True
                elif present:
                    # It exists on the page but isn't filled yet (maybe validation/disabled/etc.)
                    at_least_one_existing_field_is_empty = True

            if not at_least_one_existing_field_is_empty:
                break
            #quick pause
            page.wait_for_timeout(1000)
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(400)

        print(f"Scrolled {scroll_number} times")
        # Final attempt without scrolling
        # Optional: one last pass without scrolling for any stragglers visible now
        for key, value, syns, names in fields:
            if not done[key]:
                present, filled, already = try_fill_field_anywhere(page, value, syns, names)
                if filled or already:
                    done[key] = True

        for key, value, syns, names in fields:
            if not done[key]:
                print(f"Field {key} not filled")
            else:
                print(f"Field {key} filled")


        #capture_full_page_stitched(page, out_dir="out", filename="full_page.png")
        width = page.evaluate("() => document.documentElement.scrollWidth")
        height = page.evaluate("() => document.documentElement.scrollHeight")

        # Chrome tends to glitch beyond ~16384px; cap to avoid blanks
        safe_height = min(height, 16000)
        page.set_viewport_size({"width": width, "height": safe_height})

        page.wait_for_timeout(500)  # let layout settle
        page.screenshot(path="out/full_page.png", full_page=False, animations="disabled")
        browser.close()
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Open a URL and fill the First Name with 'Aziz'.")
    parser.add_argument("--url", required=True, help="Target URL with a form")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    args = parser.parse_args()

    run(url=args.url, headless=args.headless)


if __name__ == "__main__":
    main()
    #python apply2.py --url "https://turnriver.com/careers/openings/?gh_jid=4797921008&gh_src=6857f9d98us"
    #or python apply2.py --url "https://job-boards.greenhouse.io/xai/jobs/4756472007?gh_src=fu0zy1zn7us&source=LinkedIn" --headless
    #python apply2.py --url "https://job-boards.greenhouse.io/xai/jobs/4756472007?gh_src=fu0zy1zn7us&source=LinkedIn"