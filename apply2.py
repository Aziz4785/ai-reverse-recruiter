"""
Minimal form filler: open a URL and fill the First Name field with "Aziz".

Usage:
  pip install playwright
  python -m playwright install
  python apply2.py --url "<job url>" [--headless]
"""

import argparse
import re
from typing import List, NamedTuple, Generator, Optional
from user_data import *
from playwright.sync_api import Page, TimeoutError as PWTimeout, Frame, sync_playwright
from function_utils import *
from function_utils import _attempt_on_locator, find_field_locator_anywhere, _walk_frames
from take_screenshot import capture_full_page_stitched
from combobox_filler3 import try_select_combobox_anywhere

def _try_upload_in_context(ctx: Page | Frame, file_path: Path) -> bool:
    """
    Attempt to locate a file input (resume/CV upload) inside the given context and upload.
    Returns True if successful.
    """
    # 1) Explicit name / id patterns (most common in ATS)
    patterns = ["resume", "cv", "upload", "file"]
    for pat in patterns:
        try:
            locator = ctx.locator(f"input[type='file'][name*='{pat}' i], input[type='file'][id*='{pat}' i]")
            if locator.count() > 0:
                locator.first.set_input_files(str(file_path))
                return True
        except Exception:
            pass

    # 2) Label-based (e.g. <label>Upload Resume<input type="file">...</label>)
    for pat in patterns:
        try:
            locator = ctx.locator(f"label:has-text('{pat}')").locator("input[type='file']")
            if locator.count() > 0:
                locator.first.set_input_files(str(file_path))
                return True
        except Exception:
            pass

    # 3) Generic visible file input
    try:
        locator = ctx.locator("input[type='file']:not([disabled])")
        if locator.count() > 0:
            locator.first.set_input_files(str(file_path))
            return True
    except Exception:
        pass

    return False


def try_upload_resume_anywhere(page: Page) -> bool:
    """
    Try to upload resume.pdf into any resume/CV file input across page and frames.
    Returns True if successful, False otherwise.
    """
    # A) If Greenhouse-hosted page
    if GH_RE.search(page.url or ""):
        if _try_upload_in_context(page, RESUME_PATH):
            return True

    # B) Greenhouse iframe
    gh = _get_greenhouse_frame(page)
    if gh and _try_upload_in_context(gh, RESUME_PATH):
        return True

    # 1) Try main document
    if _try_upload_in_context(page, RESUME_PATH):
        return True

    # 2) Try all nested iframes
    for fr in _walk_frames(page):
        if fr == page.main_frame:
            continue
        try:
            fr.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass
        if _try_upload_in_context(fr, RESUME_PATH):
            return True

    return False
def _get_greenhouse_frame(page: Page, timeout_ms: int = 10000) -> Optional[Frame]:
    # 1) Wait for the iframe node to appear (common IDs/selectors Greenhouse uses)
    try:
        page.wait_for_selector("iframe#grnhse_iframe, #grnhse_app iframe, iframe[src*='greenhouse']", timeout=timeout_ms)
    except Exception:
        pass  # we'll still try to find by URL below

    # 2) Find by URL or name
    for fr in page.frames:
        try:
            if (fr.name and "grnhse_iframe" in fr.name) or (fr.url and GH_RE.search(fr.url)):
                return fr
        except Exception:
            continue
    return None


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
    # 0) Role-based (often more robust across frameworks)
    for lt in synonyms:
        try:
            res = _attempt_on_locator(ctx.get_by_role("textbox", name=lt, exact=False), value)
            if res.present: return res
        except Exception:
            pass

    # 1) Accessible label
    for lt in synonyms:
        res = _attempt_on_locator(ctx.get_by_label(lt, exact=False), value)
        if res.present: return res

    # 1b) Label text → control (covers odd label/for wiring)
    for lt in synonyms:
        res = _attempt_on_locator(
            ctx.locator(f"label:has-text('{lt}')").locator("input, textarea, [contenteditable='true']"),
            value
        )
        if res.present: return res

    # 2) Placeholder (case-insensitive)
    for ph in synonyms:
        res = _attempt_on_locator(
            ctx.locator(f"input[placeholder*='{ph}' i], textarea[placeholder*='{ph}' i]"),
            value
        )
        if res.present: return res

    # 3) name= (case-insensitive)
    for name_key in input_names:
        res = _attempt_on_locator(
            ctx.locator(f"input[name*='{name_key}' i], textarea[name*='{name_key}' i]"),
            value
        )
        if res.present: return res

    # 4) aria-label (case-insensitive)
    for aria in synonyms:
        res = _attempt_on_locator(
            ctx.locator(f"input[aria-label*='{aria}' i], textarea[aria-label*='{aria}' i]"),
            value
        )
        if res.present: return res

    # 5) Generic visible text inputs (common types) + textarea + contenteditable
    generic_selector = (
        "input:not([type='hidden']):not([disabled]):is([type='text'],[type='email'],"
        "[type='tel'],[type='search'],[type='url'],[type='number']), "
        "textarea, "
        "[contenteditable='true']"
    )
    res = _attempt_on_locator(ctx.locator(generic_selector), value)
    if res.present: return res

    return FillResult(False, False, False)

