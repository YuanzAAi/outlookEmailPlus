"""Outlook OAuth mailbox transport selection.

This module keeps protocol selection separate from the external API controller.
It treats an empty mailbox as a successful capability probe: access to the
folder is what matters, not whether a message already exists.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from outlook_web.services import graph as graph_service
from outlook_web.services import imap as imap_service

IMAP_SERVER_NEW = "outlook.live.com"
IMAP_SERVER_OLD = "outlook.office365.com"

GRAPH_INBOX = "graph_inbox"
GRAPH_JUNK = "graph_junk"
IMAP_NEW = "imap_new"
IMAP_OLD = "imap_old"

VALID_CHANNELS = {GRAPH_INBOX, GRAPH_JUNK, IMAP_NEW, IMAP_OLD}
DEFAULT_CHANNELS = (GRAPH_INBOX, GRAPH_JUNK, IMAP_NEW, IMAP_OLD)


def is_terminal_refresh_token_failure(payload: Any) -> bool:
    """Return True only when the upstream explicitly rejects the refresh token."""
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str).casefold()
    except (TypeError, ValueError):
        text = str(payload or "").casefold()
    return "invalid_grant" in text


def normalize_channel(value: Any) -> Optional[str]:
    value = str(value or "").strip().lower()
    return value if value in VALID_CHANNELS else None


def _channel_for_method(method: str, folder: str) -> str:
    if method == "graph":
        return GRAPH_JUNK if folder == "junkemail" else GRAPH_INBOX
    return method


def _method_for_channel(channel: Optional[str]) -> Optional[str]:
    channel = normalize_channel(channel)
    if channel in (GRAPH_INBOX, GRAPH_JUNK):
        return "graph"
    if channel == IMAP_NEW:
        return IMAP_NEW
    if channel == IMAP_OLD:
        return IMAP_OLD
    return None


def build_plan(account: Dict[str, Any], folder: str = "inbox") -> List[str]:
    """Return a method plan with the remembered channel first."""
    folder = str(folder or "inbox").strip().lower() or "inbox"
    if folder not in {"inbox", "junkemail"}:
        return ["graph", IMAP_NEW, IMAP_OLD]
    preferred = normalize_channel(account.get("preferred_verification_channel"))
    preferred_method = _method_for_channel(preferred)
    if preferred_method:
        remaining = ["graph", IMAP_NEW, IMAP_OLD]
        return [preferred_method] + [item for item in remaining if item != preferred_method]
    return ["graph", IMAP_NEW, IMAP_OLD]


def _graph_list(account: Dict[str, Any], folder: str, skip: int, top: int, proxy_url: str) -> Dict[str, Any]:
    return graph_service.get_emails_graph(
        account.get("client_id") or "",
        account.get("refresh_token") or "",
        folder=folder,
        skip=skip,
        top=top,
        proxy_url=proxy_url,
    )


def _imap_list(
    account: Dict[str, Any],
    folder: str,
    skip: int,
    top: int,
    server: str,
    include_search_body: bool = False,
) -> Dict[str, Any]:
    return imap_service.get_emails_imap_with_server(
        account.get("email") or "",
        account.get("client_id") or "",
        account.get("refresh_token") or "",
        folder,
        skip,
        top,
        server,
        include_search_body=include_search_body,
    )


def list_messages(
    account: Dict[str, Any],
    *,
    folder: str = "inbox",
    skip: int = 0,
    top: int = 20,
    proxy_url: str = "",
    preferred_method: Optional[str] = None,
    include_search_body: bool = False,
) -> Dict[str, Any]:
    """Read a folder using the remembered transport before falling back."""
    folder = str(folder or "inbox").strip().lower() or "inbox"
    plan = build_plan(account, folder)
    if preferred_method in {"graph", IMAP_NEW, IMAP_OLD}:
        plan = [preferred_method] + [item for item in plan if item != preferred_method]

    errors: Dict[str, Any] = {}
    graph_auth_expired = False
    for method in plan:
        if method == "graph":
            result = _graph_list(account, folder, skip, top, proxy_url)
            if result.get("success"):
                return {
                    "success": True,
                    "emails": result.get("emails") or [],
                    "method": "Graph API",
                    "method_key": "graph",
                    "channel": _channel_for_method("graph", folder),
                    "new_refresh_token": result.get("new_refresh_token"),
                }
            errors["graph"] = result.get("error") or result
            graph_auth_expired = bool(result.get("auth_expired"))
            if is_terminal_refresh_token_failure(result):
                return {
                    "success": False,
                    "auth_expired": True,
                    "error": result.get("error") or result,
                    "errors": errors,
                }
            if isinstance(result.get("error"), dict) and result["error"].get("type") in (
                "ProxyError",
                "ConnectionError",
            ):
                return {
                    "success": False,
                    "proxy_error": True,
                    "auth_expired": graph_auth_expired,
                    "error": result.get("error"),
                    "errors": errors,
                }
            continue

        server = IMAP_SERVER_NEW if method == IMAP_NEW else IMAP_SERVER_OLD
        result = _imap_list(
            account,
            folder,
            skip,
            top,
            server,
            include_search_body=include_search_body,
        )
        if result.get("success"):
            return {
                "success": True,
                "emails": result.get("emails") or [],
                "method": "IMAP (New)" if method == IMAP_NEW else "IMAP (Old)",
                "method_key": method,
                "channel": method,
                "new_refresh_token": result.get("new_refresh_token"),
            }
        errors[method] = result.get("error") or result
        if is_terminal_refresh_token_failure(result):
            return {
                "success": False,
                "auth_expired": True,
                "error": result.get("error") or result,
                "errors": errors,
            }

    return {
        "success": False,
        "auth_expired": graph_auth_expired,
        "error": errors.get(plan[-1]) or "所有读取方式均失败",
        "errors": errors,
    }


def _graph_detail(account: Dict[str, Any], message_id: str, proxy_url: str) -> Optional[Dict[str, Any]]:
    return graph_service.get_email_detail_graph(
        account.get("client_id") or "",
        account.get("refresh_token") or "",
        message_id,
        proxy_url,
    )


def _imap_detail(account: Dict[str, Any], message_id: str, folder: str, server: str) -> Optional[Dict[str, Any]]:
    return imap_service.get_email_detail_imap_with_server(
        account.get("email") or "",
        account.get("client_id") or "",
        account.get("refresh_token") or "",
        message_id,
        folder,
        server,
    )


def get_detail(
    account: Dict[str, Any],
    *,
    message_id: str,
    folder: str = "inbox",
    proxy_url: str = "",
    preferred_method: Optional[str] = None,
) -> Dict[str, Any]:
    folder = str(folder or "inbox").strip().lower() or "inbox"
    plan = build_plan(account, folder)
    if preferred_method in {"graph", IMAP_NEW, IMAP_OLD}:
        plan = [preferred_method] + [item for item in plan if item != preferred_method]

    for method in plan:
        detail = None
        graph_raw = None
        if method == "graph":
            detail = _graph_detail(account, message_id, proxy_url)
            if detail:
                graph_raw = graph_service.get_email_raw_graph(
                    account.get("client_id") or "",
                    account.get("refresh_token") or "",
                    message_id,
                    proxy_url,
                )
        else:
            server = IMAP_SERVER_NEW if method == IMAP_NEW else IMAP_SERVER_OLD
            detail = _imap_detail(account, message_id, folder, server)
        if detail:
            return {
                "success": True,
                "detail": detail,
                "method": "Graph API" if method == "graph" else ("IMAP (New)" if method == IMAP_NEW else "IMAP (Old)"),
                "method_key": method,
                "channel": _channel_for_method("graph", folder) if method == "graph" else method,
                "raw_content": graph_raw,
            }
    return {"success": False, "error": "未找到邮件详情"}


def probe_account(account: Dict[str, Any], proxy_url: str = "") -> Dict[str, Any]:
    """Probe transport capability without requiring a message to exist."""
    if (account.get("account_type") or "outlook").strip().lower() != "outlook":
        return {"success": True, "method_key": "imap_generic", "channel": "imap_generic", "skipped": False}

    # A successful Graph folder read with zero messages still proves access.
    graph_result = _graph_list(account, "inbox", 0, 1, proxy_url)
    if graph_result.get("success"):
        return {
            "success": True,
            "method_key": "graph",
            "channel": GRAPH_INBOX,
            "new_refresh_token": graph_result.get("new_refresh_token"),
        }

    imap_new = _imap_list(account, "inbox", 0, 1, IMAP_SERVER_NEW)
    if imap_new.get("success"):
        return {
            "success": True,
            "method_key": IMAP_NEW,
            "channel": IMAP_NEW,
            "new_refresh_token": imap_new.get("new_refresh_token"),
        }

    imap_old = _imap_list(account, "inbox", 0, 1, IMAP_SERVER_OLD)
    if imap_old.get("success"):
        return {
            "success": True,
            "method_key": IMAP_OLD,
            "channel": IMAP_OLD,
            "new_refresh_token": imap_old.get("new_refresh_token"),
        }

    return {
        "success": False,
        "method_key": "unknown",
        "errors": {
            "graph": graph_result.get("error") or graph_result,
            "imap_new": imap_new.get("error") or imap_new,
            "imap_old": imap_old.get("error") or imap_old,
        },
    }
