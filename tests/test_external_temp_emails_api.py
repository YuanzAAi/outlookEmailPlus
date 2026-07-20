from __future__ import annotations

import unittest
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class ExternalTempEmailsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
            from outlook_web.db import get_db
            from outlook_web.repositories import settings as settings_repo

            db = get_db()
            db.execute("DELETE FROM external_api_keys")
            db.execute("DELETE FROM external_probe_cache")
            db.execute("DELETE FROM temp_email_messages WHERE email_address LIKE '%@ext-temp.test'")
            db.execute("DELETE FROM temp_emails WHERE email LIKE '%@ext-temp.test'")
            db.commit()
            settings_repo.set_setting("external_api_key", "contract-key")
            settings_repo.set_setting("temp_mail_provider", "custom_domain_temp_mail")
            settings_repo.set_setting("temp_mail_domains", "[]")
            settings_repo.set_setting("temp_mail_default_domain", "")
            settings_repo.set_setting(
                "temp_mail_prefix_rules",
                '{"min_length":1,"max_length":32,"pattern":"^[a-z0-9][a-z0-9._-]*$"}',
            )

    @staticmethod
    def _headers(api_key: str = "contract-key") -> dict[str, str]:
        return {"X-API-Key": api_key}

    def test_apply_endpoint_returns_hidden_task_mailbox_and_persists_record(self):
        client = self.app.test_client()

        with patch("outlook_web.services.gptmail.generate_temp_email", return_value=("demo123@ext-temp.test", None)):
            resp = client.post(
                "/api/external/temp-emails/apply",
                headers=self._headers(),
                json={
                    "caller_id": "register-worker-1",
                    "task_id": "job-001",
                    "prefix": "demo123",
                    "domain": "ext-temp.test",
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["code"], "OK")
        self.assertEqual(data["data"]["email"], "demo123@ext-temp.test")
        self.assertFalse(data["data"]["visible_in_ui"])
        self.assertTrue(data["data"]["task_token"].startswith("tmptask_"))

        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            saved = temp_emails_repo.get_temp_email_by_task_token(data["data"]["task_token"])

        self.assertIsNotNone(saved)
        self.assertEqual(saved["consumer_key"], "legacy:settings.external_api_key")
        self.assertEqual(saved["mailbox_type"], "task")
        self.assertFalse(saved["visible_in_ui"])

    def test_apply_endpoint_requires_caller_id_and_task_id(self):
        client = self.app.test_client()
        payloads = [
            {"task_id": "job-001"},
            {"caller_id": "worker-1"},
        ]

        for payload in payloads:
            with self.subTest(payload=payload):
                resp = client.post(
                    "/api/external/temp-emails/apply",
                    headers=self._headers(),
                    json=payload,
                )
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(resp.get_json()["code"], "INVALID_PARAM")

    def test_finish_endpoint_marks_finished_and_cancels_pending_probe(self):
        client = self.app.test_client()

        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.repositories import temp_emails as temp_emails_repo

            temp_emails_repo.create_temp_email(
                email_addr="finish@ext-temp.test",
                mailbox_type="task",
                visible_in_ui=False,
                source="custom_domain_temp_mail",
                prefix="finish",
                domain="ext-temp.test",
                task_token="tmptask_finish",
                consumer_key="legacy:settings.external_api_key",
                caller_id="worker-1",
                task_id="job-001",
            )
            db = get_db()
            db.execute(
                """
                INSERT INTO external_probe_cache
                    (id, email_addr, folder, from_contains, subject_contains, since_minutes,
                     timeout_seconds, poll_interval, status, expires_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', '+5 minutes'), datetime('now'), datetime('now'))
                """,
                ("probe-finish", "finish@ext-temp.test", "inbox", "", "", None, 30, 5, "pending"),
            )
            db.commit()

        resp = client.post(
            "/api/external/temp-emails/tmptask_finish/finish",
            headers=self._headers(),
            json={"result": "success", "detail": "done"},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["task_token"], "tmptask_finish")
        self.assertEqual(data["data"]["status"], "finished")

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            mailbox = db.execute(
                "SELECT status, finished_at FROM temp_emails WHERE task_token = ?",
                ("tmptask_finish",),
            ).fetchone()
            probe = db.execute(
                "SELECT status, error_code FROM external_probe_cache WHERE id = ?",
                ("probe-finish",),
            ).fetchone()

        self.assertEqual(mailbox["status"], "finished")
        self.assertTrue(mailbox["finished_at"])
        self.assertEqual(probe["status"], "cancelled")
        self.assertEqual(probe["error_code"], "PROBE_CANCELLED")

    def test_finish_endpoint_rejects_invalid_token_and_repeat_finish(self):
        client = self.app.test_client()

        invalid_resp = client.post(
            "/api/external/temp-emails/tmptask_missing/finish",
            headers=self._headers(),
            json={"result": "failed"},
        )
        self.assertEqual(invalid_resp.status_code, 404)
        self.assertEqual(invalid_resp.get_json()["code"], "TASK_TOKEN_INVALID")

        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            temp_emails_repo.create_temp_email(
                email_addr="repeat@ext-temp.test",
                mailbox_type="task",
                visible_in_ui=False,
                source="custom_domain_temp_mail",
                prefix="repeat",
                domain="ext-temp.test",
                task_token="tmptask_repeat",
                consumer_key="legacy:settings.external_api_key",
                caller_id="worker-1",
                task_id="job-002",
            )

        first_resp = client.post(
            "/api/external/temp-emails/tmptask_repeat/finish",
            headers=self._headers(),
            json={"result": "success"},
        )
        self.assertEqual(first_resp.status_code, 200)

        second_resp = client.post(
            "/api/external/temp-emails/tmptask_repeat/finish",
            headers=self._headers(),
            json={"result": "success"},
        )
        self.assertEqual(second_resp.status_code, 409)
        self.assertEqual(second_resp.get_json()["code"], "TASK_ALREADY_FINISHED")

    def test_finish_endpoint_rejects_other_consumer_key(self):
        with self.app.app_context():
            from outlook_web.repositories import external_api_keys as external_api_keys_repo
            from outlook_web.repositories import temp_emails as temp_emails_repo

            owner = external_api_keys_repo.create_external_api_key(name="owner", api_key="owner-key")
            external_api_keys_repo.create_external_api_key(name="other", api_key="other-key")
            temp_emails_repo.create_temp_email(
                email_addr="owned@ext-temp.test",
                mailbox_type="task",
                visible_in_ui=False,
                source="custom_domain_temp_mail",
                prefix="owned",
                domain="ext-temp.test",
                task_token="tmptask_owned",
                consumer_key=owner["consumer_key"],
                caller_id="worker-1",
                task_id="job-002",
            )

        client = self.app.test_client()
        resp = client.post(
            "/api/external/temp-emails/tmptask_owned/finish",
            headers=self._headers("other-key"),
            json={"result": "success"},
        )

        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertEqual(data["code"], "FORBIDDEN")

    def test_wait_message_returns_task_finished_when_finish_happens_during_wait(self):
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            temp_emails_repo.create_temp_email(
                email_addr="wait@ext-temp.test",
                mailbox_type="task",
                visible_in_ui=False,
                source="custom_domain_temp_mail",
                prefix="wait",
                domain="ext-temp.test",
                task_token="tmptask_wait",
                consumer_key="legacy:settings.external_api_key",
                caller_id="worker-1",
                task_id="job-003",
            )

        call_count = {"value": 0}

        def _finish_during_first_poll(*, email_addr: str, **_: object):
            call_count["value"] += 1
            if call_count["value"] == 1:
                with self.app.app_context():
                    from outlook_web.repositories import temp_emails as temp_emails_repo

                    temp_emails_repo.finish_task_temp_email("tmptask_wait")
                from outlook_web.services import external_api as external_api_service

                raise external_api_service.MailNotFoundError("not yet")
            raise AssertionError("wait-message should stop before a second upstream poll")

        client = self.app.test_client()
        with patch("outlook_web.services.external_api.get_latest_message_for_external", side_effect=_finish_during_first_poll):
            with patch("outlook_web.services.external_api.time.sleep", return_value=None):
                resp = client.get(
                    "/api/external/wait-message?email=wait@ext-temp.test&timeout_seconds=2&poll_interval=1",
                    headers=self._headers(),
                )

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["code"], "TASK_FINISHED")

    def test_inbound_endpoint_requires_api_key_and_persists_cloudflare_message(self):
        client = self.app.test_client()
        payload = {
            "email": "inbound@ext-temp.test",
            "address_id": 71,
            "provider_jwt": "jwt-71",
            "message": {
                "id": 9001,
                "from_address": "sender@example.com",
                "subject": "Code 445566",
                "content": "Your verification code is 445566",
                "created_at": "2026-07-20T00:00:00Z",
            },
        }

        unauthorized = client.post("/api/external/temp-emails/inbound", json=payload)
        self.assertEqual(unauthorized.status_code, 401)

        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo

            settings_repo.set_setting("temp_mail_provider", "cloudflare_temp_mail")
            settings_repo.set_setting(
                "cf_worker_domains",
                '[{"name":"ext-temp.test","enabled":true}]',
            )

        resp = client.post(
            "/api/external/temp-emails/inbound",
            headers=self._headers(),
            json=payload,
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["message_id"], "cf_9001")
        self.assertTrue(data["data"]["visible_in_ui"])

        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            mailbox = temp_emails_repo.get_temp_email_by_address("inbound@ext-temp.test")
            messages = temp_emails_repo.get_temp_email_messages("inbound@ext-temp.test")

        self.assertEqual(mailbox["meta_json"]["provider_jwt"], "jwt-71")
        self.assertEqual(messages[0]["subject"], "Code 445566")
