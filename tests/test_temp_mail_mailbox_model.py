from __future__ import annotations

import unittest

from tests._import_app import clear_login_attempts, import_web_app_module


class TempMailMailboxModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
            from outlook_web.db import get_db

            db = get_db()
            db.execute("DELETE FROM temp_email_messages WHERE email_address LIKE '%@mailbox-model.test'")
            db.execute("DELETE FROM temp_emails WHERE email LIKE '%@mailbox-model.test'")
            db.commit()

    def test_repo_returns_record_descriptor_and_public_views(self):
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            created = temp_emails_repo.create_temp_email(
                email_addr="demo@mailbox-model.test",
                mailbox_type="user",
                visible_in_ui=True,
                source="custom_domain_temp_mail",
                meta={
                    "provider_name": "custom_domain_temp_mail",
                    "provider_cursor": "cursor-1",
                    "provider_capabilities": {
                        "create_mailbox": True,
                        "list_messages": False,
                        "get_message_detail": False,
                        "delete_mailbox": False,
                        "delete_message": True,
                        "clear_messages": True,
                    },
                },
            )
            self.assertTrue(created)

            record = temp_emails_repo.get_temp_email_by_address("demo@mailbox-model.test")
            descriptor = temp_emails_repo.get_temp_email_by_address("demo@mailbox-model.test", view="descriptor")
            public = temp_emails_repo.get_temp_email_by_address("demo@mailbox-model.test", view="public")

        self.assertEqual(record["provider_name"], "custom_domain_temp_mail")
        self.assertEqual(record["meta_json"]["provider_cursor"], "cursor-1")
        self.assertTrue(record["visible_in_ui"])

        self.assertEqual(descriptor["kind"], "temp")
        self.assertEqual(descriptor["email"], "demo@mailbox-model.test")
        self.assertEqual(descriptor["provider_name"], "custom_domain_temp_mail")
        self.assertEqual(descriptor["mailbox_type"], "user")
        self.assertEqual(descriptor["meta"]["provider_cursor"], "cursor-1")

        self.assertEqual(public["email"], "demo@mailbox-model.test")
        self.assertEqual(public["mailbox_type"], "user")
        self.assertTrue(public["visible_in_ui"])
        expected_capabilities = {
            "create_mailbox": True,
            "list_messages": False,
            "get_message_detail": False,
            "delete_mailbox": False,
            "delete_message": True,
            "clear_messages": True,
        }
        for key, value in expected_capabilities.items():
            self.assertEqual(public["provider_capabilities"].get(key), value)
        # fork 保留了发送/已发送文件夹能力键，不能因上游基础契约而丢失。
        self.assertIn("send_message", public["provider_capabilities"])
        self.assertIn("list_sent_messages", public["provider_capabilities"])
        self.assertNotIn("meta", public)

    def test_legacy_and_task_mailboxes_share_unified_descriptor_shape(self):
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            temp_emails_repo.create_temp_email(
                email_addr="legacy@mailbox-model.test",
                mailbox_type="user",
                visible_in_ui=True,
                source="legacy_gptmail",
            )
            temp_emails_repo.create_temp_email(
                email_addr="task@mailbox-model.test",
                mailbox_type="task",
                visible_in_ui=False,
                source="custom_domain_temp_mail",
                task_token="tmptask_model",
                consumer_key="consumer:model",
                caller_id="worker-model",
                task_id="job-model",
                meta={"provider_cursor": "task-cursor"},
            )

            legacy = temp_emails_repo.get_temp_email_by_address("legacy@mailbox-model.test", view="descriptor")
            task = temp_emails_repo.get_temp_email_by_address("task@mailbox-model.test", view="descriptor")

        self.assertEqual(legacy["provider_name"], "legacy_bridge")
        self.assertEqual(legacy["meta"]["provider_debug"]["bridge"], "gptmail")
        self.assertEqual(task["mailbox_type"], "task")
        self.assertFalse(task["visible_in_ui"])
        self.assertEqual(task["task_token"], "tmptask_model")
        self.assertEqual(task["consumer_key"], "consumer:model")
        self.assertEqual(task["meta"]["provider_cursor"], "task-cursor")
