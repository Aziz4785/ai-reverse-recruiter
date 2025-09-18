from enum import Enum
from typing import List, Optional, Dict, Type
from playwright.sync_api import Page, Frame, Locator
from playwright.async_api import async_playwright
import re
from FieldClass import Field, InputType, NotFoundField, TextField, AriaComboBoxField, CustomComboBoxField, TextAreaField, CheckboxField, RadioField, SelectField, DateField, NumberField
from functions_util import print_html_element
# ---- Registry & Factory -----------------------------------------------------
FIELD_REGISTRY: Dict[InputType, Type[Field]] = {
    InputType.NOT_FOUND: NotFoundField, # Not used by factory, but useful for adapters
    InputType.TEXTBOX: TextField,
    InputType.TEXTAREA: TextAreaField,
    InputType.NUMBER: NumberField,
    InputType.DATE: DateField,
    InputType.CHECKBOX: CheckboxField,
    InputType.RADIO: RadioField,
    InputType.SELECT: SelectField,
    InputType.COMBOBOX: AriaComboBoxField,
    InputType.CUSTOM_COMBOBOX: CustomComboBoxField,
}

# String-name compatibility map so we can work with external InputType enums
# that use names like INPUT_TEXT, COMBOBOX, CUSTOM_COMBOBOX, etc.
FIELD_REGISTRY_BY_NAME: Dict[str, Type[Field]] = {
    "INPUT_TEXT": TextField,
    "TEXTBOX": TextField,
    "TEXTAREA": TextAreaField,
    "CHECKBOX": CheckboxField,
    "RADIO": RadioField,
    "SELECT": SelectField,
    "COMBOBOX": AriaComboBoxField, # unified handler (native select + ARIA)
    "CUSTOM_COMBOBOX": CustomComboBoxField,
    "DATE": DateField,
    "NUMBER": NumberField,
}

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
        # Correct role for a plain email input
        candidates.append(ctx.get_by_role("textbox", name=s, exact=True))
        candidates.append(ctx.locator(f"[id='{s}'], [attrid='{s}'], [formcontrolname='{s}']"))
         # ---- NEW: prefer text inputs for phone-like labels ----
        if re.search(r"\b(phone|téléphone|mobile|cell)\b", s, re.I):
            # Direct aria-label match (Angular Material uses this a lot)
            candidates.append(ctx.locator(f"input[aria-label='{s}' i], textarea[aria-label='{s}' i]"))
            # <mat-form-field> with a <mat-label> that has the text
            candidates.append(
                ctx.locator(f"mat-form-field:has(mat-label:has-text('{s}'))").locator("input, textarea, [matinput]")
            )
            # Role-based textbox (kept exact to avoid grabbing “Phone Extension” unless you pass it)
            candidates.append(ctx.get_by_role("textbox", name=s, exact=True))

    #print("we have ", len(candidates), "candidates from the strong signals")
    # Fallbacks: placeholder/name
    for s in synonyms:
        candidates.append(ctx.locator(f"input[placeholder='{s}' i], select[placeholder='{s}' i]")) #replace = with *= if you want to be more flexible
        candidates.append(ctx.locator(f"input[name='{s}' i], select[name='{s}' i], [role='combobox'][name='{s}' i]")) #replace = with *= if you want to be more flexible

    # Return first visible hit
    print("we have ", len(candidates), "candidates")
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

def _proper_aria_combobox(el: Locator) -> bool:
    role = (el.get_attribute("role") or "").lower()
    haspopup = (el.get_attribute("aria-haspopup") or "").lower()
    if role == "combobox" or haspopup == "listbox":
        #print("it is a combobox because of ARIA combobox pattern")
        return True
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
        print("root :")
        print_html_element(root)

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
        has_dropdown_cls = root.locator("xpath=.//*[contains(@class,'dropdown')]").first.count() > 0
        if has_dropdown_cls:
            print("_nearby_custom_dropdown return true because we found a .//* with class 'dropdown'")
            return True
        has_typeahead_cls = root.locator("xpath=.//*[contains(@class,'typeahead')]").first.count() > 0
        if has_typeahead_cls:
            print("_nearby_custom_dropdown return true because we found a following::* with class 'typeahead'")
            return True
        has_autocomplete_cls = root.locator("xpath=.//*[contains(@class,'autocomplete')]").first.count() > 0
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
    print("_classify_field()")
    tag = _tag_name(el)
    attr_id = _attr(el, "id")
    attr_name = _attr(el, "name")
    print("tag :", tag)
    #print("Locator repr:", el)  # shows frame + selector
    print("tag:",tag)
    print("id:", attr_id)
    print("name:", attr_name)
    # print("class:", _attr(el, "class"))
    # print("role:", _attr(el, "role"))
    # print("aria-autocomplete:", _attr(el, "aria-autocomplete"))
    # print("placeholder:", _attr(el, "placeholder"))
    # Native select
    print_html_element(el)
    if tag == "select":
        print("it is a combobox because we have a select tag")
        return InputType.COMBOBOX

    # input + datalist
    if tag == "input" and _has_datalist(ctx, el):
        print("it is a combobox because we have a input tag with a datalist")
        return InputType.COMBOBOX

    if _proper_aria_combobox(el):
        return InputType.COMBOBOX
    # ARIA combobox/auto
    if _aria_combobox_like(el):
        return InputType.COMBOBOX if _aria_listbox_wired(ctx, el) else InputType.CUSTOM_COMBOBOX

    # Custom dropdown patterns near a text input
    if tag == "input":
        if _nearby_custom_dropdown(ctx, el):
            print("it is a combobox because we have a input tag with a nearby custom dropdown")
            return InputType.CUSTOM_COMBOBOX

        return InputType.TEXTBOX


    # Fallback
    return InputType.TEXTBOX


def get_field_of(page: Page, synonyms: List[str]) -> Field:
    """Return a concrete :class:`Field` instance ready to ``fill(value)``.


    Searches the main page and iframes, finds the first field matching the
    provided synonyms, classifies it, and returns the appropriate object.
    """
    for ctx in _all_contexts(page):
        loc = _find_first_matching_field(ctx, synonyms)
        print_html_element(loc)
        if not loc:
            continue
        try:
            loc.wait_for(state="attached", timeout=800)
            input_type = _classify_field(ctx, loc)
            print("classify_field return ", input_type)
            # Prefer exact enum-key match; fall back to name/value strings
            name = getattr(input_type, "name", None) or getattr(input_type, "value", None) or str(input_type)

            if isinstance(name, str):
                name = name.split(".")[-1].upper()
            else:
                print("name is not a string")
            print("name :", name)
            field_cls = FIELD_REGISTRY.get(input_type) or FIELD_REGISTRY_BY_NAME.get(name, TextField)
            print("field_cls :", field_cls)
            return field_cls(ctx, loc)
        except Exception as e:
            print("exception in get_field_of", e)
            continue
    return NotFoundField()