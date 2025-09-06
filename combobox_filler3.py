from playwright.sync_api import sync_playwright

import re
from playwright.sync_api import Page, Frame, Locator, expect
import re, unicodedata
from typing import List, Optional, Tuple, Set
from function_utils import *
from function_utils import _attempt_on_locator, find_field_locator_anywhere,_walk_frames

_word_re = re.compile(r"[a-z0-9]+")

def _normalize(text: str) -> str:
    # lowercase + strip accents
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text

def _tokens(text: str) -> list[str]:
    return _word_re.findall(_normalize(text))

def _score_option(value_tokens_unique: set[str], option_tokens: list[str]) -> tuple[float, int, bool]:
    # overlap count uses distinct value tokens present in the option
    opt_set = set(option_tokens)
    overlap = sum(1 for t in value_tokens_unique if t in opt_set)
    denom = max(1, len(option_tokens))
    score = overlap / denom
    # exact-full-coverage bonus flag (used only as an extra tiebreaker)
    full_coverage = (overlap == len(value_tokens_unique))
    # return tuple for sorting: higher score, then fewer tokens, then full coverage True first
    return (score, -len(option_tokens), full_coverage)

def pick_location_suggestion(page: Page, value: str, click_on_best: bool = False, debug: bool = False):
    # 1) Find and prepare the combobox (robust, non-crashing)
    try:
        combobox = page.locator("input[role='combobox'][placeholder*='Location' i]")
        if combobox.count() == 0:
            # Fallback: role with accessible name containing location/city
            combobox = page.get_by_role("combobox", name=re.compile("location|city", re.I))
        if combobox.count() == 0:
            # Last resort: any combobox
            combobox = page.get_by_role("combobox")
        if combobox.count() == 0:
            return FillResult(False, False, False)
        target_input = combobox.first
        try:
            target_input.wait_for(state="visible", timeout=2000)
        except Exception:
            pass
        target_input.click(timeout=2000)
    except Exception as e:
        print(f"pick_location_suggestion: could not focus combobox: {e}")
        return FillResult(False, False, False)

    # 2) Build a pragmatic value_to_fill (city + first letter of state/country if present)
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if len(parts) == 3:
        city, state, country = parts
        value_to_fill = f"{city}, {state[:1]}"
    elif len(parts) == 2:
        city, country = parts
        value_to_fill = f"{city}, {country[:1]}"
    else:
        city = parts[0] if parts else value
        value_to_fill = city

    did_fill = False
    try:
        target_input.fill(value_to_fill, timeout=2000)
        did_fill = True
    except Exception as e:
        print(f"pick_location_suggestion: fill failed: {e}")
        return FillResult(True, False, False)

    # 3) Wait for suggestions to render
    try:
        page.wait_for_selector("ul._599r li[role='option']", timeout=3000)
    except Exception:
        print("pick_location_suggestion: suggestions did not render in time")
        return FillResult(True, did_fill, False)

    # 4) Grab texts of all suggestions
    options = page.locator("ul._599r li[role='option']")
    option_texts = options.all_text_contents()

    print(f"Found {len(option_texts)} suggestions:")
    if debug:
        for t in option_texts:
            print(f"- {t}")

    # 5) Score each option vs the full desired value
    value_tokens_unique = set(_tokens(value))
    scored = []
    for idx, opt_text in enumerate(option_texts):
        opt_tokens = _tokens(opt_text)
        score, neg_len, full_coverage = _score_option(value_tokens_unique, opt_tokens)
        scored.append((idx, score, neg_len, full_coverage, opt_text, opt_tokens))

    if not scored:
        print("No suggestions available.")
        return

    # Sort: best score desc, then shorter option, then full coverage True first
    scored.sort(key=lambda x: (x[1], x[2], x[3]), reverse=True)

    best_idx, best_score, _, best_full, best_text, best_tokens = scored[0]
    print(f"\nBest match: {best_text!r} "
          f"(score={best_score:.3f}, tokens={len(best_tokens)}, full_coverage={best_full})")

    if click_on_best:
        # 6) Click the best option
        try:
            options.nth(best_idx).click(timeout=2000)
            return FillResult(True, True, True)
        except Exception as e:
            print(f"pick_location_suggestion: clicking best option failed: {e}")
            return FillResult(True, did_fill, False)
    return FillResult(True, False, False)

