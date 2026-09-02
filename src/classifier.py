"""
classifier.py
Rule-based classification of an email into the job-search tracker categories.

No ML here on purpose: job-application emails follow very predictable templates
(ATS confirmation emails, recruiter LinkedIn-style outreach, interview scheduling
tools like Calendly/GoodTime, rejection boilerplate). Regex heuristics catch the
overwhelming majority and are fully transparent/debuggable -- important for
something making decisions about your job search.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from gmail_client import EmailMessage

# Common Applicant Tracking System domains -> used to detect "this is an application
# system email" even when the company name isn't obviously in the sender address.
ATS_DOMAINS = [
    "greenhouse.io", "lever.co", "myworkdayjobs.com", "workday.com", "icims.com",
    "taleo.net", "smartrecruiters.com", "bamboohr.com", "ashbyhq.com", "jobvite.com",
    "successfactors.com", "breezy.hr", "recruitee.com", "jazzhr.com", "wellfound.com",
]

APPLICATION_CONFIRMATION_PATTERNS = [
    r"thank you for (applying|your application)",
    r"we('| ha)ve received your application",
    r"your application (has been|was) (received|submitted)",
    r"application confirmation",
    r"we appreciate your interest in",
]

RECRUITER_PATTERNS = [
    r"\brecruiter\b", r"\btalent (acquisition|partner)\b", r"\bhiring manager\b",
    r"reaching out (about|regarding)", r"\bwould you be (open|interested) to",
    r"i came across your (profile|resume)", r"quick chat about (a|an|the) (role|opportunity)",
    r"\btalent scout\b", r"sourcing for",
]

INTERVIEW_PATTERNS = [
    r"schedule (a|an|your) (interview|call)", r"interview invit", r"next steps? in (the|our) (interview )?process",
    r"phone screen", r"technical (interview|screen|assessment)", r"\bcalendly\.com\b", r"\bgoodtime\.io\b",
]

REJECTION_PATTERNS = [
    r"we('| ha)ve decided to (move forward with|proceed with) other",
    r"will not be moving forward", r"unable to offer you", r"not selected",
    r"we regret to inform", r"after careful consideration",
]

OFFER_PATTERNS = [
    r"\bwe('re| are)? (pleased|excited|happy) to (offer|extend)", r"job offer", r"offer letter",
]

# Generic "is this even job related" gate — applied when nothing above hits,
# to avoid tracking pure newsletters/spam.
JOB_RELATED_HINT_PATTERNS = [
    r"\bapplication\b", r"\bposition\b", r"\brole\b", r"\bcareers?\b", r"\bhiring\b",
    r"\binterview\b", r"\brequisition\b", r"\bjob id\b", r"\bopportunity\b",
]

ROLE_EXTRACT_PATTERNS = [
    r"(?:position|role) of[:\s]+([A-Z][\w \-/&]{2,60})",
    r"applying (?:for|to) the[:\s]+([A-Z][\w \-/&]{2,60}?)\s*(?:position|role)\b",
    r"for (?:the|our|a|an) ([A-Z][\w \-/&]{2,60}) (?:position|role)",
    r"(?:job title|position title)[:\s]+([A-Z][\w \-/&]{2,60})",
    r"fit for (?:our|a|an) ([A-Z][\w \-/&]{2,60}) role",
]

REQ_ID_EXTRACT_PATTERNS = [
    r"(?:req(?:uisition)?\s*(?:id|#|number)?[:\s]+)([A-Z0-9\-]{4,20})",
    r"(?:job id[:\s]+)([A-Z0-9\-]{4,20})",
    r"(?:application\s*(?:id|#|number)[:\s]+)([A-Z0-9\-]{4,20})",
]


@dataclass
class Classification:
    is_job_related: bool
    category: str  # application_confirmation | recruiter_outreach | interview | rejection | offer | other_update
    is_recruiter: bool
    company: str
    role: str
    req_id: Optional[str]
    next_action: str  # "Wait" | "Reply to recruiter" | "Prepare for interview" | "Review offer" | "None"
    needs_review: bool  # True when extraction confidence is low -> flagged in Notion instead of guessed silently


def _matches_any(patterns, text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _extract_company(email: EmailMessage) -> str:
    domain = email.sender_email.split("@")[-1].lower() if "@" in email.sender_email else ""

    # ATS emails: company is usually in the sender display name ("Acme Corp via Greenhouse")
    if any(ats in domain for ats in ATS_DOMAINS):
        cleaned = re.sub(r"\s*(via|on behalf of).*", "", email.sender_name, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s*(careers|recruiting|talent(?: acquisition)?|hr|jobs)\s*$", "", cleaned, flags=re.IGNORECASE).strip()
        if cleaned and cleaned.lower() not in ("careers", "recruiting", "talent", "no-reply", "noreply", ""):
            return cleaned
        # fall back to subject line, e.g. "Your application to Acme Corp"
        m = re.search(r"(?:application to|applying to|interest in)\s+([A-Z][\w &\-]{2,40})", email.subject)
        if m:
            return m.group(1).strip()
        return domain.split(".")[0].title() if domain else "Unknown"

    # Non-ATS: use the sender's domain's registrable part, title-cased
    if domain and domain not in ("gmail.com", "outlook.com", "yahoo.com", "icloud.com"):
        base = domain.split(".")[0]
        return base.replace("-", " ").title()

    return email.sender_name or "Unknown"


def _extract_role(text: str) -> str:
    for pattern in ROLE_EXTRACT_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def _extract_req_id(text: str) -> Optional[str]:
    for pattern in REQ_ID_EXTRACT_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def classify(email: EmailMessage) -> Classification:
    text = f"{email.subject}\n{email.body}\n{email.snippet}"

    is_recruiter = _matches_any(RECRUITER_PATTERNS, text)
    is_confirmation = _matches_any(APPLICATION_CONFIRMATION_PATTERNS, text)
    is_interview = _matches_any(INTERVIEW_PATTERNS, text)
    is_rejection = _matches_any(REJECTION_PATTERNS, text)
    is_offer = _matches_any(OFFER_PATTERNS, text)
    is_generic_job_hint = _matches_any(JOB_RELATED_HINT_PATTERNS, text)

    is_job_related = any([is_recruiter, is_confirmation, is_interview, is_rejection, is_offer, is_generic_job_hint])

    if is_offer:
        category, next_action = "offer", "Review offer"
    elif is_interview:
        category, next_action = "interview", "Prepare for interview"
    elif is_rejection:
        category, next_action = "rejection", "None"
    elif is_recruiter:
        category, next_action = "recruiter_outreach", "Reply to recruiter"
    elif is_confirmation:
        category, next_action = "application_confirmation", "Wait"
    else:
        category, next_action = "other_update", "Wait"

    role = _extract_role(text)
    company = _extract_company(email)

    # Low-confidence extraction gets flagged for a human to check rather than
    # silently written as fact -- this is the closest a rule-based system gets
    # to "self-correcting": it knows what it doesn't know.
    needs_review = (not role) or company == "Unknown"

    return Classification(
        is_job_related=is_job_related,
        category=category,
        is_recruiter=is_recruiter,
        company=company,
        role=role or "(role not detected — check email)",
        req_id=_extract_req_id(text),
        next_action=next_action,
        needs_review=needs_review,
    )
