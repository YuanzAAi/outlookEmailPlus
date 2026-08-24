"""
邮箱池服务层（PRD-00009 MT-1）

职责：
- 输入校验（caller_id / task_id / lease_seconds / result / detail 长度）
- 读取 settings（在 Flask app_context 下用 get_db，或直接接受 conn）
- 调用 repositories/pool.py 的原子操作
- 将 repository 层的异常转换为业务错误码
"""

from __future__ import annotations

import json
import logging
from typing import Iterable, Optional

from outlook_web.db import create_sqlite_connection
from outlook_web.repositories import pool as pool_repo
from outlook_web.repositories import settings as settings_repo
from outlook_web.services.providers import MAIL_PROVIDERS

logger = logging.getLogger(__name__)

CALLER_ID_MAX_LEN = 64
TASK_ID_MAX_LEN = 128
PROJECT_KEY_MAX_LEN = 128
EMAIL_DOMAIN_MAX_LEN = 128
REASON_MAX_LEN = 256
DETAIL_MAX_LEN = 512

VALID_RESULTS = set(pool_repo.RESULT_TO_POOL_STATUS.keys())
VALID_ACCOUNT_SCOPES = {"all", "regular", "temp"}

# CF 邮箱 complete 时需要删除远程邮箱的 result 值
CF_DELETE_ON_RESULTS = {"success", "credential_invalid"}

# 支持的 provider 白名单（空字符串视为 None，不做校验）
VALID_PROVIDERS = set(MAIL_PROVIDERS) | {"imap", "gptmail", "cloudflare_temp_mail"}

# 这些 provider（含未指定）在 accounts 池无命中时，回退到 temp_emails 临时邮箱池领取。
# custom/gptmail 对应「通用 API (GPTMail)」临时邮箱；None 表示不限 provider。
_TEMP_ELIGIBLE_PROVIDERS = {None, "custom", "gptmail", "cloudflare_temp_mail"}


def _validate_provider(provider: Optional[str]) -> Optional[str]:
    """
    校验 provider 参数。

    - 空字符串视为 None
    - 非空时校验是否在 VALID_PROVIDERS 中
    - 返回规范化后的 provider（None 或有效值）
    """
    if provider is None:
        return None
    p = provider.strip()
    if not p:
        return None
    if p not in VALID_PROVIDERS:
        raise PoolServiceError(
            f"provider 必须是 {sorted(VALID_PROVIDERS)} 之一，或留空",
            "invalid_provider",
        )
    return p


class PoolServiceError(Exception):
    """业务错误，包含 HTTP 状态码和错误码。"""

    def __init__(self, message: str, error_code: str, http_status: int = 400):
        super().__init__(message)
        self.error_code = error_code
        self.http_status = http_status


def _validate_caller_id(caller_id: str) -> None:
    if not caller_id or not caller_id.strip():
        raise PoolServiceError("caller_id 不能为空", "caller_id_empty")
    if len(caller_id) > CALLER_ID_MAX_LEN:
        raise PoolServiceError(f"caller_id 超过最大长度 {CALLER_ID_MAX_LEN}", "caller_id_too_long")


def _validate_task_id(task_id: str) -> None:
    if not task_id or not task_id.strip():
        raise PoolServiceError("task_id 不能为空", "task_id_empty")
    if len(task_id) > TASK_ID_MAX_LEN:
        raise PoolServiceError(f"task_id 超过最大长度 {TASK_ID_MAX_LEN}", "task_id_too_long")


def _validate_lease_seconds(lease_seconds: int, max_lease: int = 3600) -> None:
    if lease_seconds <= 0:
        raise PoolServiceError("lease_seconds 必须大于 0", "lease_seconds_invalid")
    if lease_seconds > max_lease:
        raise PoolServiceError(f"lease_seconds 不能超过 {max_lease} 秒", "lease_seconds_too_large")


def _validate_project_key(project_key: Optional[str]) -> Optional[str]:
    if project_key is None:
        return None
    pk = project_key.strip()
    if not pk:
        return None
    if len(pk) > PROJECT_KEY_MAX_LEN:
        raise PoolServiceError(f"project_key 超过最大长度 {PROJECT_KEY_MAX_LEN}", "project_key_too_long")
    return pk


