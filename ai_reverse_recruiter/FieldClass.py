from enum import Enum
from typing import Union, Optional
from playwright.sync_api import Page, Frame, Locator
from playwright.sync_api import expect
import re
from playwright.async_api import async_playwright
import asyncio
import difflib
import asyncio
import time
from angular_helper import reveal_all_select_options
from functions_util import string_similarity,_norm, select_from_mat_select, get_closest_match, all_inner_texts_fast
from playwright.async_api import TimeoutError as PwTimeoutError
class InputType(Enum):
    NOT_FOUND = "NOT_FOUND"
    TEXTBOX = "TEXTBOX"
    TEXTAREA = "TEXTAREA"
    CHECKBOX = "CHECKBOX"
    RADIO = "RADIO"
    SELECT = "SELECT"
    COMBOBOX = "COMBOBOX" # ARIA combobox (standard)
    CUSTOM_COMBOBOX = "CUSTOM_COMBOBOX" # Framework-specific combobox (MUI, PrimeNG, etc.)
    DATE = "DATE"
    NUMBER = "NUMBER"
class Field:
    """Abstract base class for any form field.

    Every Field wraps a *context* (Page or Frame) and a root Locator.
    Subclasses should implement :meth:`fill`.
    """

    input_type: InputType = InputType.NOT_FOUND

    def __init__(self, ctx: Union[Page, Frame, None], locator: Optional[Locator]):
        self.ctx = ctx
        self.locator = locator

    # Convenience flags
    @property
    def is_found(self) -> bool:
        return self.locator is not None and self.input_type is not InputType.NOT_FOUND

    # Lifecycle helpers
    def _ensure_visible(self, timeout: float = 1500) -> None:
        if not self.locator:
            return
        try:
            self.locator.wait_for(state="attached", timeout=timeout)
            # Avoid flakiness with offscreen elements
            self.locator.scroll_into_view_if_needed(timeout=timeout)
        except Exception:
            pass

    # Public API
    def fill(self, value) -> None:  # pragma: no cover -- abstract-ish
        raise NotImplementedError(f"fill() not implemented for {self.__class__.__name__}")




# ---- Concrete Field types ---------------------------------------------------
class NotFoundField(Field):
    input_type = InputType.NOT_FOUND

    def __init__(self):
        super().__init__(None, None)

    def fill(self, value) -> None:
        # Intentionally a no-op; caller can check is_found
        pass


class TextField(Field):
    input_type = InputType.TEXTBOX

    def fill(self, value) -> None:
        self._ensure_visible()
        if not self.locator:
            return
        self.locator.fill("")
        self.locator.type(str(value))


class TextAreaField(Field):
    input_type = InputType.TEXTAREA

    def fill(self, value) -> None:
        self._ensure_visible()
        if not self.locator:
            return
        self.locator.fill("")
        self.locator.type(str(value))


class NumberField(Field):
    input_type = InputType.NUMBER

    def fill(self, value) -> None:
        self._ensure_visible()
        if not self.locator:
            return
        self.locator.fill(str(value))


class DateField(Field):
    input_type = InputType.DATE

    def fill(self, value) -> None:
        self._ensure_visible()
        if not self.locator:
            return
        # Most date inputs accept yyyy-mm-dd; adapt if your app needs a formatter
        self.locator.fill(str(value))


class CheckboxField(Field):
    input_type = InputType.CHECKBOX

    def fill(self, value) -> None:
        self._ensure_visible()
        if not self.locator:
            return
        desired = bool(value)
        try:
            checked = self.locator.is_checked()
        except Exception:
            checked = False
        if desired and not checked:
            self.locator.check()
        elif not desired and checked:
            self.locator.uncheck()


