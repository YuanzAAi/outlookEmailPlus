from __future__ import annotations

import json
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class _FakeTempMailService:
    def __init__(self) -> None:
        self.deleted_ids: list[str] = []
        self.mailbox_args: list[dict] = []
        self.detail_override: dict | None = None

    def list_messages(self, mailbox, *, sync_remote=True):
        self.mailbox_args.append(mailbox)
        return [
            {
                "id": "cf_msg_1",
                "from_address": "noreply@example.com",
                "subject": "Verification code",
                "content_preview": "Use code 246810",
                "created_at": "2026-07-20T10:00:00Z",
            }
        ]

    def get_message_detail(self, mailbox, message_id, *, refresh_if_missing=True):
        self.mailbox_args.append(mailbox)
        if self.detail_override is not None:
            return self.detail_override
        return {
            "id": message_id,
            "email_address": mailbox["email"],
            "from_address": "noreply@example.com",
            "to_address": mailbox["email"],
            "subject": "Verification code",
            "content": "Use code 246810",
            "html_content": "",
            "raw_content": "raw-message",
            "created_at": "2026-07-20T10:00:00Z",
        }

    def delete_message(self, mailbox, message_id):
        self.mailbox_args.append(mailbox)
        self.deleted_ids.append(message_id)
        return True


class AccountBackedTempMailUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
            from outlook_web.db import get_db

            db = get_db()
            db.execute("DELETE FROM temp_email_messages WHERE email_address LIKE '%@ui-cf-temp.test'")
            db.execute("DELETE FROM temp_emails WHERE email LIKE '%@ui-cf-temp.test'")
            db.execute("DELETE FROM accounts WHERE email LIKE '%@ui-cf-temp.test'")
            db.commit()

    def _login(self, client) -> None:
        response = client.post("/login", json={"password": "testpass123"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])

    def _insert_account(self) -> tuple[int, str]:
        email_addr = f"cf-ui-{uuid.uuid4().hex}@ui-cf-temp.test"
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            group = db.execute("SELECT id FROM groups WHERE name = '默认分组' LIMIT 1").fetchone()
            cursor = db.execute(
                """
                INSERT INTO accounts (
                    email, client_id, refresh_token, account_type, provider,
                    status, group_id, temp_mail_meta
                ) VALUES (?, '', '', 'temp_mail', 'cloudflare_temp_mail', 'active', ?, ?)
                """,
                (
                    email_addr,
                    int(group["id"]) if group else 1,
                    json.dumps(
                        {
                            "provider_name": "cloudflare_temp_mail",
                            "provider_mailbox_id": "501",
                            "provider_jwt": "jwt-501",
                        }
                    ),
                ),
            )
            db.commit()
            return int(cursor.lastrowid), email_addr

    def test_regular_mailbox_workspace_routes_account_backed_temp_mail(self):
        _account_id, email_addr = self._insert_account()
        client = self.app.test_client()
        self._login(client)
        service = _FakeTempMailService()

        with (
            patch("outlook_web.controllers.emails.get_temp_mail_service", return_value=service),
            patch(
                "outlook_web.controllers.emails.compact_summary_service.update_summary_from_message_list",
                return_value={"latest_email_subject": "Verification code"},
            ),
            patch("outlook_web.controllers.emails.outlook_transport.list_messages") as outlook_list,
        ):
            list_response = client.get(f"/api/emails/{email_addr}?folder=inbox&skip=0&top=20")
            detail_response = client.get(f"/api/email/{email_addr}/cf_msg_1?folder=inbox&method=temp")
            delete_response = client.post(
                "/api/emails/delete",
                json={"email": email_addr, "folder": "inbox", "ids": ["cf_msg_1"]},
            )

        self.assertEqual(list_response.status_code, 200)
        list_payload = list_response.get_json()
        self.assertEqual(list_payload["method"], "Temp Mail")
        self.assertEqual(list_payload["emails"][0]["from"], "noreply@example.com")
        self.assertEqual(list_payload["emails"][0]["body_preview"], "Use code 246810")

        self.assertEqual(detail_response.status_code, 200)
        detail = detail_response.get_json()["email"]
        self.assertEqual(detail["body"], "Use code 246810")
        self.assertEqual(detail["method"], "Temp Mail")

        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.get_json()["success_count"], 1)
        self.assertEqual(service.deleted_ids, ["cf_msg_1"])
        self.assertTrue(all(mailbox.get("account_backed") for mailbox in service.mailbox_args))
        outlook_list.assert_not_called()

    def test_account_backed_temp_detail_rewrites_inline_cid_resources(self):
        _account_id, email_addr = self._insert_account()
        client = self.app.test_client()
        self._login(client)
        service = _FakeTempMailService()
        service.detail_override = {
            "id": "cf_msg_inline",
            "email_address": email_addr,
            "from_address": "noreply@example.com",
            "to_address": email_addr,
            "subject": "Inline image",
            "content": "",
            "html_content": '<p>Logo</p><img src="cid:logo-1">',
            "raw_content": json.dumps({"cid_map": {"logo-1": "data:image/png;base64,QUJDRA=="}}),
            "created_at": "2026-07-20T10:00:00Z",
        }

        with patch("outlook_web.controllers.emails.get_temp_mail_service", return_value=service):
            response = client.get(f"/api/email/{email_addr}/cf_msg_inline?folder=inbox&method=temp")

        self.assertEqual(response.status_code, 200)
        detail = response.get_json()["email"]
        self.assertNotIn("cid:logo-1", detail["body"])
        self.assertIn("data:image/png;base64,QUJDRA==", detail["body"])
        self.assertEqual(detail["inline_resources"]["logo-1"], "data:image/png;base64,QUJDRA==")

    def test_batch_fetch_includes_account_backed_temp_mail(self):
        account_id, email_addr = self._insert_account()
        client = self.app.test_client()
        self._login(client)
        service = _FakeTempMailService()

        with (
            patch("outlook_web.controllers.emails.get_temp_mail_service", return_value=service),
            patch(
                "outlook_web.controllers.emails.compact_summary_service.update_summary_from_message_list",
                return_value={},
            ),
        ):
            response = client.post(
                "/api/emails/batch",
                json={
                    "account_ids": [account_id],
                    "folders": ["inbox", "junkemail"],
                    "skip": 0,
                    "top": 10,
                },
            )

        self.assertEqual(response.status_code, 200)
        result = response.get_json()["results"][0]
        self.assertEqual(result["email"], email_addr)
        self.assertTrue(result["success"])
        self.assertEqual(result["folders"]["inbox"]["method"], "Temp Mail")
        self.assertEqual(result["folders"]["junkemail"]["emails"], [])

    def test_poll_engine_uses_existing_verification_endpoint(self):
        poll_engine = (Path(__file__).resolve().parents[1] / "static" / "js" / "features" / "poll-engine.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("/api/emails/' + encodeURIComponent(email) + '/verification?field=code", poll_engine)
        self.assertNotIn("/api/extract-verification?email=", poll_engine)
