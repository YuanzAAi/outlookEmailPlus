from __future__ import annotations

import json
from typing import Any

from outlook_web.repositories import accounts as accounts_repo
from outlook_web.repositories import temp_emails as temp_emails_repo
from outlook_web.security.auth import get_external_api_consumer


def _external_api_service():
    from outlook_web.services import external_api as external_api_service

    return external_api_service


def _temp_mail_service():
    from outlook_web.services.temp_mail_service import get_temp_mail_service

    return get_temp_mail_service()


def normalize_alias_email(email_addr: str | None) -> str | None:
    """剥离邮箱别名后缀，返回主地址。

    Outlook/大多数邮箱服务商支持 + 子地址：user+tag@domain → user@domain。
    本函数将 user+anything@domain 规范化为 user@domain，使系统能正确
    将别名地址回溯到主账号。

    不含 + 的地址原样返回。
    """
    if email_addr is None:
        return None
    if not email_addr or "@" not in email_addr:
        return email_addr
    local, domain = email_addr.rsplit("@", 1)
    if "+" in local:
        local = local[: local.index("+")]
    return f"{local}@{domain}"


def is_account_backed_temp_mailbox(account: dict[str, Any] | None) -> bool:
    return str((account or {}).get("provider") or "").strip().lower() == "cloudflare_temp_mail"


