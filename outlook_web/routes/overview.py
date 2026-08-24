from __future__ import annotations

from flask import Blueprint

from outlook_web.controllers import overview as overview_controller


def create_blueprint() -> Blueprint:
    bp = Blueprint("overview", __name__)
    bp.add_url_rule("/api/overview/summary", view_func=overview_controller.api_get_overview_summary, methods=["GET"])
    bp.add_url_rule("/api/overview/verification", view_func=overview_controller.api_get_overview_verification, methods=["GET"])
    bp.add_url_rule(
        "/api/overview/verification-stats", view_func=overview_controller.api_get_overview_verification, methods=["GET"]
    )
    bp.add_url_rule("/api/overview/external-api", view_func=overview_controller.api_get_overview_external_api, methods=["GET"])
    bp.add_url_rule(
        "/api/overview/external-api-stats", view_func=overview_controller.api_get_overview_external_api, methods=["GET"]
    )
    bp.add_url_rule("/api/overview/pool", view_func=overview_controller.api_get_overview_pool, methods=["GET"])
    bp.add_url_rule("/api/overview/pool-stats", view_func=overview_controller.api_get_overview_pool, methods=["GET"])
    bp.add_url_rule("/api/overview/activity", view_func=overview_controller.api_get_overview_activity, methods=["GET"])
    bp.add_url_rule("/api/overview/performance", view_func=overview_controller.api_get_overview_performance, methods=["GET"])
    bp.add_url_rule("/api/performance/client", view_func=overview_controller.api_report_client_performance, methods=["POST"])
    return bp
