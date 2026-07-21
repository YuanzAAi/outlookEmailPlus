"""
CloudflareTempMailProvider
~~~~~~~~~~~~~~~~~~~~~~~~~~

对接 dreamhunter2333/cloudflare_temp_email 的 TempMailProviderBase 实现。

认证模型
--------
- 管理操作（创建/删除邮箱）：HTTP 头 ``x-admin-auth: <ADMIN_PASSWORD>``
- 用户操作（读取/删除邮件）：HTTP 头 ``Authorization: Bearer <jwt>``
  JWT 在创建邮箱时由 CF Worker 颁发，存储在 mailbox.meta["provider_jwt"]。

字段映射
--------
CF Worker 使用以下非标准字段名，本模块统一转换为平台标准字段名：
- ``source``      -> ``from_address``
- ``created_at``  -> ``timestamp`` (ISO 8601 -> int unix timestamp)
- ``id``          -> ``message_id`` (加 "cf_" 前缀，避免与其他 provider 冲突)
- ``raw``         -> 解析 MIME 后提取 subject/content/html_content/has_html
"""

from __future__ import annotations

import email as _email_lib
import email.policy
import json
import logging
import secrets
import string
import time
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from outlook_web.repositories import settings as settings_repo
from outlook_web.services.temp_mail_provider_base import TempMailProviderBase, register_provider
from outlook_web.services.temp_mail_provider_custom import TempMailProviderReadError

logger = logging.getLogger(__name__)

_CF_REQUEST_TIMEOUT = (5, 12)
_CF_SESSION = requests.Session()
_CF_SESSION.trust_env = False
_CF_SESSION.headers.update({"Connection": "keep-alive"})
_CF_ADAPTER = HTTPAdapter(pool_connections=4, pool_maxsize=16, max_retries=0, pool_block=False)
_CF_SESSION.mount("http://", _CF_ADAPTER)
_CF_SESSION.mount("https://", _CF_ADAPTER)

DEFAULT_PREFIX_RULES = {
    "min_length": 1,
    "max_length": 32,
    "pattern": r"^[a-z0-9][a-z0-9._-]*$",
}


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class CloudflareTempMailProviderError(TempMailProviderReadError):
    def __init__(self, code: str, message: str, *, data: dict[str, Any] | None = None):
        super().__init__(code, message, data=data)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _map_cf_http_error(status_code: int, text: str = "") -> str:
    if status_code in (401, 403):
        return "UNAUTHORIZED"
    if status_code == 404:
        return "TEMP_EMAIL_NOT_FOUND"
    if status_code == 429:
        return "UPSTREAM_RATE_LIMITED"
    if status_code >= 500:
        return "UPSTREAM_SERVER_ERROR"
    return "UPSTREAM_BAD_PAYLOAD"


def _iso_to_timestamp(iso_str: str) -> int:
    """将 CF Worker 返回的 ISO 8601 字符串转换为 Unix timestamp（整数）。"""
    try:
        clean = iso_str.replace("Z", "+00:00")
        # 兼容毫秒格式：2025-12-07T10:30:00.000+00:00
        if "." in clean:
            clean = clean[: clean.index(".")] + clean[clean.index("+") :]
        parsed = datetime.fromisoformat(clean)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except (ValueError, AttributeError):
        return 0


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_mime_raw(raw_mime: str) -> dict[str, Any]:
    """
    使用 Python 标准库解析 CF Worker 返回的原始 MIME 字符串。

    返回包含以下键的字典：
    - subject       : str
    - from_address  : str
    - content       : str  （纯文本正文）
    - html_content  : str  （HTML 正文，可能为空）
    - has_html      : bool
    """
    try:
        msg = _email_lib.message_from_string(raw_mime, policy=_email_lib.policy.compat32)
    except Exception:
        return {
            "subject": "",
            "from_address": "",
            "content": raw_mime,
            "html_content": "",
            "has_html": False,
        }

    # subject
    raw_subject = msg.get("Subject", "") or ""
    try:
        from email.header import decode_header as _decode_header

        decoded_parts = _decode_header(raw_subject)
        subject_parts = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                subject_parts.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                subject_parts.append(str(part))
        subject = "".join(subject_parts)
    except Exception:
        subject = raw_subject

    # from_address
    from_address = str(msg.get("From", "") or "").strip()

    # body parts
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cdisp = str(part.get("Content-Disposition") or "")
            if "attachment" in cdisp:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                text = payload.decode(charset, errors="replace")
            except Exception:
                continue
            if ct == "text/plain":
                plain_parts.append(text)
            elif ct == "text/html":
                html_parts.append(text)
    else:
        ct = msg.get_content_type()
        charset = msg.get_content_charset() or "utf-8"
        try:
            payload = msg.get_payload(decode=True)
            text = payload.decode(charset, errors="replace") if payload else ""
        except Exception:
            text = str(msg.get_payload() or "")
        if ct == "text/html":
            html_parts.append(text)
        else:
            plain_parts.append(text)

    content = "\n".join(plain_parts).strip()
    html_content = "\n".join(html_parts).strip()
    has_html = bool(html_content)

    return {
        "subject": subject,
        "from_address": from_address,
        "content": content,
        "html_content": html_content,
        "has_html": has_html,
    }


def _normalize_domain_entries(raw_domains: Any, default_domain: str) -> list[dict[str, Any]]:
    domains: list[dict[str, Any]] = []
    seen: set[str] = set()
    values: list[Any] = raw_domains if isinstance(raw_domains, list) else []
    for item in values:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            enabled = bool(item.get("enabled", True))
        else:
            name = str(item or "").strip()
            enabled = True
        if not name or name in seen:
            continue
        seen.add(name)
        domains.append(
            {
                "name": name,
                "enabled": enabled,
                "is_default": bool(default_domain and name == default_domain),
            }
        )
    if default_domain and default_domain not in seen:
        domains.append({"name": default_domain, "enabled": True, "is_default": True})
    return domains


