from __future__ import annotations

"""
TDD D 层：Overview API 接口测试

覆盖 docs/TDD/2026-04-19-数据概览大盘TDD.md §8
当前运行会失败（红）—— /api/overview/* 接口尚未注册（404）。
实现 Blueprint + 5 个接口后，所有用例应通过（绿）。
"""

import json
import unittest

from tests._import_app import import_web_app_module


class OverviewApiBaseTests(unittest.TestCase):
    """基础: client 创建 + 登录获取 session"""

    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app
        cls.client = cls.app.test_client()
        cls.session_cookie = cls._login(cls.client)

    @staticmethod
    def _login(client) -> str:
        resp = client.post(
            "/login",
            json={"password": "testpass123"},
            content_type="application/json",
        )
        if resp.status_code != 200:
            raise RuntimeError(f"测试用户登录失败 ({resp.status_code}): {resp.data[:200]}")
        return "loggedin"

    def _get(self, url: str, *, authed: bool = True):
        headers = {}
        if authed:
            headers["Cookie"] = self.session_cookie
        return self.client.get(url, headers=headers)

    def _assert_json(self, resp) -> dict:
        self.assertEqual(resp.content_type, "application/json", f"非 JSON 响应: {resp.data[:200]}")
        return json.loads(resp.data)

    def setUp(self):
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            db.execute("DELETE FROM verification_extract_logs")
            db.commit()


# ===== A-01: GET /api/overview/summary =====


class OverviewSummaryApiTests(OverviewApiBaseTests):

    _URL = "/api/overview/summary"

    def test_get_summary_unauthorized_returns_401(self):
        """A-01 鉴权: 未登录时返回 401"""
        resp = self.app.test_client().get(self._URL)
        self.assertEqual(resp.status_code, 401)

    def test_get_summary_authed_returns_200(self):
        """A-01 成功: 已登录时返回 200"""
        resp = self._get(self._URL)
        self.assertEqual(resp.status_code, 200)

    def test_get_summary_response_has_required_top_level_keys(self):
        """A-01 Schema: 响应包含 account_status / pool_snapshot / refresh_health / kpi"""
        resp = self._get(self._URL)
        data = self._assert_json(resp)
        for key in ("account_status", "pool_snapshot", "refresh_health", "kpi"):
            self.assertIn(key, data, f"响应缺少顶层键: {key}")

    def test_get_summary_values_are_numeric(self):
        """A-01 数据类型: account_status 各值为整数"""
        resp = self._get(self._URL)
        data = self._assert_json(resp)
        for k, v in data.get("account_status", {}).items():
            self.assertIsInstance(v, (int, float), f"account_status.{k} 应为数值, 实际: {type(v)}")


# ===== A-02: GET /api/overview/verification =====


class OverviewVerificationApiTests(OverviewApiBaseTests):

    _URL = "/api/overview/verification"

    def test_get_verification_unauthorized_returns_401(self):
        """A-02 鉴权: 未登录时返回 401"""
        resp = self.app.test_client().get(self._URL)
        self.assertEqual(resp.status_code, 401)

    def test_get_verification_authed_returns_200(self):
        """A-02 成功: 已登录时返回 200"""
        resp = self._get(self._URL)
        self.assertEqual(resp.status_code, 200)

    def test_get_verification_response_has_kpi_key(self):
        """A-02 Schema: 响应包含 kpi 字段"""
        resp = self._get(self._URL)
        data = self._assert_json(resp)
        self.assertIn("kpi", data)

    def test_get_verification_kpi_has_expected_keys(self):
        """A-02 Schema: kpi 包含 total_count / success_count / success_rate / avg_duration_ms"""
        resp = self._get(self._URL)
        data = self._assert_json(resp)
        kpi = data.get("kpi", {})
        for key in ("total_count", "success_count", "success_rate", "avg_duration_ms"):
            self.assertIn(key, kpi, f"kpi 缺少键: {key}")

    def test_get_verification_empty_data_returns_zero_counts(self):
        """A-02 空数据: 无日志时 kpi.total_count 为 0，recent 为空数组"""
        resp = self._get(self._URL)
        data = self._assert_json(resp)
        self.assertEqual(data.get("kpi", {}).get("total_count"), 0)
        self.assertEqual(data.get("recent", ["x"]), [])


