from pydantic import BaseModel, Field
from typing import Dict, Optional, NamedTuple
import json
from playwright.sync_api import Page, Frame, Locator
import re

GH_RE = re.compile(r"(job-boards\.greenhouse\.io|boards\.greenhouse\.io|grnh\.se)")


class FillResult(NamedTuple):
    present: bool         # we found a matching input in this context
    filled: bool          # we actually filled it right now
    already_ok: bool      # it already had the desired value

# --- Core helpers ------------------------------------------------------------
def _attempt_on_locator(loc: Locator, value: str) -> FillResult:
    try:
        if loc.count() == 0:
            return FillResult(False, False, False)
        target = loc.first
        try:
            current = target.input_value(timeout=300)
        except Exception:
            current = ""
        if current.strip() == value.strip():
            return FillResult(True, False, True)
        target.fill(value, timeout=1000)
        return FillResult(True, True, False)
    except Exception:
        # The element existed but couldn't be filled (disabled/hidden/etc.)
        return FillResult(True, False, False)

# --- Locator discovery (without filling) --------------------------------------
def _find_field_locator_in_context(ctx: Page | Frame,
                                   synonyms: list[str],
                                   input_names: list[str]) -> Optional[Locator]:
    # 1) By accessible label
    for lt in synonyms:
        try:
            loc = ctx.get_by_label(lt, exact=False)
            if loc.count() > 0:
                return loc.first
        except Exception:
            pass

    # 2) Placeholder
    for ph in synonyms:
        try:
            loc = ctx.locator(f"input[placeholder*='{ph}']")
            if loc.count() > 0:
                return loc.first
        except Exception:
            pass

    # 3) name=
    for name_key in input_names:
        try:
            loc = ctx.locator(f"input[name*='{name_key}']")
            if loc.count() > 0:
                return loc.first
        except Exception:
            pass

    # 4) aria-label
    for aria in synonyms:
        try:
            loc = ctx.locator(f"input[aria-label*='{aria}']")
            if loc.count() > 0:
                return loc.first
        except Exception:
            pass

    # 5) Generic text input as last resort
    try:
        loc = ctx.locator("input[type='text']")
        if loc.count() > 0:
            return loc.first
    except Exception:
        pass
    return None

def find_field_locator_anywhere(page: Page,
                                synonyms: list[str],
                                input_names: list[str]) -> Optional[Locator]:
    loc = _find_field_locator_in_context(page, synonyms, input_names)
    if loc is not None:
        return loc
    for fr in page.frames:
        if fr == page.main_frame:
            continue
        try:
            loc = _find_field_locator_in_context(fr, synonyms, input_names)
            if loc is not None:
                return loc
        except Exception:
            continue
    return None
    
class ApplicantProfile(BaseModel):
    # Common fields; extend as needed
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None  # "City, Country" or full address
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None

    # Work auth / misc
    work_authorization: Optional[str] = None  # e.g., "EU citizen", "US citizen", "Visa required"
    relocation: Optional[str] = None          # e.g., "Yes", "No"
    salary_expectation: Optional[str] = None

    # Freeform extras
    extras: Dict[str, str] = Field(default_factory=dict)

    def to_pretty_json(self) -> str:
        return json.dumps(self.model_dump(exclude_none=True), indent=2)


def parse_all_about_me(path: str) -> ApplicantProfile:
    """Parses key:value pairs from a .txt file. Also supports JSON content.
       Lines like: First Name: Aziz
                    Email: foo@bar.com
       Unknown keys go into `extras`.
    """
    text = open(path, "r", encoding="utf-8").read().strip()
    # Try JSON first
    try:
        data = json.loads(text)
        return ApplicantProfile(**data)
    except json.JSONDecodeError:
        pass

    # Fallback: key: value per line
    kv: Dict[str, str] = {}
    extras: Dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.strip().startswith(('#', '//')):
            continue
        if ':' in line:
            k, v = line.split(':', 1)
            key = k.strip().lower()
            val = v.strip()
            kv[key] = val

    def pick(*names):
        for n in names:
            if n in kv:
                return kv.pop(n)
        return None

    profile = ApplicantProfile(
        first_name = pick('first name', 'firstname', 'given name'),
        last_name  = pick('last name', 'lastname', 'family name', 'surname'),
        email      = pick('email', 'e-mail'),
        phone      = pick('phone', 'phone number', 'mobile'),
        location   = pick('location', 'city, country'),
        address    = pick('address', 'street address', 'addr'),
        city       = pick('city',),
        state      = pick('state', 'province', 'region'),
        postal_code= pick('postal code', 'zip', 'zip code'),
        country    = pick('country',),
        linkedin   = pick('linkedin', 'linkedin url', 'linkedin profile'),
        github     = pick('github', 'github url'),
        portfolio  = pick('portfolio', 'website', 'site', 'personal site'),
        work_authorization = pick('work authorization', 'work permit', 'visa'),
        relocation = pick('relocation', 'willing to relocate'),
        salary_expectation = pick('salary', 'salary expectation', 'expected salary'),
    )

    # Remaining pairs => extras
    profile.extras = kv
    return profile