def _validate_email_domain(email_domain: Optional[str]) -> Optional[str]:
    if email_domain is None:
        return None
    d = email_domain.strip().lower()
    if not d:
        return None
    if len(d) > EMAIL_DOMAIN_MAX_LEN:
        raise PoolServiceError(f"email_domain 超过最大长度 {EMAIL_DOMAIN_MAX_LEN}", "email_domain_too_long")
    return d


def _normalize_allowed_emails(allowed_emails: Iterable[str] | None) -> list[str]:
    return sorted(
        {
            str(email or "").strip().lower()
            for email in (allowed_emails or [])
            if str(email or "").strip() and "@" in str(email or "")
        }
    )


def _normalize_group_id(group_id: int | str | None) -> Optional[int]:
    if group_id in (None, "", 0, "0"):
        return None
    try:
        value = int(group_id)
    except (TypeError, ValueError) as exc:
        raise PoolServiceError("group_id 必须为正整数", "invalid_group_id") from exc
    if value <= 0:
        raise PoolServiceError("group_id 必须为正整数", "invalid_group_id")
    return value


def _ensure_allowed_email(email_addr: str, allowed_emails: Iterable[str] | None) -> None:
    normalized_allowed_emails = _normalize_allowed_emails(allowed_emails)
    if normalized_allowed_emails and str(email_addr or "").strip().lower() not in normalized_allowed_emails:
        raise PoolServiceError(
            "当前 API Key 无权操作该邮箱",
            "email_scope_forbidden",
            http_status=403,
        )


def _read_settings_via_conn(conn) -> dict:
    """在独立连接场景下直接从 settings 表读取池相关配置。"""
    rows = conn.execute(
        "SELECT key, value FROM settings WHERE key IN (?, ?)",
        ("pool_cooldown_seconds", "pool_default_lease_seconds"),
    ).fetchall()
    result = {"pool_cooldown_seconds": 86400, "pool_default_lease_seconds": 600}
    for row in rows:
        try:
            result[row["key"]] = int(row["value"])
        except (TypeError, ValueError):
            pass
    return result


def _is_project_reuse_eligible_account(
    *,
    provider: Optional[str],
    account_type: Optional[str],
    claimed_project_key: Optional[str],
) -> bool:
    """判定账号是否适用项目维度成功复用路径 (FD §2.1)。

    三重门控缺一不可：
    1. claimed_project_key 非空 — 必须在 claim 时显式传入
    2. 非 cloudflare_temp_mail — CF 临时邮箱不在本期覆盖范围
    3. 非 temp_mail — 一次性临时邮箱不在本期覆盖范围
    """
    if not claimed_project_key:
        return False
    if (provider or "").strip() == "cloudflare_temp_mail":
        return False
    if (account_type or "").strip() == "temp_mail":
        return False
    return True


