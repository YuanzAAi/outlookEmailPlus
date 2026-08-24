from __future__ import annotations

import unittest
from unittest.mock import patch

from outlook_web.repositories import temp_emails as temp_emails_repo
from outlook_web.services.temp_mail_provider_cf import CloudflareTempMailProvider
from outlook_web.services.temp_mail_service import TempMailService


class _Provider:
    provider_name = "plugin_demo"
    provider_capabilities = {
        "create_mailbox": True,
        "list_messages": True,
        "get_message_detail": True,
        "delete_mailbox": False,
        "delete_message": True,
        "clear_messages": False,
    }

    def __init__(self, api_base_url: str = "https://mail.example.test") -> None:
        self.api_base_url = api_base_url

    def get_options(self):
        return {
            "provider_name": self.provider_name,
            "api_base_url": self.api_base_url,
            "domains": [{"name": "mail.example.test", "enabled": True}],
        }


class TempMailFrontendContractTest(unittest.TestCase):
    def _get_options(self, provider: _Provider):
        with patch(
            "outlook_web.services.temp_mail_service.get_available_providers",
            return_value=[
                {
                    "name": "custom_domain_temp_mail",
                    "label": "通用 API (GPTMail)",
                    "version": "1.0.0",
                },
                {
                    "name": "plugin_demo",
                    "label": "Demo Plugin",
                    "version": "0.1.0",
                },
            ],
        ), patch(
            "outlook_web.services.temp_mail_service.settings_repo.get_temp_mail_runtime_provider_name",
            return_value="custom_domain_temp_mail",
        ):
            return TempMailService(provider=provider).get_options(provider_name="plugin_demo")

    def test_options_expose_provider_catalog_status_and_capabilities(self):
        options = self._get_options(_Provider())

        self.assertEqual(options["provider_name"], "plugin_demo")
        self.assertEqual(options["provider_label"], "Demo Plugin")
        self.assertEqual(options["provider_kind"], "plugin")
        self.assertEqual(options["status"], "ready")
        self.assertTrue(options["configured"])
        self.assertFalse(options["capabilities"]["delete_mailbox"])
        self.assertFalse(options["capabilities"]["clear_messages"])
        self.assertEqual(len(options["providers"]), 2)
        self.assertTrue(options["providers"][0]["active"])
        self.assertTrue(options["providers"][1]["selected"])

    def test_options_report_provider_without_base_url_as_not_configured(self):
        options = self._get_options(_Provider(api_base_url=""))

        self.assertTrue(options["enabled"])
        self.assertFalse(options["configured"])
        self.assertEqual(options["status"], "not_configured")

    def test_cloudflare_requires_admin_key_and_enabled_domain(self):
        provider = CloudflareTempMailProvider()
        domains = [{"name": "mail.example.test", "enabled": True}]
        with patch(
            "outlook_web.services.temp_mail_service.settings_repo.get_temp_mail_runtime_provider_name",
            return_value="custom_domain_temp_mail",
        ), patch.object(provider, "_base_url", return_value="https://mail.example.test"), patch.object(
            provider, "_admin_key", return_value=""
        ), patch(
            "outlook_web.services.temp_mail_provider_cf.settings_repo.get_cf_worker_domains",
            return_value=domains,
        ), patch(
            "outlook_web.services.temp_mail_provider_cf.settings_repo.get_cf_worker_default_domain",
            return_value="mail.example.test",
        ), patch(
            "outlook_web.services.temp_mail_provider_cf.settings_repo.get_cf_worker_prefix_rules",
            return_value={},
        ), patch(
            "outlook_web.services.temp_mail_provider_cf.settings_repo.get_temp_mail_domains",
            return_value=[],
        ), patch(
            "outlook_web.services.temp_mail_provider_cf.settings_repo.get_temp_mail_default_domain",
            return_value="",
        ), patch(
            "outlook_web.services.temp_mail_provider_cf.settings_repo.get_temp_mail_prefix_rules",
            return_value={},
        ):
            options = TempMailService(provider=provider).get_options()

        self.assertFalse(options["configured"])
        self.assertEqual(options["status"], "not_configured")

    def test_legacy_mailbox_dto_is_safe_and_keeps_compatibility_metadata(self):
        dto = temp_emails_repo.build_temp_mailbox_public_dto(
            {
                "email": "legacy@example.test",
                "source": temp_emails_repo.LEGACY_TEMP_MAIL_SOURCE,
                "mailbox_type": "user",
                "visible_in_ui": 1,
                "status": "active",
                "meta_json": '{"provider_jwt":"must-not-leak"}',
            }
        )

        self.assertEqual(dto["provider_name"], temp_emails_repo.LEGACY_TEMP_MAIL_PROVIDER_NAME)
        self.assertEqual(dto["compatibility_mode"], "legacy")
        self.assertEqual(dto["read_capability"], temp_emails_repo.TEMP_MAIL_READ_CAPABILITY)
        self.assertIn("clear_messages", dto["provider_capabilities"])
        self.assertNotIn("provider_jwt", str(dto))


if __name__ == "__main__":
    unittest.main()