def build_account_backed_temp_mailbox(
    account: dict[str, Any],
    temp_mailbox: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta_raw = account.get("temp_mail_meta") or "{}"
    if isinstance(meta_raw, str):
        try:
            meta = json.loads(meta_raw)
        except (json.JSONDecodeError, TypeError):
            meta = {}
    else:
        meta = dict(meta_raw) if meta_raw else {}
    if temp_mailbox:
        meta = temp_emails_repo.merge_temp_email_meta(
            meta,
            temp_mailbox.get("meta"),
            source="cloudflare_temp_mail",
            provider_name="cloudflare_temp_mail",
        )
    if not meta.get("provider_name"):
        meta["provider_name"] = "cloudflare_temp_mail"

    email_addr = str(account.get("email") or "").strip()
    prefix, domain = email_addr.split("@", 1) if "@" in email_addr else (email_addr, "")
    descriptor = {
        "kind": "temp",
        "email": email_addr,
        "source": "cloudflare_temp_mail",
        "provider_name": "cloudflare_temp_mail",
        "mailbox_type": "user",
        "visible_in_ui": False,
        "status": str(account.get("status") or "active"),
        "prefix": prefix,
        "domain": domain,
        "task_token": "",
        "consumer_key": "",
        "caller_id": "",
        "task_id": "",
        "created_at": str(account.get("created_at") or ""),
        "updated_at": str(account.get("updated_at") or ""),
        "finished_at": "",
        "read_capability": "temp_provider",
        "meta": meta,
        "account_backed": True,
        "account_id": account.get("id"),
        "group_id": account.get("group_id"),
    }
    if temp_mailbox:
        record = temp_mailbox.get("record") or {}
        descriptor.update(
            {
                "id": temp_mailbox.get("id"),
                "created_at": str(temp_mailbox.get("created_at") or descriptor["created_at"]),
                "updated_at": str(temp_mailbox.get("updated_at") or descriptor["updated_at"]),
                "record": dict(record) if isinstance(record, dict) else {},
            }
        )
    return descriptor


def resolve_mailbox(email_addr: str, *, discover_remote: bool = True) -> dict[str, Any]:
    external_api_service = _external_api_service()
    requested_email = str(email_addr or "").strip()
    if not requested_email or "@" not in requested_email:
        raise external_api_service.InvalidParamError("email 参数无效")
    account_lookup_email = normalize_alias_email(requested_email) or requested_email

    # BUG-04: accounts 与 temp_emails 同邮箱命中时，必须显式冲突（避免安全边界被绕开）
    account = accounts_repo.get_account_by_email(account_lookup_email)
    temp_mailbox = temp_emails_repo.get_temp_email_by_address(requested_email, view="descriptor")
    temp_source = str((temp_mailbox or {}).get("source") or "").strip().lower()
    if temp_mailbox and temp_source == temp_emails_repo.ACCOUNT_BACKED_TEMP_MAIL_SOURCE and not account:
        raise external_api_service.AccountNotFoundError("账号不存在", data={"email": requested_email})
    if account and temp_mailbox:
        temp_provider = (
            str(temp_mailbox.get("provider_name") or (temp_mailbox.get("meta") or {}).get("provider_name") or "")
            .strip()
            .lower()
        )
        if is_account_backed_temp_mailbox(account) and temp_provider == "cloudflare_temp_mail":
            return build_account_backed_temp_mailbox(account, temp_mailbox)
        raise external_api_service.MailboxConflictError(
            "邮箱冲突：accounts 与 temp_emails 同时存在",
            data={
                "email": requested_email,
                "account_id": account.get("id"),
                "account_type": account.get("account_type"),
                "account_provider": account.get("provider"),
                "temp_email_id": temp_mailbox.get("id"),
                "temp_mailbox_type": temp_mailbox.get("mailbox_type"),
                "temp_status": temp_mailbox.get("status"),
            },
        )
    if account:
        # CF pool 账号：provider=cloudflare_temp_mail → 返回 kind='temp'
        # 使外部读信链路走 TempMailService，而不是 Graph/IMAP
        if is_account_backed_temp_mailbox(account):
            return build_account_backed_temp_mailbox(account)
        return {
            "kind": "account",
            "email": str(account.get("email") or account_lookup_email),
            "source": str(account.get("provider") or account.get("account_type") or "outlook"),
            "provider_name": (
                "imap_generic" if str(account.get("account_type") or "").strip().lower() == "imap" else "outlook_graph"
            ),
            "status": str(account.get("status") or "active"),
            "read_capability": "imap" if str(account.get("account_type") or "").strip().lower() == "imap" else "graph",
            "meta": {"account": account},
        }
    if not temp_mailbox and discover_remote:
        service = _temp_mail_service()
        if service.is_managed_email(requested_email):
            try:
                temp_mailbox = service.discover_user_mailbox(requested_email)
            except Exception as exc:
                from outlook_web.services.temp_mail_service import TempMailError

                if isinstance(exc, TempMailError):
                    raise external_api_service.UpstreamReadFailedError(
                        "临时邮箱上游发现失败",
                        data=exc.data or {"email": requested_email, "provider_error_code": exc.code},
                    ) from exc
                raise
    if temp_mailbox:
        return temp_mailbox

    raise external_api_service.AccountNotFoundError("账号不存在", data={"email": requested_email})


def ensure_mailbox_scope(
    mailbox: dict[str, Any],
    *,
    consumer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """校验邮箱归属范围，不检查邮箱当前是否可读。

    普通账号和用户可见临时邮箱遵循 API Key 的 allowed_emails；
    动态任务邮箱使用申请时绑定的 consumer_key，避免静态白名单阻断任务邮箱。
    """
    external_api_service = _external_api_service()
    consumer = consumer or get_external_api_consumer() or {}
    kind = str(mailbox.get("kind") or "")

    if kind == "account":
        target = mailbox
        mailbox_meta = (mailbox.get("meta") or {}).get("account") or {}
    elif kind == "temp":
        target = mailbox
        mailbox_meta = mailbox
    else:
        raise external_api_service.AccountNotFoundError("账号不存在", data={"email": mailbox.get("email")})

    mailbox_type = str(mailbox_meta.get("mailbox_type") or "user").strip().lower()
    if kind == "temp" and mailbox_type == "task":
        expected_consumer_key = str(mailbox_meta.get("consumer_key") or "").strip()
        actual_consumer_key = str(consumer.get("consumer_key") or "").strip()
        if expected_consumer_key and actual_consumer_key != expected_consumer_key:
            raise external_api_service.EmailScopeForbiddenError(
                "当前 API Key 无权访问该邮箱",
                data={
                    "email": target.get("email"),
                    "consumer_id": consumer.get("id"),
                    "consumer_name": consumer.get("name"),
                },
            )
        return mailbox_meta

    allowed_emails = [str(item or "").strip().lower() for item in (consumer.get("allowed_emails") or [])]
    target_email = str(target.get("email") or "").strip().lower()
    if allowed_emails and target_email not in allowed_emails:
        raise external_api_service.EmailScopeForbiddenError(
            "当前 API Key 无权访问该邮箱",
            data={
                "email": target.get("email"),
                "consumer_id": consumer.get("id"),
                "consumer_name": consumer.get("name"),
            },
        )
    return mailbox_meta


def ensure_mailbox_can_read(
    mailbox: dict[str, Any],
    *,
    consumer: dict[str, Any] | None = None,
    allow_finished: bool = False,
) -> dict[str, Any]:
    external_api_service = _external_api_service()
    consumer = consumer or get_external_api_consumer() or {}
    kind = str(mailbox.get("kind") or "")

    if kind == "account":
        account = ensure_mailbox_scope(mailbox, consumer=consumer)
        return external_api_service.ensure_account_can_read(account)

    if kind != "temp":
        raise external_api_service.AccountNotFoundError("账号不存在", data={"email": mailbox.get("email")})

    temp_mailbox = mailbox if mailbox.get("kind") == "temp" else (mailbox.get("meta") or {}).get("temp_mailbox") or {}
    ensure_mailbox_scope(mailbox, consumer=consumer)
    status = str(temp_mailbox.get("status") or "active").strip().lower()
    if status == "finished" and not allow_finished:
        raise external_api_service.TaskFinishedError(
            "任务邮箱已结束，禁止继续读取",
            data={
                "email": mailbox.get("email"),
                "task_token": temp_mailbox.get("task_token"),
            },
        )
    if status not in {"active", "finished"}:
        raise external_api_service.AccountAccessForbiddenError(
            "当前邮箱不可读取",
            data={"email": mailbox.get("email"), "status": status},
        )

    return temp_mailbox


def ensure_mailbox_can_mutate(
    mailbox: dict[str, Any],
    *,
    consumer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return ensure_mailbox_can_read(mailbox, consumer=consumer, allow_finished=False)
