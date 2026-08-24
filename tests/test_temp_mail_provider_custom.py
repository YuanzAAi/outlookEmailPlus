from __future__ import annotations

import unittest
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class CustomTempMailProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
            from outlook_web.repositories import settings as settings_repo

            settings_repo.set_setting("temp_mail_provider", "custom_domain_temp_mail")
            settings_repo.set_setting("temp_mail_api_base_url", "https://bridge.example")
            settings_repo.set_setting(
                "temp_mail_domains",
                '[{"name":"mail.example.com","enabled":true},"temp.example.net"]',
            )
            settings_repo.set_setting("temp_mail_default_domain", "mail.example.com")
            settings_repo.set_setting(
                "temp_mail_prefix_rules",
                '{"min_length":2,"max_length":16,"pattern":"^[a-z0-9-]+$"}',
            )

    def test_get_options_parses_settings_contract(self):
        with self.app.app_context():
            from outlook_web.services.temp_mail_provider_custom import CustomTempMailProvider

            provider = CustomTempMailProvider()
            with patch(
                "outlook_web.services.temp_mail_provider_custom.settings_repo.get_temp_mail_api_key",
                return_value="test-api-key",
            ):
                options = provider.get_options()

        self.assertTrue(options["configured"])
        self.assertEqual(options["domain_strategy"], "auto_or_manual")
        self.assertEqual(options["default_mode"], "auto")
        self.assertEqual(options["provider"], "custom_domain_temp_mail")
        self.assertEqual(options["api_base_url"], "https://bridge.example")
        self.assertEqual(
            options["domains"],
            [
                {"name": "mail.example.com", "enabled": True, "is_default": True},
                {"name": "temp.example.net", "enabled": True, "is_default": False},
            ],
        )
        self.assertEqual(
            options["prefix_rules"],
            {"min_length": 2, "max_length": 16, "pattern": "^[a-z0-9-]+$"},
        )

    def test_get_options_is_not_configured_without_api_key(self):
        with self.app.app_context():
            from outlook_web.services.temp_mail_provider_custom import CustomTempMailProvider

            provider = CustomTempMailProvider()
            with patch(
                "outlook_web.services.temp_mail_provider_custom.settings_repo.get_temp_mail_api_key",
                return_value="",
            ):
                options = provider.get_options()

        self.assertFalse(options["configured"])

    def test_generate_mailbox_maps_bridge_errors_to_stable_codes(self):
        cases = [
            ("API Key 无效或已过期", "UNAUTHORIZED"),
            ("API 请求超时", "UPSTREAM_TIMEOUT"),
            ("临时邮箱服务暂时不可用", "UPSTREAM_SERVER_ERROR"),
            ("API 返回数据格式错误：缺少 email 字段", "UPSTREAM_BAD_PAYLOAD"),
        ]

        with self.app.app_context():
            from outlook_web.services.temp_mail_provider_custom import CustomTempMailProvider

            provider = CustomTempMailProvider()
            for error_message, expected_code in cases:
                with self.subTest(error_message=error_message):
                    with patch("outlook_web.services.gptmail.generate_temp_email", return_value=(None, error_message)):
                        result = provider.generate_mailbox(prefix="demo", domain="mail.example.com")

                self.assertFalse(result["success"])
                self.assertEqual(result["error"], error_message)
                self.assertEqual(result["error_code"], expected_code)

    def test_generate_mailbox_success_passes_prefix_and_domain(self):
        with self.app.app_context():
            from outlook_web.services.temp_mail_provider_custom import CustomTempMailProvider

            provider = CustomTempMailProvider()
            with patch(
                "outlook_web.services.gptmail.generate_temp_email",
                return_value=("demo@mail.example.com", None),
            ) as generate_mock:
                result = provider.generate_mailbox(prefix="demo", domain="mail.example.com")

        self.assertTrue(result["success"])
        self.assertEqual(result["email"], "demo@mail.example.com")
        self.assertEqual(result["meta"]["provider_name"], "custom_domain_temp_mail")
        self.assertIn("provider_capabilities", result["meta"])
        generate_mock.assert_called_once_with("demo", "mail.example.com")

    def test_list_messages_raises_stable_read_error_when_bridge_read_fails(self):
        with self.app.app_context():
            from outlook_web.services.temp_mail_provider_custom import CustomTempMailProvider, TempMailProviderReadError

            provider = CustomTempMailProvider()
            with patch(
                "outlook_web.services.gptmail.gptmail_request",
                return_value={
                    "success": False,
                    "error": "API 请求超时",
                    "error_type": "TIMEOUT_ERROR",
                    "details": "request timed out",
                },
            ):
                with self.assertRaises(TempMailProviderReadError) as ctx:
                    provider.list_messages("reader@mail.example.com")

        self.assertEqual(ctx.exception.code, "UPSTREAM_TIMEOUT")
        self.assertEqual(ctx.exception.data["operation"], "list_messages")
        self.assertEqual(ctx.exception.data["email"], "reader@mail.example.com")

    def test_get_message_detail_raises_stable_read_error_when_bridge_read_fails(self):
        with self.app.app_context():
            from outlook_web.services.temp_mail_provider_custom import CustomTempMailProvider, TempMailProviderReadError

            provider = CustomTempMailProvider()
            with patch(
                "outlook_web.services.gptmail.gptmail_request",
                return_value={
                    "success": False,
                    "error": "临时邮箱服务暂时不可用",
                    "error_type": "SERVER_ERROR",
                    "details": "HTTP 503",
                },
            ):
                with self.assertRaises(TempMailProviderReadError) as ctx:
                    provider.get_message_detail("reader@mail.example.com", "msg-1")

        self.assertEqual(ctx.exception.code, "UPSTREAM_SERVER_ERROR")
        self.assertEqual(ctx.exception.data["operation"], "get_message_detail")
        self.assertEqual(ctx.exception.data["message_id"], "msg-1")
