"""
tests/test_notion_wrapper.py

The Notion SDK is mocked out entirely -- these tests check the *logic*
(does a repeat email update the existing row instead of duplicating it?
does a brand-new company create a row?) without making real API calls or
requiring a live Notion workspace, so this runs in CI on every push.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from notion_client_wrapper import upsert_application


def _mock_client_with_existing_row(page_id="page-123", role_text="Software Engineer"):
    client = MagicMock()
    client.databases.query.return_value = {
        "results": [
            {
                "id": page_id,
                "properties": {"Role / Req ID": {"rich_text": [{"plain_text": role_text}]}},
            }
        ]
    }
    return client


def _mock_client_with_no_existing_row():
    client = MagicMock()
    client.databases.query.return_value = {"results": []}
    return client


def test_new_company_creates_a_row():
    client = _mock_client_with_no_existing_row()

    action = upsert_application(
        client=client,
        database_id="db-1",
        company="Acme Corp",
        role="Software Engineer",
        req_id=None,
        category="application_confirmation",
        is_recruiter=False,
        needs_review=False,
        email_date=datetime(2026, 8, 20, tzinfo=timezone.utc),
        thread_url="https://mail.google.com/mail/u/0/#inbox/t1",
    )

    assert action == "created"
    client.pages.create.assert_called_once()
    client.pages.update.assert_not_called()

    call_kwargs = client.pages.create.call_args.kwargs
    assert call_kwargs["properties"]["Company"]["title"][0]["text"]["content"] == "Acme Corp"
    assert call_kwargs["properties"]["Status"]["select"]["name"] == "Applied"


def test_repeat_contact_for_same_company_updates_existing_row_not_duplicate():
    client = _mock_client_with_existing_row(page_id="page-123", role_text="Software Engineer")

    action = upsert_application(
        client=client,
        database_id="db-1",
        company="Acme Corp",
        role="Software Engineer",
        req_id=None,
        category="interview",
        is_recruiter=False,
        needs_review=False,
        email_date=datetime(2026, 8, 25, tzinfo=timezone.utc),
        thread_url="https://mail.google.com/mail/u/0/#inbox/t2",
    )

    assert action == "updated"
    client.pages.create.assert_not_called()
    client.pages.update.assert_called_once()

    call_kwargs = client.pages.update.call_args.kwargs
    assert call_kwargs["page_id"] == "page-123"
    assert call_kwargs["properties"]["Status"]["select"]["name"] == "Interview Scheduled"
    assert call_kwargs["properties"]["Next Action"]["select"]["name"] == "Prepare for interview"


def test_recruiter_flag_and_needs_review_are_passed_through():
    client = _mock_client_with_no_existing_row()

    upsert_application(
        client=client,
        database_id="db-1",
        company="Unknown",
        role="(role not detected — check email)",
        req_id=None,
        category="recruiter_outreach",
        is_recruiter=True,
        needs_review=True,
        email_date=datetime(2026, 8, 20, tzinfo=timezone.utc),
        thread_url="https://mail.google.com/mail/u/0/#inbox/t3",
    )

    props = client.pages.create.call_args.kwargs["properties"]
    assert props["Recruiter Contact"]["checkbox"] is True
    assert props["Needs Review"]["checkbox"] is True
    assert props["Next Action"]["select"]["name"] == "Reply to recruiter"
