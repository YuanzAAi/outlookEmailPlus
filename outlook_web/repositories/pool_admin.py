from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from outlook_web.repositories import pool as pool_repo
from outlook_web.repositories.temp_emails import ACCOUNT_BACKED_TEMP_MAIL_SOURCE


def _unified_pool_cte() -> str:
    return f"""
        WITH unified AS (
            SELECT
                a.id AS id,
                'account' AS resource_type,
                a.email AS email,
                a.provider AS provider,
                a.account_type AS account_type,
                a.status AS status,
                a.pool_status AS pool_status,
                a.claimed_by AS claimed_by,
                a.claimed_at AS claimed_at,
                a.lease_expires_at AS lease_expires_at,
                a.last_result AS last_result,
                a.last_result_detail AS last_result_detail,
                a.group_id AS group_id,
                a.remark AS remark,
                a.email_domain AS email_domain,
                a.created_at AS created_at,
                a.updated_at AS updated_at,
                g.name AS group_name,
                g.color AS group_color,
                CASE WHEN a.pool_status IS NULL THEN 0 ELSE 1 END AS in_pool
            FROM accounts a
            LEFT JOIN groups g ON a.group_id = g.id

            UNION ALL

            SELECT
                te.id + {pool_repo.TEMP_POOL_ID_OFFSET} AS id,
                'temp' AS resource_type,
                te.email AS email,
                COALESCE(
                    CASE
                        WHEN json_valid(COALESCE(te.meta_json, ''))
                        THEN NULLIF(json_extract(te.meta_json, '$.provider_name'), '')
                    END,
                    NULLIF(te.source, ''),
                    'temp_mail'
                ) AS provider,
                'temp_mail' AS account_type,
                te.status AS status,
                COALESCE(te.pool_status, 'available') AS pool_status,
                te.claimed_by AS claimed_by,
                te.claimed_at AS claimed_at,
                te.lease_expires_at AS lease_expires_at,
                te.last_result AS last_result,
                NULL AS last_result_detail,
                tg.id AS group_id,
                '' AS remark,
                COALESCE(NULLIF(te.domain, ''), substr(te.email, instr(te.email, '@') + 1)) AS email_domain,
                te.created_at AS created_at,
                te.updated_at AS updated_at,
                tg.name AS group_name,
                tg.color AS group_color,
                CASE WHEN COALESCE(te.pool_status, 'available') = 'retired' THEN 0 ELSE 1 END AS in_pool
            FROM temp_emails te
            LEFT JOIN groups tg ON tg.name = '临时邮箱'
            WHERE COALESCE(te.status, 'active') = 'active'
              AND COALESCE(te.mailbox_type, 'user') = 'user'
              AND COALESCE(te.source, '') != '{ACCOUNT_BACKED_TEMP_MAIL_SOURCE}'
        )
    """


