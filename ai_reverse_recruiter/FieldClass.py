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

    def fill(self, value) -> None:
        self._ensure_visible()
        if not self.locator or self.ctx is None:
            return
        # Prefer ARIA radio by accessible name matching the value
        target = self.ctx.get_by_role("radio", name=str(value), exact=True)
        if target.count() == 0:
            target = self.ctx.locator("[role='radio']", has_text=str(value)).first
        target.click()


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
        print("click_all_optgroups : clicked the combobox")
        # 2) Wait for the overlayed listbox (the open panel) to appear
        #    We scope to the overlay container & require "open" surface to avoid stale panels
        overlay = page.locator("div.cdk-overlay-container div[role='listbox'].mdc-menu-surface--open").first
        expect(overlay).to_be_visible()
        print("click_all_optgroups : the overlay is visible")
        # Optional: ensure the panel is scrolled to top before we start
        overlay.evaluate("el => el.scrollTo(0, 0)")
        print("click_all_optgroups : the overlay is scrolled to top")
        # 3) Click every optgroup label
        groups = overlay.get_by_role("group")  # mat-optgroup has role="group"
        count = groups.count()
        print("click_all_optgroups : the groups are found")
        for i in range(count):
            # Re-query each time in case DOM shifts after clicks/animations
            group = overlay.get_by_role("group").nth(i)
            # Try common label targets inside the group
            label_locator = group.locator(".mat-mdc-optgroup-label, .mdc-list-item__primary-text").first

            # If the label isn't there yet (virtual scroll), scroll it into view
            label_locator.scroll_into_view_if_needed()

            try:
                label_locator.click()
                print(f"click_all_optgroups : clicked the label {label_locator}")
                time.sleep(4)
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
                #print(f"Selected option in group {gi} with score {best_score:.3f}")
                return  # stop after selecting the best acceptable option

        print("No option met the similarity threshold; nothing was clicked.")
    def fill(self, value) -> None:
        print("filling a aria combobox...")
        self._ensure_visible()
        if not self.locator:
            return
        # Open the popup
        self.locator.click()
        # If there's an inner input, type to filter
        inner = self.locator.locator("input, [contenteditable='true']").first
        if inner.count() > 0:
            print("filling the inner input...with value", value)
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
            #self.select_contractor(self.ctx, value)
            self.click_all_optgroups(self.ctx, value)
            return

        # Prefer role=option in the same context (handles portals if ctx is a Page)
        option = None
        if self.ctx is not None:
            print("finding the option in the same context...")
            option = self.ctx.get_by_role("option", name=str(value), exact=True)
            print("lets ccheck : ")
            if option.count() == 0:
                print("no option found with first try")
                option = self.ctx.locator("[role='option']", has_text=str(value)).first
        else:
            print("no context found")
            option = self.locator.locator("[role='option']", has_text=str(value)).first
        print("clicking the option...")
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
        print("filling a custom combobox...")
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
                print("no option found with first try")
                option = self.ctx.locator("[role='option']", has_text=str(value)).first
            # Many libs render listbox/menuitem options
            if option.count() == 0:
                print("no option found with second try")
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

