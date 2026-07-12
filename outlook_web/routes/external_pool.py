from __future__ import annotations

from typing import Callable, Optional

from flask import Blueprint

from outlook_web.controllers import external_pool as external_pool_controller


def create_blueprint(csrf_exempt: Optional[Callable] = None) -> Blueprint:
    """创建 external_pool Blueprint。

    外部池接口面向 worker/合作方直接调用，POST 请求不应被浏览器态 CSRF 校验拦截。
    这里统一在 Blueprint 装配阶段透传 csrf_exempt，避免后续新增端点时遗漏。
    """
    bp = Blueprint("external_pool", __name__)
    handlers = [
        (
            "/api/external/pool/claim-random",
            external_pool_controller.api_external_pool_claim_random,
            ["POST"],
        ),
        (
            "/api/external/pool/claim-domain",
            external_pool_controller.api_external_pool_claim_domain,
            ["POST"],
        ),
        (
            "/api/external/pool/claim-release",
            external_pool_controller.api_external_pool_claim_release,
            ["POST"],
        ),
        (
            "/api/external/pool/claim-complete",
            external_pool_controller.api_external_pool_claim_complete,
            ["POST"],
        ),
        (
            "/api/external/pool/stats",
            external_pool_controller.api_external_pool_stats,
            ["GET"],
        ),
    ]

    # 所有 external_pool 端点都走同一套鉴权链路，这里只负责统一挂载 CSRF 豁免。
    for path, handler, methods in handlers:
        view_func = csrf_exempt(handler) if csrf_exempt else handler
        bp.add_url_rule(path, view_func=view_func, methods=methods)
    return bp