def print_location_suggestions_gold(page,value):
    # Locate the combobox input
    combobox = page.locator("input[role='combobox'][placeholder*='Location']")
    combobox.click()
    #split by ,
    splitted_values= value.split(",")
    if len(splitted_values) == 3:
        #must be city, state, country
        city=splitted_values[0]
        state=splitted_values[1]
        country=splitted_values[2]
        value_to_fill=city+", "+state[0]
    elif len(splitted_values) == 2:
        #must be city, country
        city=splitted_values[0]
        country=splitted_values[1]
        value_to_fill=city+", "+country[0]
    else:
        #must be city
        city=value
        value_to_fill=city
    combobox.fill(value_to_fill)

    # Wait until suggestion list appears
    page.wait_for_selector("ul._599r li[role='option']")

    # Grab all suggestions
    options = page.locator("ul._599r li[role='option']")
    count = options.count()

    print(f"Found {count} suggestions:")
    for i in range(count):
        text = options.nth(i).inner_text()
        print(f"- {text}")


def find_combobox_anywhere(
    page: Page, 
    value: str, 
    synonyms: List[str], 
    input_names: List[str]
) -> Tuple[bool, bool, bool]:
    """
    Find a combobox/autocomplete input on the page matching synonyms or input_names.

    Returns a tuple (present, filled, matches_value):
        - (False, False, False) → no combobox found
        - (True, True, True)   → combobox found and already has the expected value
        - (True, True, False)  → combobox found but has a different value
        - (True, False, False) → combobox found but is empty
    """

    candidates: List[Locator] = []

    # 1) Generic role combobox
    candidates.append(page.get_by_role("combobox"))

    # 2) Role with accessible name
    for lt in synonyms:
        candidates.append(page.get_by_role("combobox", name=lt, exact=False))

    # 3) Label → input mapping
    for lt in synonyms:
        candidates.append(
            page.locator(f"label:has-text('{lt}')")
                .locator("input[role='combobox'], input[aria-autocomplete]")
        )

    # 4) Placeholder matches
    for lt in synonyms:
        candidates.append(page.locator(f"input[placeholder*='{lt}' i][role='combobox']"))

    # 5) Input name attribute matches
    for key in input_names:
        candidates.append(
            page.locator(f"input[name*='{key}' i][role='combobox'], [role='combobox'][name*='{key}' i]")
        )

    # Deduplicate locators (Playwright doesn’t like duplicate queries sometimes)
    seen = set()
    unique_candidates = []
    for cand in candidates:
        try:
            sel = cand.selector
        except Exception:
            sel = str(cand)
        if sel not in seen:
            seen.add(sel)
            unique_candidates.append(cand)

    # Now check each candidate
    for cb in unique_candidates:
        try:
            if not cb.is_visible(timeout=1000):
                continue
            current_value = cb.input_value(timeout=1000).strip()
            if current_value == value: #TODO : check if the value is almost the same, not necessarly equal
                return True, True, True
            elif current_value:
                return True, True, False
            else:
                return True, False, False
        except Exception:
            continue

    return False, False, False

def try_select_combobox_anywhere(
    page: Page,
    value: str,
    synonyms: List[str],
    input_names: List[str]
):
    """
    present: bool         # we found a matching input in this context
    filled: bool          # we actually filled it right now
    already_ok: bool      # it already had the desired value
    """
    found,filled,already_ok = find_combobox_anywhere(page,value,synonyms,input_names)
    if not found:
        return FillResult(False, False, False)
    if not filled or not already_ok:
        found,filled,already_ok = pick_location_suggestion(page,value,click_on_best=True)
    return FillResult(True, filled, already_ok)


