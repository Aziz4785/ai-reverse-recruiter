
from typing import List
from pathlib import Path

FIRST_NAME_VALUE = "Aziz"
LAST_NAME_VALUE = "Kanoun"
PREFERED_NAME_VALUE = "Aziz"
PHONE_NUMBER_VALUE = "+33666436653"
EMAIL_VALUE = "aziz.kanoun@gmail.com"
FULL_NAME_VALUE = "Aziz Kanoun"
LOCATION_VALUE = "Paris, France"
RESUME_PATH = Path("data/resume.pdf")

FIRST_NAME_SYNONYMS: List[str] = [
    "first name",
    "first",
    "given name",
    "prénom",
    "prenom",
]
INPUT_NAME_FIRSTNAME = ["first", "first_name", "given_name", "fname"]

LAST_NAME_SYNONYMS: List[str] = [
    "last name",
    "family name",
    "surname",
    "nom",
]
INPUT_NAME_LASTNAME = ["last", "last_name", "family_name", "lname"]

PREFERED_NAME_SYNONYMS: List[str] = [
    "preferred name",
    "preferred",
    "prénom",
    "prenom",
]
INPUT_NAME_PREFEREDNAME = ["preferred", "preferred_name", "preferred_name", "pname"]

PHONE_NUMBER_SYNONYMS: List[str] = [
    "phone",
    "tel",
    "telephone",
    "mobile",
    "mobile phone",
    "mobile phone number",
    "mobile phone number",
]
INPUT_NAME_PHONENUMBER = ["phone", "phone_number", "tel", "telephone"]

EMAIL_SYNONYMS: List[str] = [
    "email",
    "mail",
    "email address",
    "email address",
]
INPUT_NAME_EMAIL = ["email", "mail", "email_address", "email_address"]

FULL_NAME_SYNONYMS: List[str] = [
    "full name",
    "full",
    "name",
    "Full Name"
]
INPUT_NAME_FULLNAME = ["full", "full_name", "candidateName", "fullname"]


LOCATION_SYNONYMS: List[str] = [
    "location",
    "Location",
    "city",
    "country",
    "country",
]
INPUT_NAME_LOCATION = ["location", "city", "country", "country"]