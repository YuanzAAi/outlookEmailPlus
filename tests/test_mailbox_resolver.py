from __future__ import annotations

import unittest
import uuid
from unittest.mock import MagicMock, patch

from tests._import_app import clear_login_attempts, import_web_app_module


class MailboxResolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
            from outlook_web.db import get_db

            db = get_db()
            db.execute("DELETE FROM accounts WHERE email LIKE '%@resolver.test'")
            db.execute("DELETE FROM temp_email_messages WHERE email_address LIKE '%@resolver.test'")
            db.execute("DELETE FROM temp_emails WHERE email LIKE '%@resolver.test'")
            db.commit()

    def test_resolve_mailbox_returns_account_descriptor_for_regular_account(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services import mailbox_resolver

            db = get_db()
            db.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, group_id, status, account_type, provider)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "user@resolver.test",
                    "pw",
                    "cid",
                    "rt",
                    1,
                    "active",
                    "outlook",
                    "outlook",
                ),
            )
            db.commit()

            mailbox = mailbox_resolver.resolve_mailbox("user@resolver.test")

        self.assertEqual(mailbox["kind"], "account")
        self.assertEqual(mailbox["email"], "user@resolver.test")
        self.assertEqual(mailbox["read_capability"], "graph")

    def test_resolve_mailbox_is_case_insensitive_and_returns_stored_account_email(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services import mailbox_resolver

            db = get_db()
            db.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, group_id, status, account_type, provider)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "StoredCase@resolver.test",
                    "pw",
                    "cid",
                    "rt",
                    1,
                    "active",
                    "outlook",
                    "outlook",
                ),
            )
            db.commit()

            mailbox = mailbox_resolver.resolve_mailbox("storedcase@RESOLVER.TEST")

        self.assertEqual(mailbox["email"], "StoredCase@resolver.test")

    def test_resolve_mailbox_supports_plus_alias_lookup(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services import mailbox_resolver

            db = get_db()
            db.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, group_id, status, account_type, provider)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "alias@resolver.test",
                    "pw",
                    "cid",
                    "rt",
                    1,
                    "active",
                    "outlook",
                    "outlook",
                ),
            )
            db.commit()

            mailbox = mailbox_resolver.resolve_mailbox("alias+signup@resolver.test")

        self.assertEqual(mailbox["kind"], "account")
        self.assertEqual(mailbox["email"], "alias@resolver.test")

    def test_resolve_mailbox_returns_temp_descriptor_for_temp_mailbox(self):
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services import mailbox_resolver

            temp_emails_repo.create_temp_email(
                email_addr="temp@resolver.test",
                mailbox_type="user",
                visible_in_ui=True,
                source="custom_domain_temp_mail",
            )

            mailbox = mailbox_resolver.resolve_mailbox("temp@resolver.test")

        self.assertEqual(mailbox["kind"], "temp")
        self.assertEqual(mailbox["email"], "temp@resolver.test")
        self.assertEqual(mailbox["read_capability"], "temp_provider")

    def test_resolve_temp_mailbox_preserves_plus_address_and_ignores_case(self):
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services import mailbox_resolver

            temp_emails_repo.create_temp_email(
                email_addr="User+Flow@resolver.test",
                mailbox_type="user",
                visible_in_ui=True,
                source="custom_domain_temp_mail",
            )

            mailbox = mailbox_resolver.resolve_mailbox("user+flow@RESOLVER.TEST")

        self.assertEqual(mailbox["kind"], "temp")
        self.assertEqual(mailbox["email"], "User+Flow@resolver.test")

    def test_resolve_unknown_managed_domain_uses_exact_remote_discovery(self):
        with self.app.app_context():
            from outlook_web.services import mailbox_resolver

            fake_service = MagicMock()
            fake_service.is_managed_email.return_value = True
            fake_service.discover_user_mailbox.return_value = {
                "kind": "temp",
                "email": "remote@managed.test",
                "provider_name": "cloudflare_temp_mail",
                "mailbox_type": "user",
                "visible_in_ui": True,
                "status": "active",
                "read_capability": "temp_provider",
                "meta": {"provider_jwt": "jwt"},
            }
            with patch.object(mailbox_resolver, "_temp_mail_service", return_value=fake_service):
                mailbox = mailbox_resolver.resolve_mailbox("REMOTE@managed.test")

        self.assertEqual(mailbox["email"], "remote@managed.test")
        fake_service.discover_user_mailbox.assert_called_once_with("REMOTE@managed.test")

    def test_resolve_mailbox_conflict_raises_mailbox_conflict_error(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services import external_api, mailbox_resolver

            db = get_db()
            db.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, group_id, status, account_type, provider)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "conflict@resolver.test",
                    "pw",
                    "cid",
                    "rt",
                    1,
                    "active",
                    "outlook",
                    "outlook",
                ),
            )
            db.commit()

            temp_emails_repo.create_temp_email(
                email_addr="conflict@resolver.test",
                mailbox_type="user",
                visible_in_ui=True,
                source="custom_domain_temp_mail",
            )

            with self.assertRaises(external_api.MailboxConflictError):
                mailbox_resolver.resolve_mailbox("conflict@resolver.test")

    def test_task_temp_mailbox_requires_same_consumer_key(self):
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services import external_api, mailbox_resolver

            temp_emails_repo.create_temp_email(
                email_addr="task@resolver.test",
                mailbox_type="task",
                visible_in_ui=False,
                source="custom_domain_temp_mail",
                task_token="tmptask_resolver",
                consumer_key="key:owner",
                caller_id="worker",
                task_id="job-1",
            )

            mailbox = mailbox_resolver.resolve_mailbox("task@resolver.test")
            with self.assertRaises(external_api.EmailScopeForbiddenError):
                mailbox_resolver.ensure_mailbox_can_read(
                    mailbox,
                    consumer={"consumer_key": "key:other", "allowed_emails": []},
                )

    def test_finished_task_temp_mailbox_returns_task_finished_error(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services import external_api, mailbox_resolver

            task_token = f"tmptask_finished_{uuid.uuid4().hex}"
            created = temp_emails_repo.create_temp_email(
                email_addr="finished@resolver.test",
                mailbox_type="task",
                visible_in_ui=False,
                source="custom_domain_temp_mail",
                task_token=task_token,
                consumer_key="key:owner",
                caller_id="worker",
                task_id="job-2",
            )
            self.assertTrue(created)
            db = get_db()
            db.execute(
                "UPDATE temp_emails SET status = 'finished', finished_at = CURRENT_TIMESTAMP WHERE email = ?",
                ("finished@resolver.test",),
            )
            db.commit()

            mailbox = mailbox_resolver.resolve_mailbox("finished@resolver.test")
            with self.assertRaises(external_api.TaskFinishedError):
                mailbox_resolver.ensure_mailbox_can_read(
                    mailbox,
                    consumer={"consumer_key": "key:owner", "allowed_emails": []},
                )
