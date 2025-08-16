"""
Job Application Auto-Agent (Playwright + OpenAI CUA)
---------------------------------------------------

What this does
- Opens a given job-application URL in a sandboxed browser
- Fills common fields from `all_about_me.txt`
- Uploads your resume and cover letter
- Uses OpenAI's Computer-Using Agent (CUA) loop to handle arbitrary UIs
- Stops before submitting (dry-run) unless `--auto-submit` is passed

Quick start
1) Put your files somewhere accessible, e.g.:
   - data/all_about_me.txt
   - data/resume.pdf
   - data/cover_letter.pdf

2) Create a .env with:
   OPENAI_API_KEY=sk-...

3) Install & run:
   pip install -r requirements.txt
   python -m playwright install
   python job_apply_agent.py --url "<job url>" --me data/all_about_me.txt --resume data/resume.pdf --cover data/cover_letter.pdf --dry-run

4) When satisfied, run with `--auto-submit` (still shows a confirmation prompt by default).

Notes & Safety
- This script does **not** bypass logins, paywalls, or CAPTCHAs.
- By default it pauses before actually submitting; review everything first.
- Respect each site's Terms of Service.

Requirements (save as requirements.txt if you want)
--------------------------------------------------
openai>=1.37.0
playwright>=1.46.0
python-dotenv>=1.0.1
pydantic>=2.8.2

"""
from __future__ import annotations
import argparse
import base64
import json
import os
import re
import sys
import time
from function_utils import *
from typing import Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI
from playwright.sync_api import sync_playwright, Page, FileChooser, TimeoutError as PWTimeout




# ----------------------------
# Playwright helpers
# ----------------------------

LABEL_SYNONYMS = {
    'first_name': ["first name", "first", "given name", "prénom"],
    'last_name':  ["last name", "family name", "surname", "nom"],
    'email':      ["email", "e-mail"],
    'phone':      ["phone", "mobile", "telephone", "téléphone"],
    'address':    ["address", "street address", "adresse"],
    'city':       ["city", "ville"],
    'state':      ["state", "province", "region", "département", "région"],
    'postal_code':["postal code", "zip", "zip code", "code postal"],
    'country':    ["country", "pays"],
    'linkedin':   ["linkedin", "linkedin url"],
    'github':     ["github"],
    'portfolio':  ["portfolio", "website", "site", "personal site"],
}


def safe_click(page: Page, selector: str, timeout: int = 4000) -> bool:
    try:
        page.locator(selector).first.click(timeout=timeout)
        return True
    except Exception:
        return False


def try_fill_by_label(page: Page, label_texts: List[str], value: str) -> bool:
    for lt in label_texts:
        try:
            page.get_by_label(lt, exact=False).first.fill(value, timeout=1000)
            return True
        except Exception:
            continue
    return False


def try_fill_by_placeholder(page: Page, placeholders: List[str], value: str) -> bool:
    for ph in placeholders:
        try:
            page.locator(f"input[placeholder*='{ph}']").first.fill(value, timeout=800)
            return True
        except Exception:
            continue
    return False


def generic_autofill(page: Page, prof: ApplicantProfile) -> None:
    """Best-effort autofill via labels/placeholders before invoking CUA.
       This handles many ATS (Lever/Greenhouse/Ashby) without brittle selectors.
    """
    mapping = {
        'first_name': prof.first_name,
        'last_name':  prof.last_name,
        'email':      prof.email,
        'phone':      prof.phone,
        'address':    prof.address,
        'city':       prof.city,
        'state':      prof.state,
        'postal_code':prof.postal_code,
        'country':    prof.country,
        'linkedin':   prof.linkedin,
        'github':     prof.github,
        'portfolio':  prof.portfolio,
    }

    for key, val in mapping.items():
        if not val:
            continue
        # Try label synonyms first
        if try_fill_by_label(page, LABEL_SYNONYMS.get(key, [key]), val):
            continue
        # Try placeholder
        if try_fill_by_placeholder(page, LABEL_SYNONYMS.get(key, [key]), val):
            continue
        # Try common name attribute
        try:
            page.locator(f"input[name*='{key}']").first.fill(val, timeout=800)
        except Exception:
            pass


