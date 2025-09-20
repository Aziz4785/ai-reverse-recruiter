from user_data import *
from functions_util import *
from text_extractor import *
from input_types import get_field_of
from playwright.sync_api import Page, TimeoutError as PWTimeout, Frame, sync_playwright
import asyncio
from playwright.async_api import async_playwright

#url = "https://jobs.sanofi.com/sys/apply/job/application/2649/26526708032?languageCode=en&source=LinkedIns"
url = "https://jobs.ashbyhq.com/notion/2445c305-69d1-48d4-bf21-e2b0e1bc95ba/application?source=LinkedIn"
def main():
    with sync_playwright() as p:
        #setup the browser and page 
        browser =  p.chromium.launch(headless=False)
        context =  browser.new_context(viewport={"width": 1280, "height": 800})
        page =  context.new_page()

        print(f"Opening {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
             page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        #wait for 5 seconds until everything is in place:
        page.wait_for_timeout(5000)
        dismiss_cookie_banners(page)

        page_text =  extract_all_visible_text(page)
        #save in a file:
        with open("page_text.txt", "w") as f:
            f.write(page_text)

        country_of_that_job  = extract_job_country(page_text,COUNTRY_KEYWORDS)

        fields = [
                    ("first_name",     FIRST_NAME_VALUE,     FIRST_NAME_SYNONYMS),
                    ("last_name",      LAST_NAME_VALUE,      LAST_NAME_SYNONYMS,    ),
                    ("preferred_name", PREFERED_NAME_VALUE,  PREFERED_NAME_SYNONYMS  ),
                    ("country_phone_code", COUNTRY_PHONE_CODE_VALUE, COUNTRY_PHONE_CODE_SYNONYMS),
                    ("phone_number",   PHONE_NUMBER_VALUE,   PHONE_NUMBER_SYNONYMS, ),
                    ("email",          EMAIL_VALUE,          EMAIL_SYNONYMS,         ),
                    ("full_name",      FULL_NAME_VALUE,      FULL_NAME_SYNONYMS,     ),
                    ("location",       LOCATION_VALUE,       LOCATION_SYNONYMS,       ),
                    ("recent_employer", RECENT_EMPLOYER_VALUE, RECENT_EMPLOYER_SYNONYMS),
                    ("email_confirmation", EMAIL_CONFIRMATION_VALUE, EMAIL_CONFIRMATION_SYNONYMS),
                    ("sponsorship_yes_no", requires_sponsorship(country_of_that_job), SPONSORSHIP_SYNONYMS),
                    ("hear_about_us", HEAR_ABOUT_US_VALUE, HEAR_ABOUT_US_SYNONYMS, ),
                    ("did_you_work_previously", DID_YOU_WORK_PREVIOUSLY_VALUE, DID_YOU_WORK_PREVIOUSLY_SYNONYMS),
                    ("complete_address", COMPLETE_ADDRESS_VALUE, COMPLETE_ADDRESS_SYNONYMS),
                    ("city", CITY_VALUE, CITY_SYNONYMS),
                    ("postal_code", POSTAL_CODE_VALUE, POSTAL_CODE_SYNONYMS),
                    ("linkedin_url", LINKEDIN_URL_VALUE, None),
                ]
        country_phone_code_found = False
        for key, value, syns in fields:
            print(f"-------{key}-------")
            field =  get_field_of(page, key, syns)
            print(key, "->", field.input_type.value)

            if not field.is_found:
                print(f"  field {key} is not found")
                continue
            if country_phone_code_found and key == "phone_number":
                value = PHONE_NUMBER_NOCODE_VALUE
            if key == "country_phone_code" and field.is_found:
                country_phone_code_found = True


            # OOP one-liner 🎯
            field.fill(value)

        # Keep the browser window open until user confirms
        print("\nAll fields processed. The browser will stay open.")
        input("Press Enter here to close the browser and end the script...")


# Run the async function
if __name__ == "__main__":
    main()