# ---------------------------------------------------------------------------
# Provider 实现
# ---------------------------------------------------------------------------


@register_provider
class CloudflareTempMailProvider(TempMailProviderBase):
    """
    对接 Cloudflare Workers Temp Email 的 Provider 实现。

    配置读取（来自 settings 表）：
    - ``cf_worker_base_url``          : CF Worker 部署地址（如 https://mail.example.workers.dev）
    - ``cf_worker_admin_key``         : CF Worker ADMIN_PASSWORDS 中的一个值
    - ``cf_worker_domains``           : CF Worker 配置的域名列表（JSON 数组）
    - ``cf_worker_default_domain``    : 默认域名

    兼容：若 cf_worker_* 未配置，会回退读取旧 key：
    - ``temp_mail_domains`` / ``temp_mail_default_domain`` / ``temp_mail_prefix_rules``
    """

    provider_name = "cloudflare_temp_mail"
    provider_label = "Cloudflare Worker"
    provider_version = "1.0.0"
    provider_author = "OutlookMail Plus"

    def __init__(self, *, provider_name: str | None = None):
        self.provider_name = provider_name or "cloudflare_temp_mail"

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _base_url(self) -> str:
        """读取 CF Worker 独立部署地址（cf_worker_base_url），与 GPTMail 设置完全隔离。"""
        url = settings_repo.get_cf_worker_base_url().rstrip("/")
        return url

    def _admin_key(self) -> str:
        """读取 CF Worker 独立 Admin 密码（cf_worker_admin_key）。"""
        return settings_repo.get_cf_worker_admin_key()

    def _admin_headers(self) -> dict[str, str]:
        return {"x-admin-auth": self._admin_key(), "Content-Type": "application/json"}

    def _user_headers(self, jwt: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        normalized_method = str(method or "GET").upper()
        attempts = 2 if normalized_method in {"GET", "HEAD"} else 1
        last_error: requests.RequestException | None = None
        for attempt in range(attempts):
            try:
                response = _CF_SESSION.request(
                    normalized_method,
                    f"{self._base_url()}{path}",
                    timeout=_CF_REQUEST_TIMEOUT,
                    **kwargs,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    raise
            else:
                if response.status_code not in {502, 503, 504} or attempt + 1 >= attempts:
                    return response
            time.sleep(0.2 * (attempt + 1))
        if last_error is not None:
            raise last_error
        raise requests.RequestException("CF Worker request failed without response")

    def _read_request(self, method: str, path: str, *, operation: str, **kwargs: Any) -> requests.Response:
        try:
            return self._request(method, path, **kwargs)
        except requests.Timeout as exc:
            raise CloudflareTempMailProviderError(
                "UPSTREAM_TIMEOUT",
                f"CF Worker {operation}超时",
            ) from exc
        except requests.RequestException as exc:
            raise CloudflareTempMailProviderError(
                "UPSTREAM_SERVER_ERROR",
                f"CF Worker {operation}失败: {exc}",
            ) from exc

    def _coerce_email(self, mailbox: dict[str, Any] | str) -> str:
        if isinstance(mailbox, dict):
            return str(mailbox.get("email") or "").strip()
        return str(mailbox or "").strip()

    def _get_jwt(self, mailbox: dict[str, Any] | str) -> str:
        """从 mailbox.meta 中取出 provider_jwt；无则返回空串。"""
        if isinstance(mailbox, dict):
            meta = mailbox.get("meta") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            return str(meta.get("provider_jwt") or "").strip()
        return ""

    def _get_address_id(self, mailbox: dict[str, Any] | str) -> str:
        if not isinstance(mailbox, dict):
            return ""
        meta = mailbox.get("meta") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        return str(meta.get("provider_mailbox_id") or "").strip()

    def get_capabilities(self, mailbox: dict[str, Any] | None = None) -> dict[str, bool]:
        email_addr = self._coerce_email(mailbox or {})
        domain = email_addr.rsplit("@", 1)[1].casefold() if "@" in email_addr else ""
        default_domain = str(settings_repo.get_cf_worker_default_domain() or "").strip().casefold()
        can_send = bool(domain and default_domain and domain == default_domain)
        return {
            "send_message": can_send,
            "list_sent_messages": True,
            "delete_sent_message": True,
            "clear_sent_messages": True,
        }

    def _build_meta(self, *, jwt: str = "", address_id: str = "") -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "provider_mailbox_id": address_id,
            "provider_jwt": jwt,
            "provider_cursor": "",
            "provider_labels": [],
            "provider_capabilities": {
                "delete_mailbox": True,
                "delete_message": True,
                "clear_messages": True,
                "send_message": True,
                "list_sent_messages": True,
                "delete_sent_message": True,
                "clear_sent_messages": True,
            },
            "provider_debug": {"bridge": "cloudflare_worker"},
        }

    def discover_mailbox(self, email_addr: str) -> dict[str, Any] | None:
        """按完整邮箱精确发现远程地址，不创建新邮箱。"""
        normalized_email = str(email_addr or "").strip()
        if not normalized_email or "@" not in normalized_email:
            return None
        if not self._base_url() or not self._admin_key():
            raise CloudflareTempMailProviderError(
                "TEMP_MAIL_PROVIDER_NOT_CONFIGURED",
                "CF Worker 地址或 Admin Key 未配置",
            )

        try:
            resp = self._request(
                "GET",
                "/admin/address/resolve",
                headers=self._admin_headers(),
                params={"email": normalized_email},
            )
        except requests.Timeout as exc:
            raise CloudflareTempMailProviderError("UPSTREAM_TIMEOUT", "CF Worker 地址查询超时") from exc
        except requests.RequestException as exc:
            raise CloudflareTempMailProviderError(
                "UPSTREAM_SERVER_ERROR",
                f"CF Worker 地址查询失败: {exc}",
            ) from exc

        if resp.status_code == 404:
            return self._discover_mailbox_legacy(normalized_email)
        if not resp.ok:
            self._raise_http_error(resp, operation="地址查询")

        try:
            data = resp.json()
        except Exception as exc:
            raise CloudflareTempMailProviderError(
                "UPSTREAM_BAD_PAYLOAD",
                "CF Worker 地址查询返回非 JSON 响应",
            ) from exc
        return self._normalize_discovered_mailbox(data, normalized_email)

    def _discover_mailbox_legacy(self, email_addr: str) -> dict[str, Any] | None:
        resp = self._read_request(
            "GET",
            "/admin/address",
            operation="地址查询",
            headers=self._admin_headers(),
            params={"query": email_addr, "limit": 100, "offset": 0},
        )
        if not resp.ok:
            self._raise_http_error(resp, operation="地址查询")
        try:
            rows = (resp.json() or {}).get("results") or []
        except Exception as exc:
            raise CloudflareTempMailProviderError(
                "UPSTREAM_BAD_PAYLOAD",
                "CF Worker 地址列表返回非 JSON 响应",
            ) from exc
        row = next(
            (item for item in rows if str(item.get("name") or "").strip().casefold() == email_addr.casefold()),
            None,
        )
        if not row:
            return None
        address_id = str(row.get("id") or "").strip()
        token_resp = self._read_request(
            "GET",
            f"/admin/show_password/{address_id}",
            operation="地址凭据查询",
            headers=self._admin_headers(),
        )
        if not token_resp.ok:
            self._raise_http_error(token_resp, operation="地址凭据查询")
        try:
            token_data = token_resp.json() or {}
        except Exception as exc:
            raise CloudflareTempMailProviderError(
                "UPSTREAM_BAD_PAYLOAD",
                "CF Worker 地址凭据返回非 JSON 响应",
            ) from exc
        return self._normalize_discovered_mailbox({**row, "jwt": token_data.get("jwt")}, email_addr)

    def _normalize_discovered_mailbox(self, data: dict[str, Any], requested_email: str) -> dict[str, Any] | None:
        address = str(data.get("name") or data.get("address") or "").strip()
        if not address or address.casefold() != requested_email.casefold():
            return None
        address_id = str(data.get("id") or data.get("address_id") or "").strip()
        jwt = str(data.get("jwt") or "").strip()
        if not address_id or not jwt:
            raise CloudflareTempMailProviderError(
                "UPSTREAM_BAD_PAYLOAD",
                "CF Worker 地址查询缺少 id 或 jwt",
                data={"email": requested_email},
            )
        return {
            "success": True,
            "email": address,
            "provider_name": self.provider_name,
            "meta": self._build_meta(jwt=jwt, address_id=address_id),
        }

    def list_remote_mailboxes(self, *, after_id: int = 0, limit: int = 200) -> dict[str, Any]:
        """增量读取远程地址元数据，供本地后台同步。"""
        if not self._base_url() or not self._admin_key():
            return {"results": [], "next_cursor": int(after_id or 0), "supported": False}
        safe_after_id = max(0, int(after_id or 0))
        safe_limit = max(1, min(int(limit or 200), 500))
        try:
            resp = self._request(
                "GET",
                "/admin/address/sync",
                headers=self._admin_headers(),
                params={"after_id": safe_after_id, "limit": safe_limit},
            )
        except requests.Timeout as exc:
            raise CloudflareTempMailProviderError("UPSTREAM_TIMEOUT", "CF Worker 地址同步超时") from exc
        except requests.RequestException as exc:
            raise CloudflareTempMailProviderError(
                "UPSTREAM_SERVER_ERROR",
                f"CF Worker 地址同步失败: {exc}",
            ) from exc

        if resp.status_code == 404:
            return self._list_remote_mailboxes_legacy(after_id=safe_after_id, limit=safe_limit)
        if not resp.ok:
            self._raise_http_error(resp, operation="地址同步")
        try:
            data = resp.json() or {}
        except Exception as exc:
            raise CloudflareTempMailProviderError(
                "UPSTREAM_BAD_PAYLOAD",
                "CF Worker 地址同步返回非 JSON 响应",
            ) from exc
        rows = data.get("results") or []
        if not isinstance(rows, list):
            raise CloudflareTempMailProviderError("UPSTREAM_BAD_PAYLOAD", "CF Worker 地址同步字段格式错误")
        next_cursor = max([safe_after_id] + [_safe_int(item.get("id")) for item in rows if isinstance(item, dict)])
        return {"results": rows, "next_cursor": next_cursor, "supported": True}

    def _list_remote_mailboxes_legacy(self, *, after_id: int, limit: int) -> dict[str, Any]:
        offset = 0
        collected: list[dict[str, Any]] = []
        while len(collected) < limit:
            resp = self._read_request(
                "GET",
                "/admin/address",
                operation="地址同步",
                headers=self._admin_headers(),
                params={
                    "limit": min(100, limit - len(collected)),
                    "offset": offset,
                    "sort_by": "id",
                    "sort_order": "ascend",
                },
            )
            if not resp.ok:
                self._raise_http_error(resp, operation="地址同步")
            try:
                data = resp.json() or {}
            except Exception as exc:
                raise CloudflareTempMailProviderError(
                    "UPSTREAM_BAD_PAYLOAD",
                    "CF Worker 地址同步返回非 JSON 响应",
                ) from exc
            rows = data.get("results") or []
            if not isinstance(rows, list):
                raise CloudflareTempMailProviderError(
                    "UPSTREAM_BAD_PAYLOAD",
                    "CF Worker 地址同步字段格式错误",
                )
            if not rows:
                break
            collected.extend(item for item in rows if isinstance(item, dict) and _safe_int(item.get("id")) > after_id)
            offset += len(rows)
            if offset >= _safe_int(data.get("count")):
                break
        rows = collected[:limit]
        next_cursor = max([after_id] + [_safe_int(item.get("id")) for item in rows])
        return {"results": rows, "next_cursor": next_cursor, "supported": False}

    def _raise_http_error(self, resp: requests.Response, *, operation: str) -> None:
        code = _map_cf_http_error(resp.status_code, resp.text)
        raise CloudflareTempMailProviderError(
            code,
            f"CF Worker {operation} 失败 HTTP {resp.status_code}",
            data={"status_code": resp.status_code, "body": resp.text[:500]},
        )

    # ------------------------------------------------------------------
    # TempMailProviderBase 接口实现
    # ------------------------------------------------------------------

    def get_options(self) -> dict[str, Any]:
        # v0.3: 设置页 CF Worker 配置与 GPTMail 配置隔离。
        # 优先读 cf_worker_*，为空时回退 temp_mail_*（兼容旧配置/旧数据）。
        cf_domains = settings_repo.get_cf_worker_domains()
        cf_default_domain = settings_repo.get_cf_worker_default_domain()
        cf_prefix_rules = settings_repo.get_cf_worker_prefix_rules()

        # v0.3.1: 自动同步（快速修复）
        # 现实场景中管理员可能已配置 cf_worker_base_url，但尚未点“同步域名”按钮。
        # 这会导致前端域名下拉为空（只有“自动分配域名”），用户体验较差。
        #
        # 策略：当 cf_worker_domains 为空且 base_url 已配置时，自动调用
        # GET {base_url}/open_api/settings 拉取 domains，并写回 cf_worker_domains /
        # cf_worker_default_domain（与 GPTMail 完全独立）。
        #
        # 注意：同步失败必须是非阻塞（不影响 options 返回），并继续走 legacy fallback。
        if not cf_domains:
            base_url = self._base_url()
            if base_url:
                try:
                    sync_result = self.get_cf_worker_domains()
                    if sync_result.get("success") and (sync_result.get("domains") or []):
                        domains: list[str] = sync_result.get("domains") or []
                        default_domain: str = str(sync_result.get("default_domain") or "").strip()
                        domains_payload = [{"name": d, "enabled": True} for d in domains if str(d or "").strip()]
                        if domains_payload:
                            settings_repo.set_setting(
                                "cf_worker_domains",
                                json.dumps(domains_payload, ensure_ascii=False),
                                commit=True,
                            )
                            if default_domain:
                                settings_repo.set_setting(
                                    "cf_worker_default_domain",
                                    default_domain,
                                    commit=True,
                                )
                            # 重新读取一次，确保后续逻辑使用最新配置（并避免重复回源）
                            cf_domains = settings_repo.get_cf_worker_domains()
                            cf_default_domain = settings_repo.get_cf_worker_default_domain()
                except Exception as exc:
                    logger.warning("[cf_provider] auto sync domains failed err=%s", exc)

        legacy_domains = settings_repo.get_temp_mail_domains()
        legacy_default_domain = settings_repo.get_temp_mail_default_domain()
        legacy_prefix_rules = settings_repo.get_temp_mail_prefix_rules()

        domains_payload = cf_domains if cf_domains else legacy_domains
        default_domain = (cf_default_domain or "").strip() or (legacy_default_domain or "").strip()
        prefix_rules = cf_prefix_rules if cf_prefix_rules else legacy_prefix_rules

        # 防御：确保类型
        if not isinstance(domains_payload, list):
            domains_payload = []
        if not isinstance(prefix_rules, dict):
            prefix_rules = {}

        normalized_prefix_rules = {
            "min_length": int(prefix_rules.get("min_length", DEFAULT_PREFIX_RULES["min_length"])),
            "max_length": int(prefix_rules.get("max_length", DEFAULT_PREFIX_RULES["max_length"])),
            "pattern": str(prefix_rules.get("pattern") or DEFAULT_PREFIX_RULES["pattern"]),
        }

        return {
            "domain_strategy": "auto_or_manual",
            "default_mode": "auto",
            "domains": _normalize_domain_entries(domains_payload, default_domain),
            "prefix_rules": normalized_prefix_rules,
            "provider": self.provider_name,
            "provider_name": self.provider_name,
            "provider_label": "cloudflare_temp_mail",
            "api_base_url": self._base_url(),
            "capabilities": self.get_capabilities(),
        }

    def create_mailbox(self, *, prefix: str | None = None, domain: str | None = None) -> dict[str, Any]:
        """
        调用 POST /admin/new_address 创建邮箱。

        返回格式：
        - 成功：{"success": True, "email": "...", "meta": {...}}
        - 失败：{"success": False, "error": "...", "error_code": "..."}
        """
        base_url = self._base_url()
        if not base_url:
            return {
                "success": False,
                "error": "CF Worker base_url 未配置",
                "error_code": "TEMP_MAIL_PROVIDER_NOT_CONFIGURED",
            }
        if not self._admin_key():
            return {
                "success": False,
                "error": "CF Worker admin key 未配置",
                "error_code": "TEMP_MAIL_PROVIDER_NOT_CONFIGURED",
            }

        # 确定目标域名
        options = self.get_options()
        domains_list: list[dict[str, Any]] = options.get("domains") or []
        enabled_domains = [d["name"] for d in domains_list if d.get("enabled")]
        target_domain = (domain or "").strip()
        if not target_domain:
            # 优先使用 is_default，其次第一个 enabled
            for d in domains_list:
                if d.get("is_default") and d.get("enabled"):
                    target_domain = d["name"]
                    break
            if not target_domain and enabled_domains:
                target_domain = enabled_domains[0]

        if not target_domain:
            return {
                "success": False,
                "error": "未配置可用域名",
                "error_code": "TEMP_MAIL_PROVIDER_NOT_CONFIGURED",
            }

        # CF Worker 要求 name 不能为空字符串（空串会返回 400 "Required field is missing"）。
        # 当调用方未指定 prefix 时，在 Python 侧生成随机 8 字符前缀。
        effective_name = (prefix or "").strip()
        if not effective_name:
            alphabet = string.ascii_lowercase + string.digits
            effective_name = "".join(secrets.choice(alphabet) for _ in range(8))

        # 验证：CF Worker v1.5.0+ 支持 domain 字段，可用于多域名创建。
        # 若 target_domain 非空，则传入 domain 字段以支持指定域名创建；
        # 若 target_domain 为空，则省略 domain 字段，让 CF Worker 使用其内置默认域名。
        payload: dict[str, Any] = {
            "name": effective_name,
            "enablePrefix": False,  # 禁止 CF 自动加前缀，避免邮箱名不符合预期
        }
        if target_domain:
            payload["domain"] = target_domain

        try:
            resp = self._request(
                "POST",
                "/admin/new_address",
                headers=self._admin_headers(),
                json=payload,
            )
        except requests.Timeout:
            return {
                "success": False,
                "error": "CF Worker 请求超时",
                "error_code": "UPSTREAM_TIMEOUT",
            }
        except requests.RequestException as exc:
            return {
                "success": False,
                "error": f"CF Worker 网络错误: {exc}",
                "error_code": "UPSTREAM_SERVER_ERROR",
            }

        if not resp.ok:
            code = _map_cf_http_error(resp.status_code, resp.text)
            return {
                "success": False,
                "error": f"CF Worker 创建邮箱失败 HTTP {resp.status_code}",
                "error_code": code,
            }

        try:
            data = resp.json()
        except Exception:
            return {
                "success": False,
                "error": "CF Worker 返回非 JSON 响应",
                "error_code": "UPSTREAM_BAD_PAYLOAD",
            }

        address = str(data.get("address") or "").strip()
        jwt = str(data.get("jwt") or "").strip()
        address_id = str(data.get("address_id") or data.get("id") or "").strip()

        if not address:
            return {
                "success": False,
                "error": "CF Worker 未返回邮箱地址",
                "error_code": "UPSTREAM_BAD_PAYLOAD",
            }

        return {
            "success": True,
            "email": address,
            "meta": self._build_meta(jwt=jwt, address_id=address_id),
        }

    def delete_mailbox(self, mailbox: dict[str, Any]) -> bool:
        """调用 DELETE /admin/delete_address/:id 删除邮箱（按数字 address_id）。

        CF Worker 正确路由为 DELETE /admin/delete_address/{id}，
        id 是创建邮箱时返回的数字 address_id，存储在 meta["provider_mailbox_id"] 中。
        """
        address_id = ""
        if isinstance(mailbox, dict):
            meta_raw = mailbox.get("meta") or {}
            if isinstance(meta_raw, str):
                try:
                    meta_raw = json.loads(meta_raw)
                except Exception:
                    meta_raw = {}
            address_id = str(meta_raw.get("provider_mailbox_id") or "").strip()

        if not address_id:
            email_addr = self._coerce_email(mailbox)
            logger.warning(
                "[cf_provider] delete_mailbox: no address_id in meta for %s, cannot delete",
                email_addr,
            )
            return False

        try:
            resp = self._request(
                "DELETE",
                f"/admin/delete_address/{address_id}",
                headers=self._admin_headers(),
            )
            return resp.ok
        except requests.RequestException as exc:
            logger.warning("[cf_provider] delete_mailbox failed id=%s err=%s", address_id, exc)
            return False

    def list_messages(self, mailbox: dict[str, Any] | str) -> list[dict[str, Any]]:
        """
        调用 GET /api/mails?limit=100&offset=0 获取邮件列表，解析每封邮件的 raw MIME。

        注意：正确路由为 /api/mails（不是 /mails，后者返回 HTML 前端页面）。

        返回列表中每项的字段符合平台标准（供 save_temp_email_messages 使用）：
        - id, message_id, from_address, subject, content, html_content, has_html, timestamp
        """
        email_addr = self._coerce_email(mailbox)
        jwt = self._get_jwt(mailbox) if isinstance(mailbox, dict) else ""

        if not jwt:
            raise CloudflareTempMailProviderError(
                "UNAUTHORIZED",
                f"邮箱 {email_addr} 缺少 provider_jwt，无法读取邮件",
                data={"email": email_addr},
            )

        try:
            resp = self._request(
                "GET",
                "/api/parsed_mails",
                params={"limit": 100, "offset": 0},
                headers=self._user_headers(jwt),
            )
        except requests.Timeout:
            raise CloudflareTempMailProviderError(
                "UPSTREAM_TIMEOUT",
                "CF Worker 读取邮件超时",
                data={"email": email_addr},
            )
        except requests.RequestException as exc:
            raise CloudflareTempMailProviderError(
                "UPSTREAM_SERVER_ERROR",
                f"CF Worker 网络错误: {exc}",
                data={"email": email_addr},
            )

        if resp.status_code == 404:
            try:
                resp = self._request(
                    "GET",
                    "/api/mails",
                    params={"limit": 100, "offset": 0},
                    headers=self._user_headers(jwt),
                )
            except requests.Timeout as exc:
                raise CloudflareTempMailProviderError(
                    "UPSTREAM_TIMEOUT",
                    "CF Worker 读取邮件超时",
                    data={"email": email_addr},
                ) from exc
            except requests.RequestException as exc:
                raise CloudflareTempMailProviderError(
                    "UPSTREAM_SERVER_ERROR",
                    f"CF Worker 网络错误: {exc}",
                    data={"email": email_addr},
                ) from exc

        if not resp.ok:
            code = _map_cf_http_error(resp.status_code, resp.text)
            raise CloudflareTempMailProviderError(
                code,
                f"CF Worker 读取邮件失败 HTTP {resp.status_code}",
                data={"email": email_addr, "status_code": resp.status_code},
            )

        try:
            data = resp.json()
        except Exception:
            raise CloudflareTempMailProviderError(
                "UPSTREAM_BAD_PAYLOAD",
                "CF Worker 邮件列表返回非 JSON 响应",
                data={"email": email_addr},
            )

        cf_mails = data.get("results") or data.get("mails") or []
        if not isinstance(cf_mails, list):
            raise CloudflareTempMailProviderError(
                "UPSTREAM_BAD_PAYLOAD",
                "CF Worker 邮件列表字段格式错误",
                data={"email": email_addr},
            )

        results: list[dict[str, Any]] = []
        for cf_msg in cf_mails:
            try:
                results.append(self._normalize_cf_message(cf_msg))
            except Exception as exc:
                logger.warning(
                    "[cf_provider] failed to parse cf_msg id=%s err=%s",
                    cf_msg.get("id"),
                    exc,
                )
        return results

    def _normalize_cf_message(self, cf_msg: dict[str, Any]) -> dict[str, Any]:
        """将 CF Worker 原始邮件结构转换为平台标准结构。"""
        cf_id = cf_msg.get("id")
        # BUG-CF-05：加 cf_ 前缀避免与其他 provider 的 ID 冲突
        message_id = f"cf_{cf_id}" if cf_id is not None else ""

        created_at_str = str(cf_msg.get("created_at") or "")
        # BUG-CF-07：ISO 字符串 -> int timestamp
        timestamp = _iso_to_timestamp(created_at_str) if created_at_str else 0

        raw_mime = str(cf_msg.get("raw") or "")
        if raw_mime:
            parsed = _parse_mime_raw(raw_mime)
        else:
            parsed = {
                "subject": "",
                "from_address": "",
                "content": "",
                "html_content": "",
                "has_html": False,
            }

        parsed_sender_raw = str(cf_msg.get("sender") or cf_msg.get("from_address") or "").strip()
        parsed_sender = parseaddr(parsed_sender_raw)[1] or parsed_sender_raw
        parsed_content = str(cf_msg.get("text") or cf_msg.get("content") or "")
        parsed_html = str(cf_msg.get("html") or cf_msg.get("html_content") or "")

        # BUG-CF-01：优先使用 Worker 服务端解析字段，再回退本地 MIME 解析与 source。
        from_address = (parsed_sender or parsed.get("from_address") or str(cf_msg.get("source") or "")).strip()

        # subject 优先从 MIME 中取，其次从顶层字段取（部分 CF 版本可能有）
        subject = (str(cf_msg.get("subject") or "") or parsed.get("subject") or "").strip()

        # message_id 字段（RFC 822 Message-ID），用于去重
        cf_message_id_header = str(cf_msg.get("message_id") or "")

        return {
            "id": message_id,  # 供 save_temp_email_messages 的 msg.get("id") 使用
            "message_id": message_id,  # 冗余，方便直接读取
            "from_address": from_address,
            "source": from_address,  # 保留原始字段（兼容 save_temp_email_messages 的 source fallback）
            "subject": subject,
            "content": parsed_content or parsed.get("content", ""),
            "html_content": parsed_html or parsed.get("html_content", ""),
            "has_html": bool(parsed_html or parsed.get("has_html", False)),
            "timestamp": timestamp,
            "created_at": created_at_str,
            "raw_message_id": cf_message_id_header,
        }

    def get_message_detail(self, mailbox: dict[str, Any] | str, message_id: str) -> dict[str, Any] | None:
        """
        优先调用 GET /api/parsed_mail/:id，旧 Worker 再回退列表过滤。
        """
        jwt = self._get_jwt(mailbox) if isinstance(mailbox, dict) else ""
        if not jwt:
            raise CloudflareTempMailProviderError(
                "UNAUTHORIZED",
                f"邮箱 {self._coerce_email(mailbox)} 缺少 provider_jwt，无法读取邮件",
            )
        cf_id = message_id[3:] if message_id.startswith("cf_") else message_id
        try:
            resp = self._request(
                "GET",
                f"/api/parsed_mail/{cf_id}",
                headers=self._user_headers(jwt),
            )
        except requests.Timeout as exc:
            raise CloudflareTempMailProviderError("UPSTREAM_TIMEOUT", "CF Worker 读取邮件详情超时") from exc
        except requests.RequestException as exc:
            raise CloudflareTempMailProviderError(
                "UPSTREAM_SERVER_ERROR",
                f"CF Worker 读取邮件详情失败: {exc}",
            ) from exc

        if resp.status_code == 404:
            messages = self.list_messages(mailbox)
            return next(
                (msg for msg in messages if msg.get("id") == message_id or msg.get("message_id") == message_id),
                None,
            )
        if not resp.ok:
            self._raise_http_error(resp, operation="读取邮件详情")
        try:
            data = resp.json()
        except Exception as exc:
            raise CloudflareTempMailProviderError(
                "UPSTREAM_BAD_PAYLOAD",
                "CF Worker 邮件详情返回非 JSON 响应",
            ) from exc
        if not data:
            return None
        return self._normalize_cf_message(data)

    def delete_message(self, mailbox: dict[str, Any] | str, message_id: str) -> bool:
        """
        调用 DELETE /api/mails/{id} 删除单封邮件。

        注意：正确路由为 /api/mails/{id}（不是 /mails/{id}，后者返回 405）。
        message_id 为平台格式 ``cf_<int>``，需还原为 CF 整数 ID。
        """
        jwt = self._get_jwt(mailbox) if isinstance(mailbox, dict) else ""
        if not jwt:
            logger.warning(
                "[cf_provider] delete_message: no jwt for %s",
                self._coerce_email(mailbox),
            )
            return False

        # 还原 CF 整数 ID
        cf_id: str = message_id
        if message_id.startswith("cf_"):
            cf_id = message_id[3:]

        try:
            resp = self._request(
                "DELETE",
                f"/api/mails/{cf_id}",
                headers=self._user_headers(jwt),
            )
            return resp.ok
        except requests.RequestException as exc:
            logger.warning("[cf_provider] delete_message failed id=%s err=%s", message_id, exc)
            return False

    def clear_messages(self, mailbox: dict[str, Any] | str) -> bool:
        """调用 DELETE /admin/clear_inbox/{addr_id} 清空邮箱所有邮件（Admin 接口）。

        注意：用户侧没有 clear_messages 路由，需用 Admin 接口 /admin/clear_inbox/{id}，
        id 为 meta["provider_mailbox_id"]（数字 address_id）。
        """
        address_id = ""
        if isinstance(mailbox, dict):
            meta_raw = mailbox.get("meta") or {}
            if isinstance(meta_raw, str):
                try:
                    meta_raw = json.loads(meta_raw)
                except Exception:
                    meta_raw = {}
            address_id = str(meta_raw.get("provider_mailbox_id") or "").strip()

        if not address_id:
            logger.warning(
                "[cf_provider] clear_messages: no address_id for %s",
                self._coerce_email(mailbox),
            )
            return False

        try:
            resp = self._request(
                "DELETE",
                f"/admin/clear_inbox/{address_id}",
                headers=self._admin_headers(),
            )
            return resp.ok
        except requests.RequestException as exc:
            logger.warning("[cf_provider] clear_messages failed err=%s", exc)
            return False

    def send_message(
        self,
        mailbox: dict[str, Any],
        *,
        to_email: str,
        subject: str,
        content: str,
        is_html: bool = False,
        from_name: str = "",
        to_name: str = "",
    ) -> dict[str, Any]:
        email_addr = self._coerce_email(mailbox)
        if not self.get_capabilities(mailbox).get("send_message"):
            raise CloudflareTempMailProviderError(
                "TEMP_EMAIL_SEND_UNSUPPORTED",
                "当前临时邮箱域名未启用发信",
                data={"email": email_addr},
            )
        resp = self._read_request(
            "POST",
            "/admin/send_mail",
            operation="发送邮件",
            headers=self._admin_headers(),
            json={
                "from_name": str(from_name or "").strip(),
                "from_mail": email_addr,
                "to_name": str(to_name or "").strip(),
                "to_mail": str(to_email or "").strip(),
                "subject": str(subject or "").strip(),
                "content": str(content or ""),
                "is_html": bool(is_html),
            },
        )
        if not resp.ok:
            self._raise_http_error(resp, operation="发送邮件")
        try:
            data = resp.json() or {}
        except Exception as exc:
            raise CloudflareTempMailProviderError(
                "UPSTREAM_BAD_PAYLOAD",
                "CF Worker 发信返回非 JSON 响应",
            ) from exc
        return {"success": True, "status": str(data.get("status") or "ok")}

    def list_sent_messages(
        self,
        mailbox: dict[str, Any],
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        email_addr = self._coerce_email(mailbox)
        resp = self._read_request(
            "GET",
            "/admin/sendbox",
            operation="读取发件箱",
            headers=self._admin_headers(),
            params={"address": email_addr, "limit": max(1, min(int(limit), 100)), "offset": max(0, int(offset))},
        )
        if not resp.ok:
            self._raise_http_error(resp, operation="读取发件箱")
        try:
            data = resp.json() or {}
        except Exception as exc:
            raise CloudflareTempMailProviderError(
                "UPSTREAM_BAD_PAYLOAD",
                "CF Worker 发件箱返回非 JSON 响应",
            ) from exc
        rows = data.get("results") or []
        if not isinstance(rows, list):
            raise CloudflareTempMailProviderError(
                "UPSTREAM_BAD_PAYLOAD",
                "CF Worker 发件箱字段格式错误",
            )
        return {
            "items": [self._normalize_cf_sent_message(row) for row in rows if isinstance(row, dict)],
            "count": _safe_int(data.get("count"), len(rows)),
        }

    def _normalize_cf_sent_message(self, row: dict[str, Any]) -> dict[str, Any]:
        raw_value = row.get("raw")
        if isinstance(raw_value, dict):
            payload = dict(raw_value)
        else:
            try:
                parsed = json.loads(str(raw_value or "{}"))
                payload = parsed if isinstance(parsed, dict) else {}
            except Exception:
                payload = {}

        if str(payload.get("version") or "").lower() == "v2":
            to_email = str(payload.get("to_mail") or "").strip()
            to_name = str(payload.get("to_name") or "").strip()
            subject = str(payload.get("subject") or "")
            content = str(payload.get("content") or "")
            is_html = bool(payload.get("is_html"))
        else:
            recipients = payload.get("personalizations") or []
            recipient_values: list[str] = []
            for personalization in recipients if isinstance(recipients, list) else []:
                for recipient in (personalization or {}).get("to") or []:
                    if isinstance(recipient, dict) and recipient.get("email"):
                        recipient_values.append(str(recipient["email"]))
            content_rows = payload.get("content") or []
            first_content = content_rows[0] if isinstance(content_rows, list) and content_rows else {}
            to_email = ", ".join(recipient_values)
            to_name = ""
            subject = str(payload.get("subject") or "")
            content = str((first_content or {}).get("value") or "")
            is_html = str((first_content or {}).get("type") or "").lower() != "text/plain"

        created_at = str(row.get("created_at") or "")
        raw_id = str(row.get("id") or "").strip()
        return {
            "id": f"cf_sent_{raw_id}" if raw_id else "",
            "from": str(row.get("address") or "").strip(),
            "to": f"{to_name} <{to_email}>" if to_name else to_email,
            "to_email": to_email,
            "to_name": to_name,
            "subject": subject,
            "content": content,
            "is_html": is_html,
            "body_type": "html" if is_html else "text",
            "created_at": created_at,
            "timestamp": _iso_to_timestamp(created_at) if created_at else 0,
        }

    def delete_sent_message(self, mailbox: dict[str, Any], message_id: str) -> bool:
        raw_id = str(message_id or "")
        if raw_id.startswith("cf_sent_"):
            raw_id = raw_id[len("cf_sent_") :]
        if not raw_id:
            return False
        try:
            resp = self._request(
                "DELETE",
                f"/admin/sendbox/{raw_id}",
                headers=self._admin_headers(),
                params={"address": self._coerce_email(mailbox)},
            )
            if not resp.ok:
                return False
            try:
                data = resp.json() or {}
            except Exception:
                return True
            return bool(data.get("success", True)) and data.get("deleted", True) is not False
        except requests.RequestException as exc:
            logger.warning("[cf_provider] delete_sent_message failed id=%s err=%s", message_id, exc)
            return False

    def clear_sent_messages(self, mailbox: dict[str, Any]) -> bool:
        address_id = self._get_address_id(mailbox)
        if not address_id:
            logger.warning("[cf_provider] clear_sent_messages: no address_id for %s", self._coerce_email(mailbox))
            return False
        try:
            resp = self._request(
                "DELETE",
                f"/admin/clear_sent_items/{address_id}",
                headers=self._admin_headers(),
            )
            return resp.ok
        except requests.RequestException as exc:
            logger.warning("[cf_provider] clear_sent_messages failed err=%s", exc)
            return False

    def get_cf_worker_domains(self) -> dict[str, Any]:
        """
        查询 CF Worker 的 GET /open_api/settings 接口，
        获取 CF Worker 上配置的可用域名列表（无需鉴权，公开接口）。

        返回格式：
        - 成功：{"success": True, "domains": ["a.com", "b.com"], "default_domain": "a.com",
                  "title": "...", "version": "..."}
        - 失败：{"success": False, "error": "...", "error_code": "..."}

        用途：管理员可通过此接口将 CF Worker 的实际域名配置同步到本地 settings 表，
        避免手动维护 temp_mail_domains / temp_mail_default_domain。
        """
        base_url = self._base_url()
        if not base_url:
            return {
                "success": False,
                "error": "CF Worker base_url 未配置",
                "error_code": "TEMP_MAIL_PROVIDER_NOT_CONFIGURED",
            }

        try:
            resp = self._request("GET", "/open_api/settings")
        except requests.Timeout:
            return {
                "success": False,
                "error": "CF Worker 请求超时",
                "error_code": "UPSTREAM_TIMEOUT",
            }
        except requests.RequestException as exc:
            return {
                "success": False,
                "error": f"CF Worker 网络错误: {exc}",
                "error_code": "UPSTREAM_SERVER_ERROR",
            }

        if not resp.ok:
            return {
                "success": False,
                "error": f"CF Worker 查询域名失败 HTTP {resp.status_code}",
                "error_code": _map_cf_http_error(resp.status_code, resp.text),
            }

        try:
            data = resp.json()
        except Exception:
            return {
                "success": False,
                "error": "CF Worker 返回非 JSON 响应",
                "error_code": "UPSTREAM_BAD_PAYLOAD",
            }

        # CF Worker open_api/settings 返回 domains 列表（v1.5.0+）
        raw_domains: list[Any] = data.get("domains") or data.get("defaultDomains") or []
        default_domains: list[Any] = data.get("defaultDomains") or []

        # 过滤有效域名
        domains = [str(d).strip() for d in raw_domains if str(d or "").strip()]
        # 默认域名：优先取 defaultDomains 第一个
        default_domain = ""
        if default_domains:
            default_domain = str(default_domains[0] or "").strip()
        elif domains:
            default_domain = domains[0]

        return {
            "success": True,
            "domains": domains,
            "default_domain": default_domain,
            "title": str(data.get("title") or ""),
            "version": str(data.get("version") or ""),
            "raw": data,
        }
