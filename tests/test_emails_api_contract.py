"""邮件阅读 API 契约（P3 前端迁移基线）。

不依赖真实 Microsoft Token：
- 未登录 401/403
- 不存在账号 404 ACCOUNT_NOT_FOUND
- 全链路失败时统一错误结构（mock Graph/IMAP 失败）
- 成功列表字段形状（mock Graph 成功）
- 删除接口参数校验
"""

from __future__ import annotations

import secrets
import unittest
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class TestEmailsApiContract(unittest.TestCase):
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

    def _account(self, email: str | None = None) -> dict:
        addr = email or f"mail_{secrets.token_hex(3)}@example.com"
        return {
            "id": 9001,
            "email": addr,
            "client_id": "cid-fake",
            "refresh_token": "rt-fake",
            "group_id": None,
            "account_type": "outlook",
            "provider": "outlook",
            "status": "active",
        }

    def test_emails_require_login(self):
        resp = self.client.get("/api/emails/nobody@example.com")
        self.assertIn(resp.status_code, (401, 403), resp.get_data(as_text=True))

    def test_email_detail_require_login(self):
        resp = self.client.get("/api/email/nobody@example.com/msg-1")
        self.assertIn(resp.status_code, (401, 403), resp.get_data(as_text=True))

    def test_account_not_found(self):
        self._login()
        missing = f"missing_{secrets.token_hex(4)}@example.com"
        with patch(
            "outlook_web.controllers.emails.accounts_repo.get_account_by_email",
            return_value=None,
        ):
            resp = self.client.get(
                f"/api/emails/{missing}",
                query_string={"folder": "inbox", "skip": 0, "top": 20},
            )
        self.assertEqual(resp.status_code, 404, resp.get_data(as_text=True))
        data = resp.get_json() or {}
        err = data.get("error") or {}
        if isinstance(err, dict):
            self.assertEqual(err.get("code"), "ACCOUNT_NOT_FOUND")
        else:
            self.assertFalse(data.get("success", True))

    @patch(
        "outlook_web.controllers.emails.imap_service.get_emails_imap_with_server",
        return_value={"success": False, "error": {"message": "imap_old failed"}},
    )
    @patch(
        "outlook_web.controllers.emails.graph_service.get_emails_graph",
        return_value={"success": False, "error": {"message": "graph failed"}},
    )
    @patch("outlook_web.controllers.emails.accounts_repo.get_account_by_email")
    def test_all_methods_failed_structured_error(
        self,
        mock_get_account,
        _mock_graph,
        mock_imap,
    ):
        # imap 被调用两次（new + old），统一返回失败
        mock_imap.return_value = {
            "success": False,
            "error": {"message": "imap failed"},
        }
        account = self._account()
        mock_get_account.return_value = account
        self._login()
        resp = self.client.get(
            f"/api/emails/{account['email']}",
            query_string={
                "method": "graph",
                "folder": "inbox",
                "skip": 0,
                "top": 20,
            },
        )
        self.assertIn(resp.status_code, (401, 502), resp.get_data(as_text=True))
        data = resp.get_json() or {}
        self.assertFalse(data.get("success", False))
        err = data.get("error") or {}
        self.assertIsInstance(err, dict)
        self.assertIn(
            err.get("code"),
            {
                "EMAIL_FETCH_ALL_METHODS_FAILED",
                "ACCOUNT_AUTH_EXPIRED",
                "EMAIL_PROXY_CONNECTION_FAILED",
            },
        )
        self.assertTrue(err.get("message") or err.get("message_en"))
        details = data.get("details") or err.get("details")
        if resp.status_code == 502:
            self.assertTrue(details is not None)

    @patch("outlook_web.controllers.emails.accounts_repo.touch_last_refresh_at", return_value=True)
    @patch(
        "outlook_web.controllers.emails.compact_summary_service.update_summary_from_message_list",
        return_value={"latest_email_subject": "Hello"},
    )
    @patch(
        "outlook_web.controllers.emails.graph_service.get_emails_graph",
        return_value={
            "success": True,
            "emails": [
                {
                    "id": "msg-1",
                    "subject": "Hello",
                    "from": {"emailAddress": {"address": "a@example.com"}},
                    "receivedDateTime": "2030-01-01T00:00:00Z",
                    "isRead": False,
                    "hasAttachments": False,
                    "bodyPreview": "preview text",
                }
            ],
        },
    )
    @patch("outlook_web.controllers.emails.accounts_repo.get_account_by_email")
    def test_list_success_shape(
        self,
        mock_get_account,
        _mock_graph,
        _mock_summary,
        _mock_touch,
    ):
        account = self._account()
        mock_get_account.return_value = account
        self._login()
        resp = self.client.get(
            f"/api/emails/{account['email']}",
            query_string={"folder": "inbox", "skip": 0, "top": 20},
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        data = resp.get_json() or {}
        self.assertTrue(data.get("success"))
        self.assertIsInstance(data.get("emails"), list)
        self.assertTrue(data["emails"])
        item = data["emails"][0]
        for key in ("id", "subject", "from", "date", "body_preview"):
            self.assertIn(key, item)
        self.assertIn(data.get("method"), ("Graph API", "IMAP (New)", "IMAP (Old)"))
        self.assertIn("has_more", data)

    @patch(
        "outlook_web.controllers.emails.graph_service.get_email_detail_graph",
        return_value={
            "id": "msg-1",
            "subject": "Hello",
            "from": {"emailAddress": {"address": "a@example.com"}},
            "toRecipients": [{"emailAddress": {"address": "b@example.com"}}],
            "ccRecipients": [],
            "receivedDateTime": "2030-01-01T00:00:00Z",
            "body": {"content": "<p>hi</p>", "contentType": "html"},
        },
    )
    @patch("outlook_web.controllers.emails.accounts_repo.get_account_by_email")
    def test_detail_success_shape(self, mock_get_account, _mock_detail):
        account = self._account()
        mock_get_account.return_value = account
        self._login()
        resp = self.client.get(
            f"/api/email/{account['email']}/msg-1",
            query_string={"method": "graph", "folder": "inbox"},
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        data = resp.get_json() or {}
        self.assertTrue(data.get("success"))
        email = data.get("email") or {}
        for key in ("id", "subject", "from", "body", "body_type"):
            self.assertIn(key, email)

    def test_delete_missing_params(self):
        self._login()
        resp = self.client.post("/api/emails/delete", json={})
        self.assertIn(resp.status_code, (400, 422), resp.get_data(as_text=True))
        data = resp.get_json() or {}
        self.assertFalse(data.get("success", False))

    def test_delete_account_not_found(self):
        self._login()
        with patch(
            "outlook_web.controllers.emails.accounts_repo.get_account_by_email",
            return_value=None,
        ):
            resp = self.client.post(
                "/api/emails/delete",
                json={
                    "email": f"gone_{secrets.token_hex(3)}@example.com",
                    "ids": ["a"],
                },
            )
        self.assertEqual(resp.status_code, 404, resp.get_data(as_text=True))
        data = resp.get_json() or {}
        err = data.get("error") or {}
        if isinstance(err, dict):
            self.assertEqual(err.get("code"), "ACCOUNT_NOT_FOUND")

    def test_detail_account_not_found(self):
        self._login()
        missing = f"missing_{secrets.token_hex(4)}@example.com"
        with patch(
            "outlook_web.controllers.emails.accounts_repo.get_account_by_email",
            return_value=None,
        ):
            resp = self.client.get(f"/api/email/{missing}/some-message-id")
        self.assertEqual(resp.status_code, 404, resp.get_data(as_text=True))
        data = resp.get_json() or {}
        err = data.get("error") or {}
        if isinstance(err, dict):
            self.assertEqual(err.get("code"), "ACCOUNT_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