def claim_random(
    *,
    caller_id: str,
    task_id: str,
    provider: Optional[str] = None,
    project_key: Optional[str] = None,
    email_domain: Optional[str] = None,
    group_id: int | str | None = None,
    allowed_emails: Iterable[str] | None = None,
    account_scope: str = "all",
) -> dict:
    _validate_caller_id(caller_id)
    _validate_task_id(task_id)
    provider = _validate_provider(provider)
    project_key = _validate_project_key(project_key)
    email_domain = _validate_email_domain(email_domain)
    group_id = _normalize_group_id(group_id)
    allowed_emails = _normalize_allowed_emails(allowed_emails)
    account_scope = str(account_scope or "all").strip().lower()
    if account_scope not in VALID_ACCOUNT_SCOPES:
        raise PoolServiceError("account_scope 必须是 all、regular 或 temp", "invalid_account_scope")

    conn = create_sqlite_connection()
    try:
        if group_id is not None and conn.execute("SELECT 1 FROM groups WHERE id = ?", (group_id,)).fetchone() is None:
            raise PoolServiceError("group_id 不存在", "invalid_group_id")
        settings = _read_settings_via_conn(conn)
        default_lease = settings["pool_default_lease_seconds"]
        _validate_lease_seconds(default_lease)

        try:
            account = pool_repo.claim_atomic(
                conn,
                caller_id=caller_id,
                task_id=task_id,
                lease_seconds=default_lease,
                provider=provider,
                project_key=project_key,
                email_domain=email_domain,
                group_id=group_id,
                allowed_emails=allowed_emails,
                account_scope=account_scope,
            )
        except pool_repo.PoolRepositoryError as e:
            raise PoolServiceError(str(e), e.error_code, http_status=500) from e

        if account is not None:
            return account

        # accounts 池无命中：对临时邮箱类 provider（custom/gptmail/未指定）回退到 temp_emails 池领取
        if account_scope != "regular" and provider in _TEMP_ELIGIBLE_PROVIDERS:
            try:
                temp_account = pool_repo.claim_temp_mailbox_atomic(
                    conn,
                    caller_id=caller_id,
                    task_id=task_id,
                    lease_seconds=default_lease,
                    email_domain=email_domain,
                    group_id=group_id,
                    allowed_emails=allowed_emails,
                )
            except pool_repo.PoolRepositoryError as e:
                raise PoolServiceError(str(e), e.error_code, http_status=500) from e
            if temp_account is not None:
                return temp_account

        # 池为空：仅当显式指定 provider=cloudflare_temp_mail 时，动态创建 CF 临时邮箱
        if account_scope != "regular" and provider == "cloudflare_temp_mail" and not allowed_emails:
            created_email, created_meta = _create_cf_mailbox_for_pool(email_domain=email_domain)
            dynamic_group_id = group_id or _resolve_group_id_by_name(conn, "临时邮箱")

            try:
                inserted = pool_repo.insert_claimed_account(
                    conn,
                    email=created_email,
                    caller_id=caller_id,
                    task_id=task_id,
                    lease_seconds=default_lease,
                    provider="cloudflare_temp_mail",
                    account_type="temp_mail",
                    group_id=dynamic_group_id,
                    project_key=project_key,
                    temp_mail_meta=created_meta,
                    claim_log_detail="CF邮箱动态创建",
                )
                return inserted
            except pool_repo.PoolRepositoryError as e:
                # DB 写入失败时，尽力删除已创建的远程邮箱，避免资源泄漏（非阻塞）
                _delete_cf_mailbox_nonblocking(email=created_email, meta=created_meta)
                raise PoolServiceError(str(e), e.error_code, http_status=500) from e
            except Exception as e:
                _delete_cf_mailbox_nonblocking(email=created_email, meta=created_meta)
                raise PoolServiceError("动态写入 CF 邮箱失败", "db_error", http_status=500) from e

        raise PoolServiceError("池中没有符合条件的可用邮箱", "no_available_account", http_status=200)
    finally:
        conn.close()


def _validate_claim_ownership(
    row: Optional[dict],
    *,
    action: str,
    claim_token: str,
    caller_id: str,
    task_id: str,
) -> None:
    """校验 release/complete 的领取归属（accounts 与 temp_emails 共用）。"""
    if row is None:
        raise PoolServiceError("账号不存在", "account_not_found", http_status=400)
    if row.get("pool_status") != "claimed":
        raise PoolServiceError(
            f"账号当前状态为 '{row.get('pool_status')}'，无法 {action}",
            "not_claimed",
            http_status=409,
        )
    if row.get("claim_token") != claim_token:
        raise PoolServiceError("claim_token 不匹配", "token_mismatch", http_status=403)
    if row.get("claimed_by") != f"{caller_id}:{task_id}":
        raise PoolServiceError(
            "caller_id 或 task_id 与领取记录不一致",
            "caller_mismatch",
            http_status=403,
        )


def release_claim(
    *,
    account_id: int,
    claim_token: str,
    caller_id: str,
    task_id: str,
    reason: Optional[str] = None,
    allowed_emails: Iterable[str] | None = None,
) -> None:
    """释放已领取的邮箱账号（不计入成功/失败统计，直接回 available）。"""
    _validate_caller_id(caller_id)
    _validate_task_id(task_id)
    if not claim_token or not claim_token.strip():
        raise PoolServiceError("claim_token 不能为空", "claim_token_empty")
    if reason and len(reason) > REASON_MAX_LEN:
        raise PoolServiceError(f"reason 超过最大长度 {REASON_MAX_LEN}", "reason_too_long")

    conn = create_sqlite_connection()
    try:
        # 临时邮箱池账号：account_id 带偏移，路由到 temp_emails
        if pool_repo.is_temp_pool_account_id(account_id):
            temp_id = pool_repo.temp_id_from_account_id(account_id)
            temp_row = pool_repo.get_temp_mailbox_pool_row(conn, temp_id)
            if temp_row is not None:
                _ensure_allowed_email(str(temp_row.get("email") or ""), allowed_emails)
            _validate_claim_ownership(
                temp_row, action="release", claim_token=claim_token, caller_id=caller_id, task_id=task_id
            )
            pool_repo.release_temp_mailbox(conn, temp_id, claim_token, caller_id, task_id, reason)
            return

        row = conn.execute(
            "SELECT id, email, claim_token, claimed_by, pool_status FROM accounts WHERE id = ?",
            (account_id,),
        ).fetchone()
        if row is not None:
            _ensure_allowed_email(str(row["email"] or ""), allowed_emails)
        _validate_claim_ownership(
            dict(row) if row is not None else None,
            action="release",
            claim_token=claim_token,
            caller_id=caller_id,
            task_id=task_id,
        )

        pool_repo.release(conn, account_id, claim_token, caller_id, task_id, reason)
    finally:
        conn.close()


