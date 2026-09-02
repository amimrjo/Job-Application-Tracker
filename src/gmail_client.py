"""
gmail_client.py
Thin wrapper around the Gmail API for fetching messages in a date window.

Auth model: OAuth2 "installed app" flow, run ONCE locally (see get_refresh_token.py)
to mint a long-lived refresh token. The refresh token + client id/secret are then
stored as GitHub Actions secrets so the daily workflow can run headlessly (no browser).
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


@dataclass
class EmailMessage:
    id: str
    thread_id: str
    sender_name: str
    sender_email: str
    subject: str
    date: datetime
    snippet: str
    body: str


def _get_service(client_id: str, client_secret: str, refresh_token: str):
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _decode_body(payload: dict) -> str:
    """Recursively pull plain-text (fallback: html-stripped) body out of a Gmail payload."""
    if payload.get("mimeType") == "text/plain" and "data" in payload.get("body", {}):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")

    if "parts" in payload:
        # Prefer text/plain, fall back to text/html (stripped) if that's all there is
        text_part = None
        html_part = None
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain":
                text_part = part
            elif part.get("mimeType") == "text/html":
                html_part = part
            elif "parts" in part:
                nested = _decode_body(part)
                if nested:
                    return nested
        if text_part and "data" in text_part.get("body", {}):
            return base64.urlsafe_b64decode(text_part["body"]["data"]).decode("utf-8", errors="ignore")
        if html_part and "data" in html_part.get("body", {}):
            raw = base64.urlsafe_b64decode(html_part["body"]["data"]).decode("utf-8", errors="ignore")
            return re.sub("<[^<]+?>", " ", raw)

    if "data" in payload.get("body", {}):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")

    return ""


def _parse_sender(raw_from: str) -> tuple[str, str]:
    match = re.match(r'^"?([^"<]*)"?\s*<?([\w\.\-+]+@[\w\.\-]+)?>?$', raw_from.strip())
    if not match:
        return raw_from, ""
    name = (match.group(1) or "").strip()
    email = (match.group(2) or "").strip()
    if not name:
        name = email.split("@")[0] if email else raw_from
    return name, email


def fetch_recent_emails(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    days_back: int = 1,
    max_results: int = 200,
    extra_query: Optional[str] = None,
) -> List[EmailMessage]:
    """
    Fetch inbox emails newer than `days_back` days. `extra_query` lets you
    narrow with Gmail search syntax (kept broad by default -- classification
    happens downstream in classifier.py, not here).
    """
    service = _get_service(client_id, client_secret, refresh_token)

    query = f"newer_than:{days_back}d in:inbox"
    if extra_query:
        query += f" {extra_query}"

    results: List[EmailMessage] = []
    page_token = None

    while True:
        resp = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=min(100, max_results - len(results)), pageToken=page_token)
            .execute()
        )
        ids = resp.get("messages", [])
        for m in ids:
            full = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
            headers = {h["name"].lower(): h["value"] for h in full["payload"].get("headers", [])}
            sender_name, sender_email = _parse_sender(headers.get("from", ""))
            date_hdr = headers.get("date")
            try:
                dt = datetime.strptime(date_hdr[:31].strip(), "%a, %d %b %Y %H:%M:%S %z")
            except Exception:
                dt = datetime.now(timezone.utc)

            results.append(
                EmailMessage(
                    id=full["id"],
                    thread_id=full["threadId"],
                    sender_name=sender_name,
                    sender_email=sender_email,
                    subject=headers.get("subject", "(no subject)"),
                    date=dt,
                    snippet=full.get("snippet", ""),
                    body=_decode_body(full["payload"]),
                )
            )
            if len(results) >= max_results:
                return results

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return results
