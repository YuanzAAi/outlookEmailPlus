from __future__ import annotations

import json
import logging
import re
import secrets
import threading
import time
import weakref
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any

from outlook_web.repositories import accounts as accounts_repo
from outlook_web.repositories import settings as settings_repo
from outlook_web.repositories import temp_emails as temp_emails_repo
from outlook_web.services.temp_mail_provider_custom import TempMailProviderReadError
from outlook_web.services.temp_mail_provider_factory import TempMailProviderFactoryError, get_temp_mail_provider
from outlook_web.services.verification_extract_log import (
    encode_temp_mail_log_account_id,
    resolve_extract_log_outcome,
    write_verification_extract_log,
)
from outlook_web.services.verification_extractor import (
    apply_confidence_gate,
    enhance_verification_with_ai_fallback,
    extract_verification_info_with_options,
    get_verification_ai_runtime_config,
    is_verification_ai_config_complete,
)

TEMP_MAIL_SOURCE = temp_emails_repo.DEFAULT_TEMP_MAIL_SOURCE
TEMP_MAIL_METHOD = "Temp Mail"
REMOTE_SYNC_ERROR_LOG_INTERVAL_SECONDS = 300
INBOUND_PUSH_CACHE_TTL_SECONDS = 300
MESSAGE_SYNC_STATE_MAX_ENTRIES = 256

logger = logging.getLogger(__name__)


class TempMailError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.data = data


def _shape_verification_result_by_expected_field(
    extracted: dict[str, Any],
    expected_field: str | None,
) -> dict[str, Any]:
    if expected_field not in {"verification_code", "verification_link"}:
        return extracted

    result = dict(extracted or {})
    if expected_field == "verification_code":
        result["verification_link"] = None
        result["link_confidence"] = "low"
    else:
        result["verification_code"] = None
        result["code_confidence"] = "low"

    parts = [v for v in (result.get("verification_code"), result.get("verification_link")) if v]
    result["formatted"] = " ".join(parts) if parts else None
    result["confidence"] = (
        "high" if result.get("code_confidence") == "high" or result.get("link_confidence") == "high" else "low"
    )
    return result


def _build_expected_field_not_found_error(expected_field: str) -> TempMailError:
    if expected_field == "verification_code":
        return TempMailError("VERIFICATION_CODE_NOT_FOUND", "未找到验证码", status=404)
    return TempMailError("VERIFICATION_LINK_NOT_FOUND", "未找到验证链接", status=404)


def _utc_iso_from_timestamp(value: Any, fallback: str = "") -> str:
    try:
        timestamp = int(value or 0)
    except (TypeError, ValueError):
        timestamp = 0
    if timestamp > 0:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return str(fallback or "")


def _mailbox_from_record(record: dict[str, Any]) -> dict[str, Any]:
    mailbox = temp_emails_repo.build_temp_mailbox_public_dto(record)
    mailbox["created_by"] = "task" if mailbox["mailbox_type"] == "task" else "user"
    return mailbox


def _message_summary(email_addr: str, row: dict[str, Any], *, method: str = "Temp Mail") -> dict[str, Any]:
    created_at = _utc_iso_from_timestamp(row.get("timestamp"), row.get("created_at") or "")
    content_preview = str(row.get("content") or "")[:200]
    return {
        "id": str(row.get("message_id") or ""),
        "email_address": email_addr,
        "from_address": str(row.get("from_address") or ""),
        "subject": str(row.get("subject") or "无主题"),
        "content_preview": content_preview,
        "has_html": bool(row.get("has_html")),
        "timestamp": int(row.get("timestamp") or 0),
        "created_at": created_at,
        "method": method,
    }


def _message_detail(email_addr: str, row: dict[str, Any], *, method: str = "Temp Mail") -> dict[str, Any]:
    created_at = _utc_iso_from_timestamp(row.get("timestamp"), row.get("created_at") or "")
    return {
        "id": str(row.get("message_id") or ""),
        "email_address": email_addr,
        "from_address": str(row.get("from_address") or ""),
        "to_address": email_addr,
        "subject": str(row.get("subject") or "无主题"),
        "content": str(row.get("content") or ""),
        "html_content": str(row.get("html_content") or ""),
        "raw_content": str(row.get("raw_content") or ""),
        "timestamp": int(row.get("timestamp") or 0),
        "created_at": created_at,
        "has_html": bool(row.get("has_html") or row.get("html_content")),
        "method": method,
    }


