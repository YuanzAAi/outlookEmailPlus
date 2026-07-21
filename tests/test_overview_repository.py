from __future__ import annotations

"""
TDD C 层：Overview Repository 查询测试

覆盖 docs/TDD/2026-04-19-数据概览大盘TDD.md §7
当前运行会失败（红）—— outlook_web/repositories/overview.py 尚未创建。
实现 5 个查询函数后，所有用例应通过（绿）。
"""

import time
import unittest

from tests._import_app import import_web_app_module


class OverviewRepositoryBaseTests(unittest.TestCase):
    """公共 setUp：清理测试数据，注入所需基础数据。"""

    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            # 清理本测试模块涉及的表（保留非测试数据）
            db.execute("DELETE FROM verification_extract_logs")
            db.execute("DELETE FROM audit_logs WHERE action LIKE 'ov_test_%'")
            db.execute("DELETE FROM notification_delivery_logs WHERE created_at >= datetime('now','-1 day')")
            db.execute("DELETE FROM account_claim_logs WHERE claimed_at >= datetime('now','-8 day')")
            db.execute("DELETE FROM external_api_consumer_usage_daily WHERE date >= date('now','-8 day')")
            db.commit()

    def _insert_extract_log(self, *, account_id: int, channel: str, result_type: str, duration_ms: int, used_ai: bool = False):
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            now_ts = int(time.time())
            db.execute(
                """
                INSERT INTO verification_extract_logs
                    (account_id, channel, started_at, finished_at, duration_ms, result_type, used_ai)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (account_id, channel, now_ts - 60, now_ts, duration_ms, result_type, int(used_ai)),
            )
            db.commit()


class OverviewSummaryRepositoryTests(OverviewRepositoryBaseTests):
    """R-01: get_overview_summary() 测试"""

    def test_get_overview_summary_returns_valid_schema_when_empty(self):
        """R-01 空数据: 空数据时返回合法结构，所有计数为 0"""
        with self.app.app_context():
            from outlook_web.repositories.overview import get_overview_summary

            result = get_overview_summary()

            self.assertIsInstance(result, dict)
            # 顶层键必须存在
            for key in ("account_status", "pool_snapshot", "refresh_health", "kpi"):
                self.assertIn(key, result, f"缺少顶层键: {key}")

    def test_get_overview_summary_account_status_counts(self):
        """R-01 有数据: account_status 计数与实际账号状态一致"""
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.repositories.overview import get_overview_summary

            db = get_db()
            # 插入两个 active 账号
            for i in range(2):
                db.execute(
                    """
                    INSERT INTO accounts (email, client_id, refresh_token, status, account_type, provider)
                    VALUES (?, 'cid', 'rt', 'active', 'outlook', 'outlook')
                    """,
                    (f"ov_test_{i}@summary.test",),
                )
            db.commit()

            result = get_overview_summary()
            account_status = result.get("account_status", {})
            self.assertGreaterEqual(account_status.get("active", 0), 2)

            # 清理
            db.execute("DELETE FROM accounts WHERE email LIKE '%@summary.test'")
            db.commit()

    def test_get_overview_summary_pool_snapshot_keys_exist(self):
        """R-01: pool_snapshot 包含 in_use/available/cooldown/total 键"""
        with self.app.app_context():
            from outlook_web.repositories.overview import get_overview_summary

            result = get_overview_summary()
            pool = result.get("pool_snapshot", {})
            for key in ("available", "in_use", "cooldown", "total"):
                self.assertIn(key, pool, f"pool_snapshot 缺少键: {key}")

    def test_get_overview_summary_separates_account_backed_temp_and_merges_temp_pool_capacity(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.repositories.overview import get_overview_summary

            db = get_db()
            before = get_overview_summary()
            db.execute("""
                INSERT INTO accounts (email, client_id, refresh_token, status, account_type, provider)
                VALUES ('regular@overview-temp.test', 'cid', 'rt', 'active', 'outlook', 'outlook')
                """)
            db.execute("""
                INSERT INTO accounts (
                    email, client_id, refresh_token, status, account_type, provider, pool_status
                ) VALUES ('cf@overview-temp.test', '', '', 'active', 'temp_mail', 'cloudflare_temp_mail', 'available')
                """)
            db.execute("""
                INSERT INTO temp_emails (email, status, mailbox_type, visible_in_ui, pool_status)
                VALUES
                    ('available@overview-temp.test', 'active', 'user', 1, NULL),
                    ('claimed@overview-temp.test', 'active', 'user', 1, 'claimed'),
                    ('cf@overview-temp.test', 'active', 'user', 0, NULL)
                """)
            db.execute("""
                UPDATE temp_emails
                SET source = 'cloudflare_account_temp_mail',
                    meta_json = '{"provider_name":"cloudflare_temp_mail"}'
                WHERE email = 'cf@overview-temp.test'
                """)
            db.commit()

            try:
                after = get_overview_summary()
                self.assertEqual(after["account_status"]["total"], before["account_status"]["total"] + 1)
                self.assertEqual(after["account_status"]["active"], before["account_status"]["active"] + 1)
                self.assertEqual(after["kpi"]["temp_emails_active"], before["kpi"]["temp_emails_active"] + 3)
                self.assertEqual(after["pool_snapshot"]["available"], before["pool_snapshot"]["available"] + 2)
                self.assertEqual(after["pool_snapshot"]["in_use"], before["pool_snapshot"]["in_use"] + 1)
                self.assertEqual(after["pool_snapshot"]["total"], before["pool_snapshot"]["total"] + 3)
            finally:
                db.execute("DELETE FROM temp_emails WHERE email LIKE '%@overview-temp.test'")
                db.execute("DELETE FROM accounts WHERE email LIKE '%@overview-temp.test'")
                db.commit()


class OverviewVerificationStatsRepositoryTests(OverviewRepositoryBaseTests):
    """R-02: get_verification_stats() 测试"""

    def test_get_verification_stats_empty_logs_returns_zero_kpi(self):
        """R-02 空数据: 无记录时 KPI 全为 0，recent 为空列表"""
        with self.app.app_context():
            from outlook_web.repositories.overview import get_verification_stats

            result = get_verification_stats()

            self.assertIsInstance(result, dict)
            kpi = result.get("kpi", {})
            self.assertEqual(kpi.get("total_count", -1), 0)
            self.assertEqual(kpi.get("success_count", -1), 0)
            self.assertIsInstance(result.get("recent", []), list)
            self.assertEqual(len(result.get("recent", ["x"])), 0)

    def test_get_verification_stats_aggregates_7day_kpi_correctly(self):
        """R-02 有数据: 正确统计 7 天内的 total_count 和 success_count"""
        # 插入 3 条记录：2 成功（code）1 失败（none）
        for _ in range(2):
            self._insert_extract_log(account_id=1, channel="graph_delta", result_type="code", duration_ms=300)
        self._insert_extract_log(account_id=1, channel="graph_delta", result_type="none", duration_ms=800)

        with self.app.app_context():
            from outlook_web.repositories.overview import get_verification_stats

            result = get_verification_stats()
            kpi = result.get("kpi", {})

            self.assertGreaterEqual(kpi.get("total_count", 0), 3)
            self.assertGreaterEqual(kpi.get("success_count", 0), 2)

    def test_get_verification_stats_channel_stats_structure(self):
        """R-02: channel_stats 列表元素包含 channel/count/success_rate 字段"""
        self._insert_extract_log(account_id=1, channel="imap_ssl", result_type="code", duration_ms=200)

        with self.app.app_context():
            from outlook_web.repositories.overview import get_verification_stats

            result = get_verification_stats()
            channel_stats = result.get("channel_stats", [])
            self.assertIsInstance(channel_stats, list)
            if channel_stats:
                for key in ("channel", "count", "success_rate"):
                    self.assertIn(key, channel_stats[0], f"channel_stats 元素缺少键: {key}")

    def test_get_verification_stats_recent_limited_to_10(self):
        """R-02: recent 列表最多返回 10 条，按 started_at DESC 排序"""
        for i in range(15):
            self._insert_extract_log(account_id=1, channel="graph_delta", result_type="code", duration_ms=100 + i)

        with self.app.app_context():
            from outlook_web.repositories.overview import get_verification_stats

            result = get_verification_stats()
            recent = result.get("recent", [])
            self.assertLessEqual(len(recent), 10)


class OverviewExternalApiStatsRepositoryTests(OverviewRepositoryBaseTests):
    """R-03: get_external_api_stats() 测试"""

    def test_get_external_api_stats_empty_returns_valid_schema(self):
        """R-03 空数据: 返回合法结构，计数为 0，列表为空"""
        with self.app.app_context():
            from outlook_web.repositories.overview import get_external_api_stats

            result = get_external_api_stats()

            self.assertIsInstance(result, dict)
            kpi = result.get("kpi", {})
            self.assertIn("today_calls", kpi)
            self.assertIn("week_calls", kpi)
            self.assertIsInstance(result.get("daily_series", []), list)
            self.assertIsInstance(result.get("caller_rank", []), list)

    def test_get_external_api_stats_reflects_usage_records(self):
        """R-03 有数据: daily_series 和 kpi 反映实际 usage_daily 记录"""
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.repositories.overview import get_external_api_stats

            db = get_db()
            from datetime import date

            today = date.today().isoformat()
            db.execute(
                """
                INSERT OR REPLACE INTO external_api_consumer_usage_daily
                    (consumer_key, caller_id, date, call_count)
                VALUES ('key1', 'bot1', ?, 42)
                """,
                (today,),
            )
            db.commit()

            result = get_external_api_stats()
            kpi = result.get("kpi", {})
            self.assertGreaterEqual(kpi.get("today_calls", 0), 42)

            db.execute("DELETE FROM external_api_consumer_usage_daily WHERE consumer_key='key1' AND caller_id='bot1'")
            db.commit()


class OverviewPoolStatsRepositoryTests(OverviewRepositoryBaseTests):
    """R-04: get_pool_stats() 测试"""

    def test_get_pool_stats_empty_returns_valid_schema(self):
        """R-04 空数据: 返回合法结构，计数为 0，列表为空"""
        with self.app.app_context():
            from outlook_web.repositories.overview import get_pool_stats

            result = get_pool_stats()

            self.assertIsInstance(result, dict)
            kpi = result.get("kpi", {})
            self.assertIn("available", kpi)
            self.assertIn("in_use", kpi)
            self.assertIsInstance(result.get("recent_operations", []), list)
            self.assertIsInstance(result.get("project_top5", []), list)

    def test_get_pool_stats_operation_distribution_has_expected_keys(self):
        """R-04: operation_distribution 包含 claim/complete/release/expire 分布"""
        with self.app.app_context():
            from outlook_web.repositories.overview import get_pool_stats

            result = get_pool_stats()
            dist = result.get("operation_distribution", {})
            self.assertIsInstance(dist, dict)
            # 至少有这些键（可以为 0）
            for op in ("claim", "complete", "release", "expire"):
                self.assertIn(op, dist, f"operation_distribution 缺少键: {op}")

    def test_get_pool_stats_merges_temp_mailbox_capacity_and_claim_duration(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.repositories.overview import get_pool_stats

            db = get_db()
            before = get_pool_stats()["kpi"]
            db.execute("""
                INSERT INTO temp_emails (email, status, mailbox_type, visible_in_ui, pool_status, claimed_at)
                VALUES
                    ('available@overview-pool.test', 'active', 'user', 1, NULL, NULL),
                    ('claimed@overview-pool.test', 'active', 'user', 1, 'claimed', datetime('now', '-2 minute'))
                """)
            db.commit()

            try:
                after = get_pool_stats()["kpi"]
                self.assertEqual(after["available"], before["available"] + 1)
                self.assertEqual(after["in_use"], before["in_use"] + 1)
                self.assertGreaterEqual(after["max_claimed_duration_s"], 100)
            finally:
                db.execute("DELETE FROM temp_emails WHERE email LIKE '%@overview-pool.test'")
                db.commit()


class OverviewActivityStatsRepositoryTests(OverviewRepositoryBaseTests):
    """R-05: get_activity_stats() 测试"""

    def test_get_activity_stats_empty_returns_valid_schema(self):
        """R-05 空数据: 返回合法结构，KPI 为 0，timeline 为空列表"""
        with self.app.app_context():
            from outlook_web.repositories.overview import get_activity_stats

            result = get_activity_stats()

            self.assertIsInstance(result, dict)
            kpi = result.get("kpi", {})
            self.assertIn("audit_ops_24h", kpi)
            self.assertIsInstance(result.get("timeline", []), list)

    def test_get_activity_stats_timeline_structure(self):
        """R-05: timeline 列表元素包含 time/action/status 等字段"""
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.repositories.overview import get_activity_stats

            db = get_db()
            db.execute("""
                INSERT INTO audit_logs (action, resource_type, operator, status, created_at)
                VALUES ('ov_test_action', 'test', 'tester', 'ok', datetime('now'))
                """)
            db.commit()

            result = get_activity_stats()
            timeline = result.get("timeline", [])
            self.assertIsInstance(timeline, list)
            if timeline:
                item = timeline[0]
                for key in ("time", "action", "status"):
                    self.assertIn(key, item, f"timeline 元素缺少键: {key}")
