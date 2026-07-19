import unittest
import uuid
from unittest.mock import MagicMock, patch

from outlook_web.services import outlook_transport
from tests._import_app import clear_login_attempts, import_web_app_module


class OutlookTransportTests(unittest.TestCase):
    def setUp(self):
        self.account = {
            "id": 1,
            "email": "user@example.com",
            "client_id": "cid",
            "refresh_token": "rt",
            "account_type": "outlook",
        }

    @patch("outlook_web.services.outlook_transport.graph_service.get_emails_graph")
    @patch("outlook_web.services.outlook_transport.imap_service.get_emails_imap_with_server")
    def test_remembered_imap_is_used_before_graph(self, mock_imap, mock_graph):
        self.account["preferred_verification_channel"] = outlook_transport.IMAP_NEW
        mock_imap.return_value = {"success": True, "emails": []}

        result = outlook_transport.list_messages(self.account, folder="inbox", top=1)

        self.assertTrue(result["success"])
        self.assertEqual(result["method_key"], outlook_transport.IMAP_NEW)
        mock_graph.assert_not_called()

    @patch("outlook_web.services.outlook_transport.graph_service.get_emails_graph")
    def test_empty_graph_mailbox_is_valid_probe(self, mock_graph):
        mock_graph.return_value = {"success": True, "emails": []}

        result = outlook_transport.probe_account(self.account)

        self.assertTrue(result["success"])
        self.assertEqual(result["channel"], outlook_transport.GRAPH_INBOX)

    def test_nonstandard_folder_keeps_graph_first(self):
        self.account["preferred_verification_channel"] = outlook_transport.IMAP_NEW
        self.assertEqual(outlook_transport.build_plan(self.account, "deleteditems")[0], "graph")

    @patch("outlook_web.services.outlook_transport._imap_list")
    @patch("outlook_web.services.outlook_transport._graph_list")
    def test_invalid_grant_stops_protocol_fallback(self, mock_graph, mock_imap):
        mock_graph.return_value = {
            "success": False,
            "error": {"code": "GRAPH_TOKEN_FAILED", "details": {"error": "invalid_grant"}},
        }

        result = outlook_transport.list_messages(self.account, folder="inbox", top=1)

        self.assertFalse(result["success"])
        self.assertTrue(result["auth_expired"])
        mock_graph.assert_called_once()
        mock_imap.assert_not_called()

    @patch("outlook_web.services.outlook_transport._imap_list")
    @patch("outlook_web.services.outlook_transport._graph_list")
    def test_no_mail_permission_still_falls_back_to_imap(self, mock_graph, mock_imap):
        mock_graph.return_value = {
            "success": False,
            "auth_expired": True,
            "no_mail_permission": True,
            "error": {"code": "NO_MAIL_PERMISSION"},
        }
        mock_imap.return_value = {"success": True, "emails": []}

        result = outlook_transport.list_messages(self.account, folder="inbox", top=1)

        self.assertTrue(result["success"])
        self.assertEqual(result["method_key"], outlook_transport.IMAP_NEW)
        mock_imap.assert_called_once()

    @patch("outlook_web.services.outlook_transport._graph_list")
    @patch("outlook_web.services.outlook_transport._imap_list")
    def test_remembered_imap_invalid_grant_stops_remaining_plan(self, mock_imap, mock_graph):
        self.account["preferred_verification_channel"] = outlook_transport.IMAP_NEW
        mock_imap.return_value = {
            "success": False,
            "error": {"code": "IMAP_TOKEN_FAILED", "details": {"error": "invalid_grant"}},
        }

        result = outlook_transport.list_messages(self.account, folder="inbox", top=1)

        self.assertFalse(result["success"])
        self.assertTrue(result["auth_expired"])
        mock_imap.assert_called_once()
        mock_graph.assert_not_called()


class OutlookTransportEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        self.email = f"{uuid.uuid4().hex}@transport-regression.test"
        with self.app.app_context():
            clear_login_attempts()
            from outlook_web.db import get_db

            db = get_db()
            db.execute("DELETE FROM accounts WHERE email LIKE '%@transport-regression.test'")
            db.execute(
                """
                INSERT INTO accounts (
                    email, password, client_id, refresh_token, group_id,
                    status, account_type, provider
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (self.email, "pw", "cid", "rt", 1, "active", "outlook", "outlook"),
            )
            db.commit()

        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = 1

    @patch("outlook_web.controllers.accounts.outlook_transport.probe_account")
    def test_probe_endpoint_persists_detected_channel(self, mock_probe):
        mock_probe.return_value = {
            "success": True,
            "method_key": outlook_transport.IMAP_NEW,
            "channel": outlook_transport.IMAP_NEW,
        }

        response = self.client.post("/api/accounts/probe-mail-methods", json={"emails": [self.email]})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["summary"]["imap"], 1)
        self.assertEqual(payload["results"][0]["email"], self.email)
        with self.app.app_context():
            from outlook_web.db import get_db

            row = (
                get_db()
                .execute(
                    "SELECT preferred_verification_channel FROM accounts WHERE email = ?",
                    (self.email,),
                )
                .fetchone()
            )
        self.assertEqual(row["preferred_verification_channel"], outlook_transport.IMAP_NEW)

    @patch("outlook_web.controllers.emails.imap_service.delete_emails_imap")
    def test_delete_endpoint_keeps_selected_imap_folder(self, mock_delete):
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            db.execute(
                "UPDATE accounts SET preferred_verification_channel = ? WHERE email = ?",
                (outlook_transport.IMAP_NEW, self.email),
            )
            db.commit()
        mock_delete.return_value = {"success": True, "success_count": 1, "failed_count": 0, "errors": []}

        response = self.client.post(
            "/api/emails/delete",
            json={"email": self.email, "ids": ["42"], "folder": "junkemail"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        self.assertEqual(mock_delete.call_args.kwargs["folder"], "junkemail")


class ImapDeleteTests(unittest.TestCase):
    @patch("outlook_web.services.imap.imaplib.IMAP4_SSL")
    @patch("outlook_web.services.imap.get_access_token_imap_result")
    def test_delete_uses_writable_folder_and_uid_commands(self, mock_token, mock_imap_cls):
        from outlook_web.services.imap import delete_emails_imap

        mock_token.return_value = {"success": True, "access_token": "token"}
        connection = MagicMock()
        connection.select.return_value = ("OK", [b"2"])
        connection.uid.return_value = ("OK", [b""])
        mock_imap_cls.return_value = connection

        result = delete_emails_imap(
            "user@example.com",
            "cid",
            "rt",
            ["42", "43"],
            outlook_transport.IMAP_SERVER_NEW,
            folder="junkemail",
        )

        self.assertTrue(result["success"])
        connection.select.assert_called_once_with('"Junk"', readonly=False)
        self.assertEqual(connection.uid.call_count, 2)
        connection.uid.assert_any_call("STORE", "42", "+FLAGS.SILENT", "(\\Deleted)")
        connection.uid.assert_any_call("STORE", "43", "+FLAGS.SILENT", "(\\Deleted)")
        connection.expunge.assert_called_once_with()

    def test_delete_fallback_preserves_folder_for_both_imap_servers(self):
        from outlook_web.services.email_delete import delete_emails_with_fallback

        graph_delete = MagicMock(return_value={"success": False, "error": "graph failed"})
        imap_delete = MagicMock(
            side_effect=[
                {"success": False, "error": "new failed"},
                {"success": True, "success_count": 1, "failed_count": 0, "errors": []},
            ]
        )

        result, method = delete_emails_with_fallback(
            email_addr="user@example.com",
            client_id="cid",
            refresh_token="rt",
            message_ids=["42"],
            proxy_url="",
            delete_emails_graph=graph_delete,
            delete_emails_imap=imap_delete,
            imap_server_new=outlook_transport.IMAP_SERVER_NEW,
            imap_server_old=outlook_transport.IMAP_SERVER_OLD,
            folder="junkemail",
        )

        self.assertTrue(result["success"])
        self.assertEqual(method, outlook_transport.IMAP_OLD)
        self.assertEqual(imap_delete.call_args_list[0].args[-1], "junkemail")
        self.assertEqual(imap_delete.call_args_list[1].args[-1], "junkemail")


if __name__ == "__main__":
    unittest.main()