class RadioField(Field):
    input_type = InputType.RADIO

    def _normalize_yes_no(self, value: object) -> str:
        s = ("" if value is None else str(value)).strip().lower()
        if s in {"y", "yes", "true", "1", "on"}:
            return "yes"
        if s in {"n", "no", "false", "0", "off"}:
            return "no"
        # fall back to raw text (still used as case-insensitive)
        return s or "yes"

    def _try_check(self, loc: Locator) -> bool:
        """Try to select a target radio; returns True if it looks selected."""
        try:
            # If it's a native input[type=radio], prefer check()
            tag = (loc.evaluate("e => e.tagName && e.tagName.toLowerCase()") or "").lower()
            typ = (loc.get_attribute("type") or "").lower()
            if tag == "input" and typ == "radio":
                loc.check()  # waits for actionable state
                return True
        except Exception:
            pass
        try:
            # Fallback click (works for ARIA/custom implementations)
            loc.click()
            return True
        except Exception:
            return False

    def fill(self, value) -> None:
        self._ensure_visible()
        if not self.locator or self.ctx is None:
            return

        wanted = self._normalize_yes_no(value)  # "yes" or "no"
        # Scope searches to this field/group when possible
        scope: Locator = self.locator

        # Build a case-insensitive exact-match regex for the visible/accessible text
        name_rx = re.compile(rf"^\s*{re.escape(wanted)}\s*$", re.I)

        # 1) Prefer ARIA: role="radio" with accessible name
        target = scope.get_by_role("radio", name=name_rx)
        if target.count() == 0:
            # Some libraries don't expose an accessible name; try text content
            target = scope.locator("[role='radio']", has_text=name_rx)
        if target.count() > 0 and self._try_check(target.first):
            return

        # 2) Native input radios: by value attribute (try common casings)
        for v in {wanted, wanted.capitalize(), wanted.upper(), wanted.lower(), wanted.title()}:
            cand = scope.locator(f"input[type='radio'][value='{v}']")
            if cand.count() > 0 and self._try_check(cand.first):
                return

        # 3) Angular Material: <mat-radio-button> text → inner input
        mat_btn = scope.locator("mat-radio-button", has_text=name_rx).first
        if mat_btn.count() > 0:
            inner = mat_btn.locator("input[type='radio']").first
            if inner.count() > 0 and self._try_check(inner):
                return
            # If inner input not found/actionable, click the button itself
            if self._try_check(mat_btn):
                return

        # 4) Labels associated to inputs (native pattern)
        label = scope.locator("label", has_text=name_rx).first
        if label.count() > 0:
            # Prefer clicking the label—it toggles the associated input safely
            try:
                label.click()
                return
            except Exception:
                pass
            # If clicking label fails, try its 'for' target directly
            try:
                for_id = label.get_attribute("for")
                if for_id:
                    assoc = scope.locator(f"#{for_id}")
                    if assoc.count() > 0 and self._try_check(assoc.first):
                        return
            except Exception:
                pass

        # 5) Last resort: search any descendant input[type=radio] whose
        #    nearest visible label text matches
        radios = scope.locator("input[type='radio']")
        count = radios.count()
        for i in range(count):
            r = radios.nth(i)
            # Try to locate a sibling/ancestor label text
            candidate = r.locator("xpath=ancestor::*[self::mat-radio-button or @role='radio' or @role='radiogroup'] | ..")
            if candidate.count() == 0:
                candidate = r.locator("..")
            try:
                txt = (candidate.first.inner_text(timeout=500) or "").strip()
            except Exception:
                txt = ""
            if re.search(name_rx, txt or "", flags=0):
                if self._try_check(r):
                    return

        # If we reach here, we couldn't find a matching option.
        # Surface a clear error for the caller/logs.
        raise ValueError(f"Radio option not found for value '{value}' within this field.")


class SelectField(Field):
    input_type = InputType.SELECT

    def fill(self, value) -> None:
        self._ensure_visible()
        if not self.locator:
            return
        # Try by value first, then by label
        try:
            self.locator.select_option(str(value))
            return
        except Exception:
            pass
        try:
            self.locator.select_option(label=str(value))
        except Exception:
            # Fallback: open and click option text
            self.locator.click()
            opt = self.locator.locator("option", has_text=str(value)).first
            opt.click()


