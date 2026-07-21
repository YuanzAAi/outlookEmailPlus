from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from outlook_web.db import get_db

_TEMP_EMAIL_RICH_KEYS = (
    "attachments",
    "inline_attachments",
    "inlineAttachments",
    "inline_images",
    "inlineImages",
    "resources",
    "images",
    "cid_map",
    "cidMap",
)

TEMP_MAIL_KIND = "temp"
TEMP_MAIL_READ_CAPABILITY = "temp_provider"
DEFAULT_TEMP_MAIL_SOURCE = "custom_domain_temp_mail"
ACCOUNT_BACKED_TEMP_MAIL_SOURCE = "cloudflare_account_temp_mail"
LEGACY_TEMP_MAIL_SOURCE = "legacy_gptmail"
DEFAULT_TEMP_MAIL_PROVIDER_NAME = "custom_domain_temp_mail"
LEGACY_TEMP_MAIL_PROVIDER_NAME = "legacy_bridge"

DEFAULT_PROVIDER_CAPABILITIES = {
    "delete_mailbox": False,
    "delete_message": True,
    "clear_messages": True,
    "send_message": False,
    "list_sent_messages": False,
    "delete_sent_message": False,
    "clear_sent_messages": False,
}


def _serialize_temp_email_payload(message: Dict[str, Any]) -> str:
    try:
        return json.dumps(message or {}, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return str(message or "")


def _load_temp_email_payload(raw_content: Any) -> Dict[str, Any]:
    if isinstance(raw_content, dict):
        return raw_content
    if not isinstance(raw_content, str) or not raw_content.strip():
        return {}
    try:
        payload = json.loads(raw_content)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _score_temp_email_payload(payload: Any) -> int:
    payload_dict = _load_temp_email_payload(payload)
    if not payload_dict:
        return 0

    score = 0
    if str(payload_dict.get("html_content") or payload_dict.get("body_html") or "").strip():
        score += 20
    for key in _TEMP_EMAIL_RICH_KEYS:
        value = payload_dict.get(key)
        if isinstance(value, dict) and value:
            score += 30
        elif isinstance(value, list) and value:
            score += 30
    score += min(len(payload_dict), 20)
    return score


def _choose_richer_temp_email_payload(existing_payload: Any, incoming_payload: Any) -> str:
    existing_score = _score_temp_email_payload(existing_payload)
    incoming_score = _score_temp_email_payload(incoming_payload)
    if incoming_score >= existing_score:
        normalized = _load_temp_email_payload(incoming_payload) or incoming_payload
        return _serialize_temp_email_payload(normalized)
    normalized = _load_temp_email_payload(existing_payload) or existing_payload
    return _serialize_temp_email_payload(normalized)


def _default_provider_name_for_source(source: str | None) -> str:
    normalized_source = str(source or "").strip().lower()
    if normalized_source == LEGACY_TEMP_MAIL_SOURCE:
        return LEGACY_TEMP_MAIL_PROVIDER_NAME
    return DEFAULT_TEMP_MAIL_PROVIDER_NAME


def deserialize_temp_email_meta(raw_meta: Any, *, source: str | None = None) -> Dict[str, Any]:
    if isinstance(raw_meta, dict):
        meta = dict(raw_meta)
    elif isinstance(raw_meta, str) and raw_meta.strip():
        try:
            parsed = json.loads(raw_meta)
            meta = parsed if isinstance(parsed, dict) else {}
        except Exception:
            meta = {}
    else:
        meta = {}

    provider_capabilities = meta.get("provider_capabilities")
    if not isinstance(provider_capabilities, dict):
        provider_capabilities = {}

    provider_debug = meta.get("provider_debug")
    if not isinstance(provider_debug, dict):
        provider_debug = {}

    if str(source or "").strip().lower() == LEGACY_TEMP_MAIL_SOURCE and not provider_debug.get("bridge"):
        provider_debug["bridge"] = "gptmail"

    provider_labels = meta.get("provider_labels")
    if not isinstance(provider_labels, list):
        provider_labels = []

    normalized = {
        "provider_name": str(meta.get("provider_name") or _default_provider_name_for_source(source)).strip()
        or _default_provider_name_for_source(source),
        "provider_mailbox_id": str(meta.get("provider_mailbox_id") or "").strip(),
        "provider_jwt": str(meta.get("provider_jwt") or "").strip(),
        "provider_cursor": str(meta.get("provider_cursor") or "").strip(),
        "provider_labels": [str(item).strip() for item in provider_labels if str(item or "").strip()],
        "provider_capabilities": {
            "delete_mailbox": bool(
                provider_capabilities.get("delete_mailbox", DEFAULT_PROVIDER_CAPABILITIES["delete_mailbox"])
            ),
            "delete_message": bool(
                provider_capabilities.get("delete_message", DEFAULT_PROVIDER_CAPABILITIES["delete_message"])
            ),
            "clear_messages": bool(
                provider_capabilities.get("clear_messages", DEFAULT_PROVIDER_CAPABILITIES["clear_messages"])
            ),
            "send_message": bool(provider_capabilities.get("send_message", DEFAULT_PROVIDER_CAPABILITIES["send_message"])),
            "list_sent_messages": bool(
                provider_capabilities.get("list_sent_messages", DEFAULT_PROVIDER_CAPABILITIES["list_sent_messages"])
            ),
            "delete_sent_message": bool(
                provider_capabilities.get("delete_sent_message", DEFAULT_PROVIDER_CAPABILITIES["delete_sent_message"])
            ),
            "clear_sent_messages": bool(
                provider_capabilities.get("clear_sent_messages", DEFAULT_PROVIDER_CAPABILITIES["clear_sent_messages"])
            ),
        },
        "provider_debug": provider_debug,
    }
    return normalized


def serialize_temp_email_meta(meta: Any, *, source: str | None = None) -> str:
    normalized = deserialize_temp_email_meta(meta, source=source)
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))


