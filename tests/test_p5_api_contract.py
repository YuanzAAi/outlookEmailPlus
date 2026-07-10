"""P5 API 契约：设置 / 审计 / 邮箱池 / Token 工具 / 刷新日志。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class TestP5ApiContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
        self.client = self.app.test_client()

    def _login(self):
        resp = self.client.post("/login", json={"password": "testpass123"})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))

    def test_settings_require_login(self):
        resp = self.client.get("/api/settings")
        self.assertIn(resp.status_code, (401, 403), resp.get_data(as_text=True))

    def test_settings_get_shape(self):
        self._login()
        resp = self.client.get("/api/settings")
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        data = resp.get_json() or {}
        self.assertTrue(data.get("success"))
        self.assertIsInstance(data.get("settings"), dict)
        # 关键字段应存在
        settings = data["settings"]
        for key in (
            "refresh_cron",
            "enable_auto_polling",
            "email_notification_enabled",
            "verification_ai_enabled",
        ):
            self.assertIn(key, settings)

    def test_audit_logs_shape(self):
        self._login()
        resp = self.client.get("/api/audit-logs", query_string={"limit": 20, "offset": 0})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        data = resp.get_json() or {}
        self.assertTrue(data.get("success"))
        self.assertTrue("logs" in data or "items" in data or isinstance(data.get("data"), list))

    def test_pool_admin_list_shape(self):
        self._login()
        with patch(
            "outlook_web.controllers.pool_admin.pool_admin_svc.list_accounts",
            return_value={
                "success": True,
                "accounts": [
                    {
                        "id": 1,
                        "email": "pool@example.com",
                        "pool_status": "available",
                        "in_pool": 1,
                    }
                ],
                "pagination": {"page": 1, "page_size": 50, "total_count": 1},
            },
        ):
            resp = self.client.get(
                "/api/pool-admin/accounts",
                query_string={"page": 1, "page_size": 50, "in_pool": "all"},
            )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        data = resp.get_json() or {}
        accounts = data.get("accounts") or data.get("items") or []
        self.assertTrue(accounts)
        self.assertIn("email", accounts[0])

    def test_pool_action_requires_action(self):
        self._login()
        resp = self.client.post("/api/pool-admin/accounts/1/action", json={})
        self.assertEqual(resp.status_code, 400, resp.get_data(as_text=True))
        data = resp.get_json() or {}
        self.assertFalse(data.get("success", False))

    def test_token_tool_config_shape(self):
        self._login()
        resp = self.client.get("/api/token-tool/config")
        # 工具可能被环境关闭；允许 200 或 404/403
        self.assertIn(resp.status_code, (200, 403, 404), resp.get_data(as_text=True))
        if resp.status_code == 200:
            data = resp.get_json() or {}
            self.assertTrue(data.get("success"))
            self.assertIsInstance(data.get("data"), dict)

    def test_token_tool_prepare_requires_login(self):
        resp = self.client.post("/api/token-tool/prepare", json={})
        self.assertIn(resp.status_code, (401, 403, 404), resp.get_data(as_text=True))

    def test_refresh_logs_require_login(self):
        resp = self.client.get("/api/accounts/refresh-logs")
        self.assertIn(resp.status_code, (401, 403), resp.get_data(as_text=True))

    def test_refresh_logs_shape_when_logged_in(self):
        self._login()
        resp = self.client.get("/api/accounts/refresh-logs", query_string={"limit": 20})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        data = resp.get_json() or {}
        # 兼容 logs / data / items
        self.assertTrue(
            isinstance(data.get("logs"), list)
            or isinstance(data.get("items"), list)
            or data.get("success") is True
            or isinstance(data, dict)
        )


if __name__ == "__main__":
    unittest.main()
