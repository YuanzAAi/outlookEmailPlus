"""概览 API 契约：登录后五端点应返回 200 与预期顶层字段。

注意：create_app 中 OverviewAwareFlaskClient 会对 /api/overview/* 在无显式
Cookie 头时清空 test client cookie jar，用于强制测未登录 401。
已登录场景必须显式传 Cookie 头（与 tests/test_overview_api.py 一致）。
"""

from __future__ import annotations

import unittest

from tests._import_app import clear_login_attempts, import_web_app_module


class TestOverviewApiContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app
        cls.client = cls.app.test_client()
        # 登录一次，后续用显式 Cookie 头触发“保留 jar”分支
        resp = cls.client.post("/login", json={"password": "testpass123"})
        if resp.status_code != 200:
            raise RuntimeError(f"login failed: {resp.status_code} {resp.data[:200]}")
        cls.session_cookie_marker = "loggedin"

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()

    def _get_authed(self, path: str):
        return self.client.get(path, headers={"Cookie": self.session_cookie_marker})

    def test_overview_endpoints_require_login(self):
        # 不带 Cookie 头 → OverviewAwareFlaskClient 清空 jar → 401
        for path in (
            "/api/overview/summary",
            "/api/overview/verification",
            "/api/overview/external-api",
            "/api/overview/pool",
            "/api/overview/activity",
        ):
            with self.subTest(path=path):
                resp = self.client.get(path)
                self.assertEqual(resp.status_code, 401)
                data = resp.get_json()
                self.assertTrue(data.get("need_login"))

    def test_overview_summary_shape_after_login(self):
        resp = self._get_authed("/api/overview/summary")
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        data = resp.get_json() or {}
        for key in (
            "account_status",
            "pool_snapshot",
            "refresh_health",
            "kpi",
        ):
            self.assertIn(key, data)
        self.assertIn("total", data["account_status"])

    def test_overview_other_tabs_return_objects(self):
        for path in (
            "/api/overview/verification",
            "/api/overview/external-api",
            "/api/overview/pool",
            "/api/overview/activity",
        ):
            with self.subTest(path=path):
                resp = self._get_authed(path)
                self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
                data = resp.get_json()
                self.assertIsInstance(data, dict)

    def test_overview_verification_has_kpi(self):
        """对抗：验证码 Tab 关键字段。"""
        resp = self._get_authed("/api/overview/verification")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertIn("kpi", data)
        kpi = data["kpi"]
        for key in ("total_count", "success_count", "success_rate"):
            self.assertIn(key, kpi)


if __name__ == "__main__":
    unittest.main()
