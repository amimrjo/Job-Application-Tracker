"""
tests/test_classifier.py

Each test is a realistic email shape (ATS confirmation, recruiter DM, Calendly
interview invite, rejection boilerplate, offer letter, and an unrelated
newsletter) with an assertion on every field the rest of the app depends on:
is_job_related, category, is_recruiter, next_action, and needs_review.

These are the regression guard: if someone tweaks a regex in classifier.py and
breaks a previously-working case, this suite catches it before it reaches a
real daily run.
"""

from datetime import datetime, timezone

import pytest
from classifier import classify
from gmail_client import EmailMessage


def make_email(sender_name, sender_email, subject, body, snippet=""):
    return EmailMessage(
        id="msg-1",
        thread_id="thread-1",
        sender_name=sender_name,
        sender_email=sender_email,
        subject=subject,
        date=datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
        snippet=snippet or body[:50],
        body=body,
    )


def test_application_confirmation_via_ats():
    email = make_email(
        "Acme Corp Careers",
        "careers@greenhouse.io",
        "Your application to Acme Corp",
        "Thank you for applying to the Software Engineer position at Acme Corp. "
        "We have received your application and will be in touch.",
    )
    result = classify(email)

    assert result.is_job_related is True
    assert result.category == "application_confirmation"
    assert result.is_recruiter is False
    assert result.next_action == "Wait"
    assert result.company == "Acme Corp"
    assert result.role == "Software Engineer"
    assert result.needs_review is False


def test_recruiter_outreach():
    email = make_email(
        "Jane Doe",
        "jane@somecompany.com",
        "Quick chat about a role?",
        "Hi, I came across your profile on LinkedIn and think you'd be a great "
        "fit for our Backend Engineer role. Would you be open to a quick chat "
        "this week?",
    )
    result = classify(email)

    assert result.is_job_related is True
    assert result.category == "recruiter_outreach"
    assert result.is_recruiter is True
    assert result.next_action == "Reply to recruiter"


def test_interview_invite():
    email = make_email(
        "Beta Inc Talent",
        "noreply@beta.io",
        "Interview invitation - Beta Inc",
        "We would like to schedule an interview for the position of Data "
        "Analyst. Please use this Calendly link to pick a time.",
    )
    result = classify(email)

    assert result.category == "interview"
    assert result.next_action == "Prepare for interview"
    assert result.role == "Data Analyst"


def test_rejection():
    email = make_email(
        "Gamma LLC",
        "hr@gamma.com",
        "Update on your application",
        "Thank you for your interest in Gamma LLC. After careful consideration, "
        "we have decided to move forward with other candidates for this role.",
    )
    result = classify(email)

    assert result.category == "rejection"
    assert result.next_action == "None"
    assert result.is_recruiter is False


def test_offer():
    email = make_email(
        "Delta Co",
        "hr@delta.com",
        "Your offer from Delta Co",
        "We are pleased to offer you the position of Product Manager. Please "
        "find the attached offer letter.",
    )
    result = classify(email)

    assert result.category == "offer"
    assert result.next_action == "Review offer"


def test_unrelated_newsletter_is_skipped():
    email = make_email(
        "Tech Weekly",
        "news@somewhere.com",
        "This week in tech",
        "Here is your weekly roundup of tech news and industry trends.",
    )
    result = classify(email)

    assert result.is_job_related is False


def test_low_confidence_extraction_is_flagged_for_review():
    # No detectable role, sender is a personal-email-style address with no domain signal
    email = make_email(
        "Recruiter Bot",
        "someone@gmail.com",
        "Opportunity",
        "We have an opportunity we'd love to discuss with you regarding a role.",
    )
    result = classify(email)

    assert result.is_job_related is True
    assert result.needs_review is True


def test_ats_domain_strips_careers_suffix_from_company_name():
    email = make_email(
        "Acme Corp Recruiting",
        "jobs@lever.co",
        "Application received",
        "Thank you for applying. We have received your application.",
    )
    result = classify(email)

    assert result.company == "Acme Corp"


@pytest.mark.parametrize(
    "req_text,expected",
    [
        ("Requisition ID: REQ-2026-1042", "REQ-2026-1042"),
        ("Job ID: 998877", "998877"),
        ("Application Number: APP-55", "APP-55"),
        ("no id anywhere in this text", None),
    ],
)
def test_req_id_extraction(req_text, expected):
    email = make_email("Co", "jobs@example.com", "Application", req_text)
    result = classify(email)
    assert result.req_id == expected
