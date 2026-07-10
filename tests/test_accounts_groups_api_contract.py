"""账号/分组 API 契约（P2 前端迁移基线）。"""

from __future__ import annotations

import secrets
import unittest

from tests._import_app import clear_login_attempts, import_web_app_module


class TestAccountsGroupsApiContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
        self.client = self.app.test_client()
        resp = self.client.post("/login", json={"password": "testpass123"})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))

    def _seed(self):
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            name = f"g_{secrets.token_hex(3)}"
            email = f"a_{secrets.token_hex(3)}@example.com"
            db.execute(
                "INSERT INTO groups (name, color, is_system) VALUES (?, '#123456', 0)",
                (name,),
            )
            gid = db.execute("SELECT id FROM groups WHERE name = ?", (name,)).fetchone()["id"]
            db.execute(
                """
                INSERT INTO accounts
                (email, client_id, refresh_token, status, group_id, provider, account_type)
                VALUES (?, 'cid', 'rt', 'active', ?, 'outlook', 'outlook')
                """,
                (email, gid),
            )
            db.commit()
            return int(gid), email

    def test_groups_list_shape(self):
        resp = self.client.get("/api/groups")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIsInstance(data.get("groups"), list)
        if data["groups"]:
            g = data["groups"][0]
            for key in ("id", "name", "account_count"):
                self.assertIn(key, g)

    def test_create_and_delete_group(self):
        name = f"new_{secrets.token_hex(3)}"
        create = self.client.post(
            "/api/groups",
            json={"name": name, "color": "#B85C38", "description": "p2"},
        )
        self.assertEqual(create.status_code, 200, create.get_data(as_text=True))
        body = create.get_json()
        self.assertTrue(body.get("success"))
        group_id = body.get("group_id")
        self.assertTrue(group_id)

        # 对抗：重名应失败（业务错误可能是 400 或 success=false）
        dup = self.client.post("/api/groups", json={"name": name})
        self.assertIn(dup.status_code, (200, 400), dup.get_data(as_text=True))
        dup_body = dup.get_json() or {}
        self.assertFalse(bool(dup_body.get("success") and dup_body.get("group_id")))

        delete = self.client.delete(f"/api/groups/{group_id}")
        self.assertEqual(delete.status_code, 200, delete.get_data(as_text=True))
        self.assertTrue((delete.get_json() or {}).get("success"))

    def test_accounts_list_pagination_and_group_filter(self):
        gid, email = self._seed()
        resp = self.client.get("/api/accounts", query_string={"page": 1, "page_size": 20})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("pagination", data)
        self.assertIn("accounts", data)
        emails = [a.get("email") for a in data["accounts"]]
        self.assertIn(email, emails)

        filtered = self.client.get(
            "/api/accounts",
            query_string={"group_id": gid, "page": 1, "page_size": 20},
        )
        self.assertEqual(filtered.status_code, 200)
        fdata = filtered.get_json()
        self.assertTrue(all(a.get("group_id") == gid for a in fdata.get("accounts") or []))

    def test_delete_account(self):
        _gid, email = self._seed()
        listed = self.client.get("/api/accounts", query_string={"search": email})
        self.assertEqual(listed.status_code, 200)
        accounts = (listed.get_json() or {}).get("accounts") or []
        self.assertTrue(accounts)
        account_id = accounts[0]["id"]
        deleted = self.client.delete(f"/api/accounts/{account_id}")
        self.assertEqual(deleted.status_code, 200, deleted.get_data(as_text=True))
        self.assertTrue((deleted.get_json() or {}).get("success"))


if __name__ == "__main__":
    unittest.main()