def complete_claim(
    *,
    account_id: int,
    claim_token: str,
    caller_id: str,
    task_id: str,
    result: str,
    detail: Optional[str] = None,
    allowed_emails: Iterable[str] | None = None,
) -> str:
    """
    标记领取结果并驱动状态机流转。

    返回账号的新 pool_status。
    """
    _validate_caller_id(caller_id)
    _validate_task_id(task_id)
    if not claim_token or not claim_token.strip():
        raise PoolServiceError("claim_token 不能为空", "claim_token_empty")
    if result not in VALID_RESULTS:
        raise PoolServiceError(
            f"result 必须是 {sorted(VALID_RESULTS)} 之一",
            "invalid_result",
        )
    if detail and len(detail) > DETAIL_MAX_LEN:
        raise PoolServiceError(f"detail 超过最大长度 {DETAIL_MAX_LEN}", "detail_too_long")

    conn = create_sqlite_connection()
    try:
        # 临时邮箱池账号：account_id 带偏移，路由到 temp_emails（一次性资源，无项目复用/CF 删除）
        if pool_repo.is_temp_pool_account_id(account_id):
            temp_id = pool_repo.temp_id_from_account_id(account_id)
            temp_row = pool_repo.get_temp_mailbox_pool_row(conn, temp_id)
            if temp_row is not None:
                _ensure_allowed_email(str(temp_row.get("email") or ""), allowed_emails)
            _validate_claim_ownership(
                temp_row, action="complete", claim_token=claim_token, caller_id=caller_id, task_id=task_id
            )
            return pool_repo.complete_temp_mailbox(conn, temp_id, claim_token, caller_id, task_id, result, detail)

        row = conn.execute(
            """
            SELECT id, email, provider, account_type, temp_mail_meta,
                   claimed_project_key,
                   claim_token, claimed_by, pool_status
            FROM accounts
            WHERE id = ?
            """,
            (account_id,),
        ).fetchone()
        if row is not None:
            _ensure_allowed_email(str(row["email"] or ""), allowed_emails)
        _validate_claim_ownership(
            dict(row) if row is not None else None,
            action="complete",
            claim_token=claim_token,
            caller_id=caller_id,
            task_id=task_id,
        )

        # 从 claim 上下文读取 claimed_project_key，而非依赖 API 入参
        # 保证 claim-complete 即使未传 project_key 也能正确判定复用路径（TDD §4.1 N-03）
        claimed_project_key = str(row["claimed_project_key"] or "").strip() or None
        enable_project_reuse = _is_project_reuse_eligible_account(
            provider=row["provider"],
            account_type=row["account_type"],
            claimed_project_key=claimed_project_key,
        )

        # complete 先更新本地状态（事务内），再做 CF 删除（非阻塞）
        new_status = pool_repo.complete(
            conn,
            account_id,
            claim_token,
            caller_id,
            task_id,
            result,
            detail,
            claimed_project_key=claimed_project_key,
            enable_project_reuse=enable_project_reuse,
        )

        if (row["provider"] or "").strip() == "cloudflare_temp_mail" and result in CF_DELETE_ON_RESULTS:
            meta_str = row["temp_mail_meta"]
            meta_obj = {}
            if isinstance(meta_str, str) and meta_str.strip():
                try:
                    meta_obj = json.loads(meta_str)
                except Exception:
                    meta_obj = {}
            _delete_cf_mailbox_nonblocking(email=row["email"], meta=meta_obj)

        return new_status
    finally:
        conn.close()