class AriaComboBoxField(Field):
    """Standard ARIA combobox (role=combobox + role=option listbox)."""

    input_type = InputType.COMBOBOX

    def click_all_optgroups(self,page: Page, combobox_name: str):
        # 1) Open the combobox by its accessible name (use your own locator if needed)
        # combo = page.get_by_role("combobox", name=combobox_name)
        # combo.scroll_into_view_if_needed()
        # combo.click()
        #print("click_all_optgroups : clicked the combobox")
        # 2) Wait for the overlayed listbox (the open panel) to appear
        #    We scope to the overlay container & require "open" surface to avoid stale panels
        overlay = page.locator("div.cdk-overlay-container div[role='listbox'].mdc-menu-surface--open").first
        expect(overlay).to_be_visible()
        #print("click_all_optgroups : the overlay is visible")
        # Optional: ensure the panel is scrolled to top before we start
        overlay.evaluate("el => el.scrollTo(0, 0)")
        #print("click_all_optgroups : the overlay is scrolled to top")
        # 3) Click every optgroup label
        groups = overlay.get_by_role("group")  # mat-optgroup has role="group"
        count = groups.count()
        if count == 0:
            print("click_all_optgroups : no groups found")
            return False
        #print("click_all_optgroups : the groups are found")
        for i in range(count):
            # Re-query each time in case DOM shifts after clicks/animations
            group = overlay.get_by_role("group").nth(i)
            # Try common label targets inside the group
            label_locator = group.locator(".mat-mdc-optgroup-label, .mdc-list-item__primary-text").first

            # If the label isn't there yet (virtual scroll), scroll it into view
            label_locator.scroll_into_view_if_needed()

            try:
                label_locator.click()
                #print(f"click_all_optgroups : clicked the label {label_locator}")
                time.sleep(1)
            except Exception:
                # If the panel closed or click failed, reopen and retry once
                combo = page.get_by_role("combobox", name=combobox_name)
                combo.scroll_into_view_if_needed()
                combo.click()
                expect(overlay).to_be_visible()
                group = overlay.get_by_role("group").nth(i)
                label_locator = group.locator(".mat-mdc-optgroup-label, .mdc-list-item__primary-text").first
                label_locator.scroll_into_view_if_needed()
                label_locator.click()
            # After expanding the group, select only the option closest to "linkedin"
            # for i in range(groups.count()):
            #     group = overlay.get_by_role("group").nth(i)
            #     options = group.locator("mat-option[role='option']")
            #     for j in range(options.count()):
            #         opt = options.nth(j)
            #         opt.scroll_into_view_if_needed()
            #         opt.click()  # Uncomment to select each option
            #         return
            # ---- pick the best matching option in this group ----
            options = group.locator("mat-option[role='option']")
            opt_count = options.count()

            best_idx = None
            best_score = -1.0

            # (Optional fast path) if any option text contains "linkedin" exactly, prefer that
            for oi in range(opt_count):
                opt = options.nth(oi)
                txt = (opt.inner_text() or "").strip()
                if "linkedin" in txt.casefold():
                    best_idx = oi
                    best_score = 1.0
                    return True
                    break

            # Otherwise compute similarity for all options and pick the top one
            if best_idx is None:
                for oi in range(opt_count):
                    opt = options.nth(oi)
                    txt = (opt.inner_text() or "").strip()
                    score = string_similarity(txt, "linkedin")
                    if score > best_score:
                        best_score = score
                        best_idx = oi

            # click if above threshold; otherwise continue to next group
            if best_idx is not None and best_score >= 0.7:
                target_opt = options.nth(best_idx)
                target_opt.scroll_into_view_if_needed()
                target_opt.click()
                ##print(f"Selected option in group {gi} with score {best_score:.3f}")
                return True  # stop after selecting the best acceptable option
        return True
        #print("No option met the similarity threshold; nothing was clicked.")
    def click_best_option(self, page: Page, value: str) -> bool:
        print("click_best_option: clicking the best option")
        options = page.locator("mat-option[role='option']")
        option_count = options.count()
        if option_count == 0:
            print("click_best_option: no options found")
            return False

        best_index = None
        best_score = 0.0

        for i in range(option_count):
            txt = options.nth(i).inner_text().strip()
            score = string_similarity(txt, value)
            if score > best_score:
                best_score = score
                best_index = i

        if best_index is not None:
            best_option = options.nth(best_index)
            print(f"click_best_option: clicking '{best_option.inner_text()}' (score={best_score:.2f})")
            best_option.click()
            return True
        else:
            print("click_best_option: no suitable option found")
            return False

        #use this function to click the best option score = string_similarity(txt, value)
    def fill(self, value) -> None:
        #print("filling a aria combobox...")
        self._ensure_visible()
        if not self.locator:
            return
        # Open the popup
        self.locator.click()
        # If there's an inner input, type to filter
        inner = self.locator.locator("input, [contenteditable='true']").first
        if inner.count() > 0:
            #print("filling the inner input...with value", value)
            inner.fill("")
            inner.type(str(value))
        else:
            print("no inner input found")

        # Detect Angular Material select/autocomplete patterns
        is_angular_material = False
        try:
            classes = (self.locator.get_attribute("class") or "")
            if any(token in classes for token in ("mat-select", "mat-mdc-select", "mat-autocomplete", "mat-mdc-autocomplete")):
                is_angular_material = True
            elif self.ctx is not None:
                overlay_like = self.ctx.locator("div[role='listbox'][id$='-panel'], .mat-select-panel, .mat-mdc-select-panel, .mat-mdc-autocomplete-panel")
                if overlay_like.count() > 0:
                    is_angular_material = True
        except Exception:
            pass

        if is_angular_material:
            print("filling a angular material combobox...")
            if self.click_all_optgroups(self.ctx, value):
                return
            if self.click_best_option(self.ctx, value):
                return

        # Prefer role=option in the same context (handles portals if ctx is a Page)
        option = None
        if self.ctx is not None:
            #print("finding the option in the same context...")
            option = self.ctx.get_by_role("option", name=str(value), exact=True)
            #print("lets ccheck : ")
            if option.count() == 0:
                #print("no option found with first try")
                option = self.ctx.locator("[role='option']", has_text=str(value)).first
        else:
            #print("no context found")
            option = self.locator.locator("[role='option']", has_text=str(value)).first
        #print("clicking the option...")
        option.click()


