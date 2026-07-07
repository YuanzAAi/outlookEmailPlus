from __future__ import annotations

"""
TDD B 层：验证码提取埋点逻辑测试

覆盖 docs/TDD/2026-04-19-数据概览大盘TDD.md §6
当前运行会失败（红）—— _write_extract_log 尚未实现。
实现 external_api.py 中的 _write_extract_log + _log_channel 透传后，所有用例应通过（绿）。
"""

import time
import unittest
from unittest.mock import patch

from tests._import_app import import_web_app_module


class VerificationExtractLogWriteTests(unittest.TestCase):
    """验证 _write_extract_log 写入字段正确性及异常隔离。"""

    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        """每个测试前清空 verification_extract_logs 表"""
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            db.execute("DELETE FROM verification_extract_logs")
            db.commit()

    # ===== L-01: 提取成功（code）写入字段 =====

    def test_write_extract_log_inserts_correct_fields_on_code_success(self):
        """L-01: 提取成功（code）时写入 account_id/channel/duration_ms/result_type/code_found/used_ai"""
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services.external_api import _write_extract_log

            started_at = time.time()
            finished_at = started_at + 0.5

            _write_extract_log(
                account_id=999,
                channel="graph_delta",
                started_at=started_at,
                finished_at=finished_at,
                result_type="code",
                code_found="123456",
                used_ai=False,
                error_code=None,
                trace_id="test-trace-001",
            )

            db = get_db()
            row = db.execute(
                "SELECT account_id, channel, duration_ms, result_type, code_found, used_ai, error_code "
                "FROM verification_extract_logs ORDER BY id DESC LIMIT 1"
            ).fetchone()

            self.assertIsNotNone(row, "应写入一条记录")
            self.assertEqual(row[0], 999)
            self.assertEqual(row[1], "graph_delta")
            self.assertAlmostEqual(row[2], 500, delta=50)  # duration_ms ≈ 500ms
            self.assertEqual(row[3], "code")
            self.assertEqual(row[4], "123456")
            self.assertEqual(row[5], 0)  # used_ai=False → 0
            self.assertIsNone(row[6])

    # ===== L-02: 提取成功（link）写入字段 =====

    def test_write_extract_log_inserts_correct_fields_on_link_success(self):
        """L-02: 提取成功（link）时 result_type='link'，code_found 为链接"""
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services.external_api import _write_extract_log

            _write_extract_log(
                account_id=998,
                channel="imap_ssl",
                started_at=time.time(),
                finished_at=time.time() + 0.8,
                result_type="link",
                code_found="https://example.com/verify?token=abc",
                used_ai=False,
                error_code=None,
                trace_id=None,
            )

            db = get_db()
            row = db.execute(
                "SELECT result_type, code_found FROM verification_extract_logs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "link")
            self.assertIn("https://", row[1])

    # ===== L-03: 提取失败（none）写入字段 =====

    def test_write_extract_log_inserts_correct_fields_on_failure(self):
        """L-03: 提取失败（none）时 result_type='none'，error_code 非空"""
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services.external_api import _write_extract_log

            _write_extract_log(
                account_id=997,
                channel="graph_delta",
                started_at=time.time(),
                finished_at=time.time() + 1.2,
                result_type="none",
                code_found=None,
                used_ai=False,
                error_code="VERIFICATION_NOT_FOUND",
                trace_id="test-trace-002",
            )

            db = get_db()
            row = db.execute(
                "SELECT result_type, error_code FROM verification_extract_logs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "none")
            self.assertEqual(row[1], "VERIFICATION_NOT_FOUND")

    # ===== L-01: duration_ms 计算精度 =====

    def test_write_extract_log_calculates_duration_ms_correctly(self):
        """L-01: duration_ms = int((finished_at - started_at) * 1000)，精确到整数毫秒"""
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services.external_api import _write_extract_log

            started_at = 1_000_000.000
            finished_at = 1_000_002.345  # 精确 2345 ms

            _write_extract_log(
                account_id=996,
                channel="imap_ssl",
                started_at=started_at,
                finished_at=finished_at,
                result_type="code",
                code_found="abcdef",
                used_ai=False,
                error_code=None,
                trace_id=None,
            )

            db = get_db()
            row = db.execute("SELECT duration_ms FROM verification_extract_logs ORDER BY id DESC LIMIT 1").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], 2345)

    # ===== L-04: AI fallback =====

    def test_write_extract_log_sets_used_ai_flag_for_ai_fallback(self):
        """L-04: AI fallback 时 channel='ai_fallback'，used_ai=1"""
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services.external_api import _write_extract_log

            _write_extract_log(
                account_id=995,
                channel="ai_fallback",
                started_at=time.time(),
                finished_at=time.time() + 0.3,
                result_type="code",
                code_found="654321",
                used_ai=True,
                error_code=None,
                trace_id=None,
            )

            db = get_db()
            row = db.execute("SELECT channel, used_ai FROM verification_extract_logs ORDER BY id DESC LIMIT 1").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "ai_fallback")
            self.assertEqual(row[1], 1)

    # ===== L-05: 异常隔离 =====

    def test_write_extract_log_exception_does_not_propagate_to_caller(self):
        """L-05: _write_extract_log 内部抛异常时，不向调用方传播"""
        with self.app.app_context():
            from outlook_web.services import external_api as ext_api

            # 通过 patch db 写入让其抛出异常
            with patch("outlook_web.services.external_api._get_db_for_log", side_effect=RuntimeError("inject db error")):
                # 即使内部 db 获取失败，_write_extract_log 也应吞掉异常
                try:
                    ext_api._write_extract_log(
                        account_id=0,
                        channel="test",
                        started_at=time.time(),
                        finished_at=time.time(),
                        result_type="none",
                        code_found=None,
                        used_ai=False,
                        error_code=None,
                        trace_id=None,
                    )
                except Exception as exc:
                    self.fail(f"_write_extract_log 不应向外传播异常，但抛出了: {exc}")

    def test_main_flow_returns_business_error_when_account_not_found(self):
        """L-05: get_verification_result 在账号不存在时返回业务错误（非日志写入错误）"""
        with self.app.app_context():
            from outlook_web.services.external_api import ExternalApiError, get_verification_result

            with patch("outlook_web.repositories.accounts.get_account_by_email", return_value=None):
                with self.assertRaises(ExternalApiError):
                    get_verification_result(email_addr="nonexistent@example.com")


