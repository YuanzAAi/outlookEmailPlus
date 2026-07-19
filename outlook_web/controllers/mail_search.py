from __future__ import annotations

from typing import Any

from flask import current_app, jsonify, request

from outlook_web.audit import log_audit
from outlook_web.errors import build_error_response
from outlook_web.security.auth import login_required
from outlook_web.services import mail_search as mail_search_service


@login_required
def api_start_mail_search() -> Any:
    try:
        job = mail_search_service.start_job(current_app._get_current_object(), request.get_json(silent=True) or {})
    except mail_search_service.MailSearchError as exc:
        return build_error_response("INVALID_PARAM", str(exc), message_en="Invalid search parameters", status=400)
    log_audit("search", "mail", job["job_id"], f"启动全局邮件检索：{job['params']['query']}")
    return jsonify({"success": True, "job": job}), 202


@login_required
def api_get_mail_search(job_id: str) -> Any:
    try:
        job = mail_search_service.get_job(job_id)
    except mail_search_service.MailSearchError as exc:
        return build_error_response("MAIL_SEARCH_NOT_FOUND", str(exc), message_en="Search job not found", status=404)
    return jsonify({"success": True, "job": job})


@login_required
def api_cancel_mail_search(job_id: str) -> Any:
    try:
        job = mail_search_service.cancel_job(job_id)
    except mail_search_service.MailSearchError as exc:
        return build_error_response("MAIL_SEARCH_NOT_FOUND", str(exc), message_en="Search job not found", status=404)
    return jsonify({"success": True, "job": job})