class CustomComboBoxField(Field):
    """Framework-styled comboboxes (MUI Autocomplete, PrimeNG p-dropdown, etc.).

    Strategy:
      1) Click root to open.
      2) If an inner text entry exists, type the value.
      3) Prefer clicking a matching option by role or text.
      4) Fallback to ENTER if nothing clickable is discovered.
    """

    input_type = InputType.CUSTOM_COMBOBOX
    
    def fill(self, value) -> None:
        #print("filling a custom combobox...")
        self._ensure_visible()
        if not self.locator:
            return
        # 1) Open the widget
        self.locator.click()

        # 2) Type into any inner editable
        inner = self.locator.locator("input:not([type='hidden']), [contenteditable='true']").first
        if inner.count() > 0:
            try:
                inner.fill("")
            except Exception:
                pass
            try:
                inner.type(str(value), delay=30)
            except Exception:
                pass
        else:
            print("no inner editable found")

        # 3) Try selecting an option (supporting portals rendered outside the root)
        option = None
        if self.ctx is not None:
            # Prefer ARIA roles if exposed
            option = self.ctx.get_by_role("option", name=str(value), exact=True)
            if option.count() == 0:
                #print("no option found with first try")
                option = self.ctx.locator("[role='option']", has_text=str(value)).first
            # Many libs render listbox/menuitem options
            if option.count() == 0:
                #print("no option found with second try")
                option = self.ctx.locator("[role='listbox'] [role='option'], [role='menu'] [role='menuitem']", has_text=str(value)).first
        else:
            option = self.locator.locator("[role='option']", has_text=str(value)).first

        try:
            if option and option.count() > 0:
                option.first.click()
                return
        except Exception:
            pass

        # 4) Fallback: press Enter to commit the typed value
        try:
            target = inner if inner and inner.count() > 0 else self.locator
            target.press("Enter")
        except Exception:
            # Last resort: click again to close
            try:
                self.locator.click()
            except Exception:
                pass