def _create_cf_mailbox_for_pool(*, email_domain: Optional[str]) -> tuple[str, dict]:
    """调用 CF Worker 创建邮箱（Service 层），返回 (email, meta_dict)。"""
    try:
        from outlook_web.services.temp_mail_provider_cf import CloudflareTempMailProvider

        provider = CloudflareTempMailProvider()
        result = provider.create_mailbox(prefix=None, domain=email_domain)
    except Exception as e:
        # 上游异常：统一映射为 UPSTREAM_SERVER_ERROR
        logger.warning("[pool] CF create_mailbox exception: %s", e)
        raise PoolServiceError("CF Worker 创建邮箱异常", "UPSTREAM_SERVER_ERROR", http_status=500) from e

    if not isinstance(result, dict):
        raise PoolServiceError("CF Worker 返回格式错误", "UPSTREAM_BAD_PAYLOAD", http_status=500)

    if not result.get("success"):
        error_code = str(result.get("error_code") or "UPSTREAM_SERVER_ERROR")
        error_msg = str(result.get("error") or "CF Worker 创建邮箱失败")
        raise PoolServiceError(error_msg, error_code, http_status=500)

    email = str(result.get("email") or "").strip()
    if not email:
        raise PoolServiceError("CF Worker 未返回邮箱地址", "UPSTREAM_BAD_PAYLOAD", http_status=500)

    meta = result.get("meta") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}

    if not isinstance(meta, dict):
        meta = {}

    return email, meta


def _delete_cf_mailbox_nonblocking(*, email: str, meta: dict) -> None:
    """非阻塞删除远程 CF 邮箱（仅记录日志，不抛异常）。"""
    try:
        from outlook_web.services.temp_mail_provider_cf import CloudflareTempMailProvider

        provider = CloudflareTempMailProvider()
        success = provider.delete_mailbox({"email": email, "meta": meta})
        if success:
            logger.info("[pool] 已删除 CF 远程邮箱: %s", email)
        else:
            logger.warning("[pool] 删除 CF 远程邮箱失败(返回 False): %s", email)
    except Exception as e:
        logger.warning("[pool] 删除 CF 远程邮箱异常: %s, error=%s", email, e)


def get_claim_context(*, claim_token: str) -> Optional[dict]:
    """
    根据 claim_token 查询领取上下文（email / claimed_at / email_domain 等）。
    返回 dict 或 None（token 不存在时）。
    """
    if not claim_token or not claim_token.strip():
        return None
    conn = create_sqlite_connection()
    try:
        return pool_repo.get_claim_context(conn, claim_token.strip())
    finally:
        conn.close()


def append_claim_read_context(
    *,
    account_id: int,
    claim_token: str,
    caller_id: str,
    task_id: str,
    detail: Optional[str] = None,
) -> None:
    """
    追加一条读取上下文日志（claim 邮箱被用于邮件读取时记录）。
    """
    if not claim_token or not claim_token.strip():
        return
    # 临时邮箱池账号不写 account_claim_logs（该表 account_id 对 accounts 有外键约束）
    if pool_repo.is_temp_pool_account_id(account_id):
        return
    conn = create_sqlite_connection()
    try:
        pool_repo.append_claim_read_context(conn, account_id, claim_token, caller_id, task_id, detail)
    finally:
        conn.close()


def get_pool_stats(*, allowed_emails: Iterable[str] | None = None) -> dict:
    """返回池状态统计（不修改任何数据）。"""
    conn = create_sqlite_connection()
    try:
        return pool_repo.get_stats(conn, allowed_emails=_normalize_allowed_emails(allowed_emails))
    finally:
        conn.close()


def _resolve_group_id_by_name(conn, name: str) -> Optional[int]:
    row = conn.execute("SELECT id FROM groups WHERE name = ? LIMIT 1", (name,)).fetchone()
    return int(row["id"]) if row is not None else None


def _option_type(value: object, *, temp: bool = False) -> str:
    text = str(value or "").strip().lower()
    if temp:
        # All user temp mailboxes are consumed through the CF-compatible URL/API
        # reader, regardless of the historical source label in temp_emails.
        return "cloudflare_temp_mail"
    if text == "temp_mail":
        return "cloudflare_temp_mail"
    return text or "outlook"