def try_fill_field_anywhere(page: Page, value: str,
                            synonyms: List[str], input_names: List[str]) -> FillResult:
    
    print(f"    trying filling the field : {synonyms[0]}")
    # A) If we’re already on a Greenhouse-hosted page, just fill it
    if GH_RE.search(page.url or ""):
        print("    we are on a greenhouse page")
        page.wait_for_load_state("domcontentloaded", timeout=8000)
        page.wait_for_timeout(200)
        res = _try_fill_in_context_status(page, value, synonyms, input_names)
        if res.present:
            return res

    # B) Embedded Greenhouse iframe (like the Turn/River page)
    gh = _get_greenhouse_frame(page)
    if gh:
        print("    we are on a greenhouse iframe")
        # Make sure the form (application, not just the board) is mounted
        try:
            gh.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        # Any plausible text field (GH app) — first_name shows up as input[name='first_name']
        try:
            gh.wait_for_selector("input[name], textarea, input[placeholder]", timeout=6000)
        except Exception:
            pass

        # Some sites lazy-mount sections until scrolled
        try:
            gh.evaluate("window.scrollTo(0, Math.min(600, document.body.scrollHeight));")
        except Exception:
            pass

        res = _try_fill_in_context_status(gh, value, synonyms, input_names)
        if res.present:
            return res
        
    # 1) Try main document first
    #print("    trying to fill the field in the main document")
    res = _try_fill_in_context_status(page, value, synonyms, input_names)
    if res.present:
        return res

    # 2) Try ALL nested iframes (depth-first)
    print("    trying to fill the field in the nested iframes")
    for fr in _walk_frames(page):
        if fr == page.main_frame:
            continue
        try:
            # Best-effort: ensure the frame DOM is available
            fr.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass  # Some ad/sandbox frames never settle; keep going

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
        #wait for 5 seconds until everything is in place:
        page.wait_for_timeout(5000)
        dismiss_cookie_banners(page)
        try_click_apply_buttons(page)

        fields = [
            #("first_name",     FIRST_NAME_VALUE,     FIRST_NAME_SYNONYMS,     INPUT_NAME_FIRSTNAME),
            #("last_name",      LAST_NAME_VALUE,      LAST_NAME_SYNONYMS,      INPUT_NAME_LASTNAME),
            #("preferred_name", PREFERED_NAME_VALUE,  PREFERED_NAME_SYNONYMS,  INPUT_NAME_PREFEREDNAME),
            #("phone_number",   PHONE_NUMBER_VALUE,   PHONE_NUMBER_SYNONYMS,   INPUT_NAME_PHONENUMBER),
            ("email",          EMAIL_VALUE,          EMAIL_SYNONYMS,          INPUT_NAME_EMAIL),
            ("full_name",      FULL_NAME_VALUE,      FULL_NAME_SYNONYMS,      INPUT_NAME_FULLNAME),
            ("location",       LOCATION_VALUE,       LOCATION_SYNONYMS,       INPUT_NAME_LOCATION),
        ]

        done = {key: False for key, *_ in fields} 
        scroll_number = 0

        for _ in range(12):
            scroll_number += 1
            print("scroll n° ",scroll_number)
            at_least_one_existing_field_is_empty= False

            for key, value, syns, names in fields:
                if done[key]:
                    continue

                present, filled, already = try_fill_field_anywhere(page, value, syns, names)
                if not filled and not already:
                    print(f"  we use combobox filler to fill {key}")
                    present, filled, already = try_select_combobox_anywhere(page,value,syns,names)

                if filled or already:
                    done[key] = True
                elif present:
                    print(f"  field {key} is present and still need to be filled")
                    # It exists on the page but isn't filled yet (maybe validation/disabled/etc.)
                    at_least_one_existing_field_is_empty = True

            if not at_least_one_existing_field_is_empty:
                break
            #quick pause
            page.wait_for_timeout(500)
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(200)

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

        #UPLOAD RESUME:
        print("trying uploading resume...")
        ok = try_upload_resume_anywhere(page)
        if ok:
            print("✅ Resume uploaded successfully")
        else:
            print("⚠️ Could not find any resume upload field")

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
    #python apply2.py --url "https://www.metacareers.com/resume/?req=a1KDp00000E2K2TMAV"