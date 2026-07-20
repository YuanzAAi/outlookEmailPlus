from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class ExternalApiTempMailCompatTests(unittest.TestCase):
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
            db.execute("DELETE FROM temp_email_messages WHERE email_address LIKE '%@compat-temp.test'")
            db.execute("DELETE FROM temp_emails WHERE email LIKE '%@compat-temp.test'")
            db.execute("DELETE FROM temp_email_messages WHERE email_address LIKE '%@managed-temp.test'")
            db.execute("DELETE FROM temp_emails WHERE email LIKE '%@managed-temp.test'")
            db.commit()
            settings_repo.set_setting("external_api_key", "compat-key")
            settings_repo.set_setting("temp_mail_provider", "custom_domain_temp_mail")
            settings_repo.set_setting("temp_mail_domains", "[]")
            settings_repo.set_setting("temp_mail_default_domain", "")
            settings_repo.set_setting(
                "temp_mail_prefix_rules",
                '{"min_length":1,"max_length":32,"pattern":"^[a-z0-9][a-z0-9._-]*$"}',
            )

    @staticmethod
    def _headers(api_key: str) -> dict[str, str]:
        return {"X-API-Key": api_key}

    def _create_task_mailbox(
        self,
        *,
        email_addr: str = "worker@compat-temp.test",
        task_token: str = "tmptask_compat",
        consumer_key: str = "legacy:settings.external_api_key",
        status: str = "active",
    ) -> str:
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.repositories import temp_emails as temp_emails_repo

            temp_emails_repo.create_temp_email(
                email_addr=email_addr,
                mailbox_type="task",
                visible_in_ui=False,
                source="custom_domain_temp_mail",
                prefix=email_addr.split("@", 1)[0],
                domain="compat-temp.test",
                task_token=task_token,
                consumer_key=consumer_key,
                caller_id="worker-1",
                task_id="job-001",
            )
            if status != "active":
                db = get_db()
                db.execute(
                    "UPDATE temp_emails SET status = ?, finished_at = CURRENT_TIMESTAMP WHERE email = ?",
                    (status, email_addr),
                )
                db.commit()
        return email_addr

    def _seed_message(
        self,
        email_addr: str,
        *,
        message_id: str = "msg-1",
        content: str = "Use code 246810 to continue. Verify at https://verify.example/confirm",
    ) -> str:
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            temp_emails_repo.save_temp_email_messages(
                email_addr,
                [
                    {
                        "id": message_id,
                        "from_address": "noreply@example.com",
                        "subject": "Your verification code",
                        "content": content,
                        "html_content": "",
                        "timestamp": int(time.time()),
                    }
                ],
            )
        return message_id

    @staticmethod
    def _success_gptmail_request_factory(*, message_id: str, content: str, subject: str = "Your verification code"):
        def _fake_gptmail_request(method, endpoint, params=None, json_data=None):
            if endpoint == "/api/emails":
                return {
                    "success": True,
                    "data": {
                        "emails": [
                            {
                                "id": message_id,
                                "from_address": "noreply@example.com",
                                "subject": subject,
                                "content": content,
                                "html_content": "",
                                "timestamp": int(time.time()),
                            }
                        ]
                    },
                }
            if endpoint == f"/api/email/{message_id}":
                return {
                    "success": True,
                    "data": {
                        "id": message_id,
                        "from_address": "noreply@example.com",
                        "subject": subject,
                        "content": content,
                        "html_content": "",
                        "timestamp": int(time.time()),
                    },
                }
            return {"success": False, "error": "unexpected endpoint", "error_type": "TEST_ERROR", "details": endpoint}

        return _fake_gptmail_request

    def test_task_mailbox_external_read_matrix_covers_list_latest_detail_and_verification_endpoints(self):
        email_addr = self._create_task_mailbox()
        message_id = self._seed_message(email_addr)
        client = self.app.test_client()
        with patch(
            "outlook_web.services.gptmail.gptmail_request",
            side_effect=self._success_gptmail_request_factory(
                message_id=message_id,
                content="Use code 246810 to continue. Verify at https://verify.example/confirm",
            ),
        ):
            messages_resp = client.get(
                f"/api/external/messages?email={email_addr}",
                headers=self._headers("compat-key"),
            )
            self.assertEqual(messages_resp.status_code, 200)
            self.assertEqual(messages_resp.get_json()["data"]["emails"][0]["id"], message_id)

            latest_resp = client.get(
                f"/api/external/messages/latest?email={email_addr}",
                headers=self._headers("compat-key"),
            )
            self.assertEqual(latest_resp.status_code, 200)
            self.assertEqual(latest_resp.get_json()["data"]["id"], message_id)

            detail_resp = client.get(
                f"/api/external/messages/{message_id}?email={email_addr}",
                headers=self._headers("compat-key"),
            )
            self.assertEqual(detail_resp.status_code, 200)
            detail_data = detail_resp.get_json()["data"]
            self.assertEqual(detail_data["id"], message_id)
            self.assertIn("246810", detail_data["content"])

            verification_code_resp = client.get(
                f"/api/external/verification-code?email={email_addr}",
                headers=self._headers("compat-key"),
            )
            self.assertEqual(verification_code_resp.status_code, 200)
            self.assertEqual(verification_code_resp.get_json()["data"]["verification_code"], "246810")

            verification_link_resp = client.get(
                f"/api/external/verification-link?email={email_addr}",
                headers=self._headers("compat-key"),
            )
            self.assertEqual(verification_link_resp.status_code, 200)
            self.assertEqual(
                verification_link_resp.get_json()["data"]["verification_link"],
                "https://verify.example/confirm",
            )

    def test_latest_local_only_mode_does_not_sync_temp_mail_upstream(self):
        email_addr = self._create_task_mailbox(email_addr="localonly@compat-temp.test")
        client = self.app.test_client()
        with patch("outlook_web.services.external_api.get_temp_mail_service") as get_service:
            service = get_service.return_value
            service.list_messages.return_value = [
                {
                    "id": "msg-local-only",
                    "subject": "Local verification code",
                    "content": "Use code 246810 to continue.",
                    "timestamp": int(time.time()),
                }
            ]
            response = client.get(
                f"/api/external/messages/latest?email={email_addr}&discover_remote=0",
                headers=self._headers("compat-key"),
            )

        self.assertEqual(response.status_code, 200)
        service.list_messages.assert_called_once()
        self.assertFalse(service.list_messages.call_args.kwargs["sync_remote"])

    def test_external_verification_auto_discovers_managed_cloudflare_address(self):
        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo

            settings_repo.set_setting("temp_mail_provider", "cloudflare_temp_mail")
            settings_repo.set_setting(
                "cf_worker_domains",
                '[{"name":"managed-temp.test","enabled":true,"is_default":true}]',
            )
            settings_repo.set_setting("cf_worker_default_domain", "managed-temp.test")

        discovered = {
            "success": True,
            "email": "autoflow@managed-temp.test",
            "provider_name": "cloudflare_temp_mail",
            "meta": {
                "provider_name": "cloudflare_temp_mail",
                "provider_mailbox_id": "501",
                "provider_jwt": "jwt-501",
            },
        }
        messages = [
            {
                "id": "cf_9001",
                "from_address": "noreply@example.com",
                "subject": "Your verification code",
                "content": "Use code 135790 to continue.",
                "html_content": "",
                "timestamp": int(time.time()),
            }
        ]
        client = self.app.test_client()
        with (
            patch(
                "outlook_web.services.temp_mail_provider_cf.CloudflareTempMailProvider.discover_mailbox",
                return_value=discovered,
            ) as discover_mock,
            patch(
                "outlook_web.services.temp_mail_provider_cf.CloudflareTempMailProvider.list_messages",
                return_value=messages,
            ),
        ):
            response = client.get(
                "/api/external/verification-code?email=AUTOFLOW@managed-temp.test",
                headers=self._headers("compat-key"),
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertEqual(data["verification_code"], "135790")
        self.assertEqual(data["email"], "autoflow@managed-temp.test")
        discover_mock.assert_called_once_with("AUTOFLOW@managed-temp.test")

    def test_finish_rejects_external_read_matrix_for_task_mailbox(self):
        email_addr = self._create_task_mailbox(task_token="tmptask_finish_matrix")
        message_id = self._seed_message(email_addr)
        client = self.app.test_client()

        finish_resp = client.post(
            "/api/external/temp-emails/tmptask_finish_matrix/finish",
            headers=self._headers("compat-key"),
            json={"result": "success", "detail": "done"},
        )
        self.assertEqual(finish_resp.status_code, 200)

        blocked_paths = [
            f"/api/external/messages?email={email_addr}",
            f"/api/external/messages/latest?email={email_addr}",
            f"/api/external/messages/{message_id}?email={email_addr}",
            f"/api/external/verification-code?email={email_addr}",
            f"/api/external/verification-link?email={email_addr}",
        ]
        for path in blocked_paths:
            with self.subTest(path=path):
                resp = client.get(path, headers=self._headers("compat-key"))
                self.assertEqual(resp.status_code, 409)
                self.assertEqual(resp.get_json()["code"], "TASK_FINISHED")

    def test_other_consumer_gets_403_for_task_mailbox_read_wait_and_probe_paths(self):
        with self.app.app_context():
            from outlook_web.repositories import external_api_keys as external_api_keys_repo

            owner = external_api_keys_repo.create_external_api_key(name="owner", api_key="owner-key")
            external_api_keys_repo.create_external_api_key(name="other", api_key="other-key")

        email_addr = self._create_task_mailbox(
            email_addr="owner@compat-temp.test",
            task_token="tmptask_owner",
            consumer_key=owner["consumer_key"],
        )
        message_id = self._seed_message(email_addr)
        client = self.app.test_client()

        owner_paths = [
            f"/api/external/messages?email={email_addr}",
            f"/api/external/messages/latest?email={email_addr}",
            f"/api/external/messages/{message_id}?email={email_addr}",
            f"/api/external/verification-code?email={email_addr}",
            f"/api/external/verification-link?email={email_addr}",
        ]
        with patch(
            "outlook_web.services.gptmail.gptmail_request",
            side_effect=self._success_gptmail_request_factory(
                message_id=message_id,
                content="Use code 246810 to continue. Verify at https://verify.example/confirm",
            ),
        ):
            for path in owner_paths:
                with self.subTest(owner_path=path):
                    resp = client.get(path, headers=self._headers("owner-key"))
                    self.assertEqual(resp.status_code, 200)

        wait_owner_resp = client.get(
            f"/api/external/wait-message?mode=async&email={email_addr}&timeout_seconds=30&poll_interval=5",
            headers=self._headers("owner-key"),
        )
        self.assertEqual(wait_owner_resp.status_code, 202)
        probe_id = wait_owner_resp.get_json()["data"]["probe_id"]

        probe_owner_resp = client.get(
            f"/api/external/probe/{probe_id}",
            headers=self._headers("owner-key"),
        )
        self.assertEqual(probe_owner_resp.status_code, 200)
        self.assertEqual(probe_owner_resp.get_json()["data"]["status"], "pending")

        other_paths = owner_paths + [
            f"/api/external/wait-message?mode=async&email={email_addr}&timeout_seconds=30&poll_interval=5",
            f"/api/external/probe/{probe_id}",
        ]
        for path in other_paths:
            with self.subTest(other_path=path):
                resp = client.get(path, headers=self._headers("other-key"))
                self.assertEqual(resp.status_code, 403)
                self.assertEqual(resp.get_json()["code"], "EMAIL_SCOPE_FORBIDDEN")

    def test_finish_transitions_pending_probe_to_probe_cancelled_contract(self):
        email_addr = self._create_task_mailbox(task_token="tmptask_probe")
        client = self.app.test_client()

        probe_resp = client.get(
            f"/api/external/wait-message?mode=async&email={email_addr}&timeout_seconds=30&poll_interval=5",
            headers=self._headers("compat-key"),
        )
        self.assertEqual(probe_resp.status_code, 202)
        probe_id = probe_resp.get_json()["data"]["probe_id"]

        finish_resp = client.post(
            "/api/external/temp-emails/tmptask_probe/finish",
            headers=self._headers("compat-key"),
            json={"result": "success", "detail": "done"},
        )
        self.assertEqual(finish_resp.status_code, 200)

        status_resp = client.get(
            f"/api/external/probe/{probe_id}",
            headers=self._headers("compat-key"),
        )
        self.assertEqual(status_resp.status_code, 409)
        status_data = status_resp.get_json()
        self.assertEqual(status_data["code"], "PROBE_CANCELLED")
        self.assertEqual(status_data["data"]["status"], "cancelled")
        self.assertEqual(status_data["data"]["error_code"], "PROBE_CANCELLED")

        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services import external_api as external_api_service

            db = get_db()
            row = db.execute(
                "SELECT status, error_code FROM external_probe_cache WHERE id = ?",
                (probe_id,),
            ).fetchone()
            status = external_api_service.get_probe_status(probe_id)

        self.assertEqual(row["status"], "cancelled")
        self.assertEqual(row["error_code"], "PROBE_CANCELLED")
        self.assertEqual(status["status"], "cancelled")
        self.assertEqual(status["error_code"], "PROBE_CANCELLED")

    def test_temp_mail_list_read_failure_returns_upstream_read_failed_for_external_read_endpoints(self):
        email_addr = self._create_task_mailbox(email_addr="listfail@compat-temp.test", task_token="tmptask_listfail")
        client = self.app.test_client()

        with patch(
            "outlook_web.services.gptmail.gptmail_request",
            return_value={
                "success": False,
                "error": "API 请求超时",
                "error_type": "TIMEOUT_ERROR",
                "details": "request timed out",
            },
        ):
            for path in (
                f"/api/external/messages?email={email_addr}",
                f"/api/external/messages/latest?email={email_addr}",
                f"/api/external/verification-code?email={email_addr}",
                f"/api/external/verification-link?email={email_addr}",
            ):
                with self.subTest(path=path):
                    resp = client.get(path, headers=self._headers("compat-key"))
                    self.assertEqual(resp.status_code, 502)
                    self.assertEqual(resp.get_json()["code"], "UPSTREAM_READ_FAILED")

    def test_temp_mail_detail_read_failure_returns_upstream_read_failed_for_detail_and_verification(self):
        email_addr = self._create_task_mailbox(email_addr="detailfail@compat-temp.test", task_token="tmptask_detailfail")
        client = self.app.test_client()

        def _fake_gptmail_request(method, endpoint, params=None, json_data=None):
            if endpoint == "/api/emails":
                return {
                    "success": True,
                    "data": {
                        "emails": [
                            {
                                "id": "msg-upstream-1",
                                "from_address": "noreply@example.com",
                                "subject": "Verify account",
                                "content": "Code 654321",
                                "timestamp": int(time.time()),
                            }
                        ]
                    },
                }
            if endpoint == "/api/email/msg-upstream-1":
                return {
                    "success": False,
                    "error": "临时邮箱服务暂时不可用",
                    "error_type": "SERVER_ERROR",
                    "details": "HTTP 503",
                }
            return {"success": False, "error": "unexpected endpoint", "error_type": "TEST_ERROR", "details": endpoint}

        with patch("outlook_web.services.gptmail.gptmail_request", side_effect=_fake_gptmail_request):
            detail_resp = client.get(
                f"/api/external/messages/msg-upstream-1?email={email_addr}",
                headers=self._headers("compat-key"),
            )
            self.assertEqual(detail_resp.status_code, 502)
            self.assertEqual(detail_resp.get_json()["code"], "UPSTREAM_READ_FAILED")

            for path in (
                f"/api/external/verification-code?email={email_addr}",
                f"/api/external/verification-link?email={email_addr}",
            ):
                with self.subTest(path=path):
                    resp = client.get(path, headers=self._headers("compat-key"))
                    self.assertEqual(resp.status_code, 502)
                    self.assertEqual(resp.get_json()["code"], "UPSTREAM_READ_FAILED")
