from __future__ import annotations

from typing import Any

from flask import jsonify, request

from outlook_web.security.auth import api_key_required, get_external_api_consumer
from outlook_web.security.external_api_guard import external_api_guards
from outlook_web.services import external_api as external_api_service
from outlook_web.services import mailbox_resolver
from outlook_web.services.temp_mail_service import TempMailError, get_temp_mail_service

temp_mail_service = get_temp_mail_service()


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _audit(endpoint: str, status: str, *, details: dict[str, Any], email_addr: str = "") -> None:
    external_api_service.audit_external_api_access(
        action="external_api_access",
        email_addr=email_addr,
        endpoint=endpoint,
        status=status,
        details=details,
    )


def _forbidden(endpoint: str, *, email_addr: str = "", reason: str = "consumer_mismatch"):
    _audit(endpoint, "error", details={"code": "FORBIDDEN", "reason": reason}, email_addr=email_addr)
    return jsonify(external_api_service.fail("FORBIDDEN", "当前 API Key 无权操作该任务邮箱", data={"reason": reason})), 403


def _external_error(endpoint: str, email_addr: str, exc: Exception):
    if isinstance(exc, external_api_service.ExternalApiError):
        _audit(endpoint, "error", details={"code": exc.code}, email_addr=email_addr)
        return jsonify(external_api_service.fail(exc.code, exc.message, data=exc.data)), exc.status
    if isinstance(exc, TempMailError):
        _audit(endpoint, "error", details={"code": exc.code}, email_addr=email_addr)
        return jsonify(external_api_service.fail(exc.code, exc.message, data=exc.data)), exc.status
    _audit(endpoint, "error", details={"code": "INTERNAL_ERROR", "err": type(exc).__name__}, email_addr=email_addr)
    return jsonify(external_api_service.fail("INTERNAL_ERROR", "服务内部错误")), 500


def _ensure_external_temp_mail_access(email_addr: str) -> dict[str, Any]:
    mailbox = mailbox_resolver.resolve_mailbox(email_addr, discover_remote=True)
    mailbox_resolver.ensure_mailbox_can_mutate(
        mailbox,
        consumer=get_external_api_consumer() or {},
    )
    if str(mailbox.get("kind") or "") != "temp":
        raise external_api_service.InvalidParamError("目标邮箱不是临时邮箱")
    return mailbox


@api_key_required
@external_api_guards()
def api_external_apply_temp_email():
    endpoint = "/api/external/temp-emails/apply"
    body = request.get_json(silent=True) or {}
    consumer = get_external_api_consumer() or {}

    try:
        mailbox = temp_mail_service.apply_task_mailbox(
            consumer_key=str(consumer.get("consumer_key") or ""),
            caller_id=str(body.get("caller_id") or "").strip(),
            task_id=str(body.get("task_id") or "").strip(),
            prefix=str(body.get("prefix") or "").strip() or None,
            domain=str(body.get("domain") or "").strip() or None,
        )
        payload = {
            "email": mailbox["email"],
            "prefix": mailbox["prefix"],
            "domain": mailbox["domain"],
            "task_token": mailbox["task_token"],
            "created_at": mailbox["created_at"],
            "visible_in_ui": False,
            "status": mailbox["status"],
        }
        _audit(
            endpoint,
            "ok",
            details={"task_token": mailbox["task_token"], "domain": mailbox["domain"]},
            email_addr=mailbox["email"],
        )
        return jsonify(external_api_service.ok(payload))
    except TempMailError as exc:
        _audit(endpoint, "error", details={"code": exc.code}, email_addr="")
        return jsonify(external_api_service.fail(exc.code, exc.message, data=exc.data)), exc.status
    except Exception as exc:
        _audit(endpoint, "error", details={"code": "INTERNAL_ERROR", "err": type(exc).__name__}, email_addr="")
        return jsonify(external_api_service.fail("INTERNAL_ERROR", "服务内部错误")), 500


@api_key_required
@external_api_guards()
def api_external_finish_temp_email(task_token: str):
    endpoint = "/api/external/temp-emails/{task_token}/finish"
    consumer = get_external_api_consumer() or {}
    mailbox = temp_mail_service.get_task_mailbox(task_token)
    if not mailbox:
        _audit(endpoint, "error", details={"code": "TASK_TOKEN_INVALID", "task_token": task_token}, email_addr="")
        return jsonify(external_api_service.fail("TASK_TOKEN_INVALID", "任务令牌无效")), 404

    if str(mailbox.get("consumer_key") or "").strip() != str(consumer.get("consumer_key") or "").strip():
        return _forbidden(endpoint, email_addr=str(mailbox.get("email") or ""))

    try:
        result = temp_mail_service.finish_task_mailbox(task_token)
        cancelled = external_api_service.cancel_pending_probes_for_email(
            str(result.get("email") or ""),
            error_message="探测因任务邮箱 finish 而被取消",
        )
        body = request.get_json(silent=True) or {}
        detail_text = str(body.get("detail") or "").strip()
        _audit(
            endpoint,
            "ok",
            details={
                "task_token": task_token,
                "cancelled_probes": cancelled,
                "result": str(body.get("result") or "").strip(),
                "detail": detail_text[:200],
            },
            email_addr=str(result.get("email") or ""),
        )
        return jsonify(
            external_api_service.ok(
                {"task_token": task_token, "status": result["status"], "email": str(result.get("email") or "")}
            )
        )
    except TempMailError as exc:
        _audit(
            endpoint, "error", details={"code": exc.code, "task_token": task_token}, email_addr=str(mailbox.get("email") or "")
        )
        return jsonify(external_api_service.fail(exc.code, exc.message, data=exc.data)), exc.status
    except Exception as exc:
        _audit(
            endpoint,
            "error",
            details={"code": "INTERNAL_ERROR", "err": type(exc).__name__, "task_token": task_token},
            email_addr=str(mailbox.get("email") or ""),
        )
        return jsonify(external_api_service.fail("INTERNAL_ERROR", "服务内部错误")), 500


