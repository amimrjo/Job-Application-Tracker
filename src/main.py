"""
main.py
Daily entry point: fetch recent emails -> classify -> upsert into Notion.

Run manually:
    DAYS_BACK=14 python src/main.py     # first-time backfill (2 weeks)
    python src/main.py                  # normal daily run (default: last 1 day)

All secrets are read from environment variables (see .env.example / README).
"""

from __future__ import annotations

import os
import sys

from notion_client import Client as NotionClient

from classifier import classify
from gmail_client import fetch_recent_emails
from notion_client_wrapper import bootstrap_database, upsert_application


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"ERROR: missing required environment variable {name}", file=sys.stderr)
        sys.exit(1)
    return val


def main() -> None:
    gmail_client_id = _require_env("GMAIL_CLIENT_ID")
    gmail_client_secret = _require_env("GMAIL_CLIENT_SECRET")
    gmail_refresh_token = _require_env("GMAIL_REFRESH_TOKEN")
    notion_token = _require_env("NOTION_TOKEN")

    days_back = int(os.environ.get("DAYS_BACK", "1"))

    database_id = os.environ.get("NOTION_DATABASE_ID")
    notion = NotionClient(auth=notion_token)

    if not database_id:
        parent_page_id = _require_env("NOTION_PARENT_PAGE_ID")
        database_id = bootstrap_database(notion, parent_page_id)
        print(f"Bootstrapped Notion database: {database_id}")
        print("Tip: set NOTION_DATABASE_ID to this value to skip this lookup on future runs.")

    print(f"Fetching emails from the last {days_back} day(s)...")
    emails = fetch_recent_emails(
        client_id=gmail_client_id,
        client_secret=gmail_client_secret,
        refresh_token=gmail_refresh_token,
        days_back=days_back,
    )
    print(f"Fetched {len(emails)} email(s). Classifying...")

    created, updated, skipped, flagged, failed = 0, 0, 0, 0, 0
    failures: list[str] = []

    for email in emails:
        try:
            result = classify(email)
            if not result.is_job_related:
                skipped += 1
                continue

            thread_url = f"https://mail.google.com/mail/u/0/#inbox/{email.thread_id}"
            action = upsert_application(
                client=notion,
                database_id=database_id,
                company=result.company,
                role=result.role,
                req_id=result.req_id,
                category=result.category,
                is_recruiter=result.is_recruiter,
                needs_review=result.needs_review,
                email_date=email.date,
                thread_url=thread_url,
            )
            if action == "created":
                created += 1
            else:
                updated += 1
            if result.needs_review:
                flagged += 1

            tag = "[RECRUITER] " if result.is_recruiter else ""
            review_tag = "[NEEDS REVIEW] " if result.needs_review else ""
            print(f"  {tag}{review_tag}{action.upper()}: {result.company} — {result.role} ({result.category})")

        except Exception as exc:  # noqa: BLE001 -- one bad email must not kill the whole daily run
            failed += 1
            failures.append(f"{email.subject!r} from {email.sender_email}: {exc}")
            print(f"  FAILED to process email {email.id!r}: {exc}")

    print(
        f"\nDone. {created} new row(s), {updated} updated, {flagged} flagged for review, "
        f"{skipped} not job-related, {failed} failed."
    )

    if failures:
        # Non-zero exit so a GitHub Actions run with failures shows red, not green --
        # you want to notice silently-dropped emails, not just successes.
        print("\nFailures:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
