from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from outlook_web.repositories import settings as settings_repo
from outlook_web.security.crypto import encrypt_data
from tests._import_app import clear_login_attempts, import_web_app_module


class NotificationDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
            from outlook_web.db import get_db

            db = get_db()
            db.execute("DELETE FROM account_claim_logs")
            db.execute("DELETE FROM account_refresh_logs")
            db.execute("DELETE FROM account_tags")
            db.execute("DELETE FROM notification_cursor_states")
            db.execute("DELETE FROM notification_delivery_logs")
            db.execute("DELETE FROM telegram_push_log")
            db.execute("DELETE FROM temp_email_messages")
            db.execute("DELETE FROM temp_emails")
            db.execute("DELETE FROM accounts")
            db.commit()
            settings_repo.set_setting("email_notification_enabled", "false")
            settings_repo.set_setting("email_notification_recipient", "")
            settings_repo.set_setting("telegram_bot_token", "")
            settings_repo.set_setting("telegram_chat_id", "")
            settings_repo.set_setting("webhook_notification_enabled", "false")
            settings_repo.set_setting("webhook_notification_url", "")
            settings_repo.set_setting("webhook_notification_token", "")

    def _login(self, client):
        resp = client.post("/login", json={"password": "testpass123"})
        self.assertEqual(resp.status_code, 200)

    def _insert_account(
        self,
        email_addr: str,
        *,
        provider: str = "imap",
        account_type: str | None = None,
        telegram_enabled: int = 0,
        telegram_cursor: str | None = "2026-03-01T00:00:00",
    ) -> int:
        conn = self.module.create_sqlite_connection()
        try:
            cur = conn.execute(
                """
                INSERT INTO accounts (
                    email, password, client_id, refresh_token, account_type, provider,
                    imap_host, imap_port, imap_password, group_id, remark, status,
                    telegram_push_enabled, telegram_last_checked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email_addr,
                    "",
                    "cid_test",
                    "rt_test",
                    account_type or ("outlook" if provider == "outlook" else "imap"),
                    provider,
                    "imap.test.com",
                    993,
                    "enc:dummy",
                    1,
                    "",
                    "active",
                    telegram_enabled,
                    telegram_cursor,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def _insert_temp_email(
        self,
        email_addr: str,
        *,
        provider_name: str | None = None,
        mailbox_type: str = "user",
        visible_in_ui: bool = True,
        status: str = "active",
    ):
        conn = self.module.create_sqlite_connection()
        try:
            meta_json = json.dumps({"provider_name": provider_name}) if provider_name else None
            conn.execute(
                """
                INSERT INTO temp_emails (email, status, mailbox_type, visible_in_ui, meta_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (email_addr, status, mailbox_type, 1 if visible_in_ui else 0, meta_json),
            )
            conn.commit()
        finally:
            conn.close()

    def test_email_test_endpoint_sends_real_message_via_saved_recipient(self):
        client = self.app.test_client()
        self._login(client)
        with self.app.app_context():
            settings_repo.set_setting("email_notification_recipient", "notify@example.com")

        with (
            patch.dict(
                os.environ,
                {
                    "EMAIL_NOTIFICATION_SMTP_HOST": "smtp.example.com",
                    "EMAIL_NOTIFICATION_SMTP_PORT": "587",
                    "EMAIL_NOTIFICATION_FROM": "noreply@example.com",
                },
                clear=False,
            ),
            patch("smtplib.SMTP") as smtp_mock,
        ):
            resp = client.post("/api/settings/email-test", json={})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertEqual(data.get("success"), True)
        smtp_mock.return_value.__enter__.return_value.send_message.assert_called_once()
        sent_message = smtp_mock.return_value.__enter__.return_value.send_message.call_args[0][0]
        self.assertEqual(sent_message["To"], "notify@example.com")

    def test_first_email_notification_scan_only_initializes_cursor(self):
        with self.app.app_context():
            from outlook_web.repositories import notification_state as notification_state_repo
            from outlook_web.services import notification_dispatch

            self._insert_account("first@example.com", telegram_enabled=1)
            settings_repo.set_setting("email_notification_enabled", "true")
            settings_repo.set_setting("email_notification_recipient", "notify@example.com")

            with (
                patch.dict(
                    os.environ,
                    {
                        "EMAIL_NOTIFICATION_SMTP_HOST": "smtp.example.com",
                        "EMAIL_NOTIFICATION_SMTP_PORT": "587",
                        "EMAIL_NOTIFICATION_FROM": "noreply@example.com",
                    },
                    clear=False,
                ),
                patch("outlook_web.services.notification_dispatch.send_business_email_notification") as send_mock,
            ):
                notification_dispatch.run_email_notification_job(self.app)

            send_mock.assert_not_called()
            cursor = notification_state_repo.get_cursor(
                notification_dispatch.CHANNEL_EMAIL,
                notification_dispatch.SOURCE_ACCOUNT,
                notification_dispatch.build_source_key(notification_dispatch.SOURCE_ACCOUNT, "first@example.com"),
            )
            self.assertTrue(cursor)

    def test_email_notification_job_covers_account_and_temp_email_and_uses_delivery_logs(
        self,
    ):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services import notification_dispatch

            self._insert_account("notify-account@example.com", telegram_enabled=1)
            self._insert_temp_email("notify-temp@example.com")
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_EMAIL,
                cursor_value="2026-03-01T00:00:00",
            )
            settings_repo.set_setting("email_notification_enabled", "true")
            settings_repo.set_setting("email_notification_recipient", "notify@example.com")

            def fake_fetch(source, since):
                if source["source_type"] == notification_dispatch.SOURCE_ACCOUNT:
                    return [
                        {
                            "message_id": "<account-1@example.com>",
                            "subject": "Account Subject",
                            "sender": "sender@example.com",
                            "received_at": "2026-03-02T10:00:00",
                            "content": "account body",
                            "folder": "inbox",
                        }
                    ]
                return [
                    {
                        "message_id": "temp-1",
                        "subject": "Temp Subject",
                        "sender": "temp@example.com",
                        "received_at": "2026-03-02T11:00:00",
                        "content": "temp body",
                        "folder": "inbox",
                    }
                ]

            with (
                patch.dict(
                    os.environ,
                    {
                        "EMAIL_NOTIFICATION_SMTP_HOST": "smtp.example.com",
                        "EMAIL_NOTIFICATION_SMTP_PORT": "587",
                        "EMAIL_NOTIFICATION_FROM": "noreply@example.com",
                    },
                    clear=False,
                ),
                patch(
                    "outlook_web.services.notification_dispatch.fetch_source_messages",
                    side_effect=fake_fetch,
                ),
                patch("outlook_web.services.notification_dispatch.send_business_email_notification") as send_mock,
            ):
                notification_dispatch.run_email_notification_job(self.app)

            self.assertEqual(send_mock.call_count, 2)
            db = get_db()
            rows = db.execute(
                "SELECT channel, source_type, source_key, status FROM notification_delivery_logs ORDER BY source_type ASC"
            ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual({row["source_type"] for row in rows}, {"account", "temp_email"})
            self.assertTrue(all(row["status"] == "sent" for row in rows))

    def test_hidden_task_mailbox_is_excluded_from_global_notification_sources(self):
        with self.app.app_context():
            from outlook_web.services import notification_dispatch

            self._insert_temp_email("visible-notify@example.com")
            self._insert_temp_email(
                "hidden-task@example.com",
                mailbox_type="task",
                visible_in_ui=False,
            )
            self._insert_temp_email("inactive-notify@example.com", status="finished")

            sources = notification_dispatch.list_email_notification_sources()

        self.assertEqual(
            {source["email"] for source in sources if source["source_type"] == notification_dispatch.SOURCE_TEMP_EMAIL},
            {"visible-notify@example.com"},
        )

    def test_cf_pool_account_notification_uses_temp_mail_source(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services import notification_dispatch

            account_id = self._insert_account(
                "cf-pool-notify@example.com",
                provider="cloudflare_temp_mail",
                account_type="temp_mail",
                telegram_enabled=1,
            )
            get_db().execute(
                "UPDATE accounts SET temp_mail_meta = ? WHERE id = ?",
                (
                    json.dumps(
                        {
                            "provider_name": "cloudflare_temp_mail",
                            "provider_mailbox_id": "501",
                            "provider_jwt": "jwt-501",
                        }
                    ),
                    account_id,
                ),
            )
            get_db().commit()

            source = next(
                item
                for item in notification_dispatch.list_email_notification_sources()
                if item["email"] == "cf-pool-notify@example.com"
            )
            self.assertEqual(source["source_type"], notification_dispatch.SOURCE_TEMP_EMAIL)
            self.assertTrue(notification_dispatch._is_source_notification_enabled(source))

            with (
                patch.dict(os.environ, {"TEMP_MAIL_INBOUND_PUSH_ENABLED": ""}, clear=False),
                patch(
                    "outlook_web.services.notification_dispatch.TempMailService.list_messages",
                    return_value=[],
                ) as list_messages,
            ):
                notification_dispatch.fetch_source_messages(source, "2026-03-01T00:00:00")

        mailbox_arg = list_messages.call_args.args[0]
        self.assertEqual(mailbox_arg["kind"], "temp")
        self.assertEqual(mailbox_arg["email"], "cf-pool-notify@example.com")
        self.assertTrue(list_messages.call_args.kwargs["sync_remote"])

    def test_cf_pool_account_keeps_telegram_channel_after_temp_routing(self):
        with self.app.app_context():
            from outlook_web.services import notification_dispatch

            self._insert_account(
                "cf-telegram-notify@example.com",
                provider="cloudflare_temp_mail",
                account_type="temp_mail",
                telegram_enabled=1,
            )
            source = next(
                item
                for item in notification_dispatch.list_email_notification_sources()
                if item["email"] == "cf-telegram-notify@example.com"
            )
            channels = notification_dispatch._build_active_channels_for_source(
                source,
                email_enabled=False,
                telegram_runtime={"bot_token": "token", "chat_id": "chat"},
                webhook_runtime=None,
            )

        self.assertEqual([channel for channel, _sender, _limit in channels], [notification_dispatch.CHANNEL_TELEGRAM])

    def test_legacy_telegram_scanner_excludes_cf_pool_accounts(self):
        with self.app.app_context():
            from outlook_web.repositories import accounts as accounts_repo

            self._insert_account(
                "regular-telegram@example.com",
                provider="outlook",
                account_type="outlook",
                telegram_enabled=1,
            )
            self._insert_account(
                "cf-legacy-telegram@example.com",
                provider="cloudflare_temp_mail",
                account_type="outlook",
                telegram_enabled=1,
            )
            accounts = accounts_repo.get_telegram_push_accounts()

        self.assertEqual({account["email"] for account in accounts}, {"regular-telegram@example.com"})

    def test_cf_pool_account_and_legacy_visible_temp_row_share_one_notification_source(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services import notification_dispatch

            account_id = self._insert_account(
                "cf-duplicate-notify@example.com",
                provider="cloudflare_temp_mail",
                account_type="temp_mail",
                telegram_enabled=1,
            )
            db = get_db()
            db.execute(
                "UPDATE accounts SET temp_mail_meta = ? WHERE id = ?",
                ('{"provider_name":"cloudflare_temp_mail","provider_jwt":"jwt"}', account_id),
            )
            db.execute(
                """
                INSERT INTO temp_emails (email, status, mailbox_type, visible_in_ui, source, meta_json)
                VALUES (?, 'active', 'user', 1, 'custom_domain_temp_mail', ?)
                """,
                (
                    "cf-duplicate-notify@example.com",
                    '{"provider_name":"cloudflare_temp_mail","provider_jwt":"jwt"}',
                ),
            )
            db.commit()

            sources = [
                source
                for source in notification_dispatch.list_email_notification_sources()
                if source["email"] == "cf-duplicate-notify@example.com"
            ]

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["source_type"], notification_dispatch.SOURCE_TEMP_EMAIL)
        self.assertEqual(sources[0]["account"]["id"], account_id)

    def test_missing_message_id_uses_stable_fallback_dedup(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services import notification_dispatch

            self._insert_account("fallback@example.com")
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_EMAIL,
                cursor_value="2026-03-01T00:00:00",
            )
            sources = notification_dispatch.list_email_notification_sources()
            messages = [
                {
                    "subject": "Fallback Subject",
                    "sender": "sender@example.com",
                    "received_at": "2026-03-02T10:00:00",
                    "content": "same body",
                    "folder": "inbox",
                }
            ]
            sent = []

            def fake_sender(source, message):
                sent.append((source["source_key"], message["subject"]))

            with patch(
                "outlook_web.services.notification_dispatch.fetch_source_messages",
                return_value=messages,
            ):
                notification_dispatch.process_channel_for_sources(
                    channel=notification_dispatch.CHANNEL_EMAIL,
                    sources=sources,
                    sender=fake_sender,
                )
                notification_dispatch.process_channel_for_sources(
                    channel=notification_dispatch.CHANNEL_EMAIL,
                    sources=sources,
                    sender=fake_sender,
                )

            self.assertEqual(len(sent), 1)
            row = get_db().execute("SELECT message_id FROM notification_delivery_logs").fetchone()
            self.assertTrue((row["message_id"] or "").startswith("fallback:"))

    def test_email_failure_keeps_cursor_for_retry(self):
        with self.app.app_context():
            from outlook_web.repositories import notification_state as notification_state_repo
            from outlook_web.services import email_push, notification_dispatch

            self._insert_account("retry@example.com")
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_EMAIL,
                cursor_value="2026-03-01T00:00:00",
            )
            sources = notification_dispatch.list_email_notification_sources()
            messages = [
                {
                    "message_id": "<retry@example.com>",
                    "subject": "Retry",
                    "sender": "sender@example.com",
                    "received_at": "2026-03-02T10:00:00",
                    "content": "body",
                    "folder": "inbox",
                }
            ]
            attempts = []

            def flaky_sender(source, message):
                attempts.append(message["message_id"])
                if len(attempts) == 1:
                    raise email_push.EmailPushError(
                        "EMAIL_TEST_SEND_FAILED",
                        "测试邮件发送失败",
                        message_en="Failed to send test email",
                    )

            with patch(
                "outlook_web.services.notification_dispatch.fetch_source_messages",
                return_value=messages,
            ):
                notification_dispatch.process_channel_for_sources(
                    channel=notification_dispatch.CHANNEL_EMAIL,
                    sources=sources,
                    sender=flaky_sender,
                )

            cursor = notification_state_repo.get_cursor(
                notification_dispatch.CHANNEL_EMAIL,
                notification_dispatch.SOURCE_ACCOUNT,
                notification_dispatch.build_source_key(notification_dispatch.SOURCE_ACCOUNT, "retry@example.com"),
            )
            self.assertEqual(cursor, "2026-03-01T00:00:00")

            with patch(
                "outlook_web.services.notification_dispatch.fetch_source_messages",
                return_value=messages,
            ):
                notification_dispatch.process_channel_for_sources(
                    channel=notification_dispatch.CHANNEL_EMAIL,
                    sources=sources,
                    sender=flaky_sender,
                )

            self.assertEqual(len(attempts), 2)
            cursor = notification_state_repo.get_cursor(
                notification_dispatch.CHANNEL_EMAIL,
                notification_dispatch.SOURCE_ACCOUNT,
                notification_dispatch.build_source_key(notification_dispatch.SOURCE_ACCOUNT, "retry@example.com"),
            )
            self.assertEqual(cursor, "2026-03-02T10:00:00")

    def test_unified_notification_job_fetches_source_once_for_dual_channels(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services import notification_dispatch

            self._insert_account(
                "shared-fetch@example.com",
                telegram_enabled=1,
                telegram_cursor="2026-03-01T00:00:00",
            )
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_EMAIL,
                cursor_value="2026-03-01T00:00:00",
            )
            settings_repo.set_setting("email_notification_enabled", "true")
            settings_repo.set_setting("email_notification_recipient", "notify@example.com")
            settings_repo.set_setting("telegram_bot_token", encrypt_data("bot_token"))
            settings_repo.set_setting("telegram_chat_id", "123456")
            message = [
                {
                    "message_id": "<shared-fetch@example.com>",
                    "subject": "Shared fetch",
                    "sender": "sender@example.com",
                    "received_at": "2026-03-02T10:00:00",
                    "content": "body",
                    "preview": "body",
                    "folder": "inbox",
                }
            ]

            with (
                patch.dict(
                    os.environ,
                    {
                        "EMAIL_NOTIFICATION_SMTP_HOST": "smtp.example.com",
                        "EMAIL_NOTIFICATION_SMTP_PORT": "587",
                        "EMAIL_NOTIFICATION_FROM": "noreply@example.com",
                    },
                    clear=False,
                ),
                patch(
                    "outlook_web.services.notification_dispatch.fetch_source_messages",
                    return_value=message,
                ) as fetch_mock,
                patch("outlook_web.services.notification_dispatch.send_business_email_notification") as email_send,
                patch("outlook_web.services.notification_dispatch.send_business_telegram_notification") as telegram_send,
            ):
                notification_dispatch.run_notification_dispatch_job(self.app)

            fetch_mock.assert_called_once()
            email_send.assert_called_once()
            telegram_send.assert_called_once()
            rows = (
                get_db()
                .execute(
                    """
                SELECT channel, status
                FROM notification_delivery_logs
                WHERE source_key = ?
                ORDER BY channel ASC
                """,
                    (
                        notification_dispatch.build_source_key(
                            notification_dispatch.SOURCE_ACCOUNT,
                            "shared-fetch@example.com",
                        ),
                    ),
                )
                .fetchall()
            )
            self.assertEqual(
                [(row["channel"], row["status"]) for row in rows],
                [("email", "sent"), ("telegram", "sent")],
            )

    def test_build_active_channels_includes_webhook_when_enabled(self):
        with self.app.app_context():
            from outlook_web.services import notification_dispatch

            source = {
                "source_type": notification_dispatch.SOURCE_ACCOUNT,
                "source_key": notification_dispatch.build_source_key(
                    notification_dispatch.SOURCE_ACCOUNT,
                    "with-webhook@example.com",
                ),
                "label": "with-webhook@example.com",
                "account": {
                    "id": 1,
                    "email": "with-webhook@example.com",
                    "telegram_push_enabled": 1,
                },
            }
            settings_repo.set_setting("webhook_notification_enabled", "true")
            settings_repo.set_setting("webhook_notification_url", "https://example.com/hook")

            webhook_runtime = notification_dispatch._get_webhook_runtime_config()
            channels = notification_dispatch._build_active_channels_for_source(
                source,
                email_enabled=False,
                telegram_runtime=None,
                webhook_runtime=webhook_runtime,
            )
            self.assertEqual(
                [channel for channel, *_ in channels],
                [notification_dispatch.CHANNEL_WEBHOOK],
            )

    def test_build_active_channels_excludes_webhook_when_disabled(self):
        with self.app.app_context():
            from outlook_web.services import notification_dispatch

            source = {
                "source_type": notification_dispatch.SOURCE_ACCOUNT,
                "source_key": notification_dispatch.build_source_key(
                    notification_dispatch.SOURCE_ACCOUNT,
                    "without-webhook@example.com",
                ),
                "label": "without-webhook@example.com",
                "account": {
                    "id": 1,
                    "email": "without-webhook@example.com",
                    "telegram_push_enabled": 1,
                },
            }
            settings_repo.set_setting("webhook_notification_enabled", "false")
            settings_repo.set_setting("webhook_notification_url", "https://example.com/hook")

            webhook_runtime = notification_dispatch._get_webhook_runtime_config()
            channels = notification_dispatch._build_active_channels_for_source(
                source,
                email_enabled=False,
                telegram_runtime=None,
                webhook_runtime=webhook_runtime,
            )
            self.assertEqual(channels, [])

    def test_run_notification_dispatch_job_email_and_webhook_coexist(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services import notification_dispatch

            self._insert_account(
                "email-webhook@example.com",
                telegram_enabled=1,
                telegram_cursor="2026-03-01T00:00:00",
            )
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_EMAIL,
                cursor_value="2026-03-01T00:00:00",
            )
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_WEBHOOK,
                cursor_value="2026-03-01T00:00:00",
            )
            settings_repo.set_setting("email_notification_enabled", "true")
            settings_repo.set_setting("email_notification_recipient", "notify@example.com")
            settings_repo.set_setting("webhook_notification_enabled", "true")
            settings_repo.set_setting("webhook_notification_url", "https://example.com/hook")

            message = [
                {
                    "message_id": "<email-webhook@example.com>",
                    "subject": "Email Webhook",
                    "sender": "sender@example.com",
                    "received_at": "2026-03-02T10:00:00",
                    "content": "body",
                    "preview": "body",
                    "folder": "inbox",
                }
            ]

            with (
                patch.dict(
                    os.environ,
                    {
                        "EMAIL_NOTIFICATION_SMTP_HOST": "smtp.example.com",
                        "EMAIL_NOTIFICATION_SMTP_PORT": "587",
                        "EMAIL_NOTIFICATION_FROM": "noreply@example.com",
                    },
                    clear=False,
                ),
                patch(
                    "outlook_web.services.notification_dispatch.fetch_source_messages",
                    return_value=message,
                ) as fetch_mock,
                patch("outlook_web.services.notification_dispatch.send_business_email_notification") as email_send,
                patch("outlook_web.services.notification_dispatch.send_business_webhook_notification") as webhook_send,
            ):
                notification_dispatch.run_notification_dispatch_job(self.app)

            fetch_mock.assert_called_once()
            email_send.assert_called_once()
            webhook_send.assert_called_once()

            rows = (
                get_db()
                .execute(
                    """
                SELECT channel, status
                FROM notification_delivery_logs
                WHERE source_key = ?
                ORDER BY channel ASC
                """,
                    (
                        notification_dispatch.build_source_key(
                            notification_dispatch.SOURCE_ACCOUNT,
                            "email-webhook@example.com",
                        ),
                    ),
                )
                .fetchall()
            )
            self.assertEqual(
                [(row["channel"], row["status"]) for row in rows],
                [("email", "sent"), ("webhook", "sent")],
            )

    def test_run_notification_dispatch_job_telegram_and_webhook_coexist(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services import notification_dispatch

            self._insert_account(
                "telegram-webhook@example.com",
                telegram_enabled=1,
                telegram_cursor="2026-03-01T00:00:00",
            )
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_TELEGRAM,
                cursor_value="2026-03-01T00:00:00",
            )
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_WEBHOOK,
                cursor_value="2026-03-01T00:00:00",
            )
            settings_repo.set_setting("telegram_bot_token", encrypt_data("bot_token"))
            settings_repo.set_setting("telegram_chat_id", "123456")
            settings_repo.set_setting("webhook_notification_enabled", "true")
            settings_repo.set_setting("webhook_notification_url", "https://example.com/hook")

            message = [
                {
                    "message_id": "<telegram-webhook@example.com>",
                    "subject": "Telegram Webhook",
                    "sender": "sender@example.com",
                    "received_at": "2026-03-02T10:00:00",
                    "content": "body",
                    "preview": "body",
                    "folder": "inbox",
                }
            ]

            with (
                patch(
                    "outlook_web.services.notification_dispatch.fetch_source_messages",
                    return_value=message,
                ) as fetch_mock,
                patch("outlook_web.services.notification_dispatch.send_business_telegram_notification") as telegram_send,
                patch("outlook_web.services.notification_dispatch.send_business_webhook_notification") as webhook_send,
            ):
                notification_dispatch.run_notification_dispatch_job(self.app)

            fetch_mock.assert_called_once()
            telegram_send.assert_called_once()
            webhook_send.assert_called_once()

            rows = (
                get_db()
                .execute(
                    """
                SELECT channel, status
                FROM notification_delivery_logs
                WHERE source_key = ?
                ORDER BY channel ASC
                """,
                    (
                        notification_dispatch.build_source_key(
                            notification_dispatch.SOURCE_ACCOUNT,
                            "telegram-webhook@example.com",
                        ),
                    ),
                )
                .fetchall()
            )
            self.assertEqual(
                [(row["channel"], row["status"]) for row in rows],
                [("telegram", "sent"), ("webhook", "sent")],
            )

    def test_run_notification_dispatch_job_three_channels_coexist(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services import notification_dispatch

            self._insert_account(
                "triple@example.com",
                telegram_enabled=1,
                telegram_cursor="2026-03-01T00:00:00",
            )
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_EMAIL,
                cursor_value="2026-03-01T00:00:00",
            )
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_TELEGRAM,
                cursor_value="2026-03-01T00:00:00",
            )
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_WEBHOOK,
                cursor_value="2026-03-01T00:00:00",
            )
            settings_repo.set_setting("email_notification_enabled", "true")
            settings_repo.set_setting("email_notification_recipient", "notify@example.com")
            settings_repo.set_setting("telegram_bot_token", encrypt_data("bot_token"))
            settings_repo.set_setting("telegram_chat_id", "123456")
            settings_repo.set_setting("webhook_notification_enabled", "true")
            settings_repo.set_setting("webhook_notification_url", "https://example.com/hook")

            message = [
                {
                    "message_id": "<triple@example.com>",
                    "subject": "Three Channels",
                    "sender": "sender@example.com",
                    "received_at": "2026-03-02T10:00:00",
                    "content": "body",
                    "preview": "body",
                    "folder": "inbox",
                }
            ]

            with (
                patch.dict(
                    os.environ,
                    {
                        "EMAIL_NOTIFICATION_SMTP_HOST": "smtp.example.com",
                        "EMAIL_NOTIFICATION_SMTP_PORT": "587",
                        "EMAIL_NOTIFICATION_FROM": "noreply@example.com",
                    },
                    clear=False,
                ),
                patch(
                    "outlook_web.services.notification_dispatch.fetch_source_messages",
                    return_value=message,
                ) as fetch_mock,
                patch("outlook_web.services.notification_dispatch.send_business_email_notification") as email_send,
                patch("outlook_web.services.notification_dispatch.send_business_telegram_notification") as telegram_send,
                patch("outlook_web.services.notification_dispatch.send_business_webhook_notification") as webhook_send,
            ):
                notification_dispatch.run_notification_dispatch_job(self.app)

            fetch_mock.assert_called_once()
            email_send.assert_called_once()
            telegram_send.assert_called_once()
            webhook_send.assert_called_once()

            rows = (
                get_db()
                .execute(
                    """
                SELECT channel, status
                FROM notification_delivery_logs
                WHERE source_key = ?
                ORDER BY channel ASC
                """,
                    (
                        notification_dispatch.build_source_key(
                            notification_dispatch.SOURCE_ACCOUNT,
                            "triple@example.com",
                        ),
                    ),
                )
                .fetchall()
            )
            self.assertEqual(
                [(row["channel"], row["status"]) for row in rows],
                [("email", "sent"), ("telegram", "sent"), ("webhook", "sent")],
            )

    def test_active_channels_follow_shared_account_participation_rule(self):
        with self.app.app_context():
            from outlook_web.services import notification_dispatch

            account = {
                "id": 1,
                "email": "model@example.com",
                "telegram_push_enabled": 1,
            }
            source = {
                "source_type": notification_dispatch.SOURCE_ACCOUNT,
                "source_key": notification_dispatch.build_source_key(
                    notification_dispatch.SOURCE_ACCOUNT, "model@example.com"
                ),
                "label": "model@example.com",
                "account": account,
            }
            telegram_runtime = {"bot_token": "token", "chat_id": "123"}

            email_only = notification_dispatch._build_active_channels_for_source(
                source,
                email_enabled=True,
                telegram_runtime=None,
            )
            self.assertEqual(
                [channel for channel, *_ in email_only],
                [notification_dispatch.CHANNEL_EMAIL],
            )

            telegram_only = notification_dispatch._build_active_channels_for_source(
                source,
                email_enabled=False,
                telegram_runtime=telegram_runtime,
            )
            self.assertEqual(
                [channel for channel, *_ in telegram_only],
                [notification_dispatch.CHANNEL_TELEGRAM],
            )

            dual_channel = notification_dispatch._build_active_channels_for_source(
                source,
                email_enabled=True,
                telegram_runtime=telegram_runtime,
            )
            self.assertEqual(
                [channel for channel, *_ in dual_channel],
                [
                    notification_dispatch.CHANNEL_EMAIL,
                    notification_dispatch.CHANNEL_TELEGRAM,
                ],
            )

            disabled_source = {
                **source,
                "account": {
                    **account,
                    "telegram_push_enabled": 0,
                },
            }
            disabled_channels = notification_dispatch._build_active_channels_for_source(
                disabled_source,
                email_enabled=True,
                telegram_runtime=telegram_runtime,
            )
            self.assertEqual(disabled_channels, [])

    def test_unified_notification_job_sends_email_when_only_email_channel_enabled(self):
        with self.app.app_context():
            from outlook_web.services import notification_dispatch

            self._insert_account("email-only@example.com", telegram_enabled=1)
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_EMAIL,
                cursor_value="2026-03-01T00:00:00",
            )
            settings_repo.set_setting("email_notification_enabled", "true")
            settings_repo.set_setting("email_notification_recipient", "notify@example.com")
            message = [
                {
                    "message_id": "<email-only@example.com>",
                    "subject": "Email only",
                    "sender": "sender@example.com",
                    "received_at": "2026-03-02T10:00:00",
                    "content": "body",
                    "preview": "body",
                    "folder": "inbox",
                }
            ]

            with (
                patch.dict(
                    os.environ,
                    {
                        "EMAIL_NOTIFICATION_SMTP_HOST": "smtp.example.com",
                        "EMAIL_NOTIFICATION_SMTP_PORT": "587",
                        "EMAIL_NOTIFICATION_FROM": "noreply@example.com",
                    },
                    clear=False,
                ),
                patch(
                    "outlook_web.services.notification_dispatch.fetch_source_messages",
                    return_value=message,
                ),
                patch("outlook_web.services.notification_dispatch.send_business_email_notification") as email_send,
                patch("outlook_web.services.notification_dispatch.send_business_telegram_notification") as telegram_send,
            ):
                notification_dispatch.run_notification_dispatch_job(self.app)

            email_send.assert_called_once()
            telegram_send.assert_not_called()

    def test_unified_notification_job_skips_email_when_account_notification_disabled(
        self,
    ):
        with self.app.app_context():
            from outlook_web.services import notification_dispatch

            self._insert_account("email-disabled@example.com", telegram_enabled=0)
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_EMAIL,
                cursor_value="2026-03-01T00:00:00",
            )
            settings_repo.set_setting("email_notification_enabled", "true")
            settings_repo.set_setting("email_notification_recipient", "notify@example.com")
            message = [
                {
                    "message_id": "<email-disabled@example.com>",
                    "subject": "Disabled",
                    "sender": "sender@example.com",
                    "received_at": "2026-03-02T10:00:00",
                    "content": "body",
                    "preview": "body",
                    "folder": "inbox",
                }
            ]

            with (
                patch.dict(
                    os.environ,
                    {
                        "EMAIL_NOTIFICATION_SMTP_HOST": "smtp.example.com",
                        "EMAIL_NOTIFICATION_SMTP_PORT": "587",
                        "EMAIL_NOTIFICATION_FROM": "noreply@example.com",
                    },
                    clear=False,
                ),
                patch(
                    "outlook_web.services.notification_dispatch.fetch_source_messages",
                    return_value=message,
                ) as fetch_mock,
                patch("outlook_web.services.notification_dispatch.send_business_email_notification") as email_send,
            ):
                notification_dispatch.run_notification_dispatch_job(self.app)

            fetch_mock.assert_not_called()
            email_send.assert_not_called()

    def test_unified_notification_job_skips_all_channels_when_account_notification_disabled(
        self,
    ):
        with self.app.app_context():
            from outlook_web.services import notification_dispatch

            self._insert_account("disabled-dual@example.com", telegram_enabled=0)
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_EMAIL,
                cursor_value="2026-03-01T00:00:00",
            )
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_TELEGRAM,
                cursor_value="2026-03-01T00:00:00",
            )
            settings_repo.set_setting("email_notification_enabled", "true")
            settings_repo.set_setting("email_notification_recipient", "notify@example.com")
            settings_repo.set_setting("telegram_bot_token", encrypt_data("bot_token"))
            settings_repo.set_setting("telegram_chat_id", "123456")

            with (
                patch.dict(
                    os.environ,
                    {
                        "EMAIL_NOTIFICATION_SMTP_HOST": "smtp.example.com",
                        "EMAIL_NOTIFICATION_SMTP_PORT": "587",
                        "EMAIL_NOTIFICATION_FROM": "noreply@example.com",
                    },
                    clear=False,
                ),
                patch(
                    "outlook_web.services.notification_dispatch.fetch_source_messages",
                ) as fetch_mock,
                patch("outlook_web.services.notification_dispatch.send_business_email_notification") as email_send,
                patch("outlook_web.services.notification_dispatch.send_business_telegram_notification") as telegram_send,
            ):
                notification_dispatch.run_notification_dispatch_job(self.app)

            fetch_mock.assert_not_called()
            email_send.assert_not_called()
            telegram_send.assert_not_called()

    def test_reenable_account_notification_resets_email_cursor_without_backfilling_disabled_period(
        self,
    ):
        with self.app.app_context():
            from outlook_web.repositories import accounts as accounts_repo
            from outlook_web.repositories import notification_state as notification_state_repo
            from outlook_web.services import notification_dispatch

            account_id = self._insert_account("reenable@example.com", telegram_enabled=1)
            source_key = notification_dispatch.build_source_key(notification_dispatch.SOURCE_ACCOUNT, "reenable@example.com")
            notification_state_repo.reset_channel_cursor(
                notification_dispatch.CHANNEL_EMAIL,
                notification_dispatch.SOURCE_ACCOUNT,
                source_key,
                "2026-03-01T00:00:00",
            )
            notification_state_repo.reset_channel_cursor(
                notification_dispatch.CHANNEL_TELEGRAM,
                notification_dispatch.SOURCE_ACCOUNT,
                source_key,
                "2026-03-01T00:00:00",
            )
            accounts_repo.toggle_telegram_push(account_id, False)
            accounts_repo.toggle_telegram_push(account_id, True)
            settings_repo.set_setting("email_notification_enabled", "true")
            settings_repo.set_setting("email_notification_recipient", "notify@example.com")

            fetched_cursors = []

            def fake_fetch(source, since):
                fetched_cursors.append(since)
                return []

            with (
                patch.dict(
                    os.environ,
                    {
                        "EMAIL_NOTIFICATION_SMTP_HOST": "smtp.example.com",
                        "EMAIL_NOTIFICATION_SMTP_PORT": "587",
                        "EMAIL_NOTIFICATION_FROM": "noreply@example.com",
                    },
                    clear=False,
                ),
                patch(
                    "outlook_web.services.notification_dispatch.fetch_source_messages",
                    side_effect=fake_fetch,
                ),
                patch("outlook_web.services.notification_dispatch.send_business_email_notification") as email_send,
            ):
                notification_dispatch.run_notification_dispatch_job(self.app)

            email_send.assert_not_called()
            self.assertEqual(len(fetched_cursors), 1)
            self.assertNotEqual(fetched_cursors[0], "2026-03-01T00:00:00")

    def test_unified_notification_job_sends_telegram_when_only_telegram_channel_enabled(
        self,
    ):
        with self.app.app_context():
            from outlook_web.services import notification_dispatch

            self._insert_account(
                "telegram-only@example.com",
                telegram_enabled=1,
                telegram_cursor="2026-03-01T00:00:00",
            )
            message = [
                {
                    "message_id": "<telegram-only@example.com>",
                    "subject": "Telegram only",
                    "sender": "sender@example.com",
                    "received_at": "2026-03-02T10:00:00",
                    "content": "body",
                    "preview": "body",
                    "folder": "inbox",
                }
            ]
            settings_repo.set_setting("telegram_bot_token", encrypt_data("bot_token"))
            settings_repo.set_setting("telegram_chat_id", "123456")

            with (
                patch(
                    "outlook_web.services.notification_dispatch.fetch_source_messages",
                    return_value=message,
                ),
                patch("outlook_web.services.notification_dispatch.send_business_email_notification") as email_send,
                patch("outlook_web.services.notification_dispatch.send_business_telegram_notification") as telegram_send,
            ):
                notification_dispatch.run_notification_dispatch_job(self.app)

            telegram_send.assert_called_once()
            email_send.assert_not_called()

    def test_unified_notification_job_fetches_per_cursor_group_when_channels_diverge(
        self,
    ):
        with self.app.app_context():
            from outlook_web.services import notification_dispatch

            self._insert_account(
                "diverged-fetch@example.com",
                telegram_enabled=1,
                telegram_cursor="2026-03-10T00:00:00",
            )
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_EMAIL,
                cursor_value="2026-03-01T00:00:00",
            )
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_TELEGRAM,
                cursor_value="2026-03-10T00:00:00",
            )
            settings_repo.set_setting("email_notification_enabled", "true")
            settings_repo.set_setting("email_notification_recipient", "notify@example.com")
            settings_repo.set_setting("telegram_bot_token", encrypt_data("bot_token"))
            settings_repo.set_setting("telegram_chat_id", "123456")

            def fake_fetch(source, since):
                if since == "2026-03-01T00:00:00":
                    return [
                        {
                            "message_id": "<old-backlog@example.com>",
                            "subject": "Old backlog",
                            "sender": "sender@example.com",
                            "received_at": "2026-03-02T10:00:00",
                            "content": "old body",
                            "preview": "old body",
                            "folder": "inbox",
                        }
                    ]
                return [
                    {
                        "message_id": "<fresh-message@example.com>",
                        "subject": "Fresh",
                        "sender": "sender@example.com",
                        "received_at": "2026-03-11T10:00:00",
                        "content": "fresh body",
                        "preview": "fresh body",
                        "folder": "inbox",
                    }
                ]

            with (
                patch.dict(
                    os.environ,
                    {
                        "EMAIL_NOTIFICATION_SMTP_HOST": "smtp.example.com",
                        "EMAIL_NOTIFICATION_SMTP_PORT": "587",
                        "EMAIL_NOTIFICATION_FROM": "noreply@example.com",
                    },
                    clear=False,
                ),
                patch(
                    "outlook_web.services.notification_dispatch.fetch_source_messages",
                    side_effect=fake_fetch,
                ) as fetch_mock,
                patch("outlook_web.services.notification_dispatch.send_business_email_notification") as email_send,
                patch("outlook_web.services.notification_dispatch.send_business_telegram_notification") as telegram_send,
            ):
                notification_dispatch.run_notification_dispatch_job(self.app)

            called_cursors = [call.args[1] for call in fetch_mock.call_args_list]
            self.assertEqual(called_cursors, ["2026-03-01T00:00:00", "2026-03-10T00:00:00"])
            self.assertEqual(email_send.call_args[0][1]["message_id"], "<old-backlog@example.com>")
            self.assertEqual(
                telegram_send.call_args[0][1]["message_id"],
                "<fresh-message@example.com>",
            )

    def test_unified_notification_job_does_not_repeat_sent_message_after_cursor_advance(
        self,
    ):
        with self.app.app_context():
            from outlook_web.repositories import notification_state as notification_state_repo
            from outlook_web.services import notification_dispatch

            self._insert_account(
                "unified-dedup@example.com",
                telegram_enabled=1,
                telegram_cursor="2026-03-01T00:00:00",
            )
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_EMAIL,
                cursor_value="2026-03-01T00:00:00",
            )
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_TELEGRAM,
                cursor_value="2026-03-01T00:00:00",
            )
            settings_repo.set_setting("email_notification_enabled", "true")
            settings_repo.set_setting("email_notification_recipient", "notify@example.com")
            settings_repo.set_setting("telegram_bot_token", encrypt_data("bot_token"))
            settings_repo.set_setting("telegram_chat_id", "123456")
            message = [
                {
                    "message_id": "<unified-dedup@example.com>",
                    "subject": "Unified Dedup",
                    "sender": "sender@example.com",
                    "received_at": "2026-03-02T10:00:00",
                    "content": "body",
                    "preview": "body",
                    "folder": "inbox",
                }
            ]

            with (
                patch.dict(
                    os.environ,
                    {
                        "EMAIL_NOTIFICATION_SMTP_HOST": "smtp.example.com",
                        "EMAIL_NOTIFICATION_SMTP_PORT": "587",
                        "EMAIL_NOTIFICATION_FROM": "noreply@example.com",
                    },
                    clear=False,
                ),
                patch(
                    "outlook_web.services.notification_dispatch.fetch_source_messages",
                    return_value=message,
                ),
                patch("outlook_web.services.notification_dispatch.send_business_email_notification") as email_send,
                patch("outlook_web.services.notification_dispatch.send_business_telegram_notification") as telegram_send,
            ):
                notification_dispatch.run_notification_dispatch_job(self.app)
                notification_dispatch.run_notification_dispatch_job(self.app)

            self.assertEqual(email_send.call_count, 1)
            self.assertEqual(telegram_send.call_count, 1)
            email_cursor = notification_state_repo.get_cursor(
                notification_dispatch.CHANNEL_EMAIL,
                notification_dispatch.SOURCE_ACCOUNT,
                notification_dispatch.build_source_key(notification_dispatch.SOURCE_ACCOUNT, "unified-dedup@example.com"),
            )
            telegram_cursor = notification_state_repo.get_cursor(
                notification_dispatch.CHANNEL_TELEGRAM,
                notification_dispatch.SOURCE_ACCOUNT,
                notification_dispatch.build_source_key(notification_dispatch.SOURCE_ACCOUNT, "unified-dedup@example.com"),
            )
            self.assertEqual(email_cursor, "2026-03-02T10:00:00")
            self.assertEqual(telegram_cursor, "2026-03-02T10:00:00")

    def test_temp_email_html_body_is_converted_for_notification(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services import notification_dispatch

            self._insert_temp_email("html-temp@example.com")
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_EMAIL,
                cursor_value="2026-03-01T00:00:00",
            )
            settings_repo.set_setting("email_notification_enabled", "true")
            settings_repo.set_setting("email_notification_recipient", "notify@example.com")
            get_db().execute(
                """
                INSERT INTO temp_email_messages (
                    message_id, email_address, from_address, subject, content, html_content, has_html, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "html-only-message",
                    "html-temp@example.com",
                    "sender@example.com",
                    "HTML only",
                    "",
                    "<div>Hello <strong>HTML</strong> world</div>",
                    1,
                    1772407200,
                ),
            )
            get_db().commit()

            with (
                patch.dict(
                    os.environ,
                    {
                        "EMAIL_NOTIFICATION_SMTP_HOST": "smtp.example.com",
                        "EMAIL_NOTIFICATION_SMTP_PORT": "587",
                        "EMAIL_NOTIFICATION_FROM": "noreply@example.com",
                    },
                    clear=False,
                ),
                patch(
                    "outlook_web.services.notification_dispatch.TempMailService.list_messages",
                    return_value=[],  # 跳过远端 sync；DB 中已直接插入测试邮件
                ),
                patch("outlook_web.services.notification_dispatch.send_business_email_notification") as send_mock,
            ):
                notification_dispatch.run_email_notification_job(self.app)

            send_mock.assert_called_once()
            sent_message = send_mock.call_args[0][1]
            self.assertEqual(sent_message["content"], "Hello HTML world")
            self.assertEqual(sent_message["preview"], "Hello HTML world")

    def test_temp_email_notification_syncs_remote_by_default(self):
        with self.app.app_context():
            from outlook_web.services import notification_dispatch

            self._insert_temp_email(
                "default-sync@example.com",
                provider_name=settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER,
            )
            source = next(
                item
                for item in notification_dispatch.list_email_notification_sources()
                if item["email"] == "default-sync@example.com"
            )

            with (
                patch.dict(os.environ, {"TEMP_MAIL_INBOUND_PUSH_ENABLED": ""}, clear=False),
                patch(
                    "outlook_web.services.notification_dispatch.TempMailService.list_messages",
                    return_value=[],
                ) as list_messages,
            ):
                notification_dispatch.fetch_source_messages(source, "2026-03-01T00:00:00")

            list_messages.assert_called_once_with("default-sync@example.com", sync_remote=True)

    def test_cloudflare_inbound_push_mode_uses_local_notification_cache(self):
        with self.app.app_context():
            from outlook_web.services import notification_dispatch

            self._insert_temp_email(
                "inbound-push@example.com",
                provider_name=settings_repo.CLOUDFLARE_TEMP_MAIL_PROVIDER,
            )
            source = next(
                item
                for item in notification_dispatch.list_email_notification_sources()
                if item["email"] == "inbound-push@example.com"
            )

            with (
                patch.dict(os.environ, {"TEMP_MAIL_INBOUND_PUSH_ENABLED": "true"}, clear=False),
                patch(
                    "outlook_web.services.notification_dispatch.TempMailService.list_messages",
                    return_value=[],
                ) as list_messages,
            ):
                notification_dispatch.fetch_source_messages(source, "2026-03-01T00:00:00")

            list_messages.assert_called_once_with("inbound-push@example.com", sync_remote=False)

    def test_inbound_push_mode_keeps_non_cloudflare_provider_remote_sync(self):
        with self.app.app_context():
            from outlook_web.services import notification_dispatch

            self._insert_temp_email(
                "custom-provider@example.com",
                provider_name="custom_domain_temp_mail",
            )
            source = next(
                item
                for item in notification_dispatch.list_email_notification_sources()
                if item["email"] == "custom-provider@example.com"
            )

            with (
                patch.dict(os.environ, {"TEMP_MAIL_INBOUND_PUSH_ENABLED": "true"}, clear=False),
                patch(
                    "outlook_web.services.notification_dispatch.TempMailService.list_messages",
                    return_value=[],
                ) as list_messages,
            ):
                notification_dispatch.fetch_source_messages(source, "2026-03-01T00:00:00")

            list_messages.assert_called_once_with("custom-provider@example.com", sync_remote=True)

    def test_claim_delivery_attempt_is_atomic_for_same_message(self):
        with self.app.app_context():
            from outlook_web.repositories import notification_state as notification_state_repo

            result1 = notification_state_repo.claim_delivery_attempt(
                "email",
                "account",
                "account:atomic@example.com",
                "msg-atomic",
            )
            result2 = notification_state_repo.claim_delivery_attempt(
                "email",
                "account",
                "account:atomic@example.com",
                "msg-atomic",
            )
            notification_state_repo.complete_delivery_attempt(
                "email",
                "account",
                "account:atomic@example.com",
                "msg-atomic",
                status="sent",
            )
            result3 = notification_state_repo.claim_delivery_attempt(
                "email",
                "account",
                "account:atomic@example.com",
                "msg-atomic",
            )

            self.assertEqual(result1, "acquired")
            self.assertEqual(result2, "processing")
            self.assertEqual(result3, "sent")

    def test_upsert_cursor_is_monotonic(self):
        with self.app.app_context():
            from outlook_web.repositories import notification_state as notification_state_repo

            notification_state_repo.reset_channel_cursor(
                "email",
                "account",
                "account:cursor@example.com",
                "2026-03-10T10:00:00",
            )
            notification_state_repo.upsert_cursor(
                "email",
                "account",
                "account:cursor@example.com",
                "2026-03-12T10:00:00",
            )
            notification_state_repo.upsert_cursor(
                "email",
                "account",
                "account:cursor@example.com",
                "2026-03-11T10:00:00",
            )

            cursor = notification_state_repo.get_cursor("email", "account", "account:cursor@example.com")
            self.assertEqual(cursor, "2026-03-12T10:00:00")

    def test_inbox_to_junkemail_move_does_not_repeat_same_channel(self):
        with self.app.app_context():
            from outlook_web.services import notification_dispatch

            self._insert_account("folder-move@example.com")
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_EMAIL,
                cursor_value="2026-03-01T00:00:00",
            )
            sources = notification_dispatch.list_email_notification_sources()
            sent = []

            def fake_sender(source, message):
                sent.append(message["folder"])

            with patch(
                "outlook_web.services.notification_dispatch.fetch_source_messages",
                side_effect=[
                    [
                        {
                            "message_id": "<same-message@example.com>",
                            "subject": "Move",
                            "sender": "sender@example.com",
                            "received_at": "2026-03-02T10:00:00",
                            "content": "body",
                            "folder": "inbox",
                        }
                    ],
                    [
                        {
                            "message_id": "<same-message@example.com>",
                            "subject": "Move",
                            "sender": "sender@example.com",
                            "received_at": "2026-03-02T10:01:00",
                            "content": "body",
                            "folder": "junkemail",
                        }
                    ],
                ],
            ):
                notification_dispatch.process_channel_for_sources(
                    channel=notification_dispatch.CHANNEL_EMAIL,
                    sources=sources,
                    sender=fake_sender,
                )
                notification_dispatch.process_channel_for_sources(
                    channel=notification_dispatch.CHANNEL_EMAIL,
                    sources=sources,
                    sender=fake_sender,
                )

            self.assertEqual(sent, ["inbox"])

    def test_email_failure_does_not_block_telegram_delivery(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.services import email_push, notification_dispatch, telegram_push

            account_id = self._insert_account(
                "dual-channel@example.com",
                telegram_enabled=1,
                telegram_cursor="2026-03-01T00:00:00",
            )
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_EMAIL,
                cursor_value="2026-03-01T00:00:00",
            )
            notification_dispatch.bootstrap_channel_cursors(
                notification_dispatch.CHANNEL_TELEGRAM,
                cursor_value="2026-03-01T00:00:00",
            )
            settings_repo.set_setting("email_notification_enabled", "true")
            settings_repo.set_setting("email_notification_recipient", "notify@example.com")
            settings_repo.set_setting("telegram_bot_token", encrypt_data("bot_token"))
            settings_repo.set_setting("telegram_chat_id", "123456")

            message = [
                {
                    "message_id": "<dual-message@example.com>",
                    "subject": "Dual",
                    "sender": "sender@example.com",
                    "received_at": "2026-03-02T10:00:00",
                    "content": "body",
                    "preview": "body",
                    "folder": "inbox",
                }
            ]

            with (
                patch(
                    "outlook_web.services.notification_dispatch.fetch_source_messages",
                    return_value=message,
                ),
                patch.dict(
                    os.environ,
                    {
                        "EMAIL_NOTIFICATION_SMTP_HOST": "smtp.example.com",
                        "EMAIL_NOTIFICATION_SMTP_PORT": "587",
                        "EMAIL_NOTIFICATION_FROM": "noreply@example.com",
                    },
                    clear=False,
                ),
                patch(
                    "outlook_web.services.notification_dispatch.send_business_email_notification",
                    side_effect=email_push.EmailPushError(
                        "EMAIL_TEST_SEND_FAILED",
                        "测试邮件发送失败",
                        message_en="Failed to send test email",
                    ),
                ),
                patch(
                    "outlook_web.services.telegram_push._fetch_new_emails_imap",
                    return_value=message,
                ),
                patch(
                    "outlook_web.services.telegram_push._send_telegram_message",
                    return_value=True,
                ) as telegram_send,
                patch(
                    "outlook_web.services.telegram_push.TELEGRAM_PUSH_DELAY_SEC",
                    0,
                ),
            ):
                notification_dispatch.run_email_notification_job(self.app)
                telegram_push.run_telegram_push_job(self.app)

            telegram_send.assert_called_once()
            rows = (
                get_db()
                .execute(
                    """
                SELECT channel, status
                FROM notification_delivery_logs
                WHERE source_key = ?
                ORDER BY channel ASC
                """,
                    (
                        notification_dispatch.build_source_key(
                            notification_dispatch.SOURCE_ACCOUNT,
                            "dual-channel@example.com",
                        ),
                    ),
                )
                .fetchall()
            )
            self.assertEqual(
                [(row["channel"], row["status"]) for row in rows],
                [("email", "failed"), ("telegram", "sent")],
            )
            legacy_row = (
                get_db()
                .execute(
                    "SELECT 1 FROM telegram_push_log WHERE account_id = ? AND message_id = ?",
                    (account_id, "<dual-message@example.com>"),
                )
                .fetchone()
            )
            self.assertIsNotNone(legacy_row)

    def test_legacy_outlook_imap_account_fetches_via_imap(self):
        with self.app.app_context():
            from outlook_web.services import notification_dispatch

            source = {
                "source_type": notification_dispatch.SOURCE_ACCOUNT,
                "source_key": notification_dispatch.build_source_key(
                    notification_dispatch.SOURCE_ACCOUNT, "legacy-outlook@example.com"
                ),
                "email": "legacy-outlook@example.com",
                "label": "legacy-outlook@example.com",
                "account": {
                    "id": 1,
                    "email": "legacy-outlook@example.com",
                    "provider": "outlook",
                    "account_type": "imap",
                    "imap_host": "outlook.live.com",
                    "imap_port": 993,
                    "imap_password": "enc:dummy",
                },
            }

            with (
                patch(
                    "outlook_web.services.telegram_push._fetch_new_emails_imap",
                    return_value=[],
                ) as mock_imap,
                patch("outlook_web.services.telegram_push._fetch_new_emails_graph") as mock_graph,
            ):
                notification_dispatch.fetch_source_messages(source, "2026-03-01T00:00:00")

            self.assertEqual(mock_imap.call_count, 2)
            mock_graph.assert_not_called()
