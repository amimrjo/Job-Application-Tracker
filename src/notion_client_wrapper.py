"""
notion_client_wrapper.py
Upserts job-application rows into a Notion database.

Matching logic: an incoming email is matched to an existing row by
(company, role) fuzzy-ish equality. If found, the row's Status / Next Action /
Last Update fields are refreshed (this is how "we hear back a few days later"
updates get reflected without creating duplicate rows). If not found, a new
row is created with Application Date = the email's date.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from notion_client import Client

STATUS_LABELS = {
    "application_confirmation": "Applied",
    "recruiter_outreach": "Recruiter Contact",
    "interview": "Interview Scheduled",
    "rejection": "Rejected",
    "offer": "Offer",
    "other_update": "Update Received",
}

DB_TITLE = "Job Application Tracker"

SCHEMA = {
    "Company": {"title": {}},
    "Role / Req ID": {"rich_text": {}},
    "Application Date": {"date": {}},
    "Status": {
        "select": {
            "options": [
                {"name": "Applied", "color": "blue"},
                {"name": "Recruiter Contact", "color": "yellow"},
                {"name": "Interview Scheduled", "color": "green"},
                {"name": "Offer", "color": "purple"},
                {"name": "Rejected", "color": "red"},
                {"name": "Update Received", "color": "orange"},
            ]
        }
    },
    "Next Action": {
        "select": {
            "options": [
                {"name": "Wait", "color": "gray"},
                {"name": "Reply to recruiter", "color": "yellow"},
                {"name": "Prepare for interview", "color": "green"},
                {"name": "Review offer", "color": "purple"},
                {"name": "None", "color": "default"},
            ]
        }
    },
    "Recruiter Contact": {"checkbox": {}},
    "Needs Review": {"checkbox": {}},
    "Last Email Date": {"date": {}},
    "Source Thread": {"url": {}},
}


def bootstrap_database(client: Client, parent_page_id: str) -> str:
    """Create the tracker database under `parent_page_id` if one doesn't already exist. Returns database_id."""
    children = client.blocks.children.list(block_id=parent_page_id)["results"]
    for block in children:
        if block.get("type") == "child_database":
            db = client.databases.retrieve(database_id=block["id"])
            title = "".join(t["plain_text"] for t in db.get("title", []))
            if title == DB_TITLE:
                return block["id"]

    db = client.databases.create(
        parent={"type": "page_id", "page_id": parent_page_id},
        title=[{"type": "text", "text": {"content": DB_TITLE}}],
        properties=SCHEMA,
    )
    return db["id"]


def _find_existing_row(client: Client, database_id: str, company: str, role: str) -> Optional[str]:
    resp = client.databases.query(
        database_id=database_id,
        filter={"property": "Company", "title": {"equals": company}},
    )
    results = resp.get("results", [])
    if not results:
        return None
    if len(results) == 1 or not role:
        return results[0]["id"]

    # Prefer a role match when there are multiple rows for the same company
    for page in results:
        rt = page["properties"].get("Role / Req ID", {}).get("rich_text", [])
        existing_role = "".join(t["plain_text"] for t in rt)
        if existing_role and role and existing_role.lower() in role.lower():
            return page["id"]
    return results[0]["id"]


def upsert_application(
    client: Client,
    database_id: str,
    company: str,
    role: str,
    req_id: Optional[str],
    category: str,
    is_recruiter: bool,
    needs_review: bool,
    email_date: datetime,
    thread_url: str,
) -> str:
    """Create or update a tracker row. Returns 'created' or 'updated'."""
    role_display = f"{role}" + (f" ({req_id})" if req_id else "")
    status = STATUS_LABELS.get(category, "Update Received")
    next_action = {
        "application_confirmation": "Wait",
        "recruiter_outreach": "Reply to recruiter",
        "interview": "Prepare for interview",
        "rejection": "None",
        "offer": "Review offer",
        "other_update": "Wait",
    }.get(category, "Wait")

    existing_id = _find_existing_row(client, database_id, company, role_display)

    properties = {
        "Status": {"select": {"name": status}},
        "Next Action": {"select": {"name": next_action}},
        "Recruiter Contact": {"checkbox": is_recruiter},
        "Needs Review": {"checkbox": needs_review},
        "Last Email Date": {"date": {"start": email_date.isoformat()}},
        "Source Thread": {"url": thread_url},
    }

    if existing_id:
        client.pages.update(page_id=existing_id, properties=properties)
        return "updated"

    properties["Company"] = {"title": [{"text": {"content": company}}]}
    properties["Role / Req ID"] = {"rich_text": [{"text": {"content": role_display}}]}
    properties["Application Date"] = {"date": {"start": email_date.isoformat()}}
    client.pages.create(parent={"database_id": database_id}, properties=properties)
    return "created"
