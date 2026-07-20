from __future__ import annotations

import unittest

from tests._import_app import clear_login_attempts, import_web_app_module


class _MailboxFirstProvider:
    provider_name = "custom_domain_temp_mail"

    def __init__(self):
        self.create_calls = []
        self.list_calls = []
        self.delete_mailbox_calls = []
        self.send_calls = []
        self.sent_list_calls = []
        self.deleted_sent_ids = []
        self.clear_sent_calls = []

    def get_options(self):
        return {
            "domains": [{"name": "service-platform.test", "enabled": True, "is_default": True}],
            "prefix_rules": {"min_length": 1, "max_length": 32, "pattern": r"^[a-z0-9][a-z0-9._-]*$"},
            "provider": "custom_domain_temp_mail",
            "provider_name": "custom_domain_temp_mail",
            "provider_label": "temp_mail",
        }

    def create_mailbox(self, *, prefix=None, domain=None):
        email_addr = f"{prefix or 'auto'}@{domain or 'service-platform.test'}"
        self.create_calls.append({"prefix": prefix, "domain": domain, "email": email_addr})
        return {
            "success": True,
            "email": email_addr,
            "meta": {
                "provider_name": "custom_domain_temp_mail",
                "provider_cursor": f"cursor:{email_addr}",
                "provider_capabilities": {
                    "delete_mailbox": False,
                    "delete_message": True,
                    "clear_messages": True,
                },
            },
        }

    def delete_mailbox(self, mailbox):
        self.delete_mailbox_calls.append(mailbox)
        return True

    def list_messages(self, mailbox):
        self.list_calls.append(mailbox)
        return [
            {
                "id": "msg-1",
                "from_address": "noreply@example.com",
                "subject": "Your verification code",
                "content": "Code: 112233",
                "timestamp": 1711111111,
            }
        ]

    def get_message_detail(self, mailbox, message_id):
        return {
            "id": message_id,
            "from_address": "noreply@example.com",
            "subject": "Your verification code",
            "content": "Code: 112233",
            "html_content": "",
            "timestamp": 1711111111,
        }

    def delete_message(self, mailbox, message_id):
        return True

    def clear_messages(self, mailbox):
        return True

    def get_capabilities(self, mailbox=None):
        return {
            "send_message": True,
            "list_sent_messages": True,
            "delete_sent_message": True,
            "clear_sent_messages": True,
        }

    def send_message(self, mailbox, **payload):
        self.send_calls.append((mailbox, payload))
        return {"success": True, "status": "ok"}

    def list_sent_messages(self, mailbox, *, limit=100, offset=0):
        self.sent_list_calls.append((mailbox, limit, offset))
        return {
            "items": [
                {
                    "id": "sent-1",
                    "from": mailbox["email"],
                    "to": "target@example.com",
                    "subject": "Hello",
                    "content": "World",
                    "body_type": "text",
                }
            ],
            "count": 1,
        }

    def delete_sent_message(self, mailbox, message_id):
        self.deleted_sent_ids.append((mailbox["email"], message_id))
        return True

    def clear_sent_messages(self, mailbox):
        self.clear_sent_calls.append(mailbox["email"])
        return True


class TempMailServicePlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
            from outlook_web.db import get_db

            db = get_db()
            db.execute("DELETE FROM temp_email_messages WHERE email_address LIKE '%@service-platform.test'")
            db.execute("DELETE FROM temp_emails WHERE email LIKE '%@service-platform.test'")
            db.commit()

    def test_service_uses_factory_and_persists_provider_meta(self):
        provider = _MailboxFirstProvider()
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services.temp_mail_service import TempMailService

            service = TempMailService(provider_factory=lambda provider_name=None: provider)
            mailbox = service.generate_user_mailbox(prefix="demo", domain="service-platform.test")
            record = temp_emails_repo.get_temp_email_by_address("demo@service-platform.test")

        self.assertEqual(mailbox["email"], "demo@service-platform.test")
        self.assertEqual(provider.create_calls[0]["domain"], "service-platform.test")
        self.assertEqual(record["meta_json"]["provider_cursor"], "cursor:demo@service-platform.test")
        self.assertEqual(record["provider_name"], "custom_domain_temp_mail")

    def test_service_reads_messages_through_mailbox_descriptor(self):
        provider = _MailboxFirstProvider()
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services.temp_mail_service import TempMailService

            temp_emails_repo.create_temp_email(
                email_addr="reader@service-platform.test",
                mailbox_type="user",
                visible_in_ui=True,
                meta={"provider_name": "custom_domain_temp_mail"},
            )
            service = TempMailService(provider_factory=lambda provider_name=None: provider)
            messages = service.list_messages("reader@service-platform.test", sync_remote=True)

        self.assertEqual(messages[0]["id"], "msg-1")
        self.assertEqual(provider.list_calls[0]["kind"], "temp")
        self.assertEqual(provider.list_calls[0]["provider_name"], "custom_domain_temp_mail")

    def test_delete_mailbox_skips_remote_delete_when_capability_disabled(self):
        provider = _MailboxFirstProvider()
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services.temp_mail_service import TempMailService

            temp_emails_repo.create_temp_email(
                email_addr="delete-local@service-platform.test",
                mailbox_type="user",
                visible_in_ui=True,
                meta={
                    "provider_name": "custom_domain_temp_mail",
                    "provider_capabilities": {
                        "delete_mailbox": False,
                        "delete_message": True,
                        "clear_messages": True,
                    },
                },
            )
            service = TempMailService(provider_factory=lambda provider_name=None: provider)
            service.delete_mailbox("delete-local@service-platform.test")
            record = temp_emails_repo.get_temp_email_by_address("delete-local@service-platform.test")

        self.assertIsNone(record)
        self.assertEqual(provider.delete_mailbox_calls, [])

    def test_service_dispatches_send_and_sent_item_operations(self):
        provider = _MailboxFirstProvider()
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo
            from outlook_web.services.temp_mail_service import TempMailService

            temp_emails_repo.create_temp_email(
                email_addr="sender@service-platform.test",
                mailbox_type="user",
                visible_in_ui=True,
                meta={"provider_name": "custom_domain_temp_mail"},
            )
            service = TempMailService(provider_factory=lambda provider_name=None: provider)
            send_result = service.send_message(
                "sender@service-platform.test",
                to_email="Target <target@example.com>",
                subject=" Hello ",
                content="World",
            )
            sent_result = service.list_sent_messages("sender@service-platform.test", limit=20, offset=0)
            service.delete_sent_message("sender@service-platform.test", "sent-1")
            service.clear_sent_messages("sender@service-platform.test")

        self.assertTrue(send_result["success"])
        self.assertEqual(provider.send_calls[0][1]["to_email"], "target@example.com")
        self.assertEqual(provider.send_calls[0][1]["subject"], "Hello")
        self.assertEqual(sent_result["count"], 1)
        self.assertEqual(provider.sent_list_calls[0][1:], (20, 0))
        self.assertEqual(provider.deleted_sent_ids, [("sender@service-platform.test", "sent-1")])
        self.assertEqual(provider.clear_sent_calls, ["sender@service-platform.test"])
