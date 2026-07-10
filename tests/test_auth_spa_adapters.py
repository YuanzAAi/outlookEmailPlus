"""SPA / Ant Design Pro 鉴权适配端点测试。"""

from __future__ import annotations

import unittest

from tests._import_app import clear_login_attempts, import_web_app_module


class TestAuthSpaAdapters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
        # 每个用例独立 client，避免 session 串扰
        self.client = self.app.test_client()

    def _login(self, password: str = "testpass123"):
        resp = self.client.post("/login", json={"password": password})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        data = resp.get_json()
        self.assertTrue(data.get("success"))

    def test_current_user_requires_login(self):
        resp = self.client.get("/api/auth/current-user")
        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertFalse(data.get("success"))
        self.assertTrue(data.get("need_login"))

    def test_current_user_after_login(self):
        self._login()
        resp = self.client.get("/api/auth/current-user")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        user = data.get("data") or {}
        self.assertEqual(user.get("access"), "admin")
        self.assertEqual(user.get("userid"), "admin")
        self.assertTrue(user.get("name"))

    def test_api_logout_json(self):
        self._login()
        resp = self.client.post(
            "/api/auth/logout",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))

        # 退出后 current-user 应 401
        resp2 = self.client.get("/api/auth/current-user")
        self.assertEqual(resp2.status_code, 401)
        data2 = resp2.get_json()
        self.assertTrue(data2.get("need_login"))

    def test_legacy_logout_redirect_still_works(self):
        self._login()
        resp = self.client.get("/logout", follow_redirects=False)
        self.assertIn(resp.status_code, (302, 303))
        # 重定向后会话应失效
        resp2 = self.client.get("/api/auth/current-user")
        self.assertEqual(resp2.status_code, 401)

    def test_logout_accept_json_returns_json(self):
        """对抗：旧 /logout 在 Accept: application/json 时也应返回 JSON。"""
        self._login()
        resp = self.client.get(
            "/logout",
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))


if __name__ == "__main__":
    unittest.main()