@api_key_required
@external_api_guards()
def api_external_send_temp_email(email_addr: str):
    endpoint = "/api/external/temp-emails/{email}/send"
    normalized_email = str(email_addr or "").strip()
    body = request.get_json(silent=True) or {}
    try:
        mailbox = _ensure_external_temp_mail_access(normalized_email)
        result = temp_mail_service.send_message(
            mailbox,
            to_email=str(body.get("to_email") or body.get("to") or "").strip(),
            to_name=str(body.get("to_name") or "").strip(),
            from_name=str(body.get("from_name") or "").strip(),
            subject=str(body.get("subject") or ""),
            content=str(body.get("content") or body.get("body") or ""),
            is_html=_parse_bool(body.get("is_html"), default=False),
        )
        _audit(
            endpoint,
            "ok",
            details={
                "to": str(body.get("to_email") or body.get("to") or "").strip(),
                "is_html": _parse_bool(body.get("is_html"), default=False),
            },
            email_addr=normalized_email,
        )
        return jsonify(external_api_service.ok(result, message="message sent"))
    except Exception as exc:
        return _external_error(endpoint, normalized_email, exc)


@api_key_required
@external_api_guards()
def api_external_get_temp_email_sent_messages(email_addr: str):
    endpoint = "/api/external/temp-emails/{email}/sent"
    normalized_email = str(email_addr or "").strip()
    try:
        mailbox = _ensure_external_temp_mail_access(normalized_email)
        try:
            limit = int(request.args.get("limit") or 100)
            offset = int(request.args.get("offset") or 0)
        except (TypeError, ValueError) as exc:
            raise external_api_service.InvalidParamError("分页参数无效") from exc
        if limit < 1 or limit > 100 or offset < 0:
            raise external_api_service.InvalidParamError("分页参数无效")
        result = temp_mail_service.list_sent_messages(mailbox, limit=limit, offset=offset)
        _audit(
            endpoint, "ok", details={"count": result["count"], "limit": limit, "offset": offset}, email_addr=normalized_email
        )
        return jsonify(external_api_service.ok({**result, "limit": limit, "offset": offset}))
    except Exception as exc:
        return _external_error(endpoint, normalized_email, exc)


@api_key_required
@external_api_guards()
def api_external_delete_temp_email_sent_message(email_addr: str, message_id: str):
    endpoint = "/api/external/temp-emails/{email}/sent/{message_id}"
    normalized_email = str(email_addr or "").strip()
    try:
        mailbox = _ensure_external_temp_mail_access(normalized_email)
        temp_mail_service.delete_sent_message(mailbox, message_id)
        _audit(endpoint, "ok", details={"message_id": message_id}, email_addr=normalized_email)
        return jsonify(external_api_service.ok({"message_id": message_id}, message="sent item deleted"))
    except Exception as exc:
        return _external_error(endpoint, normalized_email, exc)


@api_key_required
@external_api_guards()
def api_external_clear_temp_email_sent_messages(email_addr: str):
    endpoint = "/api/external/temp-emails/{email}/sent"
    normalized_email = str(email_addr or "").strip()
    try:
        mailbox = _ensure_external_temp_mail_access(normalized_email)
        temp_mail_service.clear_sent_messages(mailbox)
        _audit(endpoint, "ok", details={"cleared": True}, email_addr=normalized_email)
        return jsonify(external_api_service.ok({"cleared": True}, message="sent items cleared"))
    except Exception as exc:
        return _external_error(endpoint, normalized_email, exc)


@api_key_required
@external_api_guards()
def api_external_ingest_temp_email():
    endpoint = "/api/external/temp-emails/inbound"
    if request.content_length and request.content_length > 2_000_000:
        return jsonify(external_api_service.fail("PAYLOAD_TOO_LARGE", "入站邮件负载过大")), 413

    body = request.get_json(silent=True)
    email_addr = str((body or {}).get("email") or "").strip()
    if not isinstance(body, dict):
        _audit(endpoint, "error", details={"code": "INVALID_PARAM"}, email_addr=email_addr)
        return jsonify(external_api_service.fail("INVALID_PARAM", "请求体必须是 JSON 对象")), 400

    try:
        result = temp_mail_service.ingest_cloudflare_inbound(body)
        _audit(
            endpoint,
            "ok",
            details={"message_id": result["message_id"], "mailbox_type": result["mailbox_type"]},
            email_addr=result["email"],
        )
        return jsonify(external_api_service.ok(result))
    except TempMailError as exc:
        _audit(endpoint, "error", details={"code": exc.code}, email_addr=email_addr)
        return jsonify(external_api_service.fail(exc.code, exc.message, data=exc.data)), exc.status
    except Exception as exc:
        _audit(endpoint, "error", details={"code": "INTERNAL_ERROR", "err": type(exc).__name__}, email_addr=email_addr)
        return jsonify(external_api_service.fail("INTERNAL_ERROR", "服务内部错误")), 500