def list_accounts(
    conn: sqlite3.Connection,
    *,
    in_pool: str = "all",
    pool_status: Optional[str] = None,
    provider: Optional[str] = None,
    group_id: Optional[int] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    """号池管理专用查询：返回账号列表与分页信息。

    参数:
        in_pool: "true" | "false" | "all"
        pool_status: 精确匹配池状态（如 claimed / available / cooldown / used / frozen / retired）
        provider: 精确匹配 provider
        group_id: 精确匹配 group_id
        search: 模糊匹配 email / remark / email_domain
        page: 页码（从 1 开始）
        page_size: 每页条数
    """
    where_clauses: List[str] = []
    params: List[Any] = []

    normalized_in_pool = str(in_pool or "all").strip().lower()
    if normalized_in_pool == "true":
        where_clauses.append("u.in_pool = 1")
    elif normalized_in_pool == "false":
        where_clauses.append("u.in_pool = 0")

    if pool_status:
        where_clauses.append("u.pool_status = ?")
        params.append(pool_status)

    if provider:
        where_clauses.append("u.provider = ?")
        params.append(provider)

    if group_id is not None:
        where_clauses.append("u.group_id = ?")
        params.append(group_id)

    normalized_search = str(search or "").strip().lower()
    if normalized_search:
        like_value = f"%{normalized_search}%"
        where_clauses.append("""
            (
                LOWER(COALESCE(u.email, '')) LIKE ?
                OR LOWER(COALESCE(u.remark, '')) LIKE ?
                OR LOWER(COALESCE(u.email_domain, '')) LIKE ?
            )
            """)
        params.extend([like_value, like_value, like_value])

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    cte = _unified_pool_cte()

    # 总数
    total_row = conn.execute(
        f"""
        {cte}
        SELECT COUNT(*) AS total_count
        FROM unified u
        {where_sql}
        """,
        params,
    ).fetchone()
    total_count = int(total_row["total_count"] or 0) if total_row else 0

    normalized_page = max(1, int(page or 1))
    normalized_page_size = max(1, int(page_size or 50))
    total_pages = (total_count + normalized_page_size - 1) // normalized_page_size if total_count > 0 else 1
    effective_page = min(normalized_page, total_pages)
    offset = (effective_page - 1) * normalized_page_size

    rows = conn.execute(
        f"""
        {cte}
        SELECT
            u.*
        FROM unified u
        {where_sql}
        ORDER BY u.updated_at DESC, u.id DESC
        LIMIT ? OFFSET ?
        """,
        [*params, normalized_page_size, offset],
    ).fetchall()

    items: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        # 确保前端拿到的是 None 而不是空字符串（保持语义一致）
        for key in ("pool_status", "claimed_by", "claimed_at", "lease_expires_at", "last_result", "last_result_detail"):
            if item.get(key) == "":
                item[key] = None
        item["in_pool"] = bool(item.get("in_pool"))
        items.append(item)

    return {
        "items": items,
        "total": total_count,
        "page": effective_page,
        "page_size": normalized_page_size,
        "total_pages": total_pages,
    }


def get_account_pool_status(conn: sqlite3.Connection, account_id: int) -> Optional[str]:
    """返回账号当前 pool_status（None 表示池外）。"""
    resource = get_pool_resource(conn, account_id)
    return resource.get("pool_status") if resource else None


def get_pool_resource(conn: sqlite3.Connection, account_id: int) -> Optional[Dict[str, Any]]:
    if pool_repo.is_temp_pool_account_id(account_id):
        temp_id = pool_repo.temp_id_from_account_id(account_id)
        row = conn.execute(
            """
            SELECT id, email, pool_status
            FROM temp_emails
            WHERE id = ?
              AND COALESCE(status, 'active') = 'active'
              AND COALESCE(mailbox_type, 'user') = 'user'
              AND COALESCE(source, '') != ?
            """,
            (temp_id, ACCOUNT_BACKED_TEMP_MAIL_SOURCE),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": account_id,
            "email": row["email"],
            "pool_status": row["pool_status"] or "available",
            "resource_type": "temp",
            "storage_id": temp_id,
        }

    row = conn.execute(
        "SELECT id, email, pool_status FROM accounts WHERE id = ?",
        (account_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "email": row["email"],
        "pool_status": row["pool_status"],
        "resource_type": "account",
        "storage_id": int(row["id"]),
    }


def update_pool_status(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    new_pool_status: Optional[str],
) -> None:
    """更新账号 pool_status，同时更新 updated_at。

    当 new_pool_status 为 None（移出号池）时，顺带清理 claim 相关字段。
    """
    from datetime import datetime, timezone

    now_str = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    if pool_repo.is_temp_pool_account_id(account_id):
        temp_id = pool_repo.temp_id_from_account_id(account_id)
        if new_pool_status is None:
            new_pool_status = "retired"
        conn.execute(
            """
            UPDATE temp_emails SET
                pool_status = ?,
                claimed_by = CASE WHEN ? = 'retired' THEN NULL ELSE claimed_by END,
                claimed_at = CASE WHEN ? = 'retired' THEN NULL ELSE claimed_at END,
                lease_expires_at = CASE WHEN ? = 'retired' THEN NULL ELSE lease_expires_at END,
                claim_token = CASE WHEN ? = 'retired' THEN NULL ELSE claim_token END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                new_pool_status,
                new_pool_status,
                new_pool_status,
                new_pool_status,
                new_pool_status,
                now_str,
                temp_id,
            ),
        )
        conn.commit()
        return

    if new_pool_status is None:
        conn.execute(
            """
            UPDATE accounts SET
                pool_status = NULL,
                claimed_by = NULL,
                claimed_at = NULL,
                lease_expires_at = NULL,
                claim_token = NULL,
                claimed_project_key = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (now_str, account_id),
        )
    else:
        conn.execute(
            """
            UPDATE accounts SET
                pool_status = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (new_pool_status, now_str, account_id),
        )
    conn.commit()


def force_release(conn: sqlite3.Connection, *, account_id: int) -> None:
    """强制释放 claimed 账号：将状态置为 available，并清空 claim 上下文。

    调用方（Service 层）应确保当前状态为 claimed。
    """
    from datetime import datetime, timezone

    now_str = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    if pool_repo.is_temp_pool_account_id(account_id):
        temp_id = pool_repo.temp_id_from_account_id(account_id)
        conn.execute(
            """
            UPDATE temp_emails SET
                pool_status = 'available',
                claimed_by = NULL,
                claimed_at = NULL,
                lease_expires_at = NULL,
                claim_token = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (now_str, temp_id),
        )
        conn.commit()
        return

    conn.execute(
        """
        UPDATE accounts SET
            pool_status = 'available',
            claimed_by = NULL,
            claimed_at = NULL,
            lease_expires_at = NULL,
            claim_token = NULL,
            claimed_project_key = NULL,
            updated_at = ?
        WHERE id = ?
        """,
        (now_str, account_id),
    )
    conn.commit()
