"""
fetch_jobs.py
=============
Pulls roles at the intersection of HR and Analytics/Data Science in the UAE
and Germany/EU, and renders them into docs/index.html using template.html.
Tracks which roles were seen in prior runs (seen_jobs.json) so today's
newly-appeared roles can be highlighted on the page.

Data sources:
  - Adzuna API (Germany + other EU countries)  https://developer.adzuna.com/
  - Jooble API (UAE)                            https://jooble.org/api/about
  - Bundesagentur fuer Arbeit (Germany, unofficial) https://github.com/bundesAPI/jobsuche-api

Neither Adzuna nor Jooble publishes a recruiter's direct email address on
job postings. This script does NOT invent one - the "contact" field is
always either the named company/agency or an explicit "not publicly listed".
"""

import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
JOOBLE_API_KEY = os.environ.get("JOOBLE_API_KEY", "")

TEMPLATE_PATH = "template.html"
OUTPUT_PATH = "docs/index.html"
SEEN_JOBS_PATH = "seen_jobs.json"
SEEN_RETENTION_DAYS = 30

HR_TERMS = [
    "people analytics", "workforce analytics", "hr analytics", "hr transformation",
    "workforce planning", "hr data", "human capital analytics", "people data",
    "hr reporting", "compensation analytics", "people & culture", "hc transformation",
]
ANALYTICS_TERMS = [
    "analytics", "data scien", "data analy", "power bi", "tableau", "sql",
    "machine learning", "predictive", "dashboard", "reporting",
]

ADZUNA_COUNTRIES = ["de", "nl", "fr", "es", "it", "pl", "at"]
SEARCH_KEYWORDS = [
    "people analytics", "workforce analytics", "HR analytics", "HR transformation",
]
JOOBLE_LOCATION = "United Arab Emirates"
MAX_DESC_CHARS = 220


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def matches_intersection(text: str) -> bool:
    t = text.lower()
    return any(h in t for h in HR_TERMS) and any(a in t for a in ANALYTICS_TERMS)


def clean_text(raw: str, limit: int = MAX_DESC_CHARS) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return (text[: limit - 1] + "...") if len(text) > limit else text


def esc(value: str) -> str:
    return html.escape(value or "", quote=True)


def job_key(job: dict) -> str:
    return f"{job['role'].strip().lower()}|{job['company'].strip().lower()}"


# ---------------------------------------------------------------------------
# Source: Adzuna (Germany / EU)
# ---------------------------------------------------------------------------

def fetch_adzuna(country: str, keyword: str, results_per_page: int = 20) -> list:
    if not (ADZUNA_APP_ID and ADZUNA_APP_KEY):
        print("[adzuna] missing ADZUNA_APP_ID/ADZUNA_APP_KEY - skipping", file=sys.stderr)
        return []

    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "results_per_page": results_per_page,
        "what": keyword,
        "content-type": "application/json",
    }
    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[adzuna] {country}/{keyword}: request failed - {e}", file=sys.stderr)
        return []

    jobs = []
    for item in resp.json().get("results", []):
        title = item.get("title", "")
        description = item.get("description", "")
        if not matches_intersection(f"{title} {description}"):
            continue
        jobs.append({
            "role": clean_text(title, 120),
            "company": clean_text((item.get("company") or {}).get("display_name", "")) or "Not listed",
            "location": clean_text((item.get("location") or {}).get("display_name", "")) or country.upper(),
            "description": clean_text(description),
            "apply_url": item.get("redirect_url", "#"),
            "region": "eu",
            "source": "Adzuna",
        })
    return jobs


# ---------------------------------------------------------------------------
# Source: Bundesagentur fuer Arbeit (Germany) - supplementary source
# ---------------------------------------------------------------------------
# NOT an officially published API. Calls the same REST endpoint the
# Bundesagentur's own "Jobsuche" app uses internally, documented by the
# open-data project bundesAPI: https://github.com/bundesAPI/jobsuche-api
# No personal key needed - 'jobboerse-jobsuche' is the app's own shared
# client ID. Because this is unofficial, it could change or break without
# notice, and these field names are a best-effort reading of partial docs -
# the debug line below will flag it on the first run if they're wrong.

