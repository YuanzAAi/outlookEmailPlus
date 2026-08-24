from __future__ import annotations

import json
from typing import Any

from outlook_web.repositories import settings as settings_repo
from outlook_web.services import gptmail
from outlook_web.services.temp_mail_provider_base import TempMailProviderBase, register_provider

DEFAULT_PREFIX_RULES = {
    "min_length": 1,
    "max_length": 32,
    "pattern": r"^[a-z0-9][a-z0-9._-]*$",
}


def _map_bridge_error_code(error_message: str, *, default_code: str = "TEMP_EMAIL_CREATE_FAILED") -> str:
    text = str(error_message or "").strip().lower()
    if not text:
        return default_code
    if "未配置" in error_message or "config_error" in text:
        return "TEMP_MAIL_PROVIDER_NOT_CONFIGURED"
    if "无效" in error_message or "auth_error" in text or "401" in text or "403" in text:
        return "UNAUTHORIZED"
    if "超时" in error_message or "timeout" in text:
        return "UPSTREAM_TIMEOUT"
    if "不可用" in error_message or "server_error" in text or "http 5" in text:
        return "UPSTREAM_SERVER_ERROR"
    if "格式错误" in error_message or "缺少 email" in error_message or "payload" in text:
        return "UPSTREAM_BAD_PAYLOAD"
    return default_code


def _build_bridge_error_message(error: Any, details: Any = None) -> str:
    message = str(error or "temp mail provider read failed").strip()
    details_text = str(details or "").strip()
    if details_text and details_text not in message:
        return f"{message}（{details_text}）"
    return message


