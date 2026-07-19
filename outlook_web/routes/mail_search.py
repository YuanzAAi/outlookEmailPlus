from __future__ import annotations

from flask import Blueprint

from outlook_web.controllers import mail_search as mail_search_controller


def create_blueprint() -> Blueprint:
    bp = Blueprint("mail_search", __name__)
    bp.add_url_rule("/api/mail-search", view_func=mail_search_controller.api_start_mail_search, methods=["POST"])
    bp.add_url_rule(
        "/api/mail-search/<job_id>",
        view_func=mail_search_controller.api_get_mail_search,
        methods=["GET"],
    )
    bp.add_url_rule(
        "/api/mail-search/<job_id>/cancel",
        view_func=mail_search_controller.api_cancel_mail_search,
        methods=["POST"],
    )
    return bp
