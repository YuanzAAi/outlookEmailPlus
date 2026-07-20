from __future__ import annotations

from typing import Callable, Optional

from flask import Blueprint

from outlook_web.controllers import external_temp_emails as external_temp_emails_controller


def create_blueprint(csrf_exempt: Optional[Callable] = None) -> Blueprint:
    bp = Blueprint("external_temp_emails", __name__)
    handlers = [
        (
            "/api/external/temp-emails/inbound",
            external_temp_emails_controller.api_external_ingest_temp_email,
            ["POST"],
        ),
        (
            "/api/external/temp-emails/apply",
            external_temp_emails_controller.api_external_apply_temp_email,
            ["POST"],
        ),
        (
            "/api/external/temp-emails/<task_token>/finish",
            external_temp_emails_controller.api_external_finish_temp_email,
            ["POST"],
        ),
        (
            "/api/external/temp-emails/<path:email_addr>/send",
            external_temp_emails_controller.api_external_send_temp_email,
            ["POST"],
        ),
        (
            "/api/external/temp-emails/<path:email_addr>/sent",
            external_temp_emails_controller.api_external_get_temp_email_sent_messages,
            ["GET"],
        ),
        (
            "/api/external/temp-emails/<path:email_addr>/sent/<path:message_id>",
            external_temp_emails_controller.api_external_delete_temp_email_sent_message,
            ["DELETE"],
        ),
        (
            "/api/external/temp-emails/<path:email_addr>/sent",
            external_temp_emails_controller.api_external_clear_temp_email_sent_messages,
            ["DELETE"],
        ),
    ]

    for path, handler, methods in handlers:
        view_func = csrf_exempt(handler) if csrf_exempt else handler
        bp.add_url_rule(path, view_func=view_func, methods=methods)
    return bp