# ===== A-03: GET /api/overview/external-api =====


class OverviewExternalApiTests(OverviewApiBaseTests):

    _URL = "/api/overview/external-api"

    def test_get_external_api_unauthorized_returns_401(self):
        """A-03 鉴权: 未登录时返回 401"""
        resp = self.app.test_client().get(self._URL)
        self.assertEqual(resp.status_code, 401)

    def test_get_external_api_authed_returns_200(self):
        """A-03 成功: 已登录时返回 200"""
        resp = self._get(self._URL)
        self.assertEqual(resp.status_code, 200)

    def test_get_external_api_response_schema(self):
        """A-03 Schema: 响应包含 kpi / daily_series / caller_rank"""
        resp = self._get(self._URL)
        data = self._assert_json(resp)
        for key in ("kpi", "daily_series", "caller_rank"):
            self.assertIn(key, data, f"响应缺少顶层键: {key}")

    def test_get_external_api_daily_series_is_list(self):
        """A-03: daily_series 是列表"""
        resp = self._get(self._URL)
        data = self._assert_json(resp)
        self.assertIsInstance(data.get("daily_series"), list)


# ===== A-04: GET /api/overview/pool =====


class OverviewPoolApiTests(OverviewApiBaseTests):

    _URL = "/api/overview/pool"

    def test_get_pool_unauthorized_returns_401(self):
        """A-04 鉴权: 未登录时返回 401"""
        resp = self.app.test_client().get(self._URL)
        self.assertEqual(resp.status_code, 401)

    def test_get_pool_authed_returns_200(self):
        """A-04 成功: 已登录时返回 200"""
        resp = self._get(self._URL)
        self.assertEqual(resp.status_code, 200)

    def test_get_pool_response_schema(self):
        """A-04 Schema: 响应包含 kpi / recent_operations / project_top5 / operation_distribution"""
        resp = self._get(self._URL)
        data = self._assert_json(resp)
        for key in ("kpi", "recent_operations", "project_top5", "operation_distribution"):
            self.assertIn(key, data, f"响应缺少顶层键: {key}")


# ===== A-05: GET /api/overview/activity =====


class OverviewActivityApiTests(OverviewApiBaseTests):

    _URL = "/api/overview/activity"

    def test_get_activity_unauthorized_returns_401(self):
        """A-05 鉴权: 未登录时返回 401"""
        resp = self.app.test_client().get(self._URL)
        self.assertEqual(resp.status_code, 401)

    def test_get_activity_authed_returns_200(self):
        """A-05 成功: 已登录时返回 200"""
        resp = self._get(self._URL)
        self.assertEqual(resp.status_code, 200)

    def test_get_activity_response_schema(self):
        """A-05 Schema: 响应包含 kpi / timeline / notification_stats"""
        resp = self._get(self._URL)
        data = self._assert_json(resp)
        for key in ("kpi", "timeline", "notification_stats"):
            self.assertIn(key, data, f"响应缺少顶层键: {key}")

    def test_get_activity_timeline_is_list(self):
        """A-05: timeline 是列表"""
        resp = self._get(self._URL)
        data = self._assert_json(resp)
        self.assertIsInstance(data.get("timeline"), list)

    def test_get_activity_empty_returns_zero_kpi(self):
        """A-05 空数据: audit_ops_24h 为整数"""
        resp = self._get(self._URL)
        data = self._assert_json(resp)
        kpi = data.get("kpi", {})
        self.assertIsInstance(kpi.get("audit_ops_24h"), int)