# ----------------------------
# File upload handling
# ----------------------------

def attach_file_on_filechooser(fc: FileChooser, resume_path: str, cover_path: Optional[str]) -> None:
    try:
        el = fc.element
        label_text = (el.get_attribute('aria-label') or '')
        name_attr  = (el.get_attribute('name') or '')
        accept     = (el.get_attribute('accept') or '')
        context = f"label={label_text} name={name_attr} accept={accept}"
        print(f"[upload] chooser opened for element: {context}")

        label = f"{label_text} {name_attr} {accept}".lower()
        if any(w in label for w in ["cover", "motivation", "coverletter", "letter"]):
            if cover_path and os.path.exists(cover_path):
                fc.set_files(cover_path)
                print("[upload] attached cover letter")
                return
        # default to resume
        if os.path.exists(resume_path):
            fc.set_files(resume_path)
            print("[upload] attached resume")
        else:
            print("[upload] resume not found; nothing attached")
    except Exception as e:
        print(f"[upload] error: {e}")


# ----------------------------
# CUA (computer-use) loop with Playwright
# ----------------------------

class CUARunner:
    def __init__(self, client: OpenAI, page: Page, display_w: int = 1280, display_h: int = 800):
        self.client = client
        self.page = page
        self.display_w = display_w
        self.display_h = display_h
        self.previous_response_id: Optional[str] = None

    def screenshot_b64(self) -> str:
        img = self.page.screenshot(full_page=True)
        return base64.b64encode(img).decode('utf-8')

    def handle_model_action(self, action) -> None:
        t = getattr(action, "type", None)

        if t == "click":
            x, y = action.x, action.y
            button = getattr(action, "button", "left")
            print(f"[CUA] click {button} at ({x},{y})")
            self.page.mouse.click(x, y, button=button)

        elif t == "double_click":
            x, y = action.x, action.y
            print(f"[CUA] double_click at ({x},{y})")
            self.page.mouse.dblclick(x, y)

        elif t == "scroll":
            x, y = getattr(action, "x", 0), getattr(action, "y", 0)
            sx, sy = getattr(action, "scroll_x", 0), getattr(action, "scroll_y", 0)
            print(f"[CUA] scroll at ({x},{y}) by ({sx},{sy})")
            self.page.mouse.move(x, y)
            self.page.evaluate(f"window.scrollBy({sx}, {sy})")

        elif t == "move":
            x, y = getattr(action, "x", 0), getattr(action, "y", 0)
            print(f"[CUA] move to ({x},{y})")
            self.page.mouse.move(x, y)

        elif t == "drag":
            path = getattr(action, "path", [])
            print(f"[CUA] drag along {path}")
            if path:
                self.page.mouse.move(*path[0])
                self.page.mouse.down()
                for px, py in path[1:]:
                    self.page.mouse.move(px, py)
                self.page.mouse.up()

        elif t == "keypress":
            keys = getattr(action, "keys", [])
            if isinstance(keys, str):
                keys = [keys]
            for k in keys:
                print(f"[CUA] keypress {k}")
                self.page.keyboard.press("Enter" if k.lower()=="enter" else k)

        elif t == "type":
            text = getattr(action, "text", "")
            print(f"[CUA] type: '{text[:40]}...' ")
            self.page.keyboard.type(text)

        elif t == "wait":
            ms = int(getattr(action, "ms", 1000))
            print(f"[CUA] wait {ms}ms")
            self.page.wait_for_timeout(ms)

        elif t == "screenshot":
            print("[CUA] screenshot (noop in runner)")

        else:
            print(f"[CUA] unrecognized action: {action}")

    def handle_model_action_old(self, action: dict) -> None:
        t = action.get('type')
        if t == 'click':
            x, y = action.get('x'), action.get('y')
            button = action.get('button', 'left')
            print(f"[CUA] click {button} at ({x},{y})")
            self.page.mouse.click(x, y, button=button)
        elif t == 'double_click':
            x, y = action.get('x'), action.get('y')
            print(f"[CUA] double_click at ({x},{y})")
            self.page.mouse.dblclick(x, y)
        elif t == 'scroll':
            x, y = action.get('x', 0), action.get('y', 0)
            sx, sy = action.get('scroll_x', 0), action.get('scroll_y', 0)
            print(f"[CUA] scroll at ({x},{y}) by ({sx},{sy})")
            self.page.mouse.move(x, y)
            self.page.evaluate(f"window.scrollBy({sx}, {sy})")
        elif t == 'keypress':
            keys = action.get('keys', [])
            for k in keys:
                print(f"[CUA] keypress {k}")
                self.page.keyboard.press('Enter' if k.lower()== 'enter' else k)
        elif t == 'type':
            text = action.get('text', '')
            print(f"[CUA] type: '{text[:40]}...' ")
            self.page.keyboard.type(text)
        elif t == 'wait':
            ms = int(action.get('ms', 1000))
            print(f"[CUA] wait {ms}ms")
            self.page.wait_for_timeout(ms)
        elif t == 'screenshot':
            print("[CUA] screenshot (noop in runner)")
        else:
            print(f"[CUA] unrecognized action: {action}")

    def run(self, system_prompt: str, user_goal: str, max_steps: int = 60) -> dict:
        # First call: include a screenshot and both prompts
        response = self.client.responses.create(
            model="computer-use-preview",
            tools=[{
                "type": "computer_use_preview",
                "display_width": self.display_w,
                "display_height": self.display_h,
                "environment": "browser",
            }],
            input=[
                {"role":"system","content":[{"type":"input_text","text":system_prompt}]},
                {"role":"user","content":[
                    {"type":"input_text","text":user_goal},
                    {"type":"input_image","image_url":f"data:image/png;base64,{self.screenshot_b64()}"},
                ]},
            ],
            reasoning={"summary":"concise"},
            truncation="auto",
        )
        self.previous_response_id = response.id

        steps = 0
        while steps < max_steps:
            steps += 1
            # collect computer_call if present
            ccalls = [item for item in response.output if getattr(item,'type',None)=="computer_call"]
            if not ccalls:
                print("[CUA] no more computer calls; finished")
                break

            c = ccalls[0]
            action = getattr(c, 'action', None) or {}
            pending = getattr(c, 'pending_safety_checks', []) or []

            if pending:
                # Acknowledge safety checks; in real app, prompt the user to confirm
                print(f"[CUA] acknowledging safety checks: {[p.code for p in pending]}")
                ack = [
                    {"id":p.id, "code":p.code, "message":p.message}
                    for p in pending
                ]
            else:
                ack = []

            # Execute action
            self.handle_model_action(action)
            time.sleep(0.8)

            # Send screenshot back
            response = self.client.responses.create(
                model="computer-use-preview",
                previous_response_id=self.previous_response_id,
                tools=[{
                    "type": "computer_use_preview",
                    "display_width": self.display_w,
                    "display_height": self.display_h,
                    "environment": "browser",
                }],
                input=[
                    {
                        "type":"computer_call_output",
                        "call_id": getattr(c, 'call_id', None),
                        "acknowledged_safety_checks": ack,
                        "output": {
                            "type":"input_image",
                            "image_url": f"data:image/png;base64,{self.screenshot_b64()}"
                        }
                    }
                ],
                truncation="auto",
            )
            self.previous_response_id = response.id

        # Return the final response for logging
        return response.to_dict_recursive() if hasattr(response, 'to_dict_recursive') else {}