def merge_temp_email_meta(
    existing_meta: Any,
    incoming_meta: Any,
    *,
    source: str | None = None,
    provider_name: Optional[str] = None,
) -> Dict[str, Any]:
    """合并 Provider 元数据，避免空凭据覆盖既有有效值。"""
    existing = deserialize_temp_email_meta(existing_meta, source=source)
    incoming = deserialize_temp_email_meta(incoming_meta, source=source)
    merged = dict(existing)
    merged["provider_name"] = str(provider_name or incoming.get("provider_name") or existing.get("provider_name") or "")
    for key in ("provider_mailbox_id", "provider_jwt", "provider_cursor"):
        incoming_value = str(incoming.get(key) or "").strip()
        if incoming_value:
            merged[key] = incoming_value
    if incoming.get("provider_labels"):
        merged["provider_labels"] = incoming["provider_labels"]
    merged["provider_capabilities"] = {
        **(existing.get("provider_capabilities") or {}),
        **(incoming.get("provider_capabilities") or {}),
    }
    merged["provider_debug"] = {
        **(existing.get("provider_debug") or {}),
        **(incoming.get("provider_debug") or {}),
    }
    return merged


def get_temp_email_group_id() -> int:
    """获取临时邮箱分组的 ID"""
    db = get_db()
    cursor = db.execute("SELECT id FROM groups WHERE name = '临时邮箱'")
    row = cursor.fetchone()
    return row["id"] if row else 2


def _serialize_temp_email_row(row: Any) -> Dict[str, Any]:
    if not row:
        return {}
    item = dict(row)
    item["visible_in_ui"] = bool(item.get("visible_in_ui", 0))
    item["created_by"] = "task" if str(item.get("mailbox_type") or "").strip().lower() == "task" else "user"
    item["meta_json"] = deserialize_temp_email_meta(item.get("meta_json"), source=item.get("source"))
    item["provider_name"] = str(
        item["meta_json"].get("provider_name") or _default_provider_name_for_source(item.get("source"))
    )
    item["tags"] = get_temp_email_tags(int(item.get("id") or 0)) if item.get("id") else []
    return item


