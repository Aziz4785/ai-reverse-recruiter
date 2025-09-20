import re
from typing import List, Optional, Union
from playwright.sync_api import Page, Frame, Locator, Error
from functions_util import _first_interactable, _label_text_for_input
LOC_RX = r"(?:location|city|town|localit(?:y|é)|place|address|addr|country|region|state|province|zip|postal|postcode)"
LOC_RE = re.compile(LOC_RX, re.I)


def _looks_like_location(ctx: Page | Frame, cand: Locator) -> bool:
    """Accept only if the label or the element itself carries location signals."""
    try:
        # 1) Check attached/nearby label text
        lab_text = _label_text_for_input(ctx, cand)
        if lab_text and LOC_RE.search(lab_text):
            return True

        # 2) Check element attributes (autocomplete/placeholder/name/id/class)
        attrs = {}
        for a in ("autocomplete", "placeholder", "name", "id", "class", "aria-label", "role"):
            try:
                v = cand.get_attribute(a)
            except Error:
                v = None
            if v:
                attrs[a] = v
        hay = " ".join(attrs.values()).lower()

        if LOC_RE.search(hay):
            return True

        # Address-y autocompletes (even if the word 'address' isn’t in our synonyms)
        if "address" in hay or "postal" in hay or "zip" in hay:
            return True

        # Combobox with list autocomplete is common for place pickers
        if attrs.get("role") == "combobox" and "list" in attrs.get("aria-autocomplete", ""):
            # still require some hint elsewhere (placeholder like 'Start typing' is too generic alone)
            ph = attrs.get("placeholder", "")
            if LOC_RE.search(ph) or "address" in ph.lower():
                return True
            # otherwise don’t accept on role alone
            return False

        return False
    except Error:
        return False

def _find_location_field(ctx: Page | Frame, synonyms: List[str]) -> Optional[Locator]:
    """
    Find a 'Location' style text/combobox input.
    Returns the first visible, enabled Locator that passes location checks.
    """
    base_terms = [
        "location", "city", "town", "locality", "place", "address",
        "country", "region", "state", "province", "postal code", "postcode", "zip code"
    ]
    terms = sorted(set([*(synonyms or []), *base_terms]), key=len, reverse=True)

    candidates: List[Locator] = []

    # 1) Exact label association
    for t in terms:
        candidates.append(ctx.get_by_label(t, exact=True))

    # 2) Role-based by name (strict)
    for t in terms:
        candidates.append(ctx.get_by_role("combobox", name=t, exact=True))
        candidates.append(ctx.get_by_role("textbox",  name=t, exact=True))

    # 3) Narrow label→field hop:
    #    Take the nearest small wrapper around the label (div/section/li) then the first input/combobox inside it.
    for t in terms:
        esc = t.replace("'", "\\'")
        label = ctx.locator(f"label:has-text('{esc}')")
        # following input within the same field block
        candidates.append(label.locator("xpath=following::input[1]"))
        # nearest ancestor block that likely wraps the pair, then first input/combobox inside
        candidates.append(
            label.locator(
                "xpath=ancestor::*[self::div or self::section or self::li or self::td or self::th][1]"
            ).locator("input, [role='combobox']")
        )

    # 4) Attribute-based hints (address-y)
    candidates.append(ctx.locator(
        "input[autocomplete*='address' i], "
        "input[autocomplete*='street' i], "
        "input[autocomplete*='country' i], "
        "input[autocomplete*='postal' i], "
        "input[autocomplete*='zip' i]"
    ))

    # 5) Name/ID/class/placeholder contains location-ish words
    candidates.append(ctx.locator(
        f"input, [role='combobox'] >> css="
        f"[name*={LOC_RX} i], [id*={LOC_RX} i], [class*={LOC_RX} i], [data-testid*={LOC_RX} i], "
        f"[placeholder*={LOC_RX} i]"
    ))

    # 6) Popular widget classes
    candidates.append(ctx.locator(
        "input.pac-target-input, input.mapboxgl-ctrl-geocoder--input, input[aria-controls*='algolia' i]"
    ))

    # Walk candidates and keep only those that truly look like location
    seen = set()
    for loc in candidates:
        cand = _first_interactable(loc)
        if not cand:
            continue
        # de-dup by DOM element handle
        try:
            handle = cand.element_handle()
            if not handle:
                continue
            key = handle
            if key in seen:
                continue
            seen.add(key)
        except Error:
            pass

        if _looks_like_location(ctx, cand):
            return cand

    return None