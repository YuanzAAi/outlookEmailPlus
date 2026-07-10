"""临时邮箱 / 插件 API 契约（P4 前端迁移基线）。

覆盖：
- 未登录鉴权
- 列表/options 成功形状
- 生成/删除参数与错误结构
- 插件列表 data.plugins 形状
"""

from __future__ import annotations

import secrets
import unittest
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class TestTempEmailsPluginsApiContract(unittest.TestCase):
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

    # ── temp-emails ──────────────────────────────────────────────

    def test_temp_emails_require_login(self):
        resp = self.client.get("/api/temp-emails")
        self.assertIn(resp.status_code, (401, 403), resp.get_data(as_text=True))

    def test_temp_emails_list_shape(self):
        self._login()
        resp = self.client.get("/api/temp-emails")
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        data = resp.get_json() or {}
        self.assertTrue(data.get("success"))
        self.assertIsInstance(data.get("emails"), list)

    def test_temp_email_options_shape(self):
        self._login()
        with patch(
            "outlook_web.controllers.temp_emails.temp_mail_service.get_options",
            return_value={
                "domains": [{"name": "temp.example", "enabled": True}],
                "providers": [{"name": "custom", "label": "Custom"}],
            },
        ):
            resp = self.client.get("/api/temp-emails/options")
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        data = resp.get_json() or {}
        self.assertTrue(data.get("success"))
        self.assertIsInstance(data.get("options"), dict)
        self.assertIn("domains", data["options"])

    def test_generate_temp_email_success_shape(self):
        self._login()
        email = f"t_{secrets.token_hex(3)}@temp.example"
        with patch(
            "outlook_web.controllers.temp_emails.temp_mail_service.generate_user_mailbox",
            return_value={"email": email, "source": "custom"},
        ):
            resp = self.client.post(
                "/api/temp-emails/generate",
                json={"prefix": "alpha", "domain": "temp.example"},
            )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        data = resp.get_json() or {}
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("email"), email)

    def test_delete_temp_email_not_found(self):
        self._login()
        from outlook_web.services.temp_mail_service import TempMailError

        missing = f"gone_{secrets.token_hex(3)}@temp.example"
        with patch(
            "outlook_web.controllers.temp_emails.temp_mail_service.delete_mailbox",
            side_effect=TempMailError("TEMP_EMAIL_NOT_FOUND", "不存在", status=404),
        ):
            resp = self.client.delete(f"/api/temp-emails/{missing}")
        self.assertEqual(resp.status_code, 404, resp.get_data(as_text=True))
        data = resp.get_json() or {}
        self.assertFalse(data.get("success", False))

    def test_messages_require_existing_mailbox(self):
        self._login()
        from outlook_web.services.temp_mail_service import TempMailError

        missing = f"gone_{secrets.token_hex(3)}@temp.example"
        with patch(
            "outlook_web.controllers.temp_emails.temp_mail_service.get_mailbox",
            side_effect=TempMailError("TEMP_EMAIL_NOT_FOUND", "不存在", status=404),
        ):
            resp = self.client.get(f"/api/temp-emails/{missing}/messages")
        self.assertEqual(resp.status_code, 404, resp.get_data(as_text=True))

    # ── plugins ──────────────────────────────────────────────────

    def test_plugins_require_login(self):
        resp = self.client.get("/api/plugins")
        self.assertIn(resp.status_code, (401, 403), resp.get_data(as_text=True))

    def test_plugins_list_shape(self):
        self._login()
        with patch(
            "outlook_web.controllers.plugins.get_installed_plugins",
            return_value=[],
        ), patch(
            "outlook_web.controllers.plugins.get_available_plugins",
            return_value=[
                {
                    "name": "mock_p4",
                    "display_name": "Mock P4",
                    "version": "0.1.0",
                    "description": "contract",
                }
            ],
        ), patch(
            "outlook_web.controllers.plugins.get_plugin_load_state",
            return_value={},
        ):
            resp = self.client.get("/api/plugins")
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        data = resp.get_json() or {}
        self.assertTrue(data.get("success"))
        plugins = (data.get("data") or {}).get("plugins")
        self.assertIsInstance(plugins, list)
        self.assertTrue(plugins)
        item = plugins[0]
        for key in ("name", "status"):
            self.assertIn(key, item)
        self.assertIn(item["status"], ("installed", "available", "load_failed"))

    def test_install_plugin_missing_name(self):
        self._login()
        resp = self.client.post("/api/plugins/install", json={})
        self.assertEqual(resp.status_code, 400, resp.get_data(as_text=True))
        data = resp.get_json() or {}
        self.assertFalse(data.get("success", False))
        err = data.get("error") or {}
        if isinstance(err, dict):
            self.assertTrue(err.get("code") or err.get("message"))


if __name__ == "__main__":
    unittest.main()
