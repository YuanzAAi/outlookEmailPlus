import unittest
from email.message import EmailMessage
from unittest.mock import patch

from outlook_web.services.imap_generic import (
    _create_imap_connection,
    _normalize_imap_auth_error_message,
    _resolve_imap_folder,
    get_emails_imap_generic,
    get_latest_matching_email_imap_generic,
)


def _message_bytes(subject: str, body: str) -> bytes:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = "sender@example.com"
    message["To"] = "receiver@example.com"
    message["Date"] = "Sun, 20 Jul 2026 00:00:00 +0000"
    message.set_content(body)
    return message.as_bytes()


class _FakeImapBase:
    def __init__(self):
        self.fetch_calls = []
        self.logged_out = False

    def login(self, _email, _password):
        return "OK", [b"logged in"]

    def select(self, _folder, readonly=True):
        return "OK", [b"2"]

    def logout(self):
        self.logged_out = True


class _BatchImap(_FakeImapBase):
    def uid(self, command, message_set, query):
        if command == "SEARCH":
            return "OK", [b"101 102"]
        self.fetch_calls.append((message_set, query))
        return "OK", [
            (b"1 (UID 101 FLAGS () RFC822 {100}", _message_bytes("Old", "Body 101")),
            (b"2 (UID 102 FLAGS (\\Seen) RFC822 {100}", _message_bytes("New", "Code 882211")),
            b")",
        ]


class _FallbackImap(_FakeImapBase):
    def uid(self, command, message_set, query):
        if command == "SEARCH":
            return "OK", [b"201 202"]
        self.fetch_calls.append((message_set, query))
        if message_set == b"202,201":
            return "NO", []
        uid_text = message_set.decode("ascii")
        return "OK", [
            (
                b"1 (FLAGS () RFC822 {100}",
                _message_bytes(f"Message {uid_text}", f"Body {uid_text}"),
            ),
            b")",
        ]


class _PartialBatchImap(_FakeImapBase):
    def uid(self, command, message_set, query):
        if command == "SEARCH":
            return "OK", [b"301 302"]
        self.fetch_calls.append((message_set, query))
        if message_set == b"302,301":
            return "OK", [
                (
                    b"2 (UID 302 FLAGS () RFC822 {100}",
                    _message_bytes("New", "Body 302"),
                ),
                b")",
            ]
        return "OK", [
            (
                b"1 (FLAGS () RFC822 {100}",
                _message_bytes("Old", "Body 301"),
            ),
            b")",
        ]


class _SpecialUseImap:
    def __init__(self):
        self.select_calls = []

    def select(self, folder, readonly=True):
        self.select_calls.append((folder, readonly))
        if folder == b"&V4NXPpCuTvY-":
            return "OK", [b"1"]
        return "NO", [b"missing"]

    def list(self):
        return "OK", [
            b'(\\HasNoChildren \\Trash) "/" "Deleted Messages"',
            b'(\\HasNoChildren \\Junk) "/" &V4NXPpCuTvY-',
        ]


class _LatestImap(_FakeImapBase):
    def __init__(self):
        super().__init__()
        self.messages = {
            b"401": _message_bytes("Older target", "Code 401401"),
            b"402": _message_bytes("Target verification", "Code 402402"),
            b"403": _message_bytes("Newest unrelated", "Code 403403"),
        }

    def uid(self, command, message_set, query):
        if command == "SEARCH":
            return "OK", [b"401 402 403"]
        self.fetch_calls.append((message_set, query))
        raw = self.messages[message_set]
        return "OK", [(b"1 (UID " + message_set + b" FLAGS () RFC822 {100}", raw), b")"]