def _domain_option_entries(conn) -> tuple[list[dict], str]:
    raw_entries = settings_repo.get_cf_worker_domains() or settings_repo.get_temp_mail_domains() or []
    default_domain = (
        settings_repo.get_cf_worker_default_domain().strip()
        or settings_repo.get_temp_mail_default_domain().strip()
    )
    domains: list[dict] = []
    seen: set[str] = set()
    for item in raw_entries:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("domain") or "").strip().lower()
            enabled = bool(item.get("enabled", True))
        else:
            name = str(item or "").strip().lower()
            enabled = True
        if not name or name in seen or not enabled:
            continue
        seen.add(name)
        domains.append({"name": name, "enabled": True, "is_default": name == default_domain})
    if not domains:
        rows = conn.execute(
            """
            SELECT DISTINCT lower(COALESCE(NULLIF(domain, ''), substr(email, instr(email, '@') + 1))) AS domain
            FROM temp_emails
            WHERE status = 'active' AND mailbox_type = 'user'
              AND COALESCE(source, '') != ? AND domain IS NOT NULL
            ORDER BY domain
            """,
            (pool_repo.ACCOUNT_BACKED_TEMP_MAIL_SOURCE,),
        ).fetchall()
        for row in rows:
            name = str(row["domain"] or "").strip().lower()
            if name and name not in seen:
                seen.add(name)
                domains.append({"name": name, "enabled": True, "is_default": name == default_domain})
    if default_domain and default_domain not in seen:
        domains.insert(0, {"name": default_domain, "enabled": True, "is_default": True})
    if not default_domain and domains:
        default_domain = str(domains[0]["name"])
        domains[0]["is_default"] = True
    return domains, default_domain


def get_pool_options(*, allowed_emails: Iterable[str] | None = None) -> dict:
    """返回只读的池选择元数据，不 claim、不创建邮箱、不暴露账号地址。"""
    allowed = _normalize_allowed_emails(allowed_emails)
    conn = create_sqlite_connection()
    try:
        group_rows = conn.execute("SELECT id, name FROM groups ORDER BY CASE WHEN name = '临时邮箱' THEN 0 ELSE 1 END, id").fetchall()
        groups: dict[int, dict] = {
            int(row["id"]): {"id": int(row["id"]), "name": str(row["name"] or ""), "types": {}, "available": 0}
            for row in group_rows
        }
        temp_group_id = _resolve_group_id_by_name(conn, "临时邮箱")
        account_sql = """
            SELECT group_id, provider, account_type, email
            FROM accounts
            WHERE status = 'active' AND pool_status = 'available'
        """
        account_params: list[str] = []
        if allowed:
            placeholders = ",".join("?" for _ in allowed)
            account_sql += f" AND lower(email) IN ({placeholders})"
            account_params.extend(allowed)
        for row in conn.execute(account_sql, account_params).fetchall():
            provider = _option_type(row["provider"] or row["account_type"])
            group_id = int(row["group_id"]) if row["group_id"] is not None else None
            if provider == "cloudflare_temp_mail" or str(row["account_type"] or "") == "temp_mail":
                group_id = group_id or temp_group_id
            if group_id is None or group_id not in groups:
                continue
            entry = groups[group_id]["types"].setdefault(provider, {"value": provider, "available": 0})
            entry["available"] += 1
            groups[group_id]["available"] += 1

        temp_sql = """
            SELECT group_id, source, email
            FROM temp_emails
            WHERE status = 'active' AND mailbox_type = 'user'
              AND (pool_status IS NULL OR pool_status = 'available')
              AND COALESCE(source, '') != ?
        """
        temp_params: list[str] = [pool_repo.ACCOUNT_BACKED_TEMP_MAIL_SOURCE]
        if allowed:
            placeholders = ",".join("?" for _ in allowed)
            temp_sql += f" AND lower(email) IN ({placeholders})"
            temp_params.extend(allowed)
        for row in conn.execute(temp_sql, temp_params).fetchall():
            if temp_group_id is None:
                continue
            provider = _option_type(row["source"], temp=True)
            entry = groups[temp_group_id]["types"].setdefault(provider, {"value": provider, "available": 0})
            entry["available"] += 1
            groups[temp_group_id]["available"] += 1

        normalized_groups = []
        type_totals: dict[str, int] = {}
        for group in groups.values():
            types = sorted(group["types"].values(), key=lambda item: item["value"])
            for item in types:
                type_totals[item["value"]] = type_totals.get(item["value"], 0) + int(item["available"])
            normalized_groups.append({"id": group["id"], "name": group["name"], "available": group["available"], "types": types})
        domains, default_domain = _domain_option_entries(conn)
        return {
            "groups": normalized_groups,
            "types": [{"value": key, "available": value} for key, value in sorted(type_totals.items())],
            "domains": domains,
            "default_domain": default_domain,
        }
    finally:
        conn.close()
