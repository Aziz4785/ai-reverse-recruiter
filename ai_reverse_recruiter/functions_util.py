from pydantic import BaseModel, Field
from typing import Dict, Optional, Generator, List
from dataclasses import dataclass
import json
from playwright.sync_api import Page, Frame, Locator
import re
from collections import Counter
from user_data import *
import time
import difflib
import asyncio, difflib, re, unicodedata
#import NamedTuple
from typing import NamedTuple

from difflib import SequenceMatcher

def string_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.casefold().strip(), b.casefold().strip()).ratio()

GH_RE = re.compile(r"(job-boards\.greenhouse\.io|boards\.greenhouse\.io|grnh\.se)")


def _norm(s: str) -> str:
    # collapse whitespace, remove diacritics, lowercase
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip().lower()

def requires_sponsorship(country: str) -> str:
    if country == "France":
        return SPONSORSHIP_FRANCE_VALUE
    elif country == "US":
        return SPONSORSHIP_US_VALUE
    elif country == "UK":
        return SPONSORSHIP_UK_VALUE
    elif country == "Netherlands":
        return SPONSORSHIP_NETHERLANDS_VALUE
    else:
        return "No"


def extract_job_country(page_text: str, COUNTRY_KEYWORDS: dict) -> str:
    # Lowercase text for case-insensitive matching
    text = page_text.lower()
    
    country_counts = Counter()

    for country, keywords in COUNTRY_KEYWORDS.items():
        for kw in keywords:
            # Count all occurrences (case-insensitive, word-boundary safe when possible)
            pattern = re.escape(kw.lower())
            matches = re.findall(pattern, text)
            country_counts[country] += len(matches)

    if not country_counts:
        return None

    # Return the country with the maximum keyword matches
    best_match = country_counts.most_common(1)[0]
    return best_match[0] if best_match[1] > 0 else None

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

def print_html_element(element: Locator) -> None:
    if element is None:
        return None
    count = element.count()
    if count > 1:
        print("this locator corresponds to ", count, " elements")
    for i in range(count):
        item = element.nth(i)
        html = item.evaluate("el => el.outerHTML")
        print(f"[{i}] {html}")



def get_closest_match(value: str, options: List[str],panel: Locator) -> str:
    closest = difflib.get_close_matches(str(value), options, n=1, cutoff=0.0)
    if closest:
        best_match = closest[0]
        print(f"Best match: {best_match}")
        panel.locator("[role='option']", has_text=best_match).first.click()
    else:
        print("No options available")



def all_inner_texts_fast(locator):
    # much faster than calling .inner_text() in a loop
    try:
        return [t.strip() for t in locator.all_inner_texts()]
    except Exception:
        # fallback if not supported in your version
        texts = []
        count = locator.count()
        for i in range(count):
            texts.append(locator.nth(i).inner_text().strip())
        return texts


def expand_collapsed_groups(container):
    """
    Best-effort expansion for nested/collapsed groups.
    Adjust selectors to fit your markup (common patterns below).
    """
    # Patterns that often indicate collapsed sections
    collapsed_selectors = [
        "[aria-expanded='false']",
        "[data-state='collapsed']",
        ".collapsed",
        # sometimes the toggle is a button or chevron inside the header
        "[role='group'] [aria-expanded='false']",
        "[role='treeitem'][aria-expanded='false']",
    ]

    # Try a few passes in case expanding one reveals more
    for _ in range(5):
        expanded_any = False
        for sel in collapsed_selectors:
            toggles = container.locator(sel)
            n = min(toggles.count(), 20)  # cap to avoid 'forever'
            for i in range(n):
                try:
                    # try clicking the toggle itself or its nearest clickable
                    t = toggles.nth(i)
                    if not t.is_visible():
                        continue
                    # Some UIs require clicking a child chevron/button:
                    clickable = t.locator("button, [role='button'], [data-action='toggle'], svg, [class*=chevron]").first
                    candidate = clickable if clickable.count() else t
                    candidate.click(timeout=500)
                    expanded_any = True
                except TimeoutError:
                    pass
                except Exception:
                    pass
        if not expanded_any:
            break



import re
import difflib
from playwright.sync_api import expect
WS = re.compile(r"\s+")

def _norm2(s: str) -> str:
    return WS.sub(" ", (s or "")).strip()

def select_from_mat_select(frame_or_page, desired_text: str, timeout=10000):
    # 1) Find the *currently open* overlay panel in THIS frame
    panel = frame_or_page.locator(".cdk-overlay-pane .mat-mdc-select-panel.mdc-menu-surface--open[role='listbox']")
    panel.wait_for(state="visible", timeout=timeout)

    # 2) Get all option *elements* (not disabled), and read the visible text spans
    # We do not use `filter(has=...)` which was failing to resolve; we iterate instead.
    option_elts = panel.locator("[role='option'][aria-disabled!='true']")
    count = option_elts.count()
    if count == 0:
        raise RuntimeError("mat-select overlay is open, but no options are rendered/enabled.")

    # Prefer the inner primary-text span if present; fall back to element inner_text
    text_spans = option_elts.locator("span.mdc-list-item__primary-text")
    texts = []
    for i in range(count):
        t = text_spans.nth(i).inner_text(timeout=1000) if text_spans.nth(i).count() else option_elts.nth(i).inner_text(timeout=1000)
        texts.append(_norm2(t))

    target_norm2 = _norm2(desired_text)

    # 3) Exact match first, then fuzzy
    try:
        idx = texts.index(target_norm2)
    except ValueError:
        best = difflib.get_close_matches(target_norm2, texts, n=1, cutoff=0.0)
        if not best:
            raise RuntimeError(f"No options similar to '{desired_text}' found.\nAvailable: {texts}")
        idx = texts.index(best[0])

    target_option = option_elts.nth(idx)

    # 4) Ensure actionable, then click
    target_option.scroll_into_view_if_needed(timeout=timeout)
    expect(target_option).to_be_visible(timeout=timeout)
    expect(target_option).to_be_enabled(timeout=timeout)

    # Some themes block clicks until open animation finishes (pointer-events:none)
    frame_or_page.wait_for_function(
        "el => getComputedStyle(el).pointerEvents !== 'none'",
        arg=panel,
        timeout=timeout
    )

    # Try clicking the <mat-option>; if it’s picky, click the inner text span
    try:
        target_option.click(timeout=timeout)
    except Exception:
        # Click inner span if present
        primary_span = target_option.locator("span.mdc-list-item__primary-text")
        if primary_span.count():
            primary_span.first.click(timeout=timeout)
        else:
            # Last resort
            target_option.click(timeout=timeout, force=True)

    # 5) Fallbacks if the panel didn’t close (selection didn’t happen)
    if panel.is_visible():
        # Typeahead: jump to item and select
        frame_or_page.keyboard.type(texts[idx][:10])
        frame_or_page.keyboard.press("Enter")