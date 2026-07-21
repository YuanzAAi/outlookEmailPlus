from __future__ import annotations

from pathlib import Path
import unittest
import uuid

from tests._import_app import clear_login_attempts, import_web_app_module


class PoolAdminTempMailboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
            from outlook_web.db import get_db

            db = get_db()
            db.execute("DELETE FROM temp_email_messages WHERE email_address LIKE '%@pool-admin-temp.test'")
            db.execute("DELETE FROM temp_emails WHERE email LIKE '%@pool-admin-temp.test'")
            db.commit()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = 1

    def _create_temp_mailbox(self, *, source: str = "custom_domain_temp_mail") -> tuple[int, str]:
        email_addr = f"pool-admin-{uuid.uuid4().hex}@pool-admin-temp.test"
        with self.app.app_context():
            from outlook_web.repositories import pool as pool_repo
            from outlook_web.repositories import temp_emails as temp_emails_repo

            created = temp_emails_repo.create_temp_email(
                email_addr=email_addr,
                source=source,
                provider_name="custom_domain_temp_mail",
                visible_in_ui=source != "cloudflare_account_temp_mail",
            )
            self.assertTrue(created)
            record = temp_emails_repo.get_temp_email_by_address(email_addr)
            return pool_repo.account_id_from_temp_id(int(record["id"])), email_addr

    def test_pool_admin_lists_visible_temp_mailbox_and_excludes_hidden_parent(self):
        account_id, email_addr = self._create_temp_mailbox()
        _hidden_id, hidden_email = self._create_temp_mailbox(source="cloudflare_account_temp_mail")

        response = self.client.get("/api/pool-admin/accounts?in_pool=true&search=pool-admin-temp.test")

        self.assertEqual(response.status_code, 200)
        items = response.get_json()["items"]
        by_email = {item["email"]: item for item in items}
        self.assertIn(email_addr, by_email)
        self.assertNotIn(hidden_email, by_email)
        self.assertEqual(by_email[email_addr]["id"], account_id)
        self.assertEqual(by_email[email_addr]["resource_type"], "temp")
        self.assertEqual(by_email[email_addr]["pool_status"], "available")
        self.assertTrue(by_email[email_addr]["in_pool"])

    def test_pool_admin_can_move_temp_mailbox_out_and_back_into_pool(self):
        account_id, email_addr = self._create_temp_mailbox()

        move_out = self.client.post(
            f"/api/pool-admin/accounts/{account_id}/action",
            json={"action": "move_out_of_pool"},
        )
        self.assertEqual(move_out.status_code, 200)
        self.assertEqual(move_out.get_json()["data"]["new_status"], "retired")

        outside = self.client.get(f"/api/pool-admin/accounts?in_pool=false&search={email_addr}")
        self.assertEqual(outside.status_code, 200)
        self.assertEqual(outside.get_json()["items"][0]["email"], email_addr)
        self.assertFalse(outside.get_json()["items"][0]["in_pool"])

        move_in = self.client.post(
            f"/api/pool-admin/accounts/{account_id}/action",
            json={"action": "move_into_pool"},
        )
        self.assertEqual(move_in.status_code, 200)
        self.assertEqual(move_in.get_json()["data"]["new_status"], "available")

    def test_pool_admin_force_releases_claimed_temp_mailbox(self):
        account_id, email_addr = self._create_temp_mailbox()
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            db.execute(
                """
                UPDATE temp_emails
                SET pool_status = 'claimed', claimed_by = 'caller:task',
                    claimed_at = '2026-07-20T10:00:00Z', lease_expires_at = '2026-07-20T10:10:00Z',
                    claim_token = 'claim-token'
                WHERE email = ?
                """,
                (email_addr,),
            )
            db.commit()

        response = self.client.post(
            f"/api/pool-admin/accounts/{account_id}/action",
            json={"action": "force_release"},
        )

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            from outlook_web.db import get_db

            row = get_db().execute(
                "SELECT pool_status, claimed_by, claimed_at, lease_expires_at, claim_token FROM temp_emails WHERE email = ?",
                (email_addr,),
            ).fetchone()
        self.assertEqual(row["pool_status"], "available")
        self.assertIsNone(row["claimed_by"])
        self.assertIsNone(row["claimed_at"])
        self.assertIsNone(row["lease_expires_at"])
        self.assertIsNone(row["claim_token"])

    def test_pool_admin_frontend_uses_explicit_in_pool_flag(self):
        script = (Path(__file__).resolve().parents[1] / "static" / "js" / "features" / "pool_admin.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("typeof item.in_pool === 'boolean'", script)
