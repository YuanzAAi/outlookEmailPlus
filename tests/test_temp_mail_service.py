from __future__ import annotations

import gc
import json
import unittest
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class _FakeTempMailProvider:
    def __init__(self):
        self.generated = []
        self.list_payload = []
        self.list_calls = 0
        self.detail_payload = {}
        self.list_exception = None
        self.detail_exception = None
        self.delete_result = True
        self.clear_result = True

    def get_options(self):
        return {
            "domain_strategy": "auto_or_manual",
            "default_mode": "auto",
            "domains": [
                {"name": "mail.service.test", "enabled": True, "is_default": True},
                {"name": "temp.service.test", "enabled": True, "is_default": False},
            ],
            "prefix_rules": {
                "min_length": 1,
                "max_length": 32,
                "pattern": r"^[a-z0-9][a-z0-9._-]*$",
            },
        }

    def generate_mailbox(self, *, prefix=None, domain=None):
        email_addr = f"{prefix or 'auto'}@{domain or 'mail.service.test'}"
        self.generated.append({"prefix": prefix, "domain": domain, "email": email_addr})
        return {"success": True, "email": email_addr}

    def list_messages(self, email_addr):
        self.list_calls += 1
        if self.list_exception is not None:
            raise self.list_exception
        return list(self.list_payload)

    def get_message_detail(self, email_addr, message_id):
        if self.detail_exception is not None:
            raise self.detail_exception
        return dict(self.detail_payload.get(message_id) or {})

    def delete_message(self, email_addr, message_id):
        return self.delete_result

    def clear_messages(self, email_addr):
        return self.clear_result


class _FakeCloudflareProvider(_FakeTempMailProvider):
    provider_name = "cloudflare_temp_mail"

    def __init__(self):
        super().__init__()
        self.discovered = None
        self.discover_calls = 0
        self.remote_rows = []
        self.remote_exception = None

    def discover_mailbox(self, email_addr):
        self.discover_calls += 1
        return dict(self.discovered) if self.discovered else None

    def list_remote_mailboxes(self, *, after_id=0, limit=200):
        if self.remote_exception is not None:
            raise self.remote_exception
        rows = [row for row in self.remote_rows if int(row.get("id") or 0) > int(after_id or 0)][:limit]
        next_cursor = max([int(after_id or 0)] + [int(row.get("id") or 0) for row in rows])
        return {"results": rows, "next_cursor": next_cursor, "supported": True}


class TempMailServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
            from outlook_web.db import get_db

            db = get_db()
            db.execute("DELETE FROM temp_email_messages WHERE email_address LIKE '%@service.test'")
            db.execute("DELETE FROM temp_emails WHERE email LIKE '%@service.test'")
            db.execute("DELETE FROM temp_email_messages WHERE email_address LIKE '%@cf-mail.example.com'")
            db.execute("DELETE FROM temp_emails WHERE email LIKE '%@cf-mail.example.com'")
            db.execute("DELETE FROM accounts WHERE email LIKE '%@cf-mail.example.com'")
            db.execute("DELETE FROM settings WHERE key = 'cf_worker_address_sync_cursor'")
            db.commit()

    def test_message_sync_locks_are_released_when_idle(self):
        from outlook_web.services.temp_mail_service import TempMailService

        service = TempMailService(provider=_FakeCloudflareProvider())
        lock = service._message_sync_lock_for("idle@cf-mail.example.com")
        self.assertEqual(len(service._message_sync_locks), 1)

        del lock
        gc.collect()

        self.assertEqual(len(service._message_sync_locks), 0)

    def test_message_sync_timestamps_are_bounded(self):
        from outlook_web.services.temp_mail_service import MESSAGE_SYNC_STATE_MAX_ENTRIES, TempMailService

        service = TempMailService(provider=_FakeCloudflareProvider())
        for index in range(MESSAGE_SYNC_STATE_MAX_ENTRIES + 20):
            service._mark_message_synced(f"mailbox-{index}@cf-mail.example.com")

        self.assertEqual(len(service._message_sync_at), MESSAGE_SYNC_STATE_MAX_ENTRIES)

    def test_generate_user_mailbox_persists_prefix_domain_and_visibility(self):
        with self.app.app_context():
            from outlook_web.services.temp_mail_service import TempMailService

            provider = _FakeTempMailProvider()
            service = TempMailService(provider=provider)

            mailbox = service.generate_user_mailbox(prefix="demo123", domain="mail.service.test")

        self.assertEqual(mailbox["email"], "demo123@mail.service.test")
        self.assertEqual(mailbox["prefix"], "demo123")
        self.assertEqual(mailbox["domain"], "mail.service.test")
        self.assertTrue(mailbox["visible_in_ui"])
        self.assertEqual(mailbox["created_by"], "user")

    def test_cloudflare_discovery_imports_exact_remote_mailbox_with_credentials(self):
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services.temp_mail_service import TempMailService

            provider = _FakeCloudflareProvider()
            provider.discovered = {
                "success": True,
                "email": "mixedcase@cf-mail.example.com",
                "provider_name": "cloudflare_temp_mail",
                "meta": {
                    "provider_name": "cloudflare_temp_mail",
                    "provider_mailbox_id": "42",
                    "provider_jwt": "jwt-42",
                },
            }
            service = TempMailService(provider=provider)

            mailbox = service.discover_user_mailbox("MixedCase@cf-mail.example.com")
            stored = temp_emails_repo.get_temp_email_by_address("MIXEDCASE@CF-MAIL.EXAMPLE.COM")

        self.assertEqual(mailbox["email"], "mixedcase@cf-mail.example.com")
        self.assertEqual(stored["meta_json"]["provider_jwt"], "jwt-42")
        self.assertEqual(provider.discover_calls, 1)

    def test_cloudflare_import_does_not_create_missing_remote_mailbox(self):
        with self.app.app_context():
            from outlook_web.services.temp_mail_service import TempMailError, TempMailService

            provider = _FakeCloudflareProvider()
            service = TempMailService(provider=provider)

            with self.assertRaises(TempMailError) as ctx:
                service.import_user_mailbox("missing@cf-mail.example.com", allow_local_fallback=True)

        self.assertEqual(ctx.exception.code, "TEMP_EMAIL_NOT_FOUND")
        self.assertEqual(provider.generated, [])

    def test_cloudflare_address_sync_imports_metadata_without_reading_messages(self):
        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services.temp_mail_service import TempMailService

            provider = _FakeCloudflareProvider()
            provider.remote_rows = [
                {"id": 10, "name": "first@cf-mail.example.com"},
                {"id": 11, "name": "second@cf-mail.example.com"},
            ]
            service = TempMailService(provider=provider)

            imported = service.sync_remote_mailboxes(force=True)
            first = temp_emails_repo.get_temp_email_by_address("FIRST@cf-mail.example.com")
            cursor = settings_repo.get_setting("cf_worker_address_sync_cursor")

        self.assertEqual(imported, 2)
        self.assertEqual(first["meta_json"]["provider_mailbox_id"], "10")
        self.assertEqual(cursor, "11")
        self.assertEqual(provider.list_calls, 0)

    def test_cloudflare_address_sync_logs_repeated_failure_once_per_interval(self):
        with self.app.app_context():
            from outlook_web.services.temp_mail_provider_custom import TempMailProviderReadError
            from outlook_web.services.temp_mail_service import TempMailService

            provider = _FakeCloudflareProvider()
            provider.remote_exception = TempMailProviderReadError("UPSTREAM_TIMEOUT", "worker timeout")
            service = TempMailService(provider=provider)

            with patch("outlook_web.services.temp_mail_service.logger.warning") as warning_mock:
                service.sync_remote_mailboxes(force=True)
                service.sync_remote_mailboxes(force=True)

        warning_mock.assert_called_once()

    def test_cloudflare_inbound_push_creates_visible_mailbox_and_uses_local_message(self):
        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services.temp_mail_service import TempMailService

            settings_repo.set_setting("temp_mail_provider", "cloudflare_temp_mail")
            settings_repo.set_setting(
                "cf_worker_domains",
                '[{"name":"cf-mail.example.com","enabled":true}]',
            )
            provider = _FakeCloudflareProvider()
            service = TempMailService(provider=provider)

            result = service.ingest_cloudflare_inbound(
                {
                    "email": "push@cf-mail.example.com",
                    "address_id": 77,
                    "provider_jwt": "jwt-77",
                    "message": {
                        "id": 501,
                        "from_address": "noreply@example.com",
                        "subject": "Your code is 778899",
                        "content": "Verification code: 778899",
                        "created_at": "2026-07-20T00:00:00Z",
                    },
                }
            )
            messages = service.list_messages("PUSH@CF-MAIL.EXAMPLE.COM", sync_remote=True)
            stored = temp_emails_repo.get_temp_email_by_address("push@cf-mail.example.com")

        self.assertTrue(result["visible_in_ui"])
        self.assertEqual(result["message_id"], "cf_501")
        self.assertEqual(stored["meta_json"]["provider_jwt"], "jwt-77")
        self.assertEqual(messages[0]["subject"], "Your code is 778899")
        self.assertEqual(provider.list_calls, 0)

    def test_cloudflare_inbound_push_preserves_hidden_task_mailbox(self):
        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services.temp_mail_service import TempMailService

            settings_repo.set_setting("temp_mail_provider", "cloudflare_temp_mail")
            settings_repo.set_setting(
                "cf_worker_domains",
                '[{"name":"cf-mail.example.com","enabled":true}]',
            )
            temp_emails_repo.create_temp_email(
                email_addr="task@cf-mail.example.com",
                mailbox_type="task",
                visible_in_ui=False,
                source="custom_domain_temp_mail",
                task_token="tmptask_push",
                consumer_key="consumer-a",
                caller_id="caller-a",
                task_id="task-a",
            )
            service = TempMailService(provider=_FakeCloudflareProvider())

            result = service.ingest_cloudflare_inbound(
                {
                    "email": "task@cf-mail.example.com",
                    "address_id": 88,
                    "provider_jwt": "jwt-88",
                    "message": {"id": 502, "subject": "Task code", "content": "112233"},
                }
            )
            stored = temp_emails_repo.get_temp_email_by_address("task@cf-mail.example.com")

        self.assertFalse(result["visible_in_ui"])
        self.assertEqual(result["mailbox_type"], "task")
        self.assertFalse(stored["visible_in_ui"])
        self.assertEqual(stored["consumer_key"], "consumer-a")

    def test_cloudflare_inbound_push_uses_hidden_message_parent_for_account_backed_mailbox(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.repositories import accounts as accounts_repo
            from outlook_web.repositories import settings as settings_repo
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services import mailbox_resolver
            from outlook_web.services.temp_mail_service import TempMailService

            settings_repo.set_setting("temp_mail_provider", "cloudflare_temp_mail")
            settings_repo.set_setting(
                "cf_worker_domains",
                '[{"name":"cf-mail.example.com","enabled":true}]',
            )
            db = get_db()
            db.execute(
                """
                INSERT INTO accounts (
                    email, password, client_id, refresh_token, account_type, provider,
                    status, pool_status, temp_mail_meta
                ) VALUES (?, '', '', '', 'temp_mail', 'cloudflare_temp_mail', 'active', 'claimed', ?)
                """,
                (
                    "PoolCase@cf-mail.example.com",
                    json.dumps({"provider_name": "cloudflare_temp_mail", "provider_mailbox_id": "77"}),
                ),
            )
            db.commit()
            provider = _FakeCloudflareProvider()
            service = TempMailService(provider=provider)

            result = service.ingest_cloudflare_inbound(
                {
                    "email": "poolcase@cf-mail.example.com",
                    "address_id": 77,
                    "provider_jwt": "jwt-77",
                    "message": {"id": 504, "subject": "Pool code", "content": "445566"},
                }
            )
            account = accounts_repo.get_account_by_email("POOLCASE@CF-MAIL.EXAMPLE.COM")
            resolved = mailbox_resolver.resolve_mailbox("poolcase@cf-mail.example.com")
            messages = service.list_messages(resolved, sync_remote=False)
            duplicate = temp_emails_repo.get_temp_email_by_address("poolcase@cf-mail.example.com")

        self.assertEqual(result["email"], "PoolCase@cf-mail.example.com")
        self.assertFalse(result["visible_in_ui"])
        self.assertIsNotNone(duplicate)
        self.assertFalse(duplicate["visible_in_ui"])
        self.assertEqual(duplicate["source"], "cloudflare_account_temp_mail")
        self.assertEqual(json.loads(account["temp_mail_meta"])["provider_jwt"], "jwt-77")
        self.assertEqual(resolved["kind"], "temp")
        self.assertEqual(messages[0]["subject"], "Pool code")

    def test_account_backed_sync_does_not_take_over_unrelated_temp_mailbox(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.repositories import settings as settings_repo
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services.temp_mail_service import TempMailError, TempMailService

            email_addr = "collision@cf-mail.example.com"
            settings_repo.set_setting("temp_mail_provider", "cloudflare_temp_mail")
            settings_repo.set_setting(
                "cf_worker_domains",
                '[{"name":"cf-mail.example.com","enabled":true}]',
            )
            temp_emails_repo.create_temp_email(
                email_addr=email_addr,
                source="custom_domain_temp_mail",
                provider_name="custom_domain_temp_mail",
                visible_in_ui=True,
            )
            db = get_db()
            db.execute(
                """
                INSERT INTO accounts (
                    email, password, client_id, refresh_token, account_type, provider,
                    status, pool_status, temp_mail_meta
                ) VALUES (?, '', '', '', 'temp_mail', 'cloudflare_temp_mail', 'active', 'claimed', ?)
                """,
                (email_addr, json.dumps({"provider_name": "cloudflare_temp_mail"})),
            )
            db.commit()
            service = TempMailService(provider=_FakeCloudflareProvider())

            with self.assertRaises(TempMailError) as ctx:
                service.ingest_cloudflare_inbound(
                    {
                        "email": email_addr,
                        "address_id": 88,
                        "provider_jwt": "jwt-88",
                        "message": {"id": 505, "subject": "Must not persist", "content": "000000"},
                    }
                )
            stored = temp_emails_repo.get_temp_email_by_address(email_addr)
            messages = temp_emails_repo.get_temp_email_messages(email_addr)

        self.assertEqual(ctx.exception.code, "TEMP_EMAIL_ACCOUNT_CONFLICT")
        self.assertTrue(stored["visible_in_ui"])
        self.assertEqual(stored["source"], "custom_domain_temp_mail")
        self.assertEqual(stored["provider_name"], "custom_domain_temp_mail")
        self.assertEqual(messages, [])

    def test_orphan_account_backed_parent_is_not_readable_through_temp_service(self):
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services.temp_mail_service import TempMailError, TempMailService

            email_addr = "orphan@cf-mail.example.com"
            temp_emails_repo.create_temp_email(
                email_addr=email_addr,
                mailbox_type="user",
                visible_in_ui=False,
                source="cloudflare_account_temp_mail",
                provider_name="cloudflare_temp_mail",
            )
            service = TempMailService(provider=_FakeCloudflareProvider())

            with self.assertRaises(TempMailError) as ctx:
                service.list_messages(email_addr, sync_remote=False)

        self.assertEqual(ctx.exception.code, "TEMP_EMAIL_NOT_FOUND")

    def test_account_backed_mailbox_missing_credentials_discovers_once_and_keeps_messages_readable(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.repositories import accounts as accounts_repo
            from outlook_web.repositories import settings as settings_repo
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services import mailbox_resolver
            from outlook_web.services.temp_mail_service import TempMailService

            settings_repo.set_setting("temp_mail_provider", "cloudflare_temp_mail")
            settings_repo.set_setting(
                "cf_worker_domains",
                '[{"name":"cf-mail.example.com","enabled":true}]',
            )
            db = get_db()
            db.execute(
                """
                INSERT INTO accounts (
                    email, password, client_id, refresh_token, account_type, provider,
                    status, pool_status, temp_mail_meta
                ) VALUES (?, '', '', '', 'temp_mail', 'cloudflare_temp_mail', 'active', 'claimed', ?)
                """,
                (
                    "LazyPool@cf-mail.example.com",
                    json.dumps({"provider_name": "cloudflare_temp_mail"}),
                ),
            )
            db.commit()
            provider = _FakeCloudflareProvider()
            provider.discovered = {
                "success": True,
                "email": "LazyPool@cf-mail.example.com",
                "provider_name": "cloudflare_temp_mail",
                "meta": {
                    "provider_name": "cloudflare_temp_mail",
                    "provider_mailbox_id": "91",
                    "provider_jwt": "jwt-91",
                },
            }
            provider.list_payload = [{"id": "cf_601", "subject": "Lazy code", "content": "667788"}]
            service = TempMailService(provider=provider)
            resolved = mailbox_resolver.resolve_mailbox("lazypool@cf-mail.example.com")
            messages = service.list_messages(resolved, sync_remote=True)
            account = accounts_repo.get_account_by_email("lazypool@cf-mail.example.com")
            shadow = temp_emails_repo.get_temp_email_by_address("lazypool@cf-mail.example.com")

        self.assertEqual(provider.discover_calls, 1)
        self.assertEqual(provider.list_calls, 1)
        self.assertEqual(messages[0]["subject"], "Lazy code")
        self.assertEqual(json.loads(account["temp_mail_meta"])["provider_jwt"], "jwt-91")
        self.assertFalse(shadow["visible_in_ui"])
        self.assertEqual(shadow["source"], "cloudflare_account_temp_mail")

    def test_account_backed_mailbox_cannot_be_deleted_through_temp_mail_api_service(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.repositories import settings as settings_repo
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services.temp_mail_service import TempMailError, TempMailService

            settings_repo.set_setting("temp_mail_provider", "cloudflare_temp_mail")
            db = get_db()
            db.execute(
                """
                INSERT INTO accounts (
                    email, password, client_id, refresh_token, account_type, provider,
                    status, pool_status, temp_mail_meta
                ) VALUES (?, '', '', '', 'temp_mail', 'cloudflare_temp_mail', 'active', 'claimed', ?)
                """,
                (
                    "ProtectedPool@cf-mail.example.com",
                    json.dumps({"provider_name": "cloudflare_temp_mail", "provider_jwt": "jwt"}),
                ),
            )
            db.commit()
            temp_emails_repo.ensure_account_backed_temp_email(
                "ProtectedPool@cf-mail.example.com",
                {"provider_name": "cloudflare_temp_mail", "provider_jwt": "jwt"},
                provider_name="cloudflare_temp_mail",
            )
            service = TempMailService(provider=_FakeCloudflareProvider())

            with self.assertRaises(TempMailError) as ctx:
                service.delete_mailbox("protectedpool@cf-mail.example.com")
            shadow = temp_emails_repo.get_temp_email_by_address("protectedpool@cf-mail.example.com")

        self.assertEqual(ctx.exception.code, "TEMP_EMAIL_POOL_ACCOUNT_MANAGED")
        self.assertIsNotNone(shadow)

    def test_cloudflare_inbound_push_rejects_unmanaged_domain(self):
        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo
            from outlook_web.services.temp_mail_service import TempMailError, TempMailService

            settings_repo.set_setting("temp_mail_provider", "cloudflare_temp_mail")
            settings_repo.set_setting(
                "cf_worker_domains",
                '[{"name":"cf-mail.example.com","enabled":true}]',
            )
            service = TempMailService(provider=_FakeCloudflareProvider())

            with self.assertRaises(TempMailError) as ctx:
                service.ingest_cloudflare_inbound(
                    {
                        "email": "outside@example.net",
                        "address_id": 99,
                        "provider_jwt": "jwt-99",
                        "message": {"id": 503},
                    }
                )

        self.assertEqual(ctx.exception.code, "TEMP_EMAIL_NOT_MANAGED")

    def test_cloudflare_list_fills_missing_jwt_and_coalesces_duplicate_sync(self):
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services.temp_mail_service import TempMailService

            provider = _FakeCloudflareProvider()
            provider.discovered = {
                "success": True,
                "email": "codes@cf-mail.example.com",
                "provider_name": "cloudflare_temp_mail",
                "meta": {
                    "provider_name": "cloudflare_temp_mail",
                    "provider_mailbox_id": "55",
                    "provider_jwt": "jwt-55",
                },
            }
            provider.list_payload = [
                {
                    "id": "cf_1",
                    "from_address": "noreply@example.com",
                    "subject": "Code",
                    "content": "778899",
                    "timestamp": 1711111111,
                }
            ]
            temp_emails_repo.create_temp_email(
                email_addr="codes@cf-mail.example.com",
                source="custom_domain_temp_mail",
                provider_name="cloudflare_temp_mail",
                meta={"provider_name": "cloudflare_temp_mail", "provider_mailbox_id": "55"},
            )
            service = TempMailService(provider=provider)

            first = service.list_messages("CODES@CF-MAIL.EXAMPLE.COM", sync_remote=True)
            second = service.list_messages("codes@cf-mail.example.com", sync_remote=True)

        self.assertEqual(first[0]["id"], "cf_1")
        self.assertEqual(second[0]["id"], "cf_1")
        self.assertEqual(provider.discover_calls, 1)
        self.assertEqual(provider.list_calls, 1)

    def test_apply_and_finish_task_mailbox_records_task_fields(self):
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services.temp_mail_service import TempMailService

            provider = _FakeTempMailProvider()
            service = TempMailService(provider=provider)

            mailbox = service.apply_task_mailbox(
                consumer_key="key:task-owner",
                caller_id="worker-1",
                task_id="job-001",
                prefix="runner",
                domain="temp.service.test",
            )
            saved = temp_emails_repo.get_temp_email_by_task_token(mailbox["task_token"])
            finished = service.finish_task_mailbox(mailbox["task_token"])

        self.assertEqual(mailbox["email"], "runner@temp.service.test")
        self.assertFalse(mailbox["visible_in_ui"])
        self.assertEqual(saved["mailbox_type"], "task")
        self.assertEqual(saved["consumer_key"], "key:task-owner")
        self.assertEqual(saved["caller_id"], "worker-1")
        self.assertEqual(saved["task_id"], "job-001")
        self.assertEqual(finished["status"], "finished")

    def test_extract_verification_returns_shared_extractor_fields(self):
        with self.app.app_context():
            from outlook_web.services.temp_mail_service import TempMailService

            provider = _FakeTempMailProvider()
            provider.list_payload = [
                {
                    "id": "msg-1",
                    "from_address": "noreply@example.com",
                    "subject": "Your verification code",
                    "content": "Code: 654321",
                    "timestamp": 1711111111,
                }
            ]
            provider.detail_payload["msg-1"] = {
                "id": "msg-1",
                "from_address": "noreply@example.com",
                "subject": "Your verification code",
                "content": "Use verification code 654321 to continue.",
                "html_content": "",
                "timestamp": 1711111111,
            }
            service = TempMailService(provider=provider)
            service.generate_user_mailbox(prefix="verify", domain="mail.service.test")

            result = service.extract_verification("verify@mail.service.test")

        self.assertEqual(result["verification_code"], "654321")
        self.assertEqual(result["matched_email_id"], "msg-1")
        self.assertIn("formatted", result)

    def test_list_messages_does_not_mask_upstream_failure_as_cached_result(self):
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services.temp_mail_provider_custom import TempMailProviderReadError
            from outlook_web.services.temp_mail_service import TempMailError, TempMailService

            provider = _FakeTempMailProvider()
            provider.list_exception = TempMailProviderReadError(
                "UPSTREAM_TIMEOUT",
                "API 请求超时",
                data={"bridge_error_type": "TIMEOUT_ERROR"},
            )
            service = TempMailService(provider=provider)
            service.generate_user_mailbox(prefix="cached", domain="mail.service.test")
            temp_emails_repo.save_temp_email_messages(
                "cached@mail.service.test",
                [
                    {
                        "id": "msg-cached-1",
                        "from_address": "sender@example.com",
                        "subject": "Cached",
                        "content": "stale",
                        "timestamp": 1711111199,
                    }
                ],
            )

            with self.assertRaises(TempMailError) as ctx:
                service.list_messages("cached@mail.service.test", sync_remote=True)

        self.assertEqual(ctx.exception.code, "TEMP_EMAIL_UPSTREAM_READ_FAILED")
        self.assertEqual(ctx.exception.status, 502)
        self.assertEqual(ctx.exception.data["operation"], "list_messages")
        self.assertEqual(ctx.exception.data["provider_error_code"], "UPSTREAM_TIMEOUT")

    def test_get_message_detail_does_not_map_upstream_failure_to_not_found(self):
        with self.app.app_context():
            from outlook_web.services.temp_mail_provider_custom import TempMailProviderReadError
            from outlook_web.services.temp_mail_service import TempMailError, TempMailService

            provider = _FakeTempMailProvider()
            provider.detail_exception = TempMailProviderReadError(
                "UPSTREAM_SERVER_ERROR",
                "临时邮箱服务暂时不可用",
                data={"bridge_error_type": "SERVER_ERROR"},
            )
            service = TempMailService(provider=provider)
            service.generate_user_mailbox(prefix="detailfail", domain="mail.service.test")

            with self.assertRaises(TempMailError) as ctx:
                service.get_message_detail("detailfail@mail.service.test", "msg-missing", refresh_if_missing=True)

        self.assertEqual(ctx.exception.code, "TEMP_EMAIL_UPSTREAM_READ_FAILED")
        self.assertEqual(ctx.exception.status, 502)
        self.assertEqual(ctx.exception.data["operation"], "get_message_detail")
        self.assertEqual(ctx.exception.data["message_id"], "msg-missing")

    def test_refresh_message_detail_surfaces_upstream_failure(self):
        with self.app.app_context():
            from outlook_web.services.temp_mail_provider_custom import TempMailProviderReadError
            from outlook_web.services.temp_mail_service import TempMailError, TempMailService

            provider = _FakeTempMailProvider()
            provider.detail_exception = TempMailProviderReadError(
                "UPSTREAM_TIMEOUT",
                "API 请求超时",
                data={"bridge_error_type": "TIMEOUT_ERROR"},
            )
            service = TempMailService(provider=provider)
            service.generate_user_mailbox(prefix="refreshfail", domain="mail.service.test")

            with self.assertRaises(TempMailError) as ctx:
                service.refresh_message_detail("refreshfail@mail.service.test", "msg-1")

        self.assertEqual(ctx.exception.code, "TEMP_EMAIL_UPSTREAM_READ_FAILED")
        self.assertEqual(ctx.exception.status, 502)
        self.assertEqual(ctx.exception.data["operation"], "refresh_message_detail")

    def test_delete_message_keeps_local_cache_when_provider_delete_fails(self):
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services.temp_mail_service import TempMailError, TempMailService

            provider = _FakeTempMailProvider()
            provider.delete_result = False
            service = TempMailService(provider=provider)
            service.generate_user_mailbox(prefix="deletecase", domain="mail.service.test")
            temp_emails_repo.save_temp_email_messages(
                "deletecase@mail.service.test",
                [
                    {
                        "id": "msg-delete-1",
                        "from_address": "sender@example.com",
                        "subject": "Delete me",
                        "content": "body",
                        "timestamp": 1711111112,
                    }
                ],
            )

            with self.assertRaises(TempMailError) as ctx:
                service.delete_message("deletecase@mail.service.test", "msg-delete-1")

            cached = temp_emails_repo.get_temp_email_message_by_id(
                "msg-delete-1",
                email_addr="deletecase@mail.service.test",
            )

        self.assertEqual(ctx.exception.code, "TEMP_EMAIL_MESSAGE_DELETE_FAILED")
        self.assertIsNotNone(cached)

    def test_clear_messages_keeps_local_cache_when_provider_clear_fails(self):
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services.temp_mail_service import TempMailError, TempMailService

            provider = _FakeTempMailProvider()
            provider.clear_result = False
            service = TempMailService(provider=provider)
            service.generate_user_mailbox(prefix="clearcase", domain="mail.service.test")
            temp_emails_repo.save_temp_email_messages(
                "clearcase@mail.service.test",
                [
                    {
                        "id": "msg-clear-1",
                        "from_address": "sender@example.com",
                        "subject": "Keep me",
                        "content": "body",
                        "timestamp": 1711111113,
                    }
                ],
            )

            with self.assertRaises(TempMailError) as ctx:
                service.clear_messages("clearcase@mail.service.test")

            cached = temp_emails_repo.get_temp_email_messages("clearcase@mail.service.test")

        self.assertEqual(ctx.exception.code, "TEMP_EMAIL_MESSAGES_CLEAR_FAILED")
        self.assertEqual(len(cached), 1)