ARBEITSAGENTUR_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/app/jobs"
ARBEITSAGENTUR_HEADERS = {
    "User-Agent": "Jobsuche/2.9.2 (de.arbeitsagentur.jobboerse; build:1077; iOS 15.1.0) Alamofire/5.4.4",
    "Host": "rest.arbeitsagentur.de",
    "X-API-Key": "jobboerse-jobsuche",
    "Connection": "keep-alive",
}


def fetch_arbeitsagentur(keyword: str, results_size: int = 50) -> list:
    params = {
        "angebotsart": "1",
        "page": "1",
        "pav": "false",
        "size": str(results_size),
        "umkreis": "200",
        "was": keyword,
        "wo": "Deutschland",
    }
    try:
        resp = requests.get(ARBEITSAGENTUR_URL, headers=ARBEITSAGENTUR_HEADERS, params=params, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[arbeitsagentur] {keyword}: request failed - {e}", file=sys.stderr)
        return []

    results = resp.json().get("stellenangebote", [])
    if results and not any(k in results[0] for k in ("titel", "beruf")):
        print(f"[arbeitsagentur] unexpected fields, first result keys: {list(results[0].keys())}", file=sys.stderr)

    jobs = []
    for item in results:
        title = item.get("titel") or item.get("beruf") or ""
        employer = item.get("arbeitgeber", "")
        ort = (item.get("arbeitsort") or {}).get("ort", "")
        refnr = item.get("refnr", "")
        if not matches_intersection(f"{title} {employer}"):
            continue
        jobs.append({
            "role": clean_text(title, 120),
            "company": clean_text(employer) or "Not listed",
            "location": clean_text(ort) or "Germany",
            "description": clean_text(item.get("beruf", "")) or "See listing for details.",
            "apply_url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}" if refnr else ARBEITSAGENTUR_URL,
            "region": "eu",
            "source": "Bundesagentur fuer Arbeit",
        })
    return jobs


# ---------------------------------------------------------------------------
# Source: Jooble (UAE)
# ---------------------------------------------------------------------------

def fetch_jooble(keyword: str, location: str = JOOBLE_LOCATION) -> list:
    if not JOOBLE_API_KEY:
        print("[jooble] missing JOOBLE_API_KEY - skipping", file=sys.stderr)
        return []

    url = f"https://jooble.org/api/{JOOBLE_API_KEY}"
    payload = {"keywords": keyword, "location": location}
    try:
        resp = requests.post(url, json=payload, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[jooble] {keyword}: request failed - {e}", file=sys.stderr)
        return []

    jobs = []
    for item in resp.json().get("jobs", []):
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        if not matches_intersection(f"{title} {snippet}"):
            continue
        jobs.append({
            "role": clean_text(title, 120),
            "company": clean_text(item.get("company", "")) or "Not listed",
            "location": clean_text(item.get("location", "")) or "UAE",
            "description": clean_text(snippet),
            "apply_url": item.get("link", "#"),
            "region": "uae",
            "source": "Jooble",
        })
    return jobs


# ---------------------------------------------------------------------------
# "New since last run" tracking
# ---------------------------------------------------------------------------

def load_seen_jobs() -> dict:
    if not os.path.exists(SEEN_JOBS_PATH):
        return {}
    try:
        with open(SEEN_JOBS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[seen_jobs] could not read {SEEN_JOBS_PATH}, starting fresh - {e}", file=sys.stderr)
        return {}


def save_seen_jobs(seen: dict) -> None:
    with open(SEEN_JOBS_PATH, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, sort_keys=True)


def mark_new_jobs(jobs: list, seen: dict, today: str, first_run: bool) -> None:
    """Flags job['is_new'] = True for any job whose key isn't already in
    `seen`, then records every job's key into `seen`. On the very first run
    (no seen_jobs.json yet), nothing is marked new - it just sets the
    baseline so tomorrow's comparison has something to compare against."""
    for job in jobs:
        key = job_key(job)
        if key in seen:
            job["is_new"] = False
        else:
            job["is_new"] = not first_run
            seen[key] = today


def prune_seen_jobs(seen: dict, retention_days: int = SEEN_RETENTION_DAYS) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    pruned = {}
    for key, date_str in seen.items():
        try:
            seen_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if seen_date >= cutoff:
            pruned[key] = date_str
    return pruned


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def dedupe(jobs: list) -> list:
    seen_keys = set()
    unique = []
    for j in jobs:
        key = job_key(j)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique.append(j)
    return unique


def render_card(job: dict) -> str:
    is_new = bool(job.get("is_new"))
    card_class = "card is-new" if is_new else "card"
    new_badge = '<span class="new-badge">NEW</span>' if is_new else ""
    return f"""
      <div class="{card_class}">
        <div class="card-top">
          <div>
            <p class="role">{new_badge}{esc(job['role'])}</p>
            <p class="company">{esc(job['company'])}</p>
            <p class="loc mono">{esc(job['location'])}</p>
          </div>
        </div>
        <p class="desc">{esc(job['description'])}</p>
        <div class="meta-line">
          <div class="meta-row"><span class="meta-label">Contact</span>
            <span class="meta-value unavailable">Not publicly listed &mdash; apply via link</span></div>
        </div>
        <div class="card-foot">
          <span class="source-tag">{esc(job['source'])} &middot; {esc(job['captured'])}</span>
          <a class="apply-btn" href="{esc(job['apply_url'])}" target="_blank" rel="noopener">Apply &rarr;</a>
        </div>
      </div>"""


def render_cards(jobs: list) -> str:
    if not jobs:
        return '<p class="empty">No matching roles found in today\'s pull.</p>'
    ordered = sorted(jobs, key=lambda j: 0 if j.get("is_new") else 1)
    return "\n".join(render_card(j) for j in ordered)


def build_page(uae_jobs: list, eu_jobs: list, new_count: int) -> str:
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    snapshot_date = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    page = (
        template
        .replace("{{SNAPSHOT_DATE}}", snapshot_date)
        .replace("{{TOTAL_COUNT}}", str(len(uae_jobs) + len(eu_jobs)))
        .replace("{{UAE_COUNT}}", str(len(uae_jobs)))
        .replace("{{EU_COUNT}}", str(len(eu_jobs)))
        .replace("{{NEW_COUNT}}", str(new_count))
        .replace("{{UAE_CARDS}}", render_cards(uae_jobs))
        .replace("{{EU_CARDS}}", render_cards(eu_jobs))
    )
    return page


def main() -> None:
    now = datetime.now(timezone.utc)
    captured = now.strftime("%d %b %Y")
    today_key = now.strftime("%Y-%m-%d")

    uae_jobs, eu_jobs = [], []

    for kw in SEARCH_KEYWORDS:
        uae_jobs.extend(fetch_jooble(kw))

    for kw in SEARCH_KEYWORDS:
        eu_jobs.extend(fetch_arbeitsagentur(kw))

    for country in ADZUNA_COUNTRIES:
        for kw in SEARCH_KEYWORDS:
            eu_jobs.extend(fetch_adzuna(country, kw))

    for j in uae_jobs + eu_jobs:
        j["captured"] = captured

    uae_jobs = dedupe(uae_jobs)
    eu_jobs = dedupe(eu_jobs)

    seen = load_seen_jobs()
    first_run = not seen
    mark_new_jobs(uae_jobs, seen, today_key, first_run)
    mark_new_jobs(eu_jobs, seen, today_key, first_run)
    seen = prune_seen_jobs(seen)
    save_seen_jobs(seen)

    new_count = sum(1 for j in uae_jobs + eu_jobs if j.get("is_new"))

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    page = build_page(uae_jobs, eu_jobs, new_count)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(page)

    print(f"Wrote {OUTPUT_PATH}: {len(uae_jobs)} UAE roles, {len(eu_jobs)} EU roles, {new_count} new since last run.")


if __name__ == "__main__":
    main()