# ----------------------------
# Main flow
# ----------------------------

def build_cua_system_prompt(profile: ApplicantProfile, resume_path: str, cover_path: Optional[str], auto_submit: bool) -> str:
    return f"""
You are assisting with a job application in a web browser.
Follow these rules:
- Work inside the current tab only. If you need to navigate, use the address bar or in-page links.
- Fill forms using the candidate data provided below. Prefer fields with matching labels.
- If you need to upload files, click the upload control. The executor will attach files automatically.
- Do NOT attempt to solve CAPTCHAs or bypass logins. Stop if you encounter them.
- {'Do NOT click buttons that submit the final application.' if not auto_submit else 'You may click the final Submit/Apply button when all required fields are complete.'}
- When the form looks complete, STOP issuing actions.

Candidate data (JSON):
{profile.to_pretty_json()}

Files available:
- Resume: {os.path.abspath(resume_path)}
- Cover Letter: {os.path.abspath(cover_path) if cover_path else 'None provided'}

Hints:
- Common labels: First Name, Last Name, Email, Phone, Address, City, Zip/Postal Code, Country, LinkedIn, GitHub, Portfolio.
- Resume upload controls often mention CV/Resume; cover letter controls mention Cover/Motivation.
""".strip()


def build_cua_user_goal(job_url: str) -> str:
    return f"Open the URL {job_url} and complete the application form with the provided data. Upload the resume and (if requested) the cover letter. Review the page to ensure all required fields are satisfied. Then stop."


