"""
fetch_jobs.py
=============
Pulls roles at the intersection of HR and Analytics/Data Science in the UAE
and Germany/EU, and renders them into docs/index.html using template.html.

Data sources:
  - Adzuna API (Germany + other EU countries)  https://developer.adzuna.com/
  - Jooble API (UAE)                            https://jooble.org/api/about

IMPORTANT — verify before relying on this in production:
  - Adzuna's supported country code list and exact query parameters:
    https://developer.adzuna.com/docs/search
  - Jooble's request/response schema, and whether one API key works across
    all of Jooble's country sites or whether the UAE-specific key issued via
    ae.jooble.org is required: https://jooble.org/api/about
  Both of the above were accurate against each provider's published docs at
  the time this script was written, but API surfaces do change — confirm
  against the live docs the first time you run this for real, not just by
  reading this comment.

Neither source publishes a recruiter's direct email address on job
postings. This script does NOT invent one — the "contact" field is always
either the named company/agency or an explicit "not publicly listed".
"""

import html
import os
import re
import sys
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
JOOBLE_API_KEY = os.environ.get("JOOBLE_API_KEY", "")

TEMPLATE_PATH = "template.html"
OUTPUT_PATH = "docs/index.html"

# A job must match at least one HR term AND at least one analytics/data term
# to count as "at the intersection". Edit these lists to tune the feed.
HR_TERMS = [
    "people analytics", "workforce analytics", "hr analytics", "hr transformation",
    "workforce planning", "hr data", "human capital analytics", "people data",
    "hr reporting", "compensation analytics", "people & culture", "hc transformation",
]
ANALYTICS_TERMS = [
    "analytics", "data scien", "data analy", "power bi", "tableau", "sql",
    "machine learning", "predictive", "dashboard", "reporting",
]

# Adzuna country codes to query. Full list:
# https://developer.adzuna.com/docs/countries
ADZUNA_COUNTRIES = ["de", "nl", "fr", "es", "it", "pl", "at"]

# Search keywords tried against every source
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
    return (text[: limit - 1] + "…") if len(text) > limit else text


def esc(value: str) -> str:
    return html.escape(value or "", quote=True)


# ---------------------------------------------------------------------------
# Source: Adzuna (Germany / EU)
# ---------------------------------------------------------------------------

def fetch_adzuna(country: str, keyword: str, results_per_page: int = 20) -> list:
    if not (ADZUNA_APP_ID and ADZUNA_APP_KEY):
        print("[adzuna] missing ADZUNA_APP_ID/ADZUNA_APP_KEY — skipping", file=sys.stderr)
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
        print(f"[adzuna] {country}/{keyword}: request failed — {e}", file=sys.stderr)
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
# Source: Jooble (UAE)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Source: Bundesagentur für Arbeit (Germany) — supplementary source
# ---------------------------------------------------------------------------
# NOT an officially published API. This calls the same REST endpoint the
# Bundesagentur's own "Jobsuche" app uses internally, documented by the
# open-data project bundesAPI: https://github.com/bundesAPI/jobsuche-api
# No personal key needed — 'jobboerse-jobsuche' is the app's own shared
# client ID, not a secret. Because this is unofficial, it could change or
# break without notice, and the exact field names below are a best-effort
# reading of partial docs, not fully confirmed — the debug line will tell
# you on the first run if they're wrong.

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
        print(f"[arbeitsagentur] {keyword}: request failed — {e}", file=sys.stderr)
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
            "source": "Bundesagentur für Arbeit",
        })
    return jobs

def fetch_jooble(keyword: str, location: str = JOOBLE_LOCATION) -> list:
    if not JOOBLE_API_KEY:
        print("[jooble] missing JOOBLE_API_KEY — skipping", file=sys.stderr)
        return []

    url = f"https://jooble.org/api/{JOOBLE_API_KEY}"
    payload = {"keywords": keyword, "location": location}
    try:
        resp = requests.post(url, json=payload, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[jooble] {keyword}: request failed — {e}", file=sys.stderr)
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
# Assembly
# ---------------------------------------------------------------------------

def dedupe(jobs: list) -> list:
    seen = set()
    unique = []
    for j in jobs:
        key = (j["role"].lower().strip(), j["company"].lower().strip())
        if key in seen:
            continue
        seen.add(key)
        unique.append(j)
    return unique


def render_card(job: dict) -> str:
    return f"""
      <div class="card">
        <div class="card-top">
          <div>
            <p class="role">{esc(job['role'])}</p>
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
    return "\n".join(render_card(j) for j in jobs)


def build_page(uae_jobs: list, eu_jobs: list) -> str:
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    snapshot_date = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    page = (
        template
        .replace("{{SNAPSHOT_DATE}}", snapshot_date)
        .replace("{{TOTAL_COUNT}}", str(len(uae_jobs) + len(eu_jobs)))
        .replace("{{UAE_COUNT}}", str(len(uae_jobs)))
        .replace("{{EU_COUNT}}", str(len(eu_jobs)))
        .replace("{{UAE_CARDS}}", render_cards(uae_jobs))
        .replace("{{EU_CARDS}}", render_cards(eu_jobs))
    )
    return page


def main() -> None:
    captured = datetime.now(timezone.utc).strftime("%d %b %Y")

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

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    page = build_page(uae_jobs, eu_jobs)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(page)

    print(f"Wrote {OUTPUT_PATH}: {len(uae_jobs)} UAE roles, {len(eu_jobs)} EU roles.")


if __name__ == "__main__":
    main()
