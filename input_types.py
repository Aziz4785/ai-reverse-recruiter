from enum import Enum
from typing import List, Optional
from playwright.sync_api import Page, Frame, Locator

class InputType(Enum):
    INPUT_TEXT = "INPUT_TEXT"
    COMBOBOX = "COMBOBOX"               # native <select>, <input list=...>, or proper ARIA combobox
    CUSTOM_COMBOBOX = "CUSTOM_COMBOBOX" # JS-enhanced text input with its own dropdown
    NOT_FOUND = "NOT_FOUND"

def get_input_type_of(page: Page, synonyms: List[str]) -> InputType:
    """
    Find the first matching field by synonyms (label/placeholder/name/role)
    across the main page + iframes, then classify it.
    """
    print("getting the input type of that field...")
    for ctx in _all_contexts(page):
        loc = _find_first_matching_field(ctx, synonyms)
        if not loc:
            continue
        try:
            # Make sure it's attached and visible enough to classify
            loc.wait_for(state="attached", timeout=800)
            return _classify_field(ctx, loc)
        except Exception:
            pass
    print("we did not find the field")
    return InputType.NOT_FOUND

# ----------------- helpers -----------------

def _all_contexts(page: Page) -> List[Page | Frame]:
    ctxs: List[Page | Frame] = [page]
    for fr in page.frames:
        if fr != page.main_frame:
            ctxs.append(fr)
    return ctxs

def _first_visible(loc: Locator) -> Optional[Locator]:
    try:
        n = loc.count()
    except Exception:
        return None
    for i in range(n):
        cand = loc.nth(i)
        try:
            if cand.is_visible():
                return cand
        except Exception:
            continue
    return None

def _find_first_matching_field(ctx: Page | Frame, synonyms: List[str]) -> Optional[Locator]:
    candidates: List[Locator] = []

    # Strong signals
    for s in synonyms:
        candidates.append(ctx.get_by_role("combobox", name=s, exact=True)) #put exact = False if you want to be more flexible
        candidates.append(ctx.get_by_label(s, exact=True)) #put exact = False if you want to be more flexible
        candidates.append(ctx.locator(f"label:text-is('{s}')").locator("input, select, [role='combobox']")) #replace text-is with has-text if you want to be more flexible

    #print("we have ", len(candidates), "candidates from the strong signals")
    # Fallbacks: placeholder/name
    for s in synonyms:
        candidates.append(ctx.locator(f"input[placeholder='{s}' i], select[placeholder='{s}' i]")) #replace = with *= if you want to be more flexible
        candidates.append(ctx.locator(f"input[name='{s}' i], select[name='{s}' i], [role='combobox'][name='{s}' i]")) #replace = with *= if you want to be more flexible

    # Return first visible hit
    #print("we have ", len(candidates), "candidates")
    for j,loc in enumerate(candidates):
        cand = _first_visible(loc)
        if cand:
            print("  the valid locator is at index ", j , " 0-indexed")
            return cand
    return None

def _tag_name(el: Locator) -> str:
    try:
        return el.evaluate("el => el.tagName.toLowerCase()")
    except Exception:
        return ""

def _attr(el: Locator, name: str) -> str:
    try:
        v = el.get_attribute(name)
        return v or ""
    except Exception:
        return ""

def _has_datalist(ctx: Page | Frame, el: Locator) -> bool:
    list_id = _attr(el, "list").strip()
    if not list_id:
        return False
    try:
        return ctx.locator(f"datalist#{list_id}").count() > 0
    except Exception:
        return False

def _aria_combobox_like(el: Locator) -> bool:
    role = _attr(el, "role").lower()
    aria_auto = _attr(el, "aria-autocomplete").lower()
    return role == "combobox" or aria_auto in ("list", "both", "inline")

def _aria_listbox_wired(ctx: Page | Frame, el: Locator) -> bool:
    lb = (_attr(el, "aria-controls") or _attr(el, "aria-owns")).strip()
    if not lb:
        return False
    box = ctx.locator(f"#{lb}")
    try:
        if box.count() == 0:
            return False
        return box.locator("[role='option']").count() > 0 or box.locator("[role='listbox']").count() > 0 or box.locator("ul li, ol li").count() > 0
    except Exception:
        return False

def _nearby_custom_dropdown(ctx: Page | Frame, el: Locator) -> bool:
    try:
        # immediate ancestor to scope relative searches
        #root = el.locator("xpath=ancestor-or-self::*[1]")
        root = el.locator("xpath=ancestor::*[contains(@class,'application') or self::form or self::div][1]")
        # hidden or tracking input nearby
        has_hidden_type = root.locator("input[type='hidden']").count() > 0
        if has_hidden_type:
            print("_nearby_custom_dropdown return true because we have a nearby input[@type='hidden']")
            return True
        has_hidden_attr = root.locator("xpath=following::input[@hidden]").first.count() > 0
        if has_hidden_attr:
            print("_nearby_custom_dropdown return true because we have a nearby input[@hidden]")
            return True
        # dropdown-ish siblings/descendants
        has_dropdown_cls = root.locator("xpath=following::*[contains(@class,'dropdown')]").first.count() > 0
        if has_dropdown_cls:
            print("_nearby_custom_dropdown return true because we found a following::* with class 'dropdown'")
            return True
        has_typeahead_cls = root.locator("xpath=following::*[contains(@class,'typeahead')]").first.count() > 0
        if has_typeahead_cls:
            print("_nearby_custom_dropdown return true because we found a following::* with class 'typeahead'")
            return True
        has_autocomplete_cls = root.locator("xpath=following::*[contains(@class,'autocomplete')]").first.count() > 0
        if has_autocomplete_cls:
            print("_nearby_custom_dropdown return true because we found a following::* with class 'autocomplete'")
            return True
        has_results_cls = root.locator("xpath=following::*[contains(@class,'results')]").first.count() > 0
        if has_results_cls:
            print("_nearby_custom_dropdown return true because we found a following::* with class 'results'")
            return True
    except Exception:
        pass
    return False

def _classify_field(ctx: Page | Frame, el: Locator) -> InputType:
    tag = _tag_name(el)
    print("Locator repr:", el)  # shows frame + selector
    print("tag:", _tag_name(el))
    print("id:", _attr(el, "id"))
    print("name:", _attr(el, "name"))
    print("class:", _attr(el, "class"))
    print("role:", _attr(el, "role"))
    print("aria-autocomplete:", _attr(el, "aria-autocomplete"))
    print("placeholder:", _attr(el, "placeholder"))
    # Native select
    if tag == "select":
        print("it is a combobox because we have a select tag")
        return InputType.COMBOBOX

    # input + datalist
    if tag == "input" and _has_datalist(ctx, el):
        print("it is a combobox because we have a input tag with a datalist")
        return InputType.COMBOBOX

    # ARIA combobox/auto
    if _aria_combobox_like(el):
        return InputType.COMBOBOX if _aria_listbox_wired(ctx, el) else InputType.CUSTOM_COMBOBOX

    # Custom dropdown patterns near a text input
    if tag == "input":
        if _nearby_custom_dropdown(ctx, el):
            print("it is a combobox because we have a input tag with a nearby custom dropdown")
            return InputType.CUSTOM_COMBOBOX
        return InputType.INPUT_TEXT

    # Fallback
    return InputType.INPUT_TEXT