class TempMailService:
    def __init__(self, provider: Any | None = None, provider_factory: Any | None = None):
        self._provider = provider
        self._provider_factory = provider_factory or get_temp_mail_provider
        self._remote_sync_lock = threading.Lock()
        self._discovery_lock = threading.Lock()
        self._remote_sync_last_attempt = 0.0
        self._remote_sync_last_error = ""
        self._remote_sync_last_error_log_at = 0.0
        self._message_sync_at: dict[str, float] = {}
        self._message_sync_locks: weakref.WeakValueDictionary[str, threading.Lock] = weakref.WeakValueDictionary()
        self._message_sync_locks_guard = threading.Lock()

    def _provider_error(self, exc: TempMailProviderFactoryError, *, purpose: str) -> TempMailError:
        if purpose == "options":
            return TempMailError("TEMP_MAIL_OPTIONS_UNAVAILABLE", exc.message, status=503, data=exc.data)
        return TempMailError(exc.code, exc.message, status=exc.status, data=exc.data)

    def _get_provider(
        self,
        *,
        provider_name: str | None = None,
        mailbox: dict[str, Any] | None = None,
        purpose: str = "runtime",
    ):
        if self._provider is not None:
            return self._provider
        resolved_provider_name = (
            str(
                provider_name
                or (mailbox or {}).get("provider_name")
                or ((mailbox or {}).get("meta") or {}).get("provider_name")
                or ""
            ).strip()
            or None
        )
        try:
            return self._provider_factory(resolved_provider_name)
        except TempMailProviderFactoryError as exc:
            raise self._provider_error(exc, purpose=purpose) from exc

    def _get_mailbox_descriptor(self, email_or_mailbox: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(email_or_mailbox, dict):
            if email_or_mailbox.get("kind") == temp_emails_repo.TEMP_MAIL_KIND:
                if str(email_or_mailbox.get("source") or "").strip() == temp_emails_repo.ACCOUNT_BACKED_TEMP_MAIL_SOURCE:
                    account = accounts_repo.get_account_by_email(str(email_or_mailbox.get("email") or ""))
                    if (
                        str((account or {}).get("provider") or "").strip().lower()
                        != settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER
                    ):
                        raise TempMailError("TEMP_EMAIL_NOT_FOUND", "临时邮箱不存在", status=404)
                    from outlook_web.services.mailbox_resolver import build_account_backed_temp_mailbox

                    email_or_mailbox = build_account_backed_temp_mailbox(account, email_or_mailbox)
                self._ensure_account_backed_message_parent(email_or_mailbox)
                return email_or_mailbox
            if email_or_mailbox.get("record"):
                return self._get_mailbox_descriptor(temp_emails_repo.build_temp_mailbox_descriptor(email_or_mailbox["record"]))
            if email_or_mailbox.get("email"):
                return self._get_mailbox_descriptor(temp_emails_repo.build_temp_mailbox_descriptor(email_or_mailbox))

        email_addr = str(email_or_mailbox or "").strip()
        descriptor = temp_emails_repo.get_temp_email_by_address(email_addr, view="descriptor")
        if descriptor:
            return self._get_mailbox_descriptor(descriptor)
        if not descriptor:
            account = accounts_repo.get_account_by_email(email_addr)
            if str((account or {}).get("provider") or "").strip().lower() == settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER:
                from outlook_web.services.mailbox_resolver import build_account_backed_temp_mailbox

                mailbox = build_account_backed_temp_mailbox(account)
                self._ensure_account_backed_message_parent(mailbox)
                return mailbox
        raise TempMailError("TEMP_EMAIL_NOT_FOUND", "临时邮箱不存在", status=404)

    def _ensure_account_backed_message_parent(self, mailbox: dict[str, Any]) -> None:
        if not mailbox.get("account_backed"):
            return
        email_addr = str(mailbox.get("email") or "").strip()
        meta = mailbox.get("meta") or {}
        record = temp_emails_repo.ensure_account_backed_temp_email(
            email_addr,
            meta,
            provider_name=settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER,
        )
        if not record:
            raise TempMailError("TEMP_EMAIL_ACCOUNT_CONFLICT", "账号对应的临时邮箱记录不可用", status=409)
        mailbox["id"] = record.get("id")
        mailbox["record"] = record
        mailbox["meta"] = temp_emails_repo.merge_temp_email_meta(
            mailbox.get("meta"),
            record.get("meta_json"),
            source=temp_emails_repo.ACCOUNT_BACKED_TEMP_MAIL_SOURCE,
            provider_name=settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER,
        )

    @staticmethod
    def _provider_name(provider: Any) -> str:
        return str(getattr(provider, "provider_name", "") or "").strip()

    def is_managed_email(self, email_addr: str) -> bool:
        """判断地址是否属于当前 CF Worker 管理的域名。"""
        normalized = str(email_addr or "").strip()
        if "@" not in normalized:
            return False
        if settings_repo.get_temp_mail_provider() != settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER:
            return False
        domain = normalized.rsplit("@", 1)[1].casefold()
        return any(
            bool(item.get("enabled", True)) and str(item.get("name") or "").strip().casefold() == domain
            for item in settings_repo.get_cf_worker_domains()
            if isinstance(item, dict)
        )

    def _provider_meta_from_remote_row(self, provider: Any, row: dict[str, Any]) -> dict[str, Any]:
        address_id = str(row.get("id") or row.get("address_id") or "").strip()
        jwt = str(row.get("jwt") or "").strip()
        build_meta = getattr(provider, "_build_meta", None)
        if callable(build_meta):
            return build_meta(jwt=jwt, address_id=address_id)
        return {
            "provider_name": self._provider_name(provider),
            "provider_mailbox_id": address_id,
            "provider_jwt": jwt,
            "provider_capabilities": {
                "delete_mailbox": True,
                "delete_message": True,
                "clear_messages": True,
            },
        }

    @staticmethod
    def _has_recent_inbound_push(mailbox: dict[str, Any]) -> bool:
        provider_debug = (mailbox.get("meta") or {}).get("provider_debug") or {}
        try:
            pushed_at = float(provider_debug.get("last_inbound_push_at") or 0)
        except (TypeError, ValueError):
            return False
        return pushed_at > 0 and time.time() - pushed_at <= INBOUND_PUSH_CACHE_TTL_SECONDS

    def ingest_cloudflare_inbound(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist a Cloudflare-delivered message without an outbound provider request."""
        email_addr = str(payload.get("email") or "").strip()
        if not self.is_managed_email(email_addr):
            raise TempMailError("TEMP_EMAIL_NOT_MANAGED", "该邮箱不属于已配置的临时邮箱域名", status=404)

        address_id = str(payload.get("address_id") or "").strip()
        provider_jwt = str(payload.get("provider_jwt") or "").strip()
        message = payload.get("message") or {}
        if not address_id or not provider_jwt or not isinstance(message, dict):
            raise TempMailError("INVALID_PARAM", "入站邮件缺少地址凭据或邮件内容", status=400)

        remote_message_id = str(message.get("id") or "").strip()
        if not remote_message_id:
            raise TempMailError("INVALID_PARAM", "入站邮件缺少消息 ID", status=400)
        if remote_message_id.startswith("cf_"):
            remote_message_id = remote_message_id[3:]

        provider = self._get_provider(
            provider_name=settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER,
            purpose="runtime",
        )
        provider_meta = self._provider_meta_from_remote_row(
            provider,
            {"id": address_id, "jwt": provider_jwt},
        )
        provider_debug = dict(provider_meta.get("provider_debug") or {})
        provider_debug.update(
            {
                "bridge": "cloudflare_inbound_push",
                "last_inbound_push_at": time.time(),
                "last_inbound_message_id": remote_message_id,
            }
        )
        provider_meta["provider_debug"] = provider_debug

        existing = temp_emails_repo.get_temp_email_by_address(email_addr)
        account = accounts_repo.get_account_by_email(email_addr)
        if (
            existing
            and account
            and str(account.get("provider") or "").strip().lower() != settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER
        ):
            raise TempMailError("TEMP_EMAIL_ACCOUNT_CONFLICT", "邮箱已被普通账号占用", status=409)
        if existing:
            canonical_email = str(existing.get("email") or email_addr)
            if account:
                if not temp_emails_repo.ensure_account_backed_temp_email(
                    canonical_email,
                    provider_meta,
                    provider_name=settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER,
                ):
                    raise TempMailError("TEMP_EMAIL_ACCOUNT_CONFLICT", "账号对应的临时邮箱记录不可用", status=409)
                if not accounts_repo.update_account_temp_mail_meta(
                    int(account["id"]),
                    provider_meta,
                    provider_name=settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER,
                ):
                    raise TempMailError("TEMP_EMAIL_META_SAVE_FAILED", "临时邮箱凭据保存失败", status=500)
            else:
                temp_emails_repo.update_temp_email_provider_meta(
                    canonical_email,
                    provider_meta,
                    provider_name=settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER,
                )
        else:
            if account:
                if str(account.get("provider") or "").strip().lower() != settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER:
                    raise TempMailError("TEMP_EMAIL_ACCOUNT_CONFLICT", "邮箱已被普通账号占用", status=409)
                canonical_email = str(account.get("email") or email_addr)
                if not temp_emails_repo.ensure_account_backed_temp_email(
                    canonical_email,
                    provider_meta,
                    provider_name=settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER,
                ):
                    raise TempMailError("TEMP_EMAIL_ACCOUNT_CONFLICT", "账号对应的临时邮箱记录不可用", status=409)
                if not accounts_repo.update_account_temp_mail_meta(
                    int(account["id"]),
                    provider_meta,
                    provider_name=settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER,
                ):
                    raise TempMailError("TEMP_EMAIL_META_SAVE_FAILED", "临时邮箱凭据保存失败", status=500)
            else:
                prefix, domain = email_addr.rsplit("@", 1)
                self._create_or_load_mailbox_record(
                    email_addr=email_addr,
                    mailbox_type="user",
                    visible_in_ui=True,
                    source=TEMP_MAIL_SOURCE,
                    prefix=prefix,
                    domain=domain,
                    meta=provider_meta,
                    provider_name=settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER,
                )
                canonical_email = email_addr

        normalized_message = {
            "id": f"cf_{remote_message_id}",
            "message_id": f"cf_{remote_message_id}",
            "raw_message_id": str(message.get("raw_message_id") or ""),
            "from_address": str(message.get("from_address") or message.get("source") or ""),
            "subject": str(message.get("subject") or ""),
            "content": str(message.get("content") or ""),
            "html_content": str(message.get("html_content") or ""),
            "has_html": bool(message.get("has_html") or message.get("html_content")),
            "created_at": str(message.get("created_at") or ""),
        }
        saved = temp_emails_repo.save_temp_email_messages(canonical_email, [normalized_message])
        if saved != 1:
            raise TempMailError("TEMP_EMAIL_MESSAGE_SAVE_FAILED", "入站邮件保存失败", status=500)
        self._mark_message_synced(canonical_email.casefold())

        mailbox = temp_emails_repo.get_temp_email_by_address(canonical_email, view="descriptor") or {}
        if account:
            visible_in_ui = False
            mailbox_type = "user"
        else:
            visible_in_ui = bool(mailbox.get("visible_in_ui"))
            mailbox_type = str(mailbox.get("mailbox_type") or "")
        return {
            "email": canonical_email,
            "message_id": normalized_message["id"],
            "visible_in_ui": visible_in_ui,
            "mailbox_type": mailbox_type,
        }

    def _log_remote_sync_error(self, exc: Exception) -> None:
        now = time.monotonic()
        signature = f"{type(exc).__name__}:{getattr(exc, 'code', '')}:{exc}"
        if (
            signature == self._remote_sync_last_error
            and now - self._remote_sync_last_error_log_at < REMOTE_SYNC_ERROR_LOG_INTERVAL_SECONDS
        ):
            return
        self._remote_sync_last_error = signature
        self._remote_sync_last_error_log_at = now
        logger.warning(
            "[temp_mail] remote address sync failed code=%s err=%s",
            getattr(exc, "code", type(exc).__name__),
            exc,
        )

    def _persist_discovered_mailbox(
        self,
        *,
        email_addr: str,
        provider: Any,
        discovered: dict[str, Any],
    ) -> dict[str, Any]:
        canonical_email = str(discovered.get("email") or email_addr).strip()
        provider_name = str(discovered.get("provider_name") or self._provider_name(provider)).strip() or None
        meta = discovered.get("meta") or {}
        existing = temp_emails_repo.get_temp_email_by_address(canonical_email)
        account = accounts_repo.get_account_by_email(canonical_email)
        if account:
            if str(account.get("provider") or "").strip().lower() != settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER:
                raise TempMailError("TEMP_EMAIL_ACCOUNT_CONFLICT", "邮箱已被普通账号占用", status=409)
            if not temp_emails_repo.ensure_account_backed_temp_email(
                str(account.get("email") or canonical_email),
                meta,
                provider_name=provider_name,
            ):
                raise TempMailError("TEMP_EMAIL_ACCOUNT_CONFLICT", "账号对应的临时邮箱记录不可用", status=409)
            if not accounts_repo.update_account_temp_mail_meta(
                int(account["id"]),
                meta,
                provider_name=provider_name,
            ):
                raise TempMailError("TEMP_EMAIL_META_SAVE_FAILED", "临时邮箱凭据保存失败", status=500)
            from outlook_web.services.mailbox_resolver import build_account_backed_temp_mailbox

            refreshed = accounts_repo.get_account_by_id(int(account["id"])) or account
            shadow = temp_emails_repo.get_temp_email_by_address(canonical_email, view="descriptor")
            return build_account_backed_temp_mailbox(refreshed, shadow)
        if existing:
            temp_emails_repo.update_temp_email_provider_meta(
                canonical_email,
                meta,
                provider_name=provider_name,
            )
        else:
            prefix, domain = canonical_email.rsplit("@", 1) if "@" in canonical_email else (canonical_email, "")
            self._create_or_load_mailbox_record(
                email_addr=canonical_email,
                mailbox_type="user",
                visible_in_ui=True,
                source=TEMP_MAIL_SOURCE,
                prefix=prefix,
                domain=domain,
                meta=meta,
                provider_name=provider_name,
            )
        return temp_emails_repo.build_temp_mailbox_descriptor(
            temp_emails_repo.get_temp_email_by_address(canonical_email) or {}
        )

    def discover_user_mailbox(
        self,
        email_addr: str,
        *,
        provider: Any | None = None,
    ) -> dict[str, Any] | None:
        """精确发现远程地址并导入本地；不存在时返回 None，不创建伪邮箱。"""
        normalized_email = str(email_addr or "").strip()
        if not normalized_email or "@" not in normalized_email:
            return None
        provider = provider or self._get_provider(purpose="runtime")
        if self._provider_name(provider) != settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER:
            return temp_emails_repo.get_temp_email_by_address(normalized_email, view="descriptor")

        existing = temp_emails_repo.get_temp_email_by_address(normalized_email, view="descriptor")
        existing_meta = (existing or {}).get("meta") or {}
        if existing and str(existing_meta.get("provider_jwt") or "").strip():
            return existing

        with self._discovery_lock:
            existing = temp_emails_repo.get_temp_email_by_address(normalized_email, view="descriptor")
            existing_meta = (existing or {}).get("meta") or {}
            if existing and str(existing_meta.get("provider_jwt") or "").strip():
                return existing
            try:
                discovered = provider.discover_mailbox(normalized_email)
            except TempMailProviderReadError as exc:
                raise TempMailError(
                    exc.code,
                    exc.message,
                    status=502,
                    data=exc.data,
                ) from exc
            if not discovered:
                return None
            return self._persist_discovered_mailbox(
                email_addr=normalized_email,
                provider=provider,
                discovered=discovered,
            )

    def sync_remote_mailboxes(self, *, force: bool = False) -> int:
        """增量同步远程地址元数据，不读取每个邮箱的邮件。"""
        now = time.monotonic()
        if not force and now - self._remote_sync_last_attempt < 15:
            return 0
        self._remote_sync_last_attempt = now
        if not self._remote_sync_lock.acquire(blocking=False):
            return 0
        imported = 0
        try:
            provider = self._get_provider(purpose="runtime")
            if self._provider_name(provider) != settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER:
                return 0
            try:
                cursor = int(settings_repo.get_setting("cf_worker_address_sync_cursor", "0") or "0")
            except (TypeError, ValueError):
                cursor = 0
            for _ in range(20):
                result = provider.list_remote_mailboxes(after_id=cursor, limit=500)
                rows = result.get("results") or []
                if not isinstance(rows, list):
                    break
                for row in rows:
                    email_addr = str(row.get("name") or row.get("address") or "").strip()
                    if not email_addr or "@" not in email_addr:
                        continue
                    meta = self._provider_meta_from_remote_row(provider, row)
                    account = accounts_repo.get_account_by_email(email_addr)
                    if account:
                        if str(account.get("provider") or "").strip().lower() == settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER:
                            shadow = temp_emails_repo.ensure_account_backed_temp_email(
                                str(account.get("email") or email_addr),
                                meta,
                                provider_name=self._provider_name(provider),
                            )
                            if shadow:
                                accounts_repo.update_account_temp_mail_meta(
                                    int(account["id"]),
                                    meta,
                                    provider_name=self._provider_name(provider),
                                )
                        continue
                    existing = temp_emails_repo.get_temp_email_by_address(email_addr)
                    if existing:
                        temp_emails_repo.update_temp_email_provider_meta(
                            email_addr,
                            meta,
                            provider_name=self._provider_name(provider),
                        )
                    else:
                        prefix, domain = email_addr.rsplit("@", 1)
                        self._create_or_load_mailbox_record(
                            email_addr=email_addr,
                            mailbox_type="user",
                            visible_in_ui=True,
                            source=TEMP_MAIL_SOURCE,
                            prefix=prefix,
                            domain=domain,
                            meta=meta,
                            provider_name=self._provider_name(provider),
                        )
                        imported += 1
                next_cursor = int(result.get("next_cursor") or cursor)
                if not rows or next_cursor <= cursor:
                    break
                cursor = next_cursor
                if len(rows) < 500:
                    break
            settings_repo.set_setting("cf_worker_address_sync_cursor", str(cursor), commit=True)
            self._remote_sync_last_error = ""
            return imported
        except TempMailProviderReadError as exc:
            # 后台同步失败不影响已有本地邮箱和 URL 取件。
            self._log_remote_sync_error(exc)
            return imported
        except Exception as exc:
            self._log_remote_sync_error(exc)
            return imported
        finally:
            self._remote_sync_lock.release()

    def _ensure_provider_credentials(
        self,
        mailbox: dict[str, Any],
        *,
        require_address_id: bool = False,
    ) -> dict[str, Any]:
        provider = self._get_provider(mailbox=mailbox, purpose="runtime")
        if self._provider_name(provider) != settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER:
            return mailbox
        meta = mailbox.get("meta") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        has_jwt = bool(str(meta.get("provider_jwt") or "").strip())
        has_address_id = bool(str(meta.get("provider_mailbox_id") or "").strip())
        if has_jwt and (not require_address_id or has_address_id):
            return mailbox
        discovered = self.discover_user_mailbox(str(mailbox.get("email") or ""), provider=provider)
        if not discovered:
            raise TempMailError("TEMP_EMAIL_NOT_FOUND", "临时邮箱不存在", status=404)
        return discovered

    def _provider_read_failed(
        self,
        exc: TempMailProviderReadError | None,
        *,
        mailbox: dict[str, Any],
        operation: str,
        message_id: str | None = None,
    ) -> TempMailError:
        data = {
            "provider_name": str(mailbox.get("provider_name") or ((mailbox.get("meta") or {}).get("provider_name") or "")),
            "email": str(mailbox.get("email") or ""),
            "operation": operation,
            "message_id": message_id,
        }
        if exc is not None:
            data["provider_error_code"] = exc.code
            data["provider_error_message"] = exc.message
            if isinstance(exc.data, dict):
                data.update(exc.data)
        else:
            data["provider_error_code"] = "UPSTREAM_BAD_PAYLOAD"
            data["provider_error_message"] = "temp mail provider returned empty read result"

        return TempMailError(
            "TEMP_EMAIL_UPSTREAM_READ_FAILED",
            "临时邮箱上游读取失败",
            status=502,
            data=data,
        )

    def _create_mailbox(self, provider: Any, *, prefix: str | None, domain: str | None) -> dict[str, Any]:
        if hasattr(provider, "create_mailbox"):
            return provider.create_mailbox(prefix=prefix, domain=domain)
        return provider.generate_mailbox(prefix=prefix, domain=domain)

    def _create_or_load_mailbox_record(
        self,
        *,
        email_addr: str,
        mailbox_type: str = "user",
        visible_in_ui: bool = True,
        source: str = TEMP_MAIL_SOURCE,
        prefix: str | None = None,
        domain: str | None = None,
        task_token: str | None = None,
        consumer_key: str | None = None,
        caller_id: str | None = None,
        task_id: str | None = None,
        meta: dict[str, Any] | None = None,
        provider_name: str | None = None,
        status: str = "active",
        failure_code: str = "TEMP_EMAIL_CREATE_FAILED",
        failure_message: str = "临时邮箱创建失败",
        failure_status: int = 502,
        allow_existing: bool = True,
    ) -> dict[str, Any]:
        normalized_email = str(email_addr or "").strip()
        created = temp_emails_repo.create_temp_email(
            email_addr=normalized_email,
            mailbox_type=mailbox_type,
            visible_in_ui=visible_in_ui,
            source=source,
            prefix=prefix,
            domain=domain,
            task_token=task_token,
            consumer_key=consumer_key,
            caller_id=caller_id,
            task_id=task_id,
            meta=meta,
            provider_name=provider_name,
            status=status,
        )
        if not created:
            existing = temp_emails_repo.get_temp_email_by_address(normalized_email)
            if existing:
                if not allow_existing:
                    raise TempMailError("TEMP_EMAIL_EXISTS", "邮箱已存在", status=409)
                return _mailbox_from_record(existing)
            raise TempMailError(failure_code, failure_message, status=failure_status)
        return _mailbox_from_record(self.get_mailbox(normalized_email))

    def get_options(self, *, provider_name: str | None = None) -> dict[str, Any]:
        """获取临时邮箱 provider 的 options。

        - 不传 provider_name：沿用当前全局 runtime provider（兼容现有接口行为）
        - 传 provider_name：按指定 provider 返回 options（用于前端 provider 下拉切换）
        """
        normalized_pn = str(provider_name or "").strip() or None
        provider = self._get_provider(provider_name=normalized_pn, purpose="options")
        options = provider.get_options()
        options.setdefault("provider_name", str(options.get("provider") or ""))
        options.setdefault("provider_label", "temp_mail")
        return options

    def _validate_prefix_and_domain(
        self,
        prefix: str | None,
        domain: str | None,
        *,
        provider_name: str | None = None,
    ) -> tuple[str | None, str | None]:
        if provider_name:
            # 指定了特定 provider：使用该 provider 的域名配置进行校验
            target_provider = self._get_provider(provider_name=provider_name, purpose="options")
            options = target_provider.get_options()
            options.setdefault("provider_name", str(options.get("provider") or ""))
            options.setdefault("provider_label", "temp_mail")
        else:
            options = self.get_options()
        normalized_prefix = str(prefix or "").strip() or None
        normalized_domain = str(domain or "").strip() or None

        if normalized_prefix:
            rules = options.get("prefix_rules") or {}
            min_length = int(rules.get("min_length", 1))
            max_length = int(rules.get("max_length", 32))
            pattern = str(rules.get("pattern") or r"^[a-z0-9][a-z0-9._-]*$")
            if len(normalized_prefix) < min_length or len(normalized_prefix) > max_length:
                raise TempMailError("PREFIX_INVALID", "前缀长度不符合要求", status=400)
            if not re.match(pattern, normalized_prefix):
                raise TempMailError("PREFIX_INVALID", "前缀格式非法", status=400)

        if normalized_domain:
            allowed_domains = {
                str(item.get("name") or "").strip()
                for item in (options.get("domains") or [])
                if bool(item.get("enabled", True))
            }
            if allowed_domains and normalized_domain not in allowed_domains:
                raise TempMailError("DOMAIN_NOT_AVAILABLE", "指定域名不可用", status=400)

        return normalized_prefix, normalized_domain

    def list_user_mailboxes(self) -> list[dict[str, Any]]:
        self.sync_remote_mailboxes(force=False)
        records = temp_emails_repo.load_temp_emails(
            visible_only=True,
            mailbox_type="user",
            status="active",
            view="record",
            order_by_latest_message=True,
        )
        results: list[dict[str, Any]] = []
        for record in records:
            mailbox = temp_emails_repo.build_temp_mailbox_descriptor(record)
            public = temp_emails_repo.build_temp_mailbox_public_dto(record)
            public["capabilities"] = self.get_mailbox_capabilities(mailbox)
            results.append(public)
        return results

    def get_mailbox_capabilities(self, email_or_mailbox: str | dict[str, Any]) -> dict[str, bool]:
        mailbox = self._get_mailbox_descriptor(email_or_mailbox)
        stored = dict((mailbox.get("meta") or {}).get("provider_capabilities") or {})
        try:
            provider = self._get_provider(mailbox=mailbox)
            resolver = getattr(provider, "get_capabilities", None)
            declared = resolver(mailbox) if callable(resolver) else {}
            if isinstance(declared, dict):
                stored.update({str(key): bool(value) for key, value in declared.items()})
        except Exception:
            pass
        return {
            "delete_mailbox": bool(stored.get("delete_mailbox")),
            "delete_message": bool(stored.get("delete_message", True)),
            "clear_messages": bool(stored.get("clear_messages", True)),
            "send_message": bool(stored.get("send_message")),
            "list_sent_messages": bool(stored.get("list_sent_messages")),
            "delete_sent_message": bool(stored.get("delete_sent_message")),
            "clear_sent_messages": bool(stored.get("clear_sent_messages")),
        }

    def _provider_for_capability(
        self,
        email_or_mailbox: str | dict[str, Any],
        capability: str,
        *,
        ensure_credentials: bool = False,
    ) -> tuple[dict[str, Any], Any]:
        mailbox = self._get_mailbox_descriptor(email_or_mailbox)
        if ensure_credentials:
            mailbox = self._ensure_provider_credentials(mailbox, require_address_id=True)
        capabilities = self.get_mailbox_capabilities(mailbox)
        if not capabilities.get(capability):
            raise TempMailError(
                "TEMP_EMAIL_CAPABILITY_UNSUPPORTED",
                "当前临时邮箱 Provider 不支持此操作",
                status=400,
                data={"email": mailbox.get("email"), "capability": capability},
            )
        return mailbox, self._get_provider(mailbox=mailbox)

    def get_mailbox(self, email_addr: str, *, view: str = "record") -> dict[str, Any]:
        record = temp_emails_repo.get_temp_email_by_address(email_addr, view=view)
        if not record:
            raise TempMailError("TEMP_EMAIL_NOT_FOUND", "临时邮箱不存在", status=404)
        return record

    def delete_mailbox(self, email_or_mailbox: str | dict[str, Any]) -> bool:
        mailbox = self._get_mailbox_descriptor(email_or_mailbox)
        if mailbox.get("account_backed"):
            raise TempMailError(
                "TEMP_EMAIL_POOL_ACCOUNT_MANAGED",
                "邮箱池管理的临时邮箱不能从临时邮箱接口删除",
                status=403,
            )
        capabilities = (mailbox.get("meta") or {}).get("provider_capabilities") or {}
        if bool(capabilities.get("delete_mailbox")):
            provider = self._get_provider(mailbox=mailbox)
            if not provider.delete_mailbox(mailbox):
                raise TempMailError("TEMP_EMAIL_DELETE_FAILED", "删除失败", status=502)
        email_addr = str(mailbox.get("email") or "")
        if not temp_emails_repo.delete_temp_email(email_addr):
            raise TempMailError("TEMP_EMAIL_DELETE_FAILED", "删除失败", status=500)
        return True

    def generate_user_mailbox(
        self,
        *,
        prefix: str | None = None,
        domain: str | None = None,
        provider_name: str | None = None,
    ) -> dict[str, Any]:
        # 标准化 provider_name（空字符串视为未指定，回退到全局设置）
        normalized_pn = str(provider_name or "").strip() or None
        normalized_prefix, normalized_domain = self._validate_prefix_and_domain(prefix, domain, provider_name=normalized_pn)
        provider = self._get_provider(provider_name=normalized_pn, purpose="runtime")
        result = self._create_mailbox(provider, prefix=normalized_prefix, domain=normalized_domain)
        if not result.get("success"):
            error_code = str(result.get("error_code") or "TEMP_EMAIL_CREATE_FAILED").strip() or "TEMP_EMAIL_CREATE_FAILED"
            raise TempMailError(
                error_code,
                str(result.get("error") or "生成临时邮箱失败"),
                status=502,
            )
        email_addr = str(result.get("email") or "").strip()
        if not email_addr:
            raise TempMailError("TEMP_EMAIL_CREATE_FAILED", "临时邮箱创建失败：缺少邮箱地址", status=502)
        mailbox = self._create_or_load_mailbox_record(
            email_addr=email_addr,
            mailbox_type="user",
            visible_in_ui=True,
            source=TEMP_MAIL_SOURCE,
            prefix=normalized_prefix,
            domain=normalized_domain,
            meta=result.get("meta"),
            provider_name=result.get("provider_name"),
            failure_code="TEMP_EMAIL_CREATE_FAILED",
            failure_message="临时邮箱创建失败",
            failure_status=502,
            allow_existing=False,
        )
        return mailbox

    def import_user_mailbox(self, email_addr: str, *, allow_local_fallback: bool = True) -> dict[str, Any]:
        normalized_email = str(email_addr or "").strip()
        if not normalized_email:
            raise TempMailError("INVALID_PARAM", "邮箱地址不能为空", status=400)

        existing = temp_emails_repo.get_temp_email_by_address(normalized_email)
        if existing:
            return _mailbox_from_record(existing)

        prefix = None
        domain = None
        if "@" in normalized_email:
            prefix, domain = normalized_email.rsplit("@", 1)

        provider = None
        provider_name = None
        try:
            provider = self._get_provider(purpose="runtime")
            provider_name = str(getattr(provider, "provider_name", "") or "").strip() or None
        except TempMailError:
            if not allow_local_fallback:
                raise

        if provider is not None:
            if self._provider_name(provider) == settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER:
                discovered = self.discover_user_mailbox(normalized_email, provider=provider)
                if discovered:
                    return _mailbox_from_record(discovered.get("record") or discovered)
                raise TempMailError("TEMP_EMAIL_NOT_FOUND", "临时邮箱不存在", status=404)

            probe_mailbox = {
                "kind": temp_emails_repo.TEMP_MAIL_KIND,
                "email": normalized_email,
                "provider_name": provider_name,
                "mailbox_type": "user",
                "status": "active",
                "visible_in_ui": True,
                "source": TEMP_MAIL_SOURCE,
                "prefix": prefix,
                "domain": domain,
                "meta": {"provider_name": provider_name} if provider_name else {},
            }
            try:
                probe_result = provider.list_messages(probe_mailbox)
            except Exception:
                probe_result = None
            else:
                # BUG-02: probe_result=[] 也会被误判为“上游存在”，导致导入假成功。
                # 这里收紧：必须探测到至少 1 条有效消息才允许落库。
                if isinstance(probe_result, list) and len(probe_result) > 0:
                    return self._create_or_load_mailbox_record(
                        email_addr=normalized_email,
                        mailbox_type="user",
                        visible_in_ui=True,
                        source=TEMP_MAIL_SOURCE,
                        prefix=prefix,
                        domain=domain,
                        meta=probe_mailbox["meta"],
                        provider_name=provider_name,
                    )

            try:
                create_result = self._create_mailbox(provider, prefix=prefix, domain=domain)
            except Exception:
                create_result = None
            if isinstance(create_result, dict) and create_result.get("success"):
                created_email = str(create_result.get("email") or "").strip() or normalized_email
                return self._create_or_load_mailbox_record(
                    email_addr=created_email,
                    mailbox_type="user",
                    visible_in_ui=True,
                    source=TEMP_MAIL_SOURCE,
                    meta=create_result.get("meta"),
                    provider_name=create_result.get("provider_name") or provider_name,
                )

        if not allow_local_fallback:
            raise TempMailError("TEMP_EMAIL_CREATE_FAILED", "临时邮箱导入失败", status=502)

        return self._create_or_load_mailbox_record(
            email_addr=normalized_email,
            mailbox_type="user",
            visible_in_ui=True,
            source=TEMP_MAIL_SOURCE,
            prefix=prefix,
            domain=domain,
            meta={"provider_name": provider_name} if provider_name else None,
            provider_name=provider_name,
        )

    def _generate_task_token(self) -> str:
        for _ in range(10):
            token = f"tmptask_{secrets.token_urlsafe(18)}"
            if not temp_emails_repo.get_temp_email_by_task_token(token):
                return token
        raise TempMailError("TEMP_EMAIL_CREATE_FAILED", "任务令牌生成失败", status=500)

    def apply_task_mailbox(
        self,
        *,
        consumer_key: str,
        caller_id: str,
        task_id: str,
        prefix: str | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        if not caller_id:
            raise TempMailError("INVALID_PARAM", "caller_id 必填", status=400)
        if not task_id:
            raise TempMailError("INVALID_PARAM", "task_id 必填", status=400)
        normalized_prefix, normalized_domain = self._validate_prefix_and_domain(prefix, domain)
        provider = self._get_provider(purpose="runtime")
        result = self._create_mailbox(provider, prefix=normalized_prefix, domain=normalized_domain)
        if not result.get("success"):
            error_code = str(result.get("error_code") or "TEMP_EMAIL_CREATE_FAILED").strip() or "TEMP_EMAIL_CREATE_FAILED"
            raise TempMailError(
                error_code,
                str(result.get("error") or "生成临时邮箱失败"),
                status=502,
            )
        email_addr = str(result.get("email") or "").strip()
        task_token = self._generate_task_token()
        mailbox = self._create_or_load_mailbox_record(
            email_addr=email_addr,
            mailbox_type="task",
            visible_in_ui=False,
            source=TEMP_MAIL_SOURCE,
            prefix=normalized_prefix,
            domain=normalized_domain,
            task_token=task_token,
            consumer_key=consumer_key,
            caller_id=caller_id,
            task_id=task_id,
            meta=result.get("meta"),
            provider_name=result.get("provider_name"),
            failure_code="TEMP_EMAIL_CREATE_FAILED",
            failure_message="任务邮箱创建失败",
            failure_status=502,
            allow_existing=False,
        )
        mailbox["task_token"] = task_token
        return mailbox

    def finish_task_mailbox(self, task_token: str) -> dict[str, Any]:
        mailbox = self.get_task_mailbox(task_token)
        if not mailbox:
            raise TempMailError("TASK_TOKEN_INVALID", "任务令牌无效", status=404)
        status = str(mailbox.get("status") or "active").strip().lower()
        if status == "finished":
            raise TempMailError("TASK_ALREADY_FINISHED", "任务已结束", status=409)
        if not temp_emails_repo.finish_task_temp_email(task_token):
            raise TempMailError("INTERNAL_ERROR", "结束任务邮箱失败", status=500)
        finished = temp_emails_repo.get_temp_email_by_task_token(task_token) or mailbox
        return {
            "task_token": task_token,
            "status": str(finished.get("status") or "finished"),
            "email": str(finished.get("email") or ""),
        }

    def get_task_mailbox(self, task_token: str, *, view: str = "record") -> dict[str, Any] | None:
        return temp_emails_repo.get_temp_email_by_task_token(task_token, view=view)

    def _message_sync_lock_for(self, email_addr: str) -> threading.Lock:
        key = str(email_addr or "").strip().casefold()
        with self._message_sync_locks_guard:
            lock = self._message_sync_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._message_sync_locks[key] = lock
            return lock

    def _message_sync_was_recent(self, key: str, now: float) -> bool:
        with self._message_sync_locks_guard:
            return now - self._message_sync_at.get(key, 0.0) < 0.75

    def _mark_message_synced(self, key: str) -> None:
        now = time.monotonic()
        with self._message_sync_locks_guard:
            self._message_sync_at[key] = now
            overflow = len(self._message_sync_at) - MESSAGE_SYNC_STATE_MAX_ENTRIES
            if overflow > 0:
                oldest = sorted(self._message_sync_at, key=self._message_sync_at.get)[:overflow]
                for stale_key in oldest:
                    self._message_sync_at.pop(stale_key, None)

    def _sync_provider_messages(self, provider: Any, mailbox: dict[str, Any]) -> None:
        email_addr = str(mailbox.get("email") or "")
        is_cloudflare = self._provider_name(provider) == settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER
        lock = self._message_sync_lock_for(email_addr) if is_cloudflare else threading.Lock()
        with lock:
            sync_key = email_addr.casefold()
            if is_cloudflare and self._message_sync_was_recent(sync_key, time.monotonic()):
                return
            try:
                api_messages = provider.list_messages(mailbox)
            except TempMailProviderReadError as exc:
                raise self._provider_read_failed(exc, mailbox=mailbox, operation="list_messages") from exc
            if api_messages is None:
                raise self._provider_read_failed(None, mailbox=mailbox, operation="list_messages")
            temp_emails_repo.save_temp_email_messages(email_addr, api_messages)
            if is_cloudflare:
                self._mark_message_synced(sync_key)

    def list_messages(self, email_or_mailbox: str | dict[str, Any], *, sync_remote: bool = True) -> list[dict[str, Any]]:
        mailbox = self._get_mailbox_descriptor(email_or_mailbox)
        email_addr = str(mailbox.get("email") or "")
        rows = temp_emails_repo.get_temp_email_messages(email_addr)
        if sync_remote and not (rows and self._has_recent_inbound_push(mailbox)):
            mailbox = self._ensure_provider_credentials(mailbox)
            email_addr = str(mailbox.get("email") or email_addr)
            provider = self._get_provider(mailbox=mailbox)
            self._sync_provider_messages(provider, mailbox)
            rows = temp_emails_repo.get_temp_email_messages(email_addr)
        return [_message_summary(email_addr, row) for row in rows]

    def get_message_detail(
        self,
        email_or_mailbox: str | dict[str, Any],
        message_id: str,
        *,
        refresh_if_missing: bool = True,
    ) -> dict[str, Any]:
        mailbox = self._get_mailbox_descriptor(email_or_mailbox)
        email_addr = str(mailbox.get("email") or "")
        row = temp_emails_repo.get_temp_email_message_by_id(message_id, email_addr=email_addr)
        if refresh_if_missing and row is None:
            # BUG-03: cache-only 场景（refresh_if_missing=False）不得依赖 provider 初始化。
            mailbox = self._ensure_provider_credentials(mailbox)
            provider = self._get_provider(mailbox=mailbox)
            try:
                api_row = provider.get_message_detail(mailbox, message_id)
            except TempMailProviderReadError as exc:
                raise self._provider_read_failed(
                    exc,
                    mailbox=mailbox,
                    operation="get_message_detail",
                    message_id=message_id,
                ) from exc
            if api_row:
                temp_emails_repo.save_temp_email_messages(email_addr, [api_row])
                row = temp_emails_repo.get_temp_email_message_by_id(message_id, email_addr=email_addr)
        if not row:
            raise TempMailError("TEMP_EMAIL_MESSAGE_NOT_FOUND", "邮件不存在", status=404)
        return _message_detail(email_addr, row)

    def get_cached_message_row(self, email_or_mailbox: str | dict[str, Any], message_id: str) -> dict[str, Any] | None:
        mailbox = self._get_mailbox_descriptor(email_or_mailbox)
        email_addr = str(mailbox.get("email") or "")
        return temp_emails_repo.get_temp_email_message_by_id(message_id, email_addr=email_addr)

    def refresh_message_detail(self, email_or_mailbox: str | dict[str, Any], message_id: str) -> dict[str, Any]:
        mailbox = self._get_mailbox_descriptor(email_or_mailbox)
        mailbox = self._ensure_provider_credentials(mailbox)
        email_addr = str(mailbox.get("email") or "")
        provider = self._get_provider(mailbox=mailbox)
        try:
            api_row = provider.get_message_detail(mailbox, message_id)
        except TempMailProviderReadError as exc:
            raise self._provider_read_failed(
                exc,
                mailbox=mailbox,
                operation="refresh_message_detail",
                message_id=message_id,
            ) from exc
        if api_row:
            temp_emails_repo.save_temp_email_messages(email_addr, [api_row])
        row = temp_emails_repo.get_temp_email_message_by_id(message_id, email_addr=email_addr)
        if not row:
            raise TempMailError("TEMP_EMAIL_MESSAGE_NOT_FOUND", "邮件不存在", status=404)
        return _message_detail(email_addr, row)

    def delete_message(self, email_or_mailbox: str | dict[str, Any], message_id: str) -> bool:
        mailbox = self._get_mailbox_descriptor(email_or_mailbox)
        mailbox = self._ensure_provider_credentials(mailbox)
        email_addr = str(mailbox.get("email") or "")
        provider = self._get_provider(mailbox=mailbox)
        if not provider.delete_message(mailbox, message_id):
            raise TempMailError("TEMP_EMAIL_MESSAGE_DELETE_FAILED", "删除失败", status=502)
        return temp_emails_repo.delete_temp_email_message(message_id, email_addr=email_addr)

    def clear_messages(self, email_or_mailbox: str | dict[str, Any]) -> bool:
        mailbox = self._get_mailbox_descriptor(email_or_mailbox)
        mailbox = self._ensure_provider_credentials(mailbox)
        email_addr = str(mailbox.get("email") or "")
        provider = self._get_provider(mailbox=mailbox)
        if not provider.clear_messages(mailbox):
            raise TempMailError("TEMP_EMAIL_MESSAGES_CLEAR_FAILED", "清空失败", status=502)
        from outlook_web.db import get_db

        db = get_db()
        db.execute("DELETE FROM temp_email_messages WHERE email_address = ?", (email_addr,))
        db.commit()
        return True

    def send_message(
        self,
        email_or_mailbox: str | dict[str, Any],
        *,
        to_email: str,
        subject: str,
        content: str,
        is_html: bool = False,
        from_name: str = "",
        to_name: str = "",
    ) -> dict[str, Any]:
        normalized_to = parseaddr(str(to_email or "").strip())[1]
        normalized_subject = str(subject or "").strip()
        normalized_content = str(content or "")
        if not normalized_to or "@" not in normalized_to:
            raise TempMailError("INVALID_PARAM", "收件邮箱地址无效", status=400)
        if not normalized_subject:
            raise TempMailError("INVALID_PARAM", "邮件主题不能为空", status=400)
        if not normalized_content.strip():
            raise TempMailError("INVALID_PARAM", "邮件正文不能为空", status=400)
        if len(normalized_to) > 320 or len(normalized_subject) > 500 or len(normalized_content) > 500_000:
            raise TempMailError("INVALID_PARAM", "邮件字段长度超过限制", status=400)

        mailbox, provider = self._provider_for_capability(email_or_mailbox, "send_message")
        try:
            result = provider.send_message(
                mailbox,
                to_email=normalized_to,
                subject=normalized_subject,
                content=normalized_content,
                is_html=bool(is_html),
                from_name=str(from_name or "").strip()[:200],
                to_name=str(to_name or "").strip()[:200],
            )
        except TempMailProviderReadError as exc:
            raise self._provider_read_failed(exc, mailbox=mailbox, operation="send_message") from exc
        except NotImplementedError as exc:
            raise TempMailError(
                "TEMP_EMAIL_CAPABILITY_UNSUPPORTED",
                "当前临时邮箱 Provider 不支持发信",
                status=400,
            ) from exc
        if not isinstance(result, dict) or not result.get("success"):
            raise TempMailError("TEMP_EMAIL_SEND_FAILED", "邮件发送失败", status=502)
        return result

    def list_sent_messages(
        self,
        email_or_mailbox: str | dict[str, Any],
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        mailbox, provider = self._provider_for_capability(email_or_mailbox, "list_sent_messages")
        try:
            result = provider.list_sent_messages(
                mailbox,
                limit=max(1, min(int(limit), 100)),
                offset=max(0, int(offset)),
            )
        except TempMailProviderReadError as exc:
            raise self._provider_read_failed(exc, mailbox=mailbox, operation="list_sent_messages") from exc
        except NotImplementedError as exc:
            raise TempMailError(
                "TEMP_EMAIL_CAPABILITY_UNSUPPORTED",
                "当前临时邮箱 Provider 不支持发件箱",
                status=400,
            ) from exc
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            raise TempMailError("UPSTREAM_BAD_PAYLOAD", "发件箱返回格式错误", status=502)
        return {"items": result["items"], "count": int(result.get("count") or 0)}

    def delete_sent_message(self, email_or_mailbox: str | dict[str, Any], message_id: str) -> bool:
        normalized_id = str(message_id or "").strip()
        if not normalized_id:
            raise TempMailError("INVALID_PARAM", "发件记录 ID 不能为空", status=400)
        mailbox, provider = self._provider_for_capability(email_or_mailbox, "delete_sent_message")
        try:
            deleted = provider.delete_sent_message(mailbox, normalized_id)
        except TempMailProviderReadError as exc:
            raise self._provider_read_failed(exc, mailbox=mailbox, operation="delete_sent_message") from exc
        except NotImplementedError as exc:
            raise TempMailError(
                "TEMP_EMAIL_CAPABILITY_UNSUPPORTED",
                "当前临时邮箱 Provider 不支持删除发件记录",
                status=400,
            ) from exc
        if not deleted:
            raise TempMailError("TEMP_EMAIL_SENT_MESSAGE_DELETE_FAILED", "删除发件记录失败", status=502)
        return True

    def clear_sent_messages(self, email_or_mailbox: str | dict[str, Any]) -> bool:
        mailbox, provider = self._provider_for_capability(
            email_or_mailbox,
            "clear_sent_messages",
            ensure_credentials=True,
        )
        try:
            cleared = provider.clear_sent_messages(mailbox)
        except TempMailProviderReadError as exc:
            raise self._provider_read_failed(exc, mailbox=mailbox, operation="clear_sent_messages") from exc
        except NotImplementedError as exc:
            raise TempMailError(
                "TEMP_EMAIL_CAPABILITY_UNSUPPORTED",
                "当前临时邮箱 Provider 不支持清空发件箱",
                status=400,
            ) from exc
        if not cleared:
            raise TempMailError("TEMP_EMAIL_SENT_MESSAGES_CLEAR_FAILED", "清空发件箱失败", status=502)
        return True

    def extract_verification(
        self,
        email_or_mailbox: str | dict[str, Any],
        *,
        code_regex: str | None = None,
        code_length: str | None = None,
        code_source: str = "all",
        expected_field: str | None = None,
    ) -> dict[str, Any]:
        # 临时邮箱验证码提取入口，结构与 external_api.get_verification_result 对齐，共享日志埋点
        started_at = time.time()
        mailbox = self._get_mailbox_descriptor(email_or_mailbox)
        record = dict(mailbox.get("record") or {})
        log_account_id = encode_temp_mail_log_account_id(record.get("id"))
        # 负数编码临时邮箱 ID，使其与 accounts 正数 ID 共享 verification_extract_logs 表
        email_addr = str(mailbox.get("email") or "")
        extracted: dict[str, Any] | None = None
        error_code: str | None = None
        try:
            messages = self.list_messages(mailbox, sync_remote=True)
            if not messages:
                raise TempMailError("TEMP_EMAIL_MESSAGE_NOT_FOUND", "未找到邮件", status=404)
            latest = messages[0]
            detail = self.get_message_detail(mailbox, latest["id"])
            extracted = extract_verification_info_with_options(
                {
                    "subject": detail.get("subject") or "",
                    "body": detail.get("content") or "",
                    "body_html": detail.get("html_content") or "",
                    "body_preview": latest.get("content_preview") or "",
                },
                code_regex=code_regex,
                code_length=code_length,
                code_source=code_source,
                enforce_mutual_exclusion=False,
            )
            ai_config = get_verification_ai_runtime_config()
            if ai_config.get("enabled") and not is_verification_ai_config_complete(ai_config):
                raise TempMailError(
                    "VERIFICATION_AI_CONFIG_INCOMPLETE",
                    "验证码 AI 已开启，请完整填写 Base URL、API Key、模型 ID",
                    status=400,
                )
            extracted = enhance_verification_with_ai_fallback(
                email={
                    "subject": detail.get("subject") or "",
                    "body": detail.get("content") or "",
                    "body_html": detail.get("html_content") or "",
                    "body_preview": latest.get("content_preview") or "",
                },
                extracted=extracted,
                code_regex=code_regex,
                code_length=code_length,
                code_source=code_source,
                enforce_mutual_exclusion=False,
            )
            # 与外部 API 保持一致：应用置信度门控
            extracted = apply_confidence_gate(extracted, enforce_mutual_exclusion=False)
            extracted["matched_email_id"] = latest["id"]
            extracted["from"] = detail.get("from_address") or latest.get("from_address") or ""
            extracted["subject"] = detail.get("subject") or latest.get("subject") or ""
            extracted["received_at"] = detail.get("created_at") or latest.get("created_at") or ""
            extracted["email"] = email_addr
            extracted = _shape_verification_result_by_expected_field(extracted, expected_field)
            if expected_field and not extracted.get(expected_field):
                error = _build_expected_field_not_found_error(expected_field)
                error.data = extracted
                raise error
            if not extracted.get("verification_code") and not extracted.get("verification_link"):
                raise TempMailError(
                    "VERIFICATION_CODE_NOT_FOUND",
                    "未找到验证码或验证链接",
                    status=404,
                    data=extracted,
                )
            return extracted
        except TempMailError as exc:
            error_code = exc.code
            raise
        except Exception as exc:
            error_code = type(exc).__name__.upper()
            raise
        finally:
            # finally 保证无论提取成功/失败都写入日志，与 external_api 路径保持一致的埋点策略
            result_type, code_found = resolve_extract_log_outcome(extracted)
            write_verification_extract_log(
                account_id=log_account_id,
                channel=(
                    "ai_fallback"
                    if extracted
                    and extracted.get("_used_ai")
                    and (extracted.get("verification_code") or extracted.get("verification_link"))
                    else "temp_mail"
                ),
                started_at=started_at,
                finished_at=time.time(),
                result_type=result_type,
                code_found=code_found,
                used_ai=bool(extracted and extracted.get("_used_ai")),
                error_code=error_code,
                trace_id=None,
            )


_service: TempMailService | None = None


def get_temp_mail_service() -> TempMailService:
    global _service
    if _service is None:
        _service = TempMailService()
    return _service
