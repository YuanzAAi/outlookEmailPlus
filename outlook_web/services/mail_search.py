"""Asynchronous global mailbox search backed by small JSON job files."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Pattern, Tuple

import requests
from requests.adapters import HTTPAdapter

from outlook_web import config
from outlook_web.db import get_db
from outlook_web.repositories import accounts as accounts_repo
from outlook_web.repositories import groups as groups_repo
from outlook_web.repositories import temp_emails as temp_emails_repo
from outlook_web.services import graph as graph_service
from outlook_web.services import outlook_transport
from outlook_web.services.imap_generic import get_email_detail_imap_generic_result, get_emails_imap_generic
from outlook_web.services.verification_extractor import extract_email_text

JOB_TTL_SECONDS = 24 * 60 * 60
MAX_ACCOUNTS = 200
MAX_RESULTS = 500
MAX_QUERY_LENGTH = 500
MAX_SEARCH_WORKERS = 24
GRAPH_TOKEN_TIMEOUT_SECONDS = 15
GRAPH_REQUEST_TIMEOUT_SECONDS = 15
VALID_FIELDS = {"subject", "sender", "preview", "body"}
VALID_FOLDERS = {"inbox", "junkemail"}
VALID_MAILBOX_SCOPES = {"regular", "temp", "all"}

_WRITE_LOCK = threading.Lock()
_HTTP_SESSION_LOCK = threading.Lock()
_SHARED_HTTP_SESSION: Optional[requests.Session] = None


class MailSearchError(ValueError):
    pass


def _job_dir() -> Path:
    path = Path(config.get_database_path()).resolve().parent / "mail-search-jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _job_path(job_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", str(job_id or "")):
        raise MailSearchError("搜索任务不存在")
    return _job_dir() / f"{job_id}.json"


def _job_cancel_path(job_id: str) -> Path:
    _job_path(job_id)
    return _job_dir() / f"{job_id}.cancel"


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    temp_path = path.with_suffix(".tmp")
    with _WRITE_LOCK:
        temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temp_path, path)


def _cleanup_jobs() -> None:
    cutoff = time.time() - JOB_TTL_SECONDS
    for path in list(_job_dir().glob("*.json")) + list(_job_dir().glob("*.cancel")):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            continue


def _cancel_running_jobs() -> None:
    """A new global search supersedes older searches in this single-user UI."""
    for path in _job_dir().glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("status") not in {"queued", "running"}:
            continue
        payload["cancel_requested"] = True
        payload["updated_at"] = time.time()
        _atomic_write(path, payload)
        try:
            _job_cancel_path(str(payload.get("job_id") or path.stem)).touch(exist_ok=True)
        except OSError:
            continue


def _build_http_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=MAX_SEARCH_WORKERS * 2,
        pool_maxsize=MAX_SEARCH_WORKERS * 2,
        max_retries=0,
        pool_block=False,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _get_shared_http_session() -> requests.Session:
    global _SHARED_HTTP_SESSION
    if _SHARED_HTTP_SESSION is None:
        with _HTTP_SESSION_LOCK:
            if _SHARED_HTTP_SESSION is None:
                _SHARED_HTTP_SESSION = _build_http_session()
    return _SHARED_HTTP_SESSION


def get_job(job_id: str) -> Dict[str, Any]:
    path = _job_path(job_id)
    if not path.exists():
        raise MailSearchError("搜索任务不存在")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MailSearchError("搜索任务状态损坏") from exc


def cancel_job(job_id: str) -> Dict[str, Any]:
    payload = get_job(job_id)
    if payload.get("status") in {"queued", "running"}:
        payload["cancel_requested"] = True
        payload["updated_at"] = time.time()
        _atomic_write(_job_path(job_id), payload)
        _job_cancel_path(job_id).touch(exist_ok=True)
    return payload


def _normalize_params(raw: Dict[str, Any]) -> Dict[str, Any]:
    query = str(raw.get("query") or "").strip()
    if not query:
        raise MailSearchError("请输入检索内容")
    if len(query) > MAX_QUERY_LENGTH:
        raise MailSearchError(f"检索内容不能超过 {MAX_QUERY_LENGTH} 个字符")

    fields = [str(item or "").strip().lower() for item in (raw.get("fields") or ["subject", "preview", "body"])]
    fields = [item for item in fields if item in VALID_FIELDS]
    if not fields:
        raise MailSearchError("至少选择一个匹配范围")

    folders = [str(item or "").strip().lower() for item in (raw.get("folders") or ["inbox", "junkemail"])]
    folders = [item for item in folders if item in VALID_FOLDERS]
    if not folders:
        raise MailSearchError("至少选择一个邮件文件夹")

    try:
        top_per_folder = max(1, min(int(raw.get("top_per_folder") or 20), 50))
        max_accounts = max(1, min(int(raw.get("max_accounts") or MAX_ACCOUNTS), MAX_ACCOUNTS))
    except (TypeError, ValueError) as exc:
        raise MailSearchError("检索数量参数无效") from exc

    group_id = raw.get("group_id")
    try:
        group_id = int(group_id) if group_id not in (None, "", "all") else None
    except (TypeError, ValueError) as exc:
        raise MailSearchError("分组参数无效") from exc

    is_regex = bool(raw.get("regex"))
    if is_regex:
        try:
            re.compile(query, re.IGNORECASE)
        except re.error as exc:
            raise MailSearchError(f"正则表达式无效：{exc}") from exc

    mailbox_scope = str(raw.get("mailbox_scope") or "regular").strip().lower()
    if mailbox_scope not in VALID_MAILBOX_SCOPES:
        raise MailSearchError("邮箱范围参数无效")

    return {
        "query": query,
        "regex": is_regex,
        "fields": fields,
        "folders": folders,
        "account_query": str(raw.get("account_query") or "").strip(),
        "group_id": group_id,
        "top_per_folder": top_per_folder,
        "max_accounts": max_accounts,
        "mailbox_scope": mailbox_scope,
    }


def start_job(app: Any, raw_params: Dict[str, Any]) -> Dict[str, Any]:
    _cleanup_jobs()
    params = _normalize_params(raw_params)
    _cancel_running_jobs()
    job_id = uuid.uuid4().hex
    now = time.time()
    payload = {
        "job_id": job_id,
        "status": "queued",
        "params": params,
        "progress": {"total_accounts": 0, "scanned_accounts": 0, "scanned_messages": 0},
        "summary": {
            "total_matches": 0,
            "stored_results": 0,
            "failed_accounts": 0,
            "truncated": False,
        },
        "results": [],
        "errors": [],
        "cancel_requested": False,
        "created_at": now,
        "updated_at": now,
    }
    _atomic_write(_job_path(job_id), payload)
    thread = threading.Thread(
        target=_run_job,
        args=(app, job_id),
        name=f"mail-search-{job_id[:8]}",
        daemon=True,
    )
    thread.start()
    return payload


def _load_accounts(params: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], bool]:
    db = get_db()
    where = ["status = 'active'", "COALESCE(provider, '') != 'cloudflare_temp_mail'"]
    values: List[Any] = []
    if params.get("group_id"):
        where.append("group_id = ?")
        values.append(params["group_id"])
    if params.get("account_query"):
        where.append("LOWER(email) LIKE ?")
        values.append(f"%{params['account_query'].lower()}%")
    limit = int(params["max_accounts"]) + 1
    rows = db.execute(
        f"SELECT id FROM accounts WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?",
        (*values, limit),
    ).fetchall()
    truncated = len(rows) > int(params["max_accounts"])
    accounts: List[Dict[str, Any]] = []
    for row in rows[: int(params["max_accounts"])]:
        account = accounts_repo.get_account_by_id(int(row["id"]))
        if not account:
            continue
        proxy_url = ""
        if account.get("group_id"):
            group = groups_repo.get_group_by_id(account["group_id"])
            if group:
                proxy_url = str(group.get("proxy_url") or "")
        account["_search_proxy_url"] = proxy_url
        accounts.append(account)
    return accounts, truncated


def _load_temp_mailboxes(params: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], bool]:
    records = temp_emails_repo.load_temp_emails(
        visible_only=True,
        mailbox_type="user",
        status="active",
        view="record",
        order_by_latest_message=True,
    )
    account_query = str(params.get("account_query") or "").casefold()
    if account_query:
        records = [record for record in records if account_query in str(record.get("email") or "").casefold()]
    max_mailboxes = int(params["max_accounts"])
    truncated = len(records) > max_mailboxes
    return records[:max_mailboxes], truncated


def _compile_matcher(params: Dict[str, Any]) -> Tuple[Optional[Pattern[str]], str]:
    if params["regex"]:
        return re.compile(params["query"], re.IGNORECASE), ""
    return None, params["query"].casefold()


def _matches(value: Any, regex: Optional[Pattern[str]], literal: str) -> bool:
    text = str(value or "")
    if regex:
        return bool(regex.search(text))
    return literal in text.casefold()


def _graph_search_query(params: Dict[str, Any]) -> Optional[str]:
    if params.get("regex"):
        return None
    query = str(params.get("query") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+", query):
        return None

    term = f"{query}*"

    properties: List[str] = []
    fields = set(params.get("fields") or [])
    if "sender" in fields:
        properties.append("from")
    if "subject" in fields:
        properties.append("subject")
    if fields.intersection({"preview", "body"}):
        properties.append("body")
    return " OR ".join(f"{name}:{term}" for name in properties) or None


def _item_body_text(item: Dict[str, Any]) -> str:
    search_body = item.get("_search_body")
    if search_body is not None:
        return str(search_body or "")
    body = item.get("body")
    if isinstance(body, dict):
        content = str(body.get("content") or "")
        if str(body.get("contentType") or "text").lower() == "html":
            return extract_email_text({"body_html": content})
        return content
    return str(body or "")


def _excerpt(value: Any, regex: Optional[Pattern[str]], literal: str, radius: int = 90) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    start = 0
    if regex:
        match = regex.search(text)
        start = match.start() if match else 0
    elif literal:
        start = text.casefold().find(literal)
        if start < 0:
            start = 0
    left = max(0, start - radius)
    right = min(len(text), start + radius * 2)
    prefix = "…" if left else ""
    suffix = "…" if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}"


def _normalize_message(
    account: Dict[str, Any],
    folder: str,
    item: Dict[str, Any],
    transport: Dict[str, Any],
) -> Dict[str, Any]:
    raw_from = item.get("from")
    if isinstance(raw_from, dict):
        raw_from = (raw_from.get("emailAddress") or {}).get("address") or ""
    return {
        "source_type": "regular",
        "account_id": int(account["id"]),
        "email": str(account.get("email") or ""),
        "group_id": account.get("group_id"),
        "message_id": str(item.get("id") or ""),
        "folder": folder,
        "from": str(raw_from or item.get("from_address") or ""),
        "subject": str(item.get("subject") or "无主题"),
        "preview": str(item.get("bodyPreview") or item.get("body_preview") or item.get("content_preview") or ""),
        "received_at": str(item.get("receivedDateTime") or item.get("date") or item.get("created_at") or ""),
        "method": str(transport.get("method") or ""),
        "method_key": str(transport.get("method_key") or ""),
    }


def _temp_message_received_at(row: Dict[str, Any]) -> str:
    try:
        timestamp = int(row.get("timestamp") or 0)
    except (TypeError, ValueError):
        timestamp = 0
    if timestamp > 0:
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            pass
    return str(row.get("created_at") or "")


def _temp_message_body(row: Dict[str, Any]) -> str:
    text_content = str(row.get("content") or "")
    html_content = str(row.get("html_content") or "")
    html_text = extract_email_text({"body_html": html_content}) if html_content else ""
    if text_content and html_text and html_text not in text_content:
        return f"{text_content}\n{html_text}"
    return text_content or html_text


def _scan_temp_mailbox(
    mailbox: Dict[str, Any],
    params: Dict[str, Any],
    cancel_event: Optional[threading.Event] = None,
    *,
    message_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    email_addr = str(mailbox.get("email") or "")
    results: List[Dict[str, Any]] = []
    scanned_messages = 0
    if "inbox" not in set(params["folders"]):
        return {
            "account_id": None,
            "email": email_addr,
            "results": results,
            "scanned_messages": scanned_messages,
            "errors": [],
            "preference_updates": [],
        }

    regex, literal = _compile_matcher(params)
    fields = set(params["fields"])
    rows = message_rows
    if rows is None:
        rows = temp_emails_repo.get_temp_email_messages(email_addr)
    rows = rows[: int(params["top_per_folder"])]
    for row in rows:
        if cancel_event and cancel_event.is_set():
            break
        scanned_messages += 1
        body = _temp_message_body(row)
        preview = re.sub(r"\s+", " ", str(row.get("content") or body)).strip()[:200]
        message = {
            "source_type": "temp",
            "account_id": None,
            "email": email_addr,
            "group_id": None,
            "message_id": str(row.get("message_id") or ""),
            "folder": "inbox",
            "from": str(row.get("from_address") or ""),
            "subject": str(row.get("subject") or "无主题"),
            "preview": preview,
            "received_at": _temp_message_received_at(row),
            "method": "Temp Mail",
            "method_key": "temp",
        }
        matched_fields: List[str] = []
        if "subject" in fields and _matches(message["subject"], regex, literal):
            matched_fields.append("subject")
        if "sender" in fields and _matches(message["from"], regex, literal):
            matched_fields.append("sender")
        if "preview" in fields and _matches(message["preview"], regex, literal):
            matched_fields.append("preview")
        if "body" in fields and not matched_fields and _matches(body, regex, literal):
            matched_fields.append("body")
        if matched_fields:
            message["matched_fields"] = matched_fields
            message["excerpt"] = _excerpt(body or message["preview"] or message["subject"], regex, literal)
            results.append(message)

    return {
        "account_id": None,
        "email": email_addr,
        "results": results,
        "scanned_messages": scanned_messages,
        "errors": [],
        "preference_updates": [],
    }


def _generic_imap_list(
    account: Dict[str, Any],
    folder: str,
    top: int,
    *,
    include_search_body: bool = False,
) -> Dict[str, Any]:
    result = get_emails_imap_generic(
        email_addr=account.get("email") or "",
        imap_password=account.get("imap_password") or "",
        imap_host=account.get("imap_host") or "",
        imap_port=account.get("imap_port") or 993,
        folder=folder,
        provider=account.get("provider") or "_default",
        skip=0,
        top=top,
        include_search_body=include_search_body,
    )
    return {
        "success": bool(result.get("success")),
        "emails": result.get("emails") or [],
        "method": str(result.get("method") or "IMAP (Generic)"),
        "method_key": "imap_generic",
        "error": result.get("error"),
    }


def _detail_text(account: Dict[str, Any], message: Dict[str, Any]) -> str:
    if message["method_key"] == "imap_generic":
        result = get_email_detail_imap_generic_result(
            email_addr=account.get("email") or "",
            imap_password=account.get("imap_password") or "",
            imap_host=account.get("imap_host") or "",
            imap_port=account.get("imap_port") or 993,
            message_id=message["message_id"],
            folder=message["folder"],
            provider=account.get("provider") or "_default",
        )
        detail = result.get("email") or {}
        return str(detail.get("body_text") or "") or extract_email_text({"body_html": detail.get("body_html") or ""})

    if message["method_key"] == "graph":
        detail_result = (
            graph_service.get_email_detail_graph(
                account.get("client_id") or "",
                account.get("refresh_token") or "",
                message["message_id"],
                account.get("_search_proxy_url") or "",
            )
            or {}
        )
        detail = (
            detail_result.get("detail") if isinstance(detail_result, dict) and "detail" in detail_result else detail_result
        )
        return _item_body_text(detail)

    result = outlook_transport.get_detail(
        account,
        message_id=message["message_id"],
        folder=message["folder"],
        proxy_url=account.get("_search_proxy_url") or "",
        preferred_method=message["method_key"],
    )
    detail = result.get("detail") or {}
    body = detail.get("body")
    if isinstance(body, dict):
        content = str(body.get("content") or "")
        return (
            content if str(body.get("contentType") or "text").lower() == "text" else extract_email_text({"body_html": content})
        )
    return str(detail.get("body") or detail.get("content") or "")


def _scan_messages(
    account: Dict[str, Any],
    folder: str,
    transport: Dict[str, Any],
    params: Dict[str, Any],
    cancel_event: Optional[threading.Event] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    regex, literal = _compile_matcher(params)
    fields = set(params["fields"])
    results: List[Dict[str, Any]] = []
    scanned_messages = 0

    for item in transport.get("emails") or []:
        if cancel_event and cancel_event.is_set():
            break
        scanned_messages += 1
        message = _normalize_message(account, folder, item, transport)
        matched_fields: List[str] = []
        if "subject" in fields and _matches(message["subject"], regex, literal):
            matched_fields.append("subject")
        if "sender" in fields and _matches(message["from"], regex, literal):
            matched_fields.append("sender")
        if "preview" in fields and _matches(message["preview"], regex, literal):
            matched_fields.append("preview")

        body = _item_body_text(item)
        if "body" in fields and not matched_fields:
            if not body:
                try:
                    body = _detail_text(account, message)
                except Exception:
                    body = ""
            if _matches(body, regex, literal):
                matched_fields.append("body")

        if matched_fields:
            message["matched_fields"] = matched_fields
            message["excerpt"] = _excerpt(body or message["preview"] or message["subject"], regex, literal)
            results.append(message)

    return results, scanned_messages


def _scan_graph_account(
    account: Dict[str, Any],
    params: Dict[str, Any],
    http_session: requests.Session,
    cancel_event: Optional[threading.Event] = None,
) -> Optional[Dict[str, Any]]:
    if cancel_event and cancel_event.is_set():
        return {
            "account_id": int(account["id"]),
            "email": str(account.get("email") or ""),
            "results": [],
            "scanned_messages": 0,
            "errors": [],
            "preference_updates": [],
        }

    token_result = graph_service.get_access_token_graph_result(
        account.get("client_id") or "",
        account.get("refresh_token") or "",
        account.get("_search_proxy_url") or "",
        session=http_session,
        timeout=GRAPH_TOKEN_TIMEOUT_SECONDS,
    )
    if not token_result.get("success"):
        if outlook_transport.is_terminal_refresh_token_failure(token_result):
            return {
                "account_id": int(account["id"]),
                "email": str(account.get("email") or ""),
                "results": [],
                "scanned_messages": 0,
                "errors": ["授权已失效"],
                "preference_updates": [],
            }
        return None
    if not graph_service.has_mail_read_permission(token_result.get("scope")):
        return None

    access_token = str(token_result.get("access_token") or "")
    search_query = _graph_search_query(params)
    include_body = "body" in set(params["fields"])
    results: List[Dict[str, Any]] = []
    scanned_messages = 0
    errors: List[str] = []
    preference_updates: List[Dict[str, Any]] = []
    last_channel: Optional[str] = None

    for folder in params["folders"]:
        if cancel_event and cancel_event.is_set():
            break
        graph_result = graph_service.get_emails_graph_with_access_token(
            access_token,
            folder=folder,
            top=params["top_per_folder"],
            proxy_url=account.get("_search_proxy_url") or "",
            search_query=search_query,
            include_body=include_body,
            session=http_session,
            timeout=GRAPH_REQUEST_TIMEOUT_SECONDS,
        )
        if not graph_result.get("success") and search_query and graph_result.get("status_code") == 400:
            graph_result = graph_service.get_emails_graph_with_access_token(
                access_token,
                folder=folder,
                top=params["top_per_folder"],
                proxy_url=account.get("_search_proxy_url") or "",
                include_body=include_body,
                session=http_session,
                timeout=GRAPH_REQUEST_TIMEOUT_SECONDS,
            )
        transport = {
            "success": bool(graph_result.get("success")),
            "emails": graph_result.get("emails") or [],
            "method": "Graph API",
            "method_key": "graph",
            "channel": (outlook_transport.GRAPH_JUNK if folder == "junkemail" else outlook_transport.GRAPH_INBOX),
            "error": graph_result.get("error"),
        }
        if not transport.get("success"):
            errors.append(f"{folder}: 读取失败")
            continue
        last_channel = str(transport.get("channel") or "")
        folder_results, folder_scanned = _scan_messages(account, folder, transport, params, cancel_event)
        results.extend(folder_results)
        scanned_messages += folder_scanned

    if last_channel:
        preference_updates.append(
            {
                "account_id": int(account["id"]),
                "channel": last_channel,
                "new_refresh_token": token_result.get("new_refresh_token"),
            }
        )

    return {
        "account_id": int(account["id"]),
        "email": str(account.get("email") or ""),
        "results": results,
        "scanned_messages": scanned_messages,
        "errors": errors,
        "preference_updates": preference_updates,
    }


def _scan_account_legacy(
    account: Dict[str, Any],
    params: Dict[str, Any],
    cancel_event: Optional[threading.Event] = None,
) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    scanned_messages = 0
    errors: List[str] = []
    preference_updates: List[Dict[str, Any]] = []

    for folder in params["folders"]:
        if cancel_event and cancel_event.is_set():
            break
        if str(account.get("account_type") or "outlook").strip().lower() == "imap":
            transport = _generic_imap_list(
                account,
                folder,
                params["top_per_folder"],
                include_search_body="body" in set(params["fields"]),
            )
        else:
            transport = outlook_transport.list_messages(
                account,
                folder=folder,
                skip=0,
                top=params["top_per_folder"],
                proxy_url=account.get("_search_proxy_url") or "",
                include_search_body="body" in set(params["fields"]),
            )
        if not transport.get("success"):
            errors.append(f"{folder}: 读取失败")
            if transport.get("auth_expired"):
                break
            continue
        if transport.get("channel"):
            preference_updates.append(
                {
                    "account_id": int(account["id"]),
                    "channel": transport.get("channel"),
                    "new_refresh_token": transport.get("new_refresh_token"),
                }
            )
        folder_results, folder_scanned = _scan_messages(account, folder, transport, params, cancel_event)
        results.extend(folder_results)
        scanned_messages += folder_scanned

    return {
        "account_id": int(account["id"]),
        "email": str(account.get("email") or ""),
        "results": results,
        "scanned_messages": scanned_messages,
        "errors": errors,
        "preference_updates": preference_updates,
    }


def _scan_account(
    account: Dict[str, Any],
    params: Dict[str, Any],
    http_session: Optional[requests.Session] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Dict[str, Any]:
    account_type = str(account.get("account_type") or "outlook").strip().lower()
    preferred = outlook_transport.normalize_channel(account.get("preferred_verification_channel"))
    if account_type != "imap" and preferred not in {
        outlook_transport.IMAP_NEW,
        outlook_transport.IMAP_OLD,
    }:
        owned_session = http_session is None
        session = http_session or _build_http_session()
        try:
            graph_result = _scan_graph_account(account, params, session, cancel_event)
            if graph_result is not None:
                return graph_result
        finally:
            if owned_session:
                session.close()
    return _scan_account_legacy(account, params, cancel_event)


def _is_cancel_requested(job_id: str) -> bool:
    if _job_cancel_path(job_id).exists():
        return True
    try:
        return bool(get_job(job_id).get("cancel_requested"))
    except MailSearchError:
        return True


def _merge_account_result(payload: Dict[str, Any], account_result: Dict[str, Any]) -> None:
    for update in account_result["preference_updates"]:
        channel = outlook_transport.normalize_channel(update.get("channel"))
        if channel:
            accounts_repo.update_preferred_verification_channel(update["account_id"], channel)
        token = str(update.get("new_refresh_token") or "").strip()
        if token:
            accounts_repo.update_refresh_token_if_changed(update["account_id"], token)

    matches = account_result["results"]
    payload["summary"]["total_matches"] += len(matches)
    remaining = MAX_RESULTS - len(payload["results"])
    if remaining > 0:
        payload["results"].extend(matches[:remaining])
    if len(matches) > max(remaining, 0):
        payload["summary"]["truncated"] = True
    payload["summary"]["stored_results"] = len(payload["results"])
    payload["progress"]["scanned_accounts"] += 1
    payload["progress"]["scanned_messages"] += account_result["scanned_messages"]
    if account_result["errors"]:
        payload["summary"]["failed_accounts"] += 1
        if len(payload["errors"]) < 30:
            payload["errors"].append(
                {
                    "email": account_result["email"],
                    "message": "；".join(account_result["errors"]),
                }
            )


def _run_job(app: Any, job_id: str) -> None:
    path = _job_path(job_id)
    executor: Optional[ThreadPoolExecutor] = None
    http_session: Optional[requests.Session] = None
    cancel_event = threading.Event()
    try:
        with app.app_context():
            payload = get_job(job_id)
            payload["status"] = "running"
            payload["updated_at"] = time.time()
            mailbox_scope = payload["params"].get("mailbox_scope", "regular")
            accounts: List[Dict[str, Any]] = []
            temp_mailboxes: List[Dict[str, Any]] = []
            accounts_truncated = False
            temp_mailboxes_truncated = False
            if mailbox_scope in {"regular", "all"}:
                accounts, accounts_truncated = _load_accounts(payload["params"])
            if mailbox_scope in {"temp", "all"}:
                temp_mailboxes, temp_mailboxes_truncated = _load_temp_mailboxes(payload["params"])
            payload["progress"]["total_accounts"] = len(accounts) + len(temp_mailboxes)
            payload["summary"]["truncated"] = accounts_truncated or temp_mailboxes_truncated
            _atomic_write(path, payload)

            if _is_cancel_requested(job_id):
                payload["status"] = "cancelled"
                payload["updated_at"] = time.time()
                _atomic_write(path, payload)
                return

            prefetched_temp_messages: Optional[Dict[str, List[Dict[str, Any]]]] = None
            if temp_mailboxes:
                try:
                    prefetched_temp_messages = temp_emails_repo.get_temp_email_messages_for_mailboxes(
                        [str(mailbox.get("email") or "") for mailbox in temp_mailboxes],
                        limit_per_mailbox=int(payload["params"]["top_per_folder"]),
                    )
                except Exception:
                    prefetched_temp_messages = None

            for mailbox in temp_mailboxes:
                if _is_cancel_requested(job_id):
                    cancel_event.set()
                    payload["status"] = "cancelled"
                    break
                try:
                    email_key = str(mailbox.get("email") or "").casefold()
                    message_rows = None if prefetched_temp_messages is None else prefetched_temp_messages.get(email_key, [])
                    mailbox_result = _scan_temp_mailbox(
                        mailbox,
                        payload["params"],
                        cancel_event,
                        message_rows=message_rows,
                    )
                except Exception as exc:
                    payload["summary"]["failed_accounts"] += 1
                    payload["progress"]["scanned_accounts"] += 1
                    if len(payload["errors"]) < 30:
                        payload["errors"].append({"email": mailbox.get("email"), "message": type(exc).__name__})
                else:
                    _merge_account_result(payload, mailbox_result)
            payload["updated_at"] = time.time()
            _atomic_write(path, payload)

            if payload.get("status") == "cancelled":
                return

            if not accounts:
                payload["status"] = "completed"
                payload["updated_at"] = time.time()
                _atomic_write(path, payload)
                return

            http_session = _get_shared_http_session()
            max_workers = min(MAX_SEARCH_WORKERS, max(1, len(accounts)))
            executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="mail-search-scan")
            pending: Dict[Any, Dict[str, Any]] = {}
            account_iter = iter(accounts)

            def submit_next() -> bool:
                try:
                    account = next(account_iter)
                except StopIteration:
                    return False
                future = executor.submit(
                    _scan_account,
                    account,
                    payload["params"],
                    http_session,
                    cancel_event,
                )
                pending[future] = account
                return True

            for _ in range(max_workers):
                if not submit_next():
                    break

            while pending:
                if _is_cancel_requested(job_id):
                    cancel_event.set()
                    payload["status"] = "cancelled"
                    payload["updated_at"] = time.time()
                    _atomic_write(path, payload)
                    break

                done, _ = wait(tuple(pending), timeout=0.25, return_when=FIRST_COMPLETED)
                if not done:
                    continue
                for future in done:
                    pending.pop(future, None)
                    try:
                        account_result = future.result()
                    except Exception as exc:
                        payload["summary"]["failed_accounts"] += 1
                        payload["progress"]["scanned_accounts"] += 1
                        if len(payload["errors"]) < 30:
                            payload["errors"].append({"message": type(exc).__name__})
                    else:
                        _merge_account_result(payload, account_result)
                    payload["updated_at"] = time.time()
                    _atomic_write(path, payload)
                    if not cancel_event.is_set() and not _is_cancel_requested(job_id):
                        submit_next()

            if payload.get("status") != "cancelled":
                payload["status"] = "completed"
            payload["updated_at"] = time.time()
            _atomic_write(path, payload)
    except Exception as exc:
        try:
            payload = get_job(job_id)
        except MailSearchError:
            payload = {"job_id": job_id, "results": [], "errors": []}
        payload["status"] = "failed"
        payload["error"] = type(exc).__name__
        payload["updated_at"] = time.time()
        _atomic_write(path, payload)
    finally:
        if executor is not None:
            executor.shutdown(wait=not cancel_event.is_set(), cancel_futures=cancel_event.is_set())
