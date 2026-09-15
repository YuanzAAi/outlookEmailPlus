from __future__ import annotations

import json
import os
from typing import Any


EDU_MAIL_PROVIDER_NAME = "edumail"
EDU_MAIL_SOURCE = "edu_mail"


def _normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def get_edu_mail_mappings() -> list[dict[str, str]]:
    mappings: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in str(os.getenv("EDU_MAIL_MAPPINGS") or "").replace("\n", ";").split(";"):
        if "=" not in item:
            continue
        display_email, backing_email = (_normalize_email(part) for part in item.split("=", 1))
        if (
            not display_email
            or not backing_email
            or "@" not in display_email
            or "@" not in backing_email
            or display_email == backing_email
            or display_email in seen
        ):
            continue
        seen.add(display_email)
        mappings.append({"email": display_email, "backing_email": backing_email})
    return mappings


def get_edu_mail_mapping(email_addr: str | None) -> dict[str, str] | None:
    normalized = _normalize_email(email_addr)
    return next((item for item in get_edu_mail_mappings() if item["email"] == normalized), None)


def get_reserved_backing_emails() -> set[str]:
    return {item["backing_email"] for item in get_edu_mail_mappings()}


def decorate_edu_mailbox(mailbox: dict[str, Any], display_email: str) -> dict[str, Any]:
    decorated = dict(mailbox)
    decorated["display_email"] = _normalize_email(display_email)
    decorated["received_for"] = _normalize_email(display_email)
    decorated["backing_email"] = _normalize_email(mailbox.get("email"))
    decorated["edu_mail"] = True
    return decorated


def get_edu_mail_capabilities() -> dict[str, bool]:
    return {
        "delete_mailbox": False,
        "delete_message": False,
        "clear_messages": False,
        "send_message": False,
        "list_sent_messages": False,
        "delete_sent_message": False,
        "clear_sent_messages": False,
    }


def message_matches_edu_mail(row: dict[str, Any], received_for: str | None) -> bool:
    expected = _normalize_email(received_for)
    if not expected:
        return True
    raw_content = row.get("raw_content")
    if isinstance(raw_content, dict):
        payload = raw_content
    else:
        try:
            payload = json.loads(str(raw_content or ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
    recipients = payload.get("received_for") if isinstance(payload, dict) else []
    if isinstance(recipients, str):
        recipients = [recipients]
    if not isinstance(recipients, list):
        return False
    return expected in {_normalize_email(item) for item in recipients}


def filter_edu_mail_messages(rows: list[dict[str, Any]], mailbox: dict[str, Any]) -> list[dict[str, Any]]:
    if not mailbox.get("edu_mail"):
        return rows
    return [row for row in rows if message_matches_edu_mail(row, mailbox.get("received_for"))]