class GenericImapBatchTests(unittest.TestCase):
    @patch("outlook_web.services.imap_generic.imaplib.IMAP4_SSL")
    def test_shared_connection_uses_bounded_timeout_and_sends_imap_id(self, mock_imap_cls):
        connection = _create_imap_connection("imap.163.com", 993)

        self.assertIs(connection, mock_imap_cls.return_value)
        mock_imap_cls.assert_called_once_with("imap.163.com", 993, timeout=15)
        mock_imap_cls.return_value._simple_command.assert_called_once_with(
            "ID",
            '("name" "outlookmail" "version" "1.0" "vendor" "outlookmail")',
        )

    def test_provider_specific_auth_messages(self):
        expected_fragments = {
            "gmail": "应用专用密码",
            "icloud": "Apple ID 应用专用密码",
            "qq": "授权码",
            "163": "客户端授权密码",
            "126": "客户端授权密码",
            "yahoo": "应用密码",
        }
        for provider, expected in expected_fragments.items():
            with self.subTest(provider=provider):
                message = _normalize_imap_auth_error_message(
                    "authentication failed",
                    provider=provider,
                    imap_host="imap.example.com",
                )
                self.assertIn(expected, message)

    def test_batch_fetch_preserves_requested_order_and_search_body(self):
        fake_mail = _BatchImap()
        with patch("outlook_web.services.imap_generic._create_imap_connection", return_value=fake_mail):
            result = get_emails_imap_generic(
                email_addr="user@icloud.com",
                imap_password="app-password",
                imap_host="imap.mail.me.com",
                provider="icloud",
                top=2,
                include_search_body=True,
            )

        self.assertTrue(result["success"])
        self.assertEqual([item["id"] for item in result["emails"]], ["102", "101"])
        self.assertEqual(len(fake_mail.fetch_calls), 1)
        self.assertEqual(fake_mail.fetch_calls[0][0], b"102,101")
        self.assertIn("882211", result["emails"][0]["_search_body"])
        self.assertTrue(result["emails"][0]["is_read"])
        self.assertTrue(fake_mail.logged_out)

    def test_batch_fetch_failure_falls_back_to_individual_uids(self):
        fake_mail = _FallbackImap()
        with patch("outlook_web.services.imap_generic._create_imap_connection", return_value=fake_mail):
            result = get_emails_imap_generic(
                email_addr="user@163.com",
                imap_password="auth-code",
                imap_host="imap.163.com",
                provider="163",
                top=2,
            )

        self.assertTrue(result["success"])
        self.assertEqual([item["id"] for item in result["emails"]], ["202", "201"])
        self.assertEqual([call[0] for call in fake_mail.fetch_calls], [b"202,201", b"202", b"201"])
        self.assertNotIn("_search_body", result["emails"][0])
        self.assertTrue(fake_mail.logged_out)

    def test_partial_batch_response_only_refetches_missing_uid(self):
        fake_mail = _PartialBatchImap()
        with patch("outlook_web.services.imap_generic._create_imap_connection", return_value=fake_mail):
            result = get_emails_imap_generic(
                email_addr="user@yahoo.com",
                imap_password="app-password",
                imap_host="imap.mail.yahoo.com",
                provider="yahoo",
                top=2,
            )

        self.assertTrue(result["success"])
        self.assertEqual([item["id"] for item in result["emails"]], ["302", "301"])
        self.assertEqual([call[0] for call in fake_mail.fetch_calls], [b"302,301", b"301"])

    def test_special_use_folder_discovery_uses_server_mailbox_token(self):
        fake_mail = _SpecialUseImap()

        selected = _resolve_imap_folder(
            fake_mail,
            ["Missing Junk Folder"],
            logical_folder="junkemail",
        )

        self.assertEqual(selected, b"&V4NXPpCuTvY-")
        self.assertEqual(fake_mail.select_calls[-1], (b"&V4NXPpCuTvY-", True))

    def test_latest_generic_imap_fetches_only_newest_message_without_filters(self):
        fake_mail = _LatestImap()
        with patch("outlook_web.services.imap_generic._create_imap_connection", return_value=fake_mail):
            result = get_latest_matching_email_imap_generic(
                email_addr="user@gmail.com",
                imap_password="app-password",
                imap_host="imap.gmail.com",
                provider="gmail",
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["email"]["id"], "403")
        self.assertEqual(result["checked"], 1)
        self.assertEqual([call[0] for call in fake_mail.fetch_calls], [b"403"])
        self.assertIn("403403", result["email"]["_search_body"])
        self.assertTrue(fake_mail.logged_out)

    def test_latest_generic_imap_walks_back_until_subject_matches(self):
        fake_mail = _LatestImap()
        with patch("outlook_web.services.imap_generic._create_imap_connection", return_value=fake_mail):
            result = get_latest_matching_email_imap_generic(
                email_addr="user@163.com",
                imap_password="auth-code",
                imap_host="imap.163.com",
                provider="163",
                subject_contains="verification",
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["email"]["id"], "402")
        self.assertEqual(result["checked"], 2)
        self.assertEqual([call[0] for call in fake_mail.fetch_calls], [b"403", b"402"])


if __name__ == "__main__":
    unittest.main()
