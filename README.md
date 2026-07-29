# People Analytics Job Radar

Daily-refreshing page of HR × Analytics/Data Science roles in the UAE and
Germany/EU, built with GitHub Actions + GitHub Pages.

## What's real vs. what needs your confirmation

I wrote and syntax-checked this code, and confirmed the two APIs it uses
(Adzuna, Jooble) are real, documented, currently-operating services with the
country coverage described below — but I have **not** run this against live
API keys, since I don't have network access to those endpoints from where
I'm working. Before you trust the daily output, do one manual test run (see
Step 5) and sanity-check the results.

Two things I'm specifically not fully certain about and you should verify
against each provider's own docs before relying on this:
- **Jooble + UAE**: Jooble runs a UAE site (ae.jooble.org) and has a
  documented REST API, but I could not confirm from their public docs
  whether one API key queries all their country sites, or whether you need
  the key issued specifically through the UAE site. If UAE results come back
  empty, this is the first thing to check with Jooble's support.
- **Adzuna does not cover the UAE at all** — its country list is Europe,
  Americas, Oceania, India, Singapore, South Africa. That's why this build
  uses Adzuna only for Germany/EU and Jooble only for the UAE.

## What it does

1. `fetch_jobs.py` queries Adzuna (Germany + a set of EU countries) and
   Jooble (UAE) for a handful of HR-analytics-flavoured keywords.
2. It keeps only postings whose title/description contain **both** an HR
   term (e.g. "people analytics", "hr transformation") **and** an
   analytics/data term (e.g. "analytics", "power bi", "sql") — the
   intersection you asked for.
3. It de-duplicates by role + company, and renders the result into
   `docs/index.html` using `template.html`.
4. GitHub Pages serves whatever is in `docs/` on `main` — no separate deploy
   step needed once it's turned on.
5. A GitHub Actions workflow (`.github/workflows/daily-job-radar.yml`) runs
   this once a day and commits the refreshed page back to the repo.

**On recruiter emails:** neither Adzuna nor Jooble returns a recruiter's
email address — that data isn't public on job postings, as noted in the
first sample page. The "Contact" field always shows either the named
company/agency or an honest "not publicly listed." Nothing is invented.

## Setup

1. **Create a new GitHub repo** (public — free GitHub Pages requires a
   public repo unless you're on GitHub Pro/Team/Enterprise).
2. **Add these files** to the repo root, keeping the folder structure:
   - `fetch_jobs.py`
   - `template.html`
   - `requirements.txt`
   - `.github/workflows/daily-job-radar.yml`
3. **Get API keys:**
   - Adzuna: register free at <https://developer.adzuna.com> → App ID + App Key.
   - Jooble: request a key at <https://jooble.org/api/about>.
4. **Add the keys as repo secrets:** Settings → Secrets and variables →
   Actions → New repository secret. Add `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`,
   `JOOBLE_API_KEY`.
5. **Do one manual test run first:** Actions tab → "Daily Job Radar" →
   "Run workflow". Check the run log for `[adzuna]`/`[jooble]` warnings, and
   open the resulting `docs/index.html` to confirm the results look right
   before trusting the schedule.
6. **Turn on Pages:** Settings → Pages → Source: "Deploy from a branch" →
   Branch: `main`, folder: `/docs` → Save. (GitHub's own Pages settings UI
   is the source of truth if this has moved by the time you set this up.)
7. Your page will be live at `https://<your-username>.github.io/<repo-name>/`
   and will update automatically each day at 05:00 UTC (edit the cron line
   in the workflow file to change the time).

## Tuning it

- Add or remove countries in `ADZUNA_COUNTRIES` in `fetch_jobs.py`
  (full Adzuna country list: <https://developer.adzuna.com/docs/countries>).
- Add or remove phrases in `HR_TERMS` / `ANALYTICS_TERMS` to widen or
  narrow what counts as "the intersection."
- Add or remove `SEARCH_KEYWORDS` to change what's queried.
