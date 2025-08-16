from openai import OpenAI
import os, json
from dotenv import load_dotenv
load_dotenv()
# Initialize the OpenAI client with the API key from the environment
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("Set the OPENAI_API_KEY environment variable before running this script.")

client = OpenAI(api_key=api_key)

#load python_jobs_paris.json
with open("python_jobs_paris.json", "r", encoding="utf-8") as file:
    jobs = json.load(file)

#load user_job_preferences.txt
with open("user_job_preferences.txt", "r", encoding="utf-8") as file:
    user_job_preferences = file.read()

schema = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "reasons": {"type": "string"},
        "matched_criteria": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["relevant", "score", "reasons"],
    "additionalProperties": False
}

for job in jobs:
        title = job.get("job_title") or job.get("title")
        company = (job.get("company_object") or {}).get("name") or job.get("company_name")
        link = job.get("final_url") or job.get("url")
        desc = job.get("job_description") or job.get("description") or ""
        if desc:
            prompt = f"""
Compare the job description below to the user's preferences. Output ONLY valid JSON with the following fields: relevant (bool), score (float between 0 and 1), reason (short string explaining the score).

User preferences:
{user_job_preferences}

Job title: {title}
Company: {company}
Link: {link}
Job description:
{desc}
"""

            resp = client.responses.create(
                model="gpt-4.1",
                input=prompt,
            )

            result = json.loads(resp.output_text)
            print(result)