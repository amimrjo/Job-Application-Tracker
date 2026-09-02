# Job Application Tracker

Automatically scans your Gmail every day, figures out which emails are related to
job applications you've sent, and keeps a running Notion database up to date —
including catching **recruiter outreach** and **status updates** on applications
you sent days or weeks ago.

Runs for free on GitHub Actions. No server, no always-on process.

## What it does

Every day at a scheduled time, the workflow:

1. Pulls Gmail messages from the last day (14 days on the very first run).
2. Classifies each one: application confirmation, recruiter outreach, interview
   invite, rejection, offer, or "not job related" (skipped).
3. Extracts company name, role / requisition ID, and application date.
4. Upserts a row into a Notion database — if the company/role already has a row
   (e.g. you applied last week), it **updates that row's status** instead of
   creating a duplicate, so you can see the whole lifecycle of one application.
5. Sets a **Next Action** for each row: `Reply to recruiter`, `Prepare for
   interview`, `Review offer`, `Wait`, or `None`.

### Notion columns

| Column | Description |
|---|---|
| Company | Extracted from sender / ATS name |
| Role / Req ID | Job title and requisition number, when detected |
| Application Date | Date of the original application email |
| Status | Applied / Recruiter Contact / Interview Scheduled / Offer / Rejected / Update Received |
| Next Action | What you should do about it |
| Recruiter Contact | Checkbox — check this column/view to see all recruiter messages |
| Last Email Date | Most recent related email |
| Source Thread | Link straight back to the Gmail thread |

Recruiter rows aren't cell-highlighted (Notion's API doesn't support per-cell
colors), but the `Status` and `Recruiter Contact` columns are colored tags —
group or filter the Notion view by `Recruiter Contact` to get the same effect,
or filter by `Next Action = Reply to recruiter`.

## Architecture

```
src/gmail_client.py    -> Gmail API: fetch messages in a date window
src/classifier.py      -> regex/heuristic classification, no ML, fully debuggable
src/notion_client_wrapper.py -> create/update Notion rows, schema bootstrap
src/main.py             -> orchestrates the above, entry point
.github/workflows/daily-scan.yml -> cron schedule that runs main.py daily
```

Classification is rule-based on purpose: application-related emails follow
very predictable templates (ATS confirmations, Calendly/GoodTime interview
links, standard rejection boilerplate), so regex catches the large majority
and — unlike an LLM call — is free, fast, and you can see exactly why any
email was tagged the way it was.

## Setup

### 1. Gmail API access

1. Go to [Google Cloud Console](https://console.cloud.google.com/), create a
   project, and enable the **Gmail API**.
2. Under **APIs & Services → Credentials**, create an **OAuth Client ID** of
   type **Desktop app**. Download the JSON as `credentials.json` and put it in
   the repo root (it's gitignored, won't be committed).
3. Locally:
   ```bash
   pip3 install google-auth-oauthlib google-api-python-client
   python3 get_refresh_token.py
   ```
   This opens a browser once for you to grant read-only Gmail access, then
   prints a `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, and `GMAIL_REFRESH_TOKEN`.
   Save all three — you won't see the refresh token again.

   > **macOS note:** use `python3`/`pip3`, not `python`/`pip` — modern macOS
   > doesn't ship a `python` command. If a browser doesn't open automatically,
   > the script prints a URL — paste it into any browser manually.

### 2. Notion access

1. Create an integration at [notion.so/my-integrations](https://www.notion.so/my-integrations),
   copy its **Internal Integration Token** → this is `NOTION_TOKEN`.
2. In Notion, create (or pick) a page for the tracker to live under, and
   **share** that page with your integration (`···` menu → *Connections* →
   add your integration).
3. Copy that page's ID from its URL (the 32-character string) → this is
   `NOTION_PARENT_PAGE_ID`. The app will create the database automatically on
   its first run. After that first run, grab the printed database ID and set
   it as `NOTION_DATABASE_ID` instead (slightly faster on every run after).

### 3. Wire it into GitHub

1. Push this repo to GitHub.
2. Repo → **Settings → Secrets and variables → Actions** → add:
   - `GMAIL_CLIENT_ID`
   - `GMAIL_CLIENT_SECRET`
   - `GMAIL_REFRESH_TOKEN`
   - `NOTION_TOKEN`
   - `NOTION_PARENT_PAGE_ID` (or `NOTION_DATABASE_ID` if you already have one)
3. In the **Actions** tab, run **Daily Job Application Scan** manually once
   with `days_back = 14` to backfill the last two weeks.
4. After that, it runs automatically every day on the cron schedule in
   `.github/workflows/daily-scan.yml`. Edit the cron hour to match your
   timezone's midnight (GitHub Actions cron is UTC).

## Tests & reliability

There's a pytest suite (`tests/`) covering every classification path —
application confirmation, recruiter outreach, interview, rejection, offer,
unrelated email, and the Notion create-vs-update matching logic — mocked so
it runs without hitting Gmail or Notion. It runs automatically in CI on every
push via `.github/workflows/tests.yml`.

```bash
pip3 install -r requirements.txt -r requirements-dev.txt
pytest -v
```

**On "self-correcting":** this is a rule-based classifier, not ML, so it
can't learn from its own mistakes the way a trained model might. What it does
instead:
- Flags low-confidence rows (no role detected, no company signal) with a
  **Needs Review** checkbox in Notion, rather than silently guessing.
- Isolates each email in a try/except in `main.py` — one malformed email
  logs an error and gets skipped, it doesn't take down the whole day's run.
- Exits non-zero on any per-email failure, so a broken run shows up red in
  the GitHub Actions tab instead of quietly succeeding with dropped emails.

If you want true self-improvement (e.g. it learns from you correcting a
misclassified row), that needs a feedback loop — logging your manual Notion
edits and periodically re-tuning the regex or swapping in a small classifier
model trained on your corrections. Doable as a follow-up, out of scope here.

## Local testing

```bash
pip3 install -r requirements.txt
cp .env.example .env   # fill in values
export $(cat .env | xargs)
python3 src/main.py
```

## Notes / limitations

- Company and role extraction are heuristic. Unusual email formats (a hiring
  manager emailing from a personal address, no-reply addresses that don't
  encode a company name) will sometimes need a manual fix in Notion.
- Gmail's `readonly` scope is used deliberately — this app never deletes,
  labels, or sends anything.
- The classifier is intentionally conservative about "not job related" —
  tune the regex lists in `src/classifier.py` if it's missing or over-catching
  emails for your inbox's specific patterns.