class VerificationChannelRoutingLogChannelTests(unittest.TestCase):
    """验证 extract_verification_for_outlook 返回值中携带 _log_channel 字段。"""

    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    # ===== L-06: _log_channel 透传 =====

    def test_extract_verification_outlook_returns_log_channel_field(self):
        """L-06: 无论提取成功或失败，返回 dict 中包含 _log_channel 字段"""
        with self.app.app_context():
            from outlook_web.services import verification_channel_routing as vcr

            fake_account = {
                "id": 1,
                "email": "test@outlook.com",
                "account_type": "outlook",
                "provider": "outlook",
                "group_id": None,
                "preferred_verification_channel": None,
                "client_id": "cid",
                "refresh_token": "rt",
            }

            # patch 内部调用，让函数走"所有渠道均不可用"路径
            with (
                patch.object(vcr, "build_verification_channel_plan", return_value=[]),
                patch(
                    "outlook_web.services.graph.get_access_token_graph_result",
                    return_value={"success": False},
                ),
            ):
                result = vcr.extract_verification_for_outlook(
                    account=fake_account,
                    resolved_policy={"code_regex": None, "code_length": "6-6"},
                    code_source="all",
                )

            self.assertIsInstance(result, dict)
            self.assertIn(
                "_log_channel",
                result,
                "extract_verification_for_outlook 返回值缺少 _log_channel 字段（TD 要求透传）",
            )

    def test_log_channel_is_ai_fallback_when_ai_is_used(self):
        """L-04: AI fallback 成功时 _log_channel 值为 'ai_fallback'"""
        with self.app.app_context():
            from outlook_web.services import verification_channel_routing as vcr

            fake_account = {
                "id": 2,
                "email": "ai@outlook.com",
                "account_type": "outlook",
                "provider": "outlook",
                "group_id": None,
                "preferred_verification_channel": None,
                "client_id": "cid",
                "refresh_token": "rt",
            }

            fake_email_obj = {
                "subject": "Your code",
                "body": "Your verification code is 888888",
                "body_html": "",
                "raw_content": "Your verification code is 888888",
                "from": "noreply@example.com",
                "date": "2026-04-19T10:00:00Z",
            }

            fake_channel_result = {
                "success": True,
                "emails": [{"id": "e1", "date": "2026-04-19T10:00:00Z"}],
            }

            with (
                patch.object(vcr, "build_verification_channel_plan", return_value=["graph_delta"]),
                patch.object(
                    vcr,
                    "fetch_emails_and_detail_for_channel",
                    return_value=fake_channel_result,
                ),
                patch.object(vcr, "fetch_email_detail_for_channel", return_value={"body": "888888"}),
                patch.object(vcr, "_build_email_obj_from_channel_detail", return_value=fake_email_obj),
                patch(
                    "outlook_web.services.graph.get_access_token_graph_result",
                    return_value={"success": True, "scope": "Mail.Read"},
                ),
                patch(
                    "outlook_web.services.verification_extractor.extract_verification_info_with_options",
                    return_value={"verification_code": None},
                ),
                patch(
                    "outlook_web.services.verification_extractor.enhance_verification_with_ai_fallback",
                    return_value={"verification_code": "888888", "_used_ai": True},
                ),
                patch(
                    "outlook_web.services.verification_extractor.apply_confidence_gate",
                    return_value={"verification_code": "888888", "_used_ai": True},
                ),
                patch.object(vcr, "_is_extraction_success", return_value=True),
            ):
                result = vcr.extract_verification_for_outlook(
                    account=fake_account,
                    resolved_policy={"code_regex": None, "code_length": "6-6"},
                    code_source="all",
                )

            self.assertIn("_log_channel", result)
            self.assertEqual(result["_log_channel"], "ai_fallback")

    def test_imap_detail_mismatch_refetches_latest_message_detail(self):
        """IMAP 连接复用返回的 detail 与最新邮件不一致时，应按 latest.id 重新取详情。"""
        with self.app.app_context():
            from outlook_web.services import verification_channel_routing as vcr

            fake_account = {
                "id": 3,
                "email": "imap@outlook.com",
                "account_type": "outlook",
                "provider": "outlook",
                "group_id": None,
                "preferred_verification_channel": "imap_new",
                "client_id": "cid",
                "refresh_token": "rt",
            }

            fake_channel_result = {
                "success": True,
                "emails": [
                    {
                        "id": "3",
                        "subject": "Old code",
                        "from": "OpenAI",
                        "date": "Tue, 19 May 2026 10:01:15 +0000",
                    },
                    {
                        "id": "5",
                        "subject": "New code",
                        "from": "OpenAI",
                        "date": "Tue, 19 May 2026 10:38:27 +0000",
                    },
                ],
                "detail": {
                    "id": "3",
                    "subject": "Old code",
                    "from": "OpenAI",
                    "date": "Tue, 19 May 2026 10:01:15 +0000",
                    "body": "Your code is 990595",
                },
            }
            latest_detail = {
                "id": "5",
                "subject": "New code",
                "from": "OpenAI",
                "date": "Tue, 19 May 2026 10:38:27 +0000",
                "body": "Your code is 701280",
            }

            with (
                patch.object(vcr, "build_verification_channel_plan", return_value=["imap_new"]),
                patch.object(vcr, "fetch_emails_and_detail_for_channel", return_value=fake_channel_result),
                patch.object(vcr, "fetch_email_detail_for_channel", return_value=latest_detail) as mock_fetch_detail,
                patch(
                    "outlook_web.services.graph.get_access_token_graph_result",
                    return_value={"success": False},
                ),
                patch("outlook_web.repositories.accounts.update_preferred_verification_channel"),
            ):
                result = vcr.extract_verification_for_outlook(
                    account=fake_account,
                    resolved_policy={"code_regex": r"(?<!\d)\d{6}(?!\d)", "code_length": "6-6"},
                    code_source="all",
                    expected_field="verification_code",
                )

            self.assertTrue(result.get("success"))
            self.assertEqual(result.get("data", {}).get("matched_email_id"), "5")
            self.assertEqual(result.get("data", {}).get("verification_code"), "701280")
            mock_fetch_detail.assert_called_once()
            self.assertEqual(mock_fetch_detail.call_args.kwargs.get("message_id"), "5")
