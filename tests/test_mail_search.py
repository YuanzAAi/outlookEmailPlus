import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from outlook_web.services import graph, mail_search
from tests._import_app import clear_login_attempts, import_web_app_module


class MailSearchTests(unittest.TestCase):
    def test_mailbox_scope_defaults_to_regular_and_rejects_unknown_values(self):
        self.assertEqual(mail_search._normalize_params({"query": "marker"})["mailbox_scope"], "regular")
        with self.assertRaises(mail_search.MailSearchError):
            mail_search._normalize_params({"query": "marker", "mailbox_scope": "unknown"})

    def test_invalid_regex_is_rejected(self):
        with self.assertRaises(mail_search.MailSearchError):
            mail_search._normalize_params({"query": "(", "regex": True})

    def test_cancel_job_uses_durable_marker(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "outlook_web.services.mail_search._job_dir", return_value=Path(temp_dir)
        ):
            job_id = "b" * 32
            path = Path(temp_dir) / f"{job_id}.json"
            path.write_text(
                json.dumps({"job_id": job_id, "status": "running", "cancel_requested": False}),
                encoding="utf-8",
            )

            result = mail_search.cancel_job(job_id)

            self.assertTrue(result["cancel_requested"])
            self.assertTrue((Path(temp_dir) / f"{job_id}.cancel").exists())
            self.assertTrue(mail_search._is_cancel_requested(job_id))

    @patch("outlook_web.services.mail_search.graph_service.get_email_detail_graph")
    @patch("outlook_web.services.mail_search.outlook_transport.list_messages")
    def test_body_search_returns_matching_account_and_message(self, mock_list, mock_detail):
        mock_list.return_value = {
            "success": True,
            "method": "Graph API",
            "method_key": "graph",
            "channel": "graph_inbox",
            "emails": [
                {
                    "id": "m1",
                    "subject": "Welcome",
                    "from": {"emailAddress": {"address": "sender@example.com"}},
                    "bodyPreview": "No visible match",
                    "receivedDateTime": "2026-07-19T00:00:00Z",
                }
            ],
        }
        mock_detail.return_value = {
            "success": True,
            "detail": {
                "body": {
                    "contentType": "text",
                    "content": "Your private marker is Alpha-7788",
                }
            },
        }
        account = {
            "id": 7,
            "email": "target@example.com",
            "client_id": "cid",
            "refresh_token": "rt",
            "account_type": "outlook",
            "group_id": 1,
            "preferred_verification_channel": "imap_new",
        }
        params = mail_search._normalize_params(
            {
                "query": "Alpha-7788",
                "fields": ["body"],
                "folders": ["inbox"],
                "top_per_folder": 10,
            }
        )

        result = mail_search._scan_account(account, params)

        self.assertEqual(result["scanned_messages"], 1)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["email"], "target@example.com")
        self.assertEqual(result["results"][0]["matched_fields"], ["body"])

    @patch("outlook_web.services.mail_search.outlook_transport.get_detail")
    @patch("outlook_web.services.mail_search.outlook_transport.list_messages")
    def test_imap_search_reuses_full_body_from_list(self, mock_list, mock_detail):
        mock_list.return_value = {
            "success": True,
            "method": "IMAP (New)",
            "method_key": "imap_new",
            "channel": "imap_new",
            "emails": [
                {
                    "id": "uid-1",
                    "subject": "Welcome",
                    "from": "sender@example.com",
                    "body_preview": "No visible match",
                    "_search_body": "The complete IMAP body contains Access-9911",
                    "date": "2026-07-19T00:00:00Z",
                }
            ],
        }
        account = {
            "id": 9,
            "email": "imap@example.com",
            "client_id": "cid",
            "refresh_token": "rt",
            "account_type": "outlook",
            "preferred_verification_channel": "imap_new",
        }
        params = mail_search._normalize_params(
            {
                "query": "Access-9911",
                "fields": ["body"],
                "folders": ["inbox"],
            }
        )

        result = mail_search._scan_account(account, params, http_session=object())

        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["matched_fields"], ["body"])
        self.assertTrue(mock_list.call_args.kwargs["include_search_body"])
        mock_detail.assert_not_called()

    @patch("outlook_web.services.mail_search.get_email_detail_imap_generic_result")
    @patch("outlook_web.services.mail_search.get_emails_imap_generic")
    def test_generic_imap_search_reuses_full_body_from_list(self, mock_list, mock_detail):
        mock_list.return_value = {
            "success": True,
            "method": "IMAP (Generic)",
            "emails": [
                {
                    "id": "uid-2",
                    "subject": "Welcome",
                    "from": "sender@example.com",
                    "body_preview": "No visible match",
                    "_search_body": "The complete generic IMAP body contains Generic-8822",
                    "date": "2026-07-19T00:00:00Z",
                }
            ],
        }
        account = {
            "id": 12,
            "email": "generic@example.com",
            "imap_password": "app-password",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "account_type": "imap",
            "provider": "custom",
        }
        params = mail_search._normalize_params(
            {
                "query": "Generic-8822",
                "fields": ["body"],
                "folders": ["inbox"],
            }
        )

        result = mail_search._scan_account(account, params)

        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["matched_fields"], ["body"])
        self.assertTrue(mock_list.call_args.kwargs["include_search_body"])
        mock_detail.assert_not_called()

    @patch("outlook_web.services.mail_search.graph_service.get_access_token_graph_result")
    def test_terminal_graph_auth_failure_skips_legacy_fallback(self, mock_token):
        mock_token.return_value = {
            "success": False,
            "error": {
                "code": "GRAPH_TOKEN_FAILED",
                "details": {"error": "invalid_grant"},
            },
        }
        account = {
            "id": 10,
            "email": "expired@example.com",
            "client_id": "cid",
            "refresh_token": "rt",
            "account_type": "outlook",
            "preferred_verification_channel": "graph_inbox",
        }
        params = mail_search._normalize_params({"query": "access", "fields": ["body"], "folders": ["inbox", "junkemail"]})

        result = mail_search._scan_graph_account(account, params, object())

        self.assertEqual(result["results"], [])
        self.assertEqual(result["errors"], ["授权已失效"])

    @patch("outlook_web.services.mail_search.outlook_transport.list_messages")
    def test_legacy_scan_stops_after_terminal_auth_failure(self, mock_list):
        mock_list.return_value = {
            "success": False,
            "auth_expired": True,
            "error": {
                "code": "IMAP_TOKEN_FAILED",
                "details": {"error": "invalid_grant"},
            },
        }
        account = {
            "id": 11,
            "email": "expired-imap@example.com",
            "client_id": "cid",
            "refresh_token": "rt",
            "account_type": "outlook",
            "preferred_verification_channel": "imap_new",
        }
        params = mail_search._normalize_params({"query": "access", "fields": ["body"], "folders": ["inbox", "junkemail"]})

        result = mail_search._scan_account_legacy(account, params)

        self.assertEqual(mock_list.call_count, 1)
        self.assertEqual(result["errors"], ["inbox: 读取失败"])

    def test_simple_literal_builds_graph_server_search(self):
        params = mail_search._normalize_params(
            {
                "query": "access",
                "fields": ["subject", "preview", "body"],
                "folders": ["inbox"],
            }
        )

        self.assertEqual(mail_search._graph_search_query(params), "subject:access* OR body:access*")

    @patch("outlook_web.services.mail_search.graph_service.get_email_detail_graph")
    @patch("outlook_web.services.mail_search.graph_service.get_emails_graph_with_access_token")
    @patch("outlook_web.services.mail_search.graph_service.get_access_token_graph_result")
    def test_graph_body_search_reuses_token_and_skips_detail(self, mock_token, mock_list, mock_detail):
        mock_token.return_value = {
            "success": True,
            "access_token": "access-token",
            "scope": "Mail.Read offline_access",
            "new_refresh_token": "rotated-token",
        }
        mock_list.return_value = {
            "success": True,
            "emails": [
                {
                    "id": "m2",
                    "subject": "Welcome",
                    "from": {"emailAddress": {"address": "sender@example.com"}},
                    "bodyPreview": "No visible match",
                    "body": {
                        "contentType": "text",
                        "content": "Your access marker is Alpha-7788",
                    },
                    "receivedDateTime": "2026-07-19T00:00:00Z",
                }
            ],
        }
        account = {
            "id": 8,
            "email": "graph@example.com",
            "client_id": "cid",
            "refresh_token": "rt",
            "account_type": "outlook",
            "preferred_verification_channel": "graph_inbox",
        }
        params = mail_search._normalize_params(
            {
                "query": "Alpha",
                "fields": ["body"],
                "folders": ["inbox"],
                "top_per_folder": 20,
            }
        )

        result = mail_search._scan_account(account, params, http_session=object())

        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["matched_fields"], ["body"])
        mock_token.assert_called_once()
        mock_list.assert_called_once()
        self.assertEqual(mock_list.call_args.kwargs["search_query"], "body:Alpha*")
        self.assertTrue(mock_list.call_args.kwargs["include_body"])
        mock_detail.assert_not_called()

    def test_graph_search_helper_reuses_access_token(self):
        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {"value": [{"id": "m3"}]}

        class FakeSession:
            def __init__(self):
                self.kwargs = None

            def get(self, _url, **kwargs):
                self.kwargs = kwargs
                return FakeResponse()

        session = FakeSession()
        result = graph.get_emails_graph_with_access_token(
            "access-token",
            folder="junkemail",
            top=10,
            search_query="body:access*",
            include_body=True,
            session=session,
            timeout=7,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["emails"], [{"id": "m3"}])
        self.assertEqual(session.kwargs["params"]["$search"], '"body:access*"')
        self.assertIn("body", session.kwargs["params"]["$select"])
        self.assertEqual(session.kwargs["timeout"], 7)

    @patch("outlook_web.services.mail_search.temp_emails_repo.get_temp_email_messages")
    def test_temp_mailbox_scan_matches_cached_body_without_remote_transport(self, mock_messages):
        mock_messages.return_value = [
            {
                "message_id": "temp-message-1",
                "from_address": "sender@example.com",
                "subject": "Welcome",
                "content": "Your temporary access marker is Temp-7788",
                "html_content": "",
                "timestamp": 1784462400,
            }
        ]
        params = mail_search._normalize_params(
            {
                "query": "Temp-7788",
                "fields": ["body"],
                "folders": ["inbox"],
                "mailbox_scope": "temp",
            }
        )

        result = mail_search._scan_temp_mailbox({"email": "local@search-temp.test"}, params)

        self.assertEqual(result["scanned_messages"], 1)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["source_type"], "temp")
        self.assertIsNone(result["results"][0]["account_id"])
        self.assertEqual(result["results"][0]["method_key"], "temp")


class MailSearchFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.template = (root / "templates" / "index.html").read_text(encoding="utf-8")
        cls.script = (root / "static" / "js" / "features" / "mail_search.js").read_text(encoding="utf-8")

    def test_mailbox_scope_selector_defaults_to_regular_and_offers_all_scopes(self):
        self.assertIn('id="mailSearchMailboxScope"', self.template)
        self.assertIn('<option value="regular" selected>普通邮箱</option>', self.template)
        self.assertIn('<option value="temp">临时邮箱</option>', self.template)
        self.assertIn('<option value="all">全部邮箱</option>', self.template)
        self.assertIn("mailbox_scope:", self.script)

    def test_temp_results_keep_temp_routes_and_skip_account_level_actions(self):
        self.assertIn("function isTempMailSearchResult(result)", self.script)
        self.assertIn("/api/temp-emails/${encodeURIComponent(result.email)}/messages/", self.script)
        self.assertIn(".filter(item => !isTempMailSearchResult(item))", self.script)


class MailSearchEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
            from outlook_web.db import get_db

            db = get_db()
            db.execute("DELETE FROM temp_email_messages WHERE email_address LIKE '%@search-temp.test'")
            db.execute("DELETE FROM temp_emails WHERE email LIKE '%@search-temp.test'")
            db.commit()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = 1

    def _insert_temp_message(self, email_addr: str, message_id: str, content: str) -> None:
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            db.execute(
                "INSERT INTO temp_emails (email, status, mailbox_type, visible_in_ui) VALUES (?, 'active', 'user', 1)",
                (email_addr,),
            )
            db.execute(
                """
                INSERT INTO temp_email_messages
                (message_id, email_address, from_address, subject, content, html_content, has_html, timestamp, raw_content)
                VALUES (?, ?, ?, ?, ?, '', 0, ?, '{}')
                """,
                (message_id, email_addr, "sender@example.com", "Temporary marker", content, 1784462400),
            )
            db.commit()

    @staticmethod
    def _queued_job(job_id: str, params: dict) -> dict:
        return {
            "job_id": job_id,
            "status": "queued",
            "params": params,
            "progress": {"total_accounts": 0, "scanned_accounts": 0, "scanned_messages": 0},
            "summary": {
                "total_matches": 0,
                "stored_results": 0,
                "failed_accounts": 0,
                "truncated": False,
            },
            "results": [],
            "errors": [],
            "cancel_requested": False,
        }

    def test_temp_scope_job_only_reads_local_temp_mail(self):
        email_addr = "temp-only@search-temp.test"
        self._insert_temp_message(email_addr, "temp-only-message", "LocalOnly-4411")
        params = mail_search._normalize_params(
            {
                "query": "LocalOnly-4411",
                "fields": ["body"],
                "folders": ["inbox"],
                "mailbox_scope": "temp",
                "account_query": email_addr,
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "outlook_web.services.mail_search._job_dir", return_value=Path(temp_dir)
        ), patch("outlook_web.services.mail_search._load_accounts") as regular_loader, patch(
            "outlook_web.services.mail_search._get_shared_http_session"
        ) as http_session, patch(
            "outlook_web.services.mail_search._scan_account"
        ) as regular_scanner, patch(
            "outlook_web.services.mail_search.temp_emails_repo.get_temp_email_messages"
        ) as per_mailbox_loader:
            job_id = "c" * 32
            mail_search._atomic_write(mail_search._job_path(job_id), self._queued_job(job_id, params))
            mail_search._run_job(self.app, job_id)
            result = mail_search.get_job(job_id)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["progress"], {"total_accounts": 1, "scanned_accounts": 1, "scanned_messages": 1})
        self.assertEqual(result["results"][0]["source_type"], "temp")
        regular_loader.assert_not_called()
        regular_scanner.assert_not_called()
        http_session.assert_not_called()
        per_mailbox_loader.assert_not_called()

    def test_all_scope_job_merges_temp_and_regular_results(self):
        email_addr = "all-scope@search-temp.test"
        self._insert_temp_message(email_addr, "all-temp-message", "Shared-5522")
        params = mail_search._normalize_params(
            {
                "query": "Shared-5522",
                "fields": ["body"],
                "folders": ["inbox"],
                "mailbox_scope": "all",
                "account_query": email_addr,
            }
        )
        regular_account = {"id": 77, "email": "regular@example.com", "group_id": 1}
        regular_result = {
            "account_id": 77,
            "email": regular_account["email"],
            "results": [
                {
                    "source_type": "regular",
                    "account_id": 77,
                    "email": regular_account["email"],
                    "group_id": 1,
                    "message_id": "regular-message",
                    "folder": "inbox",
                    "from": "sender@example.com",
                    "subject": "Regular marker",
                    "preview": "Shared-5522",
                    "received_at": "2026-07-19T00:00:00Z",
                    "method": "Graph API",
                    "method_key": "graph",
                    "matched_fields": ["body"],
                    "excerpt": "Shared-5522",
                }
            ],
            "scanned_messages": 1,
            "errors": [],
            "preference_updates": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "outlook_web.services.mail_search._job_dir", return_value=Path(temp_dir)
        ), patch("outlook_web.services.mail_search._load_accounts", return_value=([regular_account], False)), patch(
            "outlook_web.services.mail_search._get_shared_http_session", return_value=object()
        ), patch(
            "outlook_web.services.mail_search._scan_account", return_value=regular_result
        ):
            job_id = "d" * 32
            mail_search._atomic_write(mail_search._job_path(job_id), self._queued_job(job_id, params))
            mail_search._run_job(self.app, job_id)
            result = mail_search.get_job(job_id)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["progress"], {"total_accounts": 2, "scanned_accounts": 2, "scanned_messages": 2})
        self.assertEqual({item["source_type"] for item in result["results"]}, {"regular", "temp"})

    def test_start_poll_and_cancel_endpoint_contracts(self):
        job = {
            "job_id": "a" * 32,
            "status": "queued",
            "params": {"query": "marker"},
            "progress": {
                "total_accounts": 0,
                "scanned_accounts": 0,
                "scanned_messages": 0,
            },
            "summary": {
                "total_matches": 0,
                "stored_results": 0,
                "failed_accounts": 0,
                "truncated": False,
            },
            "results": [],
            "errors": [],
            "cancel_requested": False,
        }
        cancelled = {**job, "cancel_requested": True}

        with (
            patch(
                "outlook_web.controllers.mail_search.mail_search_service.start_job",
                return_value=job,
            ),
            patch(
                "outlook_web.controllers.mail_search.mail_search_service.get_job",
                return_value=job,
            ),
            patch(
                "outlook_web.controllers.mail_search.mail_search_service.cancel_job",
                return_value=cancelled,
            ),
        ):
            start_response = self.client.post("/api/mail-search", json={"query": "marker"})
            poll_response = self.client.get(f"/api/mail-search/{job['job_id']}")
            cancel_response = self.client.post(f"/api/mail-search/{job['job_id']}/cancel")

        self.assertEqual(start_response.status_code, 202)
        self.assertEqual(start_response.get_json()["job"]["job_id"], job["job_id"])
        self.assertEqual(poll_response.status_code, 200)
        self.assertEqual(poll_response.get_json()["job"]["status"], "queued")
        self.assertEqual(cancel_response.status_code, 200)
        self.assertTrue(cancel_response.get_json()["job"]["cancel_requested"])


if __name__ == "__main__":
    unittest.main()
