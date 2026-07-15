"""ZER-90：统一 /verification API 契约测试。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class UnifiedVerificationApiTests(unittest.TestCase):
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
        self.assertEqual(resp.status_code, 200)

    @patch("outlook_web.controllers.emails.external_api_service.get_verification_result")
    def test_verification_endpoint_aliases_extract_verification(self, mock_get_result):
        self._login()
        mock_get_result.return_value = {
            "verification_code": "Ab12Cd",
            "verification_link": "https://example.com/verify",
            "formatted": "Ab12Cd https://example.com/verify",
            "code_confidence": "high",
            "link_confidence": "high",
            "confidence": "high",
            "folder": "inbox",
            "matched_email_id": "msg-1",
            "subject": "Code",
            "from": "security@example.com",
            "received_at": "2026-03-20T10:00:00Z",
        }

        with patch("outlook_web.controllers.emails.accounts_repo.get_account_by_email") as mock_account:
            mock_account.return_value = {
                "id": 1,
                "email": "demo@example.com",
                "account_type": "outlook",
                "client_id": "cid",
                "refresh_token": "rt",
            }
            with patch("outlook_web.controllers.emails.compact_summary_service.update_summary_from_verification") as mock_summary:
                mock_summary.return_value = {"latest_verification_code": "Ab12Cd"}

                resp = self.client.get("/api/emails/demo@example.com/verification?field=code")

        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json() or {}
        self.assertTrue(payload.get("success"))
        self.assertEqual((payload.get("data") or {}).get("verification_code"), "Ab12Cd")
        self.assertIsNone((payload.get("data") or {}).get("verification_link"))


if __name__ == "__main__":
    unittest.main()