def run_agent(url: str, me_path: str, resume_path: str, cover_path: Optional[str], headless: bool, auto_submit: bool, dry_run: bool):
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY missing in environment.")
        sys.exit(1)

    client = OpenAI()
    profile = parse_all_about_me(me_path)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, chromium_sandbox=True, args=["--disable-extensions", "--disable-file-system"])
        context = browser.new_context(viewport={"width":1280, "height":800})
        page = context.new_page()

        # File chooser -> attach the right file
        page.on("filechooser", lambda fc: attach_file_on_filechooser(fc, resume_path, cover_path))

        # Navigate to job page
        print(f"Opening {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        print("waiting for page to load")
        page.wait_for_timeout(800)
        print("page loaded")
        # Best-effort autofill for common fields first
        try:
            generic_autofill(page, profile)
        except Exception as e:
            print(f"[autofill] skipped due to error: {e}")
        print("autofill done")
        # Start CUA loop to handle the rest
        system_prompt = build_cua_system_prompt(profile, resume_path, cover_path, auto_submit)
        user_goal = build_cua_user_goal(url)
        runner = CUARunner(client, page)
        final = runner.run(system_prompt, user_goal)

        # Optional confirm & submit (only if auto_submit)
        if auto_submit:
            print("\nAuto-submit enabled. Review the page. Submit now? [y/N] ", end="")
            if input().strip().lower() == 'y':
                # Try clicking visible buttons with common labels
                for text in ["Submit", "Apply", "Send", "Soumettre", "Postuler"]:
                    try:
                        if page.get_by_role("button", name=re.compile(text, re.I)).first.is_visible():
                            page.get_by_role("button", name=re.compile(text, re.I)).first.click()
                            print("Clicked submit-like button.")
                            break
                    except Exception:
                        pass
            else:
                print("Skipped final submission.")

        # Always save a screenshot of the filled form
        os.makedirs("out", exist_ok=True)
        shot_path = os.path.join("out", "filled_form.png")
        page.screenshot(path=shot_path, full_page=True)
        print(f"Saved screenshot => {shot_path}")

        browser.close()


# ----------------------------
# CLI
# ----------------------------

def main():
    ap = argparse.ArgumentParser(description="Auto-apply to a job using Playwright + OpenAI CUA")
    ap.add_argument('--url', required=True, help='Job application URL')
    ap.add_argument('--me', required=True, help='Path to all_about_me.txt (or JSON)')
    ap.add_argument('--resume', required=True, help='Path to your resume file (PDF/DOC)')
    ap.add_argument('--cover', default=None, help='Path to cover letter file (optional)')
    ap.add_argument('--headless', action='store_true', help='Run browser headless')
    ap.add_argument('--auto-submit', action='store_true', help='Allow final submit/apply click (still asks confirm)')
    ap.add_argument('--dry-run', action='store_true', help='Alias for not submitting (default behavior)')

    args = ap.parse_args()

    run_agent(
        url=args.url,
        me_path=args.me,
        resume_path=args.resume,
        cover_path=args.cover,
        headless=args.headless,
        auto_submit=args.auto_submit,
        dry_run=args.dry_run,
    )


if __name__ == '__main__':
    main()
    """
    python apply.py --url "https://careers.datadoghq.com/detail/6158712/?gh_jid=6158712&gh_src=8363eca61" --me data/all_about_me.txt --resume data/resume.pdf --dry-run
    """