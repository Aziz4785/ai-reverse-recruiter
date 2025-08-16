import http.client
import os
import json
from dotenv import load_dotenv
from selenium.common.exceptions import JavascriptException,StaleElementReferenceException,TimeoutException, NoSuchElementException, ElementClickInterceptedException
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import json
import random
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.wheel_input import ScrollOrigin
import requests
load_dotenv()



def use_theirstack(
    keywords="python",
    city="Paris",
    country_code="FR",
    max_age_days=30,
    limit=5,
    offset=0,
    discovered_at_gte=None,  # ISO 8601 like "2025-07-20T00:00:00Z" to fetch only new jobs
):
    """
    Search jobs via TheirStack's Jobs API.
    Docs: POST https://api.theirstack.com/v1/jobs/search  (Bearer auth)
    """
    api_key = os.getenv("THEIRSTACK_API_KEY")
    if not api_key:
        raise RuntimeError("Set THEIRSTACK_API_KEY in your environment.")

    url = "https://api.theirstack.com/v1/jobs/search"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    payload = {
        "offset": offset,
        "limit": limit,
        "posted_at_max_age_days": max_age_days,
        "job_country_code_or": [country_code],
        "job_location_pattern_or": [city],         # regex-friendly match on location
        "job_title_or": [keywords],                # simple keyword(s) in title
        #"company_type": "direct_employer",         # avoid agencies/aggregators
        # exclude internships / stages via patterns in title or description
        #"job_title_pattern_not": ["(?i)stage|stagiaire|intern(ship)?"],
        #"job_description_pattern_not": ["(?i)stage|stagiaire|intern(ship)?"],
    }
    if discovered_at_gte:
        payload["discovered_at_gte"] = discovered_at_gte  # only jobs discovered after this timestamp

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
    except requests.exceptions.HTTPError:
        print(f"HTTP {resp.status_code}: {resp.text}")
        return
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return

    data = resp.json()

    # Try to be resilient to response shapes; TheirStack typically returns a list of jobs.
    jobs = data.get("jobs") if isinstance(data, dict) else data
    if jobs is None:
        jobs = data.get("data") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        print("Unexpected response:", json.dumps(data, indent=2)[:2000])
        return

    job_list = []
    # Print the first non-internship job (the filters should already exclude them)
    for job in jobs[:5]:
        title = job.get("job_title") or job.get("title")
        company = (job.get("company_object") or {}).get("name") or job.get("company_name")
        link = job.get("final_url") or job.get("url")
        print({"title": title, "company": company, "link": link})
        # Optionally show a short snippet if available
        desc = job.get("job_description") or job.get("description") or ""
        if desc:
            job_list.append({"title": title, "company": company, "link": link, "description": desc})

    return job_list

python_jobs_paris = use_theirstack() 
if python_jobs_paris:
    with open("python_jobs_paris.json", "w", encoding="utf-8") as f:
        json.dump(python_jobs_paris, f, ensure_ascii=False, indent=2)
