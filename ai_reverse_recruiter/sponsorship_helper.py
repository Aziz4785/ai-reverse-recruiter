import re
from typing import List, Optional
from playwright.sync_api import Page, Frame, Locator
from functions_util import _first_visible
QUESTION_SCOPE_SELECTOR = (
    # things that typically carry the question text
    "label, legend, [role='heading'], h1, h2, h3, h4, h5, h6, "
    # common class name catch-alls
    "[class*='question'], [class*='title'], [class*='prompt']"
)

# controls we consider as answers
ANSWER_CONTROLS_SELECTOR = (
    "input, select, textarea, "
    "[role='group'] *, [role='radiogroup'] *, [role='combobox'], "
    "button"  # many ATS use button-based yes/no toggles
)

SPONSOR_REGEX = re.compile(
    r"(sponsor|sponsorship|work\s*permit|work\s*authorization|immigration|"
    r"visa|h[\-\s]?1b|h1b|opt|cpt|tn\s*visa|"
    r"require\s+sponsorship|need\s+sponsorship)",
    re.I,
)

YES_NO_REGEX = re.compile(r"^\s*(yes|no)\s*$", re.I)

def find_sponsorship_field(ctx: Page | Frame) -> Optional[Locator]:
    # 1) Find likely question nodes by regex against their text
    question_nodes = ctx.locator(QUESTION_SCOPE_SELECTOR).filter(has_text=SPONSOR_REGEX)

    # If nothing matched, also try a broader page-level text search and then narrow down
    if question_nodes.count() == 0:
        broad = ctx.get_by_text(SPONSOR_REGEX, exact=False)
        if broad.count():
            question_nodes = broad

    # 2) Iterate candidates
    max_candidates_to_check = min(question_nodes.count(), 25)
    for i in range(max_candidates_to_check):
        q = question_nodes.nth(i)

        # 2a) If the question is a <label for="...">, target that control by id/name
        try:
            tag = q.evaluate("el => el.tagName && el.tagName.toLowerCase()")
        except Exception:
            tag = None

        if tag == "label":
            target_id = q.get_attribute("for")
            if target_id:
                direct = ctx.locator(f"#{css_escape(target_id)}, [name='{css_escape(target_id)}']")
                cand = _first_visible(direct)
                if cand:
                    return cand

        # 2b) Otherwise, use a nearby container then search for interactive answers
        # Try: nearest ancestor that looks like a field wrapper; fall back to the question node itself
        container = q.locator(
            # climb to a likely field container (common patterns)
            "xpath=ancestor::*[self::div or self::section or self::fieldset][1]"
        )
        if container.count() == 0:
            container = q

        # Prefer obvious controls inside the same container
        within = container.locator(ANSWER_CONTROLS_SELECTOR)

        # Special case: sites using button-based Yes/No toggles
        yes_no = within.filter(has_text=YES_NO_REGEX)
        cand = _first_visible(yes_no)
        if cand:
            return cand

        # Radios/checkboxes/combobox/inputs/selects
        formish = container.locator(
            "input[type='radio'], input[type='checkbox'], select, [role='combobox'], input, textarea"
        )
        cand = _first_visible(formish)
        if cand:
            return cand

        # Fallback: any visible button in the container
        cand = _first_visible(container.locator("button"))
        if cand:
            return cand

    # 3) As a last resort, scan the whole page for a radiogroup with sponsorship text nearby
    all_groups = ctx.locator("[role='radiogroup'], [role='group'], fieldset")
    groups_to_check = min(all_groups.count(), 30)
    for i in range(groups_to_check):
        g = all_groups.nth(i)
        # Check if this group has a nearby sponsorship phrase
        if g.filter(has_text=SPONSOR_REGEX).count() or g.locator("xpath=preceding::*[1]").filter(has_text=SPONSOR_REGEX).count():
            # pick a visible option
            cand = _first_visible(g.locator("input, button, [role='radio']"))
            if cand:
                return cand

    return None

def css_escape(s: str) -> str:
    # conservative CSS id/name escape
    return s.replace("\\", "\\\\").replace("'", "\\'")