def build_temp_mailbox_descriptor(record: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _serialize_temp_email_row(record)
    email_addr = str(normalized.get("email") or "").strip()
    prefix = str(normalized.get("prefix") or (email_addr.split("@", 1)[0] if "@" in email_addr else "")).strip()
    domain = str(normalized.get("domain") or (email_addr.split("@", 1)[1] if "@" in email_addr else "")).strip()
    return {
        "kind": TEMP_MAIL_KIND,
        "email": email_addr,
        "source": str(normalized.get("source") or DEFAULT_TEMP_MAIL_SOURCE),
        "provider_name": str(normalized.get("provider_name") or _default_provider_name_for_source(normalized.get("source"))),
        "mailbox_type": str(normalized.get("mailbox_type") or "user").strip().lower() or "user",
        "visible_in_ui": bool(normalized.get("visible_in_ui")),
        "status": str(normalized.get("status") or "active").strip().lower() or "active",
        "prefix": prefix,
        "domain": domain,
        "task_token": str(normalized.get("task_token") or "").strip(),
        "consumer_key": str(normalized.get("consumer_key") or "").strip(),
        "caller_id": str(normalized.get("caller_id") or "").strip(),
        "task_id": str(normalized.get("task_id") or "").strip(),
        "group_id": normalized.get("group_id"),
        "created_at": str(normalized.get("created_at") or ""),
        "updated_at": str(normalized.get("updated_at") or ""),
        "finished_at": str(normalized.get("finished_at") or ""),
        "read_capability": TEMP_MAIL_READ_CAPABILITY,
        "meta": dict(normalized.get("meta_json") or {}),
        "record": normalized,
    }


def build_temp_mailbox_public_dto(record: Dict[str, Any]) -> Dict[str, Any]:
    descriptor = build_temp_mailbox_descriptor(record)
    stored_record = descriptor.get("record") or {}
    return {
        "email": descriptor["email"],
        "prefix": descriptor["prefix"],
        "domain": descriptor["domain"],
        "source": descriptor["source"],
        "mailbox_type": descriptor["mailbox_type"],
        "visible_in_ui": descriptor["visible_in_ui"],
        "status": descriptor["status"],
        "created_at": descriptor["created_at"],
        "task_token": descriptor["task_token"],
        "provider_name": descriptor["provider_name"],
        "capabilities": dict((descriptor.get("meta") or {}).get("provider_capabilities") or {}),
        "group_id": stored_record.get("group_id"),
        "tags": list(stored_record.get("tags") or []),
        "latest_message_at": int(stored_record.get("latest_message_at") or 0),
        "message_count": int(stored_record.get("message_count") or 0),
    }


def get_temp_email_tags(temp_email_id: int) -> List[Dict[str, Any]]:
    if temp_email_id <= 0:
        return []
    db = get_db()
    rows = db.execute(
        """
        SELECT t.* FROM tags t
        JOIN temp_email_tags tet ON tet.tag_id = t.id
        WHERE tet.temp_email_id = ?
        ORDER BY t.created_at DESC
        """,
        (temp_email_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def update_temp_email_organization(email_addr: str, *, group_id: Optional[int], tag_ids: List[int]) -> bool:
    db = get_db()
    row = db.execute("SELECT id FROM temp_emails WHERE email = ? COLLATE NOCASE", (email_addr,)).fetchone()
    if not row:
        return False
    temp_email_id = int(row["id"])
    db.execute("UPDATE temp_emails SET group_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (group_id, temp_email_id))
    db.execute("DELETE FROM temp_email_tags WHERE temp_email_id = ?", (temp_email_id,))
    for tag_id in sorted(set(int(value) for value in tag_ids if int(value) > 0)):
        db.execute("INSERT OR IGNORE INTO temp_email_tags (temp_email_id, tag_id) VALUES (?, ?)", (temp_email_id, tag_id))
    db.commit()
    return True


def get_visible_temp_email_counts_by_group() -> Dict[int, int]:
    db = get_db()
    rows = db.execute(
        """
        SELECT group_id, COUNT(*) AS count
        FROM temp_emails
        WHERE visible_in_ui = 1 AND group_id IS NOT NULL
        GROUP BY group_id
        """
    ).fetchall()
    return {int(row["group_id"]): int(row["count"] or 0) for row in rows}


def load_temp_emails(
    *,
    visible_only: bool = False,
    mailbox_type: Optional[str] = None,
    status: Optional[str] = None,
    consumer_key: Optional[str] = None,
    view: str = "record",
    order_by_latest_message: bool = False,
) -> List[Dict]:
    """加载临时邮箱，支持按可见性/类型/状态/调用方归属筛选。"""
    db = get_db()
    clauses: list[str] = []
    params: list[Any] = []
    if visible_only:
        clauses.append("te.visible_in_ui = 1")
    if mailbox_type:
        clauses.append("te.mailbox_type = ?")
        params.append(str(mailbox_type).strip())
    if status:
        clauses.append("te.status = ?")
        params.append(str(status).strip())
    if consumer_key:
        clauses.append("te.consumer_key = ?")
        params.append(str(consumer_key).strip())
    if order_by_latest_message:
        sql = """
            SELECT
                te.*,
                COALESCE(message_stats.latest_message_at, 0) AS latest_message_at,
                COALESCE(message_stats.message_count, 0) AS message_count
            FROM temp_emails AS te
            LEFT JOIN (
                SELECT
                    LOWER(email_address) AS email_key,
                    MAX(
                        COALESCE(
                            NULLIF(timestamp, 0),
                            CAST(strftime('%s', created_at) AS INTEGER),
                            0
                        )
                    ) AS latest_message_at,
                    COUNT(*) AS message_count
                FROM temp_email_messages
                GROUP BY LOWER(email_address)
            ) AS message_stats ON message_stats.email_key = LOWER(te.email)
        """
    else:
        sql = "SELECT te.* FROM temp_emails AS te"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    if order_by_latest_message:
        sql += """
            ORDER BY
                CASE WHEN COALESCE(message_stats.message_count, 0) > 0 THEN 0 ELSE 1 END,
                COALESCE(message_stats.latest_message_at, 0) DESC,
                te.created_at DESC,
                te.id DESC
        """
    else:
        sql += " ORDER BY te.created_at DESC, te.id DESC"
    cursor = db.execute(sql, params)
    rows = cursor.fetchall()
    serialized = [_serialize_temp_email_row(row) for row in rows]
    if view == "descriptor":
        return [build_temp_mailbox_descriptor(row) for row in serialized]
    if view == "public":
        return [build_temp_mailbox_public_dto(row) for row in serialized]
    return serialized


def get_temp_email_by_address(email_addr: str, *, view: str = "record") -> Optional[Dict]:
    """根据邮箱地址获取临时邮箱"""
    db = get_db()
    cursor = db.execute("SELECT * FROM temp_emails WHERE email = ? COLLATE NOCASE", (email_addr,))
    row = cursor.fetchone()
    if not row:
        return None
    serialized = _serialize_temp_email_row(row)
    if view == "descriptor":
        return build_temp_mailbox_descriptor(serialized)
    if view == "public":
        return build_temp_mailbox_public_dto(serialized)
    return serialized


def get_temp_email_by_task_token(task_token: str, *, view: str = "record") -> Optional[Dict]:
    db = get_db()
    cursor = db.execute("SELECT * FROM temp_emails WHERE task_token = ?", (task_token,))
    row = cursor.fetchone()
    if not row:
        return None
    serialized = _serialize_temp_email_row(row)
    if view == "descriptor":
        return build_temp_mailbox_descriptor(serialized)
    if view == "public":
        return build_temp_mailbox_public_dto(serialized)
    return serialized


def create_temp_email(
    *,
    email_addr: str,
    mailbox_type: str = "user",
    visible_in_ui: bool = True,
    source: str = "custom_domain_temp_mail",
    prefix: Optional[str] = None,
    domain: Optional[str] = None,
    task_token: Optional[str] = None,
    consumer_key: Optional[str] = None,
    caller_id: Optional[str] = None,
    task_id: Optional[str] = None,
    meta_json: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
    provider_name: Optional[str] = None,
    status: str = "active",
) -> bool:
    """创建临时邮箱记录。"""
    db = get_db()
    normalized_email = str(email_addr or "").strip()
    normalized_prefix = (
        prefix if prefix is not None else (normalized_email.split("@", 1)[0] if "@" in normalized_email else None)
    )
    normalized_domain = (
        domain if domain is not None else (normalized_email.split("@", 1)[1] if "@" in normalized_email else None)
    )
    normalized_source = str(source or DEFAULT_TEMP_MAIL_SOURCE).strip() or DEFAULT_TEMP_MAIL_SOURCE
    if get_temp_email_by_address(normalized_email):
        return False
    normalized_meta_source = meta if meta is not None else meta_json
    normalized_meta_json = serialize_temp_email_meta(
        normalized_meta_source,
        source=normalized_source,
    )
    if provider_name:
        normalized_meta = deserialize_temp_email_meta(normalized_meta_json, source=normalized_source)
        normalized_meta["provider_name"] = str(provider_name).strip() or _default_provider_name_for_source(normalized_source)
        normalized_meta_json = serialize_temp_email_meta(normalized_meta, source=normalized_source)
    try:
        db.execute(
            """
            INSERT INTO temp_emails (
                email, status, mailbox_type, visible_in_ui, source, prefix, domain,
                task_token, consumer_key, caller_id, task_id, meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_email,
                str(status or "active").strip() or "active",
                str(mailbox_type or "user").strip() or "user",
                1 if visible_in_ui else 0,
                normalized_source,
                normalized_prefix,
                normalized_domain,
                str(task_token or "").strip() or None,
                str(consumer_key or "").strip() or None,
                str(caller_id or "").strip() or None,
                str(task_id or "").strip() or None,
                normalized_meta_json,
            ),
        )
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def update_temp_email_provider_meta(
    email_addr: str,
    meta: Dict[str, Any],
    *,
    provider_name: Optional[str] = None,
) -> bool:
    """合并 Provider 元数据，空凭据不会覆盖既有有效值。"""
    record = get_temp_email_by_address(email_addr)
    if not record:
        return False

    source = str(record.get("source") or DEFAULT_TEMP_MAIL_SOURCE)
    merged = merge_temp_email_meta(
        record.get("meta_json"),
        meta,
        source=source,
        provider_name=provider_name,
    )

    db = get_db()
    cursor = db.execute(
        """
        UPDATE temp_emails
        SET meta_json = ?, updated_at = CURRENT_TIMESTAMP
        WHERE email = ? COLLATE NOCASE
        """,
        (serialize_temp_email_meta(merged, source=source), email_addr),
    )
    db.commit()
    return cursor.rowcount > 0


def ensure_account_backed_temp_email(
    email_addr: str,
    meta: Dict[str, Any],
    *,
    provider_name: Optional[str] = None,
) -> Dict[str, Any]:
    """为 accounts 中的动态临时邮箱确保一个隐藏的消息父记录。"""
    normalized_email = str(email_addr or "").strip()
    if not normalized_email or "@" not in normalized_email:
        return {}

    db = get_db()
    existing = get_temp_email_by_address(normalized_email)
    if existing and str(existing.get("mailbox_type") or "").strip().lower() == "task":
        return {}

    if existing:
        existing_source = str(existing.get("source") or "").strip().lower()
        existing_provider = (
            str(existing.get("provider_name") or (existing.get("meta_json") or {}).get("provider_name") or "").strip().lower()
        )
        # 不接管同地址的普通临时邮箱；只有既有记录本身已标记为 CF，
        # 或明确是账号型隐藏父记录时，才允许合并历史重复数据。
        if existing_source != ACCOUNT_BACKED_TEMP_MAIL_SOURCE and existing_provider != "cloudflare_temp_mail":
            return {}
        merged = merge_temp_email_meta(
            existing.get("meta_json"),
            meta,
            source=ACCOUNT_BACKED_TEMP_MAIL_SOURCE,
            provider_name=provider_name,
        )
        db.execute(
            """
            UPDATE temp_emails
            SET mailbox_type = 'user', visible_in_ui = 0,
                source = ?, meta_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE email = ? COLLATE NOCASE
            """,
            (
                ACCOUNT_BACKED_TEMP_MAIL_SOURCE,
                serialize_temp_email_meta(merged, source=ACCOUNT_BACKED_TEMP_MAIL_SOURCE),
                normalized_email,
            ),
        )
    else:
        prefix, domain = normalized_email.rsplit("@", 1)
        normalized_meta = merge_temp_email_meta(
            {},
            meta,
            source=ACCOUNT_BACKED_TEMP_MAIL_SOURCE,
            provider_name=provider_name,
        )
        cursor = db.execute(
            """
            INSERT OR IGNORE INTO temp_emails (
                email, status, mailbox_type, visible_in_ui, source, prefix, domain,
                task_token, consumer_key, caller_id, task_id, meta_json
            )
            VALUES (?, 'active', 'user', 0, ?, ?, ?, NULL, NULL, NULL, NULL, ?)
            """,
            (
                normalized_email,
                ACCOUNT_BACKED_TEMP_MAIL_SOURCE,
                prefix,
                domain,
                serialize_temp_email_meta(normalized_meta, source=ACCOUNT_BACKED_TEMP_MAIL_SOURCE),
            ),
        )
        if cursor.rowcount == 0:
            raced = get_temp_email_by_address(normalized_email)
            if not raced or str(raced.get("mailbox_type") or "").strip().lower() == "task":
                db.rollback()
                return {}
            merged = merge_temp_email_meta(
                raced.get("meta_json"),
                meta,
                source=ACCOUNT_BACKED_TEMP_MAIL_SOURCE,
                provider_name=provider_name,
            )
            db.execute(
                """
                UPDATE temp_emails
                SET mailbox_type = 'user', visible_in_ui = 0,
                    source = ?, meta_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE email = ? COLLATE NOCASE
                """,
                (
                    ACCOUNT_BACKED_TEMP_MAIL_SOURCE,
                    serialize_temp_email_meta(merged, source=ACCOUNT_BACKED_TEMP_MAIL_SOURCE),
                    normalized_email,
                ),
            )
    db.commit()
    return get_temp_email_by_address(normalized_email, view="record") or {}


def add_temp_email(email_addr: str) -> bool:
    """兼容旧调用：添加用户可见临时邮箱。"""
    return create_temp_email(email_addr=email_addr)


def finish_task_temp_email(task_token: str, *, result_status: str = "finished") -> bool:
    db = get_db()
    cursor = db.execute(
        """
        UPDATE temp_emails
        SET status = ?, finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE task_token = ? AND mailbox_type = 'task'
        """,
        (str(result_status or "finished").strip() or "finished", task_token),
    )
    db.commit()
    return cursor.rowcount > 0


def delete_temp_email(email_addr: str) -> bool:
    """删除临时邮箱及其所有邮件"""
    db = get_db()
    try:
        row = db.execute("SELECT id FROM temp_emails WHERE email = ? COLLATE NOCASE", (email_addr,)).fetchone()
        if row:
            db.execute("DELETE FROM temp_email_tags WHERE temp_email_id = ?", (int(row["id"]),))
        db.execute("DELETE FROM temp_email_messages WHERE email_address = ? COLLATE NOCASE", (email_addr,))
        db.execute("DELETE FROM temp_emails WHERE email = ? COLLATE NOCASE", (email_addr,))
        db.commit()
        return True
    except Exception:
        return False


def save_temp_email_messages(email_addr: str, messages: List[Dict]) -> int:
    """保存临时邮件到数据库"""
    db = get_db()
    saved = 0
    for msg in messages:
        try:
            message_id = str(msg.get("id") or "").strip()
            if not message_id:
                continue

            existing = get_temp_email_message_by_id(message_id, email_addr=email_addr)
            content = str(msg.get("content") or msg.get("body_text") or "")
            html_content = str(msg.get("html_content") or msg.get("body_html") or "")
            from_address = str(
                msg.get("from_address")
                or msg.get("source")  # CF Worker 字段名
                or msg.get("from")  # Graph API 风格
                or msg.get("sender")  # 其他常见格式
                or ""
            )
            subject = str(msg.get("subject") or "")
            _ts_raw = msg.get("timestamp") or msg.get("created_at")
            if isinstance(_ts_raw, str):
                from datetime import datetime as _dt

                try:
                    _ts_clean = _ts_raw.replace("Z", "+00:00").replace(".000", "")
                    timestamp = int(_dt.fromisoformat(_ts_clean).timestamp())
                except (ValueError, AttributeError):
                    timestamp = 0
            else:
                timestamp = int(_ts_raw or 0)
            raw_content = _serialize_temp_email_payload(msg)

            if existing:
                if not content:
                    content = str(existing.get("content") or "")
                if not html_content:
                    html_content = str(existing.get("html_content") or "")
                if not from_address:
                    from_address = str(existing.get("from_address") or "")
                if not subject:
                    subject = str(existing.get("subject") or "")
                if not timestamp:
                    timestamp = existing.get("timestamp", 0)
                raw_content = _choose_richer_temp_email_payload(existing.get("raw_content"), msg)

            has_html = bool(msg.get("has_html") or html_content or (existing and existing.get("has_html")))
            db.execute(
                """
                INSERT OR REPLACE INTO temp_email_messages
                (message_id, email_address, from_address, subject, content, html_content, has_html, timestamp, raw_content)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    email_addr,
                    from_address,
                    subject,
                    content,
                    html_content,
                    1 if has_html else 0,
                    timestamp,
                    raw_content,
                ),
            )
            saved += 1
        except Exception:
            continue
    db.commit()
    return saved


def get_temp_email_messages(email_addr: str) -> List[Dict]:
    """获取临时邮箱的所有邮件（从数据库）"""
    db = get_db()
    cursor = db.execute(
        """
        SELECT * FROM temp_email_messages
        WHERE email_address = ? COLLATE NOCASE
        ORDER BY timestamp DESC
        """,
        (email_addr,),
    )
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_temp_email_messages_for_mailboxes(
    email_addresses: List[str],
    *,
    limit_per_mailbox: int,
) -> Dict[str, List[Dict]]:
    """一次读取多个临时邮箱最近的邮件，返回以小写邮箱为键的分组结果。"""
    normalized = list(dict.fromkeys(str(item or "").strip() for item in email_addresses if str(item or "").strip()))
    grouped: Dict[str, List[Dict]] = {email.casefold(): [] for email in normalized}
    if not normalized:
        return grouped

    limit = max(1, int(limit_per_mailbox))
    placeholders = ",".join("?" for _ in normalized)
    db = get_db()
    rows = db.execute(
        f"""
        WITH ranked_messages AS (
            SELECT
                messages.*,
                LOWER(messages.email_address) AS email_key,
                ROW_NUMBER() OVER (
                    PARTITION BY LOWER(messages.email_address)
                    ORDER BY
                        COALESCE(messages.timestamp, 0) DESC,
                        messages.created_at DESC,
                        messages.id DESC
                ) AS row_number
            FROM temp_email_messages AS messages
            WHERE messages.email_address COLLATE NOCASE IN ({placeholders})
        )
        SELECT * FROM ranked_messages
        WHERE row_number <= ?
        ORDER BY email_key, COALESCE(timestamp, 0) DESC, created_at DESC, id DESC
        """,
        (*normalized, limit),
    ).fetchall()
    for row in rows:
        item = dict(row)
        grouped.setdefault(str(item.get("email_address") or "").casefold(), []).append(item)
    return grouped


def get_temp_email_message_by_id(message_id: str, *, email_addr: Optional[str] = None) -> Optional[Dict]:
    """根据消息 ID 获取临时邮件，优先按邮箱地址定位。"""
    db = get_db()
    if email_addr:
        cursor = db.execute(
            """
            SELECT * FROM temp_email_messages
            WHERE email_address = ? COLLATE NOCASE AND message_id = ?
            LIMIT 1
            """,
            (email_addr, message_id),
        )
    else:
        cursor = db.execute(
            """
            SELECT * FROM temp_email_messages
            WHERE message_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (message_id,),
        )
    row = cursor.fetchone()
    return dict(row) if row else None


def delete_temp_email_message(message_id: str, *, email_addr: Optional[str] = None) -> bool:
    """删除临时邮件，提供邮箱地址时仅删除目标邮箱下的消息。"""
    db = get_db()
    try:
        if email_addr:
            db.execute(
                "DELETE FROM temp_email_messages WHERE email_address = ? COLLATE NOCASE AND message_id = ?",
                (email_addr, message_id),
            )
        else:
            db.execute("DELETE FROM temp_email_messages WHERE message_id = ?", (message_id,))
        db.commit()
        return True
    except Exception:
        return False


def get_temp_email_count(*, visible_only: bool = False) -> int:
    """获取临时邮箱数量。"""
    db = get_db()
    if visible_only:
        cursor = db.execute("SELECT COUNT(*) as count FROM temp_emails WHERE visible_in_ui = 1")
    else:
        cursor = db.execute("SELECT COUNT(*) as count FROM temp_emails")
    row = cursor.fetchone()
    return row["count"] if row else 0
