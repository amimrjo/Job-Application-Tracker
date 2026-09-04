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


def test_job_board_digest_is_not_tracked_as_an_application():
    # "You joined our talent community" mass mailers -- not an application you sent
    email = make_email(
        "Grainger Businesses",
        "grainger-jobnotification@noreply.jobs2web.com",
        "New jobs posted from Grainger Businesses",
        "Thank you for joining the Grainger Businesses talent community! Joining our "
        "talent community will allow us to notify you directly when roles aligned to "
        "your interest present themselves. Please apply for any current openings that "
        "fit your interest. The following jobs matched your search agent at Grainger "
        "Businesses.",
    )
    result = classify(email)

    assert result.is_job_related is False


def test_recruiting_marketing_blast_is_not_tracked_as_recruiter_contact():
    # A list of open roles blasted to a mailing list is not personal recruiter outreach
    email = make_email(
        "Texas Instruments Recruiting",
        "ti_myhiring_no-reply@recruiting.ti.com",
        "New job opportunities at Texas Instruments",
        "Hello Amitha, We have new job opportunities that might interest you. Check "
        "them out: Network Engineer, AI Solutions Engineer. See all opportunities. "
        "Sincerely, Texas Instruments Recruiting team.",
    )
    result = classify(email)

    assert result.is_job_related is False
    assert result.is_recruiter is False


def test_digest_pattern_does_not_override_a_real_signal():
    # If a "digest-style" email ALSO contains a genuine interview invite, the real
    # signal should still win and the email should be tracked.
    email = make_email(
        "Acme Corp",
        "careers@acme.com",
        "New job opportunities at Acme -- plus your interview invitation",
        "We have new job opportunities you might like. Separately: we'd like to "
        "schedule an interview for the position of Backend Engineer.",
    )
    result = classify(email)

    assert result.is_job_related is True
    assert result.category == "interview"


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