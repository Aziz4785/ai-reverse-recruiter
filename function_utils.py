from pydantic import BaseModel, Field
from typing import Dict, Optional
import json

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