class TempMailProviderReadError(Exception):
    def __init__(self, code: str, message: str, *, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


def _normalize_domain_entries(raw_domains: Any, default_domain: str) -> list[dict[str, Any]]:
    domains: list[dict[str, Any]] = []
    seen: set[str] = set()
    if isinstance(raw_domains, list):
        values = raw_domains
    else:
        values = []

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


@register_provider
class CustomTempMailProvider(TempMailProviderBase):
    provider_name = "custom_domain_temp_mail"
    provider_label = "通用 API (GPTMail)"
    provider_version = "1.0.0"
    provider_author = "OutlookMail Plus"
    provider_capabilities = {
        "create_mailbox": True,
        "list_messages": True,
        "get_message_detail": True,
        "delete_mailbox": False,
        "delete_message": True,
        "clear_messages": True,
    }

    def __init__(self, *, provider_name: str | None = None):
        self.provider_name = settings_repo.get_temp_mail_runtime_provider_name(provider_name)

    def _coerce_email(self, mailbox: dict[str, Any] | str) -> str:
        if isinstance(mailbox, dict):
            return str(mailbox.get("email") or "").strip()
        return str(mailbox or "").strip()

    def _build_meta(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "provider_mailbox_id": "",
            "provider_cursor": "",
            "provider_labels": [],
            "provider_capabilities": dict(self.provider_capabilities),
            "provider_debug": {"bridge": "gptmail"},
        }

    def get_options(self) -> dict[str, Any]:
        raw_domains = settings_repo.get_setting("temp_mail_domains", "[]")
        default_domain = settings_repo.get_setting("temp_mail_default_domain", "").strip()
        raw_prefix_rules = settings_repo.get_setting("temp_mail_prefix_rules", "") or ""

        try:
            domains_payload = json.loads(raw_domains)
        except (json.JSONDecodeError, TypeError):
            domains_payload = []

        try:
            prefix_rules = json.loads(raw_prefix_rules) if raw_prefix_rules else {}
        except (json.JSONDecodeError, TypeError):
            prefix_rules = {}

        normalized_prefix_rules = {
            "min_length": int(prefix_rules.get("min_length", DEFAULT_PREFIX_RULES["min_length"])),
            "max_length": int(prefix_rules.get("max_length", DEFAULT_PREFIX_RULES["max_length"])),
            "pattern": str(prefix_rules.get("pattern") or DEFAULT_PREFIX_RULES["pattern"]),
        }
        api_base_url = settings_repo.get_temp_mail_api_base_url().strip()
        api_key = settings_repo.get_temp_mail_api_key().strip()

        return {
            "domain_strategy": "auto_or_manual",
            "default_mode": "auto",
            "domains": _normalize_domain_entries(domains_payload, default_domain),
            "prefix_rules": normalized_prefix_rules,
            "provider": self.provider_name,
            "provider_name": self.provider_name,
            "provider_label": "temp_mail",
            "api_base_url": api_base_url,
            "configured": bool(api_base_url and api_key),
        }

    def create_mailbox(self, *, prefix: str | None = None, domain: str | None = None) -> dict[str, Any]:
        email_addr, error_message = gptmail.generate_temp_email(prefix, domain)
        if not email_addr:
            message = str(error_message or "temp mail provider create failed")
            return {
                "success": False,
                "error": message,
                "error_code": _map_bridge_error_code(message),
            }
        return {"success": True, "email": email_addr, "meta": self._build_meta()}

    def delete_mailbox(self, mailbox: dict[str, Any]) -> bool:
        return True

    def _raise_read_error(
        self,
        *,
        operation: str,
        email_addr: str,
        result: dict[str, Any],
        message_id: str | None = None,
    ) -> None:
        message = _build_bridge_error_message(result.get("error"), result.get("details"))
        raise TempMailProviderReadError(
            _map_bridge_error_code(message, default_code="UPSTREAM_READ_FAILED"),
            message,
            data={
                "provider_name": self.provider_name,
                "operation": operation,
                "email": email_addr,
                "message_id": message_id,
                "bridge_error_type": str(result.get("error_type") or ""),
                "bridge_details": str(result.get("details") or ""),
            },
        )

    def list_messages(self, mailbox: dict[str, Any] | str) -> list[dict[str, Any]] | None:
        email_addr = self._coerce_email(mailbox)
        result = gptmail.list_temp_emails_result_from_api(email_addr)
        if not result.get("success"):
            self._raise_read_error(operation="list_messages", email_addr=email_addr, result=result)
        emails = result.get("emails")
        if emails is None:
            return []
        if not isinstance(emails, list):
            self._raise_read_error(
                operation="list_messages",
                email_addr=email_addr,
                result={"error": "临时邮箱邮件列表返回格式错误", "error_type": "BAD_PAYLOAD", "details": "emails is not list"},
            )
        return emails

    def get_message_detail(self, mailbox: dict[str, Any] | str, message_id: str) -> dict[str, Any] | None:
        email_addr = self._coerce_email(mailbox)
        result = gptmail.get_temp_email_detail_result_from_api(email_addr, message_id)
        if not result.get("success"):
            self._raise_read_error(
                operation="get_message_detail",
                email_addr=email_addr,
                message_id=message_id,
                result=result,
            )
        data = result.get("data")
        if data is None:
            return None
        if not isinstance(data, dict):
            self._raise_read_error(
                operation="get_message_detail",
                email_addr=email_addr,
                message_id=message_id,
                result={"error": "临时邮箱邮件详情返回格式错误", "error_type": "BAD_PAYLOAD", "details": "detail is not dict"},
            )
        return data

    def delete_message(self, mailbox: dict[str, Any] | str, message_id: str) -> bool:
        email_addr = self._coerce_email(mailbox)
        return gptmail.delete_temp_email_from_api(email_addr, message_id)

    def clear_messages(self, mailbox: dict[str, Any] | str) -> bool:
        email_addr = self._coerce_email(mailbox)
        return gptmail.clear_temp_emails_from_api(email_addr)


@register_provider
class LegacyBridgeTempMailProvider(CustomTempMailProvider):
    """兼容历史 provider 名称 legacy_bridge。"""

    provider_name = "legacy_bridge"
    provider_label = "Legacy Bridge (GPTMail)"
    provider_version = "1.0.0"
    provider_author = "OutlookMail Plus"
