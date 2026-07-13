from __future__ import annotations

import copy
import os
from typing import Optional

_APP_INSTANCE = None


def create_app(*, autostart_scheduler: Optional[bool] = None):
    """
    应用工厂（迁移期实现）：
    - 统一装配入口，便于测试与后续 Blueprint/分层拆分
    - 控制 import-time 副作用：初始化/调度器启动放到 create_app 中受控执行
    - routes 采用 Blueprint 模块化注册（URL 不变）
    """
    global _APP_INSTANCE

    if _APP_INSTANCE is None:
        from pathlib import Path

        from flask import Flask
        from flask.testing import FlaskClient
        from werkzeug.exceptions import HTTPException
        from werkzeug.middleware.proxy_fix import ProxyFix

        from outlook_web import config
        from outlook_web import config as app_config
        from outlook_web.db import init_db, register_db
        from outlook_web.middleware import (
            register_request_id,
            register_security_headers,
        )
        from outlook_web.routes import (
            accounts,
            audit,
            emails,
            overview,
            plugins,
            pool_admin,
            scheduler,
            settings,
            system,
            tags,
            temp_emails,
        )
        from outlook_web.security.csrf import csrf, csrf_exempt
        from outlook_web.services.scheduler import start_scheduler

        app = Flask(__name__)
        app.config.from_object(config)

        if app_config.PROXY_FIX_ENABLED:
            app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

        register_db(app)
        csrf.init_app(app)
        register_request_id(app)
        register_security_headers(app)

        init_db(app)

        app.register_blueprint(tags.create_blueprint())
        app.register_blueprint(accounts.create_blueprint())
        app.register_blueprint(emails.create_blueprint())
        app.register_blueprint(temp_emails.create_blueprint(csrf_exempt=csrf_exempt))
        app.register_blueprint(settings.create_blueprint())
        app.register_blueprint(plugins.create_blueprint(csrf_exempt=csrf_exempt))
        app.register_blueprint(scheduler.create_blueprint())
        app.register_blueprint(system.create_blueprint())
        app.register_blueprint(audit.create_blueprint())
        app.register_blueprint(overview.create_blueprint())
        app.register_blueprint(pool_admin.create_blueprint())

        if autostart_scheduler is None:
            autostart_scheduler = app_config.AUTOSTART_SCHEDULER
        if autostart_scheduler:
            start_scheduler(app)

        _APP_INSTANCE = app

    return _APP_INSTANCE
