import unittest
import uuid
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class MultiMailboxSupportTests(unittest.TestCase):
    """
    对齐：PRD-00005 / FD-00005 / TDD-00005 / TEST-00005
    目标：验证多邮箱（Outlook + IMAP provider）核心能力与回归门禁。
    """

    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()

    def _login(self, client, password: str = "testpass123"):
        resp = client.post("/login", json={"password": password})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("success"), True)

    def _default_group_id(self) -> int:
        conn = self.module.create_sqlite_connection()
        try:
            row = conn.execute("SELECT id FROM groups WHERE name = '默认分组' LIMIT 1").fetchone()
            return int(row["id"]) if row else 1
        finally:
            conn.close()

    def test_db_schema_v3_has_multi_mailbox_columns(self):
        conn = self.module.create_sqlite_connection()
        try:
            cols = conn.execute("PRAGMA table_info(accounts)").fetchall()
            names = {c[1] for c in cols}  # (cid, name, type, notnull, dflt_value, pk)
        finally:
            conn.close()

        self.assertIn("account_type", names)
        self.assertIn("provider", names)
        self.assertIn("imap_host", names)
        self.assertIn("imap_port", names)
        self.assertIn("imap_password", names)

    def test_providers_api_returns_fixed_order(self):
        client = self.app.test_client()
        self._login(client)

        resp = client.get("/api/providers")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("success"), True)

        providers = data.get("providers") or []
        # PRD-00006 / FD-00006：providers 列表新增 "auto"（智能识别混合导入）
        self.assertEqual(len(providers), 10)
        self.assertEqual(providers[0].get("key"), "auto")
        self.assertEqual(providers[1].get("key"), "outlook")
        self.assertEqual(providers[-1].get("key"), "custom")

        keys = [p.get("key") for p in providers]
        self.assertIn("auto", keys)
        self.assertIn("qq", keys)
        self.assertIn("163", keys)
        self.assertIn("icloud", keys)

    def test_provider_folder_candidates_contains_utf7_for_qq_junk(self):
        from outlook_web.services.providers import get_imap_folder_candidates

        candidates = get_imap_folder_candidates("qq", "junkemail")
        self.assertIn("&V4NXPpCuTvY-", candidates)

        default_candidates = get_imap_folder_candidates("unknown", "inbox")
        self.assertIn("INBOX", default_candidates)

    def test_import_imap_qq_stores_encrypted_password_and_imap_fields(self):
        client = self.app.test_client()
        self._login(client)

        unique = uuid.uuid4().hex
        email_addr = f"qq_{unique}@qq.com"
        imap_pwd = f"auth_{unique}"

        resp = client.post(
            "/api/accounts",
            json={
                "provider": "qq",
                "account_string": f"{email_addr}----{imap_pwd}",
                "group_id": self._default_group_id(),
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("success"), True)

        conn = self.module.create_sqlite_connection()
        try:
            row = conn.execute(
                """
                SELECT account_type, provider, imap_host, imap_port, imap_password, client_id, refresh_token
                FROM accounts
                WHERE email = ?
                LIMIT 1
                """,
                (email_addr,),
            ).fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row["account_type"], "imap")
        self.assertEqual(row["provider"], "qq")
        self.assertEqual(row["imap_host"], "imap.qq.com")
        self.assertEqual(int(row["imap_port"]), 993)
        self.assertEqual(row["client_id"], "")
        self.assertEqual(row["refresh_token"], "")

        stored_imap_pwd = row["imap_password"]
        self.assertTrue(stored_imap_pwd)
        self.assertNotEqual(stored_imap_pwd, imap_pwd)
        self.assertTrue(stored_imap_pwd.startswith("enc:"))

    def test_emails_api_routes_to_imap_generic_by_account_type(self):
        client = self.app.test_client()
        self._login(client)

        unique = uuid.uuid4().hex
        email_addr = f"imap_{unique}@example.com"

        encrypted_pwd = self.module.encrypt_data("pw_" + unique)

        conn = self.module.create_sqlite_connection()
        try:
            conn.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, account_type, provider, imap_host, imap_port, imap_password, group_id, remark, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email_addr,
                    "",
                    "",
                    "",
                    "imap",
                    "qq",
                    "imap.qq.com",
                    993,
                    encrypted_pwd,
                    self._default_group_id(),
                    "",
                    "active",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        fake_result = {
            "success": True,
            "emails": [
                {
                    "id": "1",
                    "subject": "s",
                    "from": "f",
                    "date": "d",
                    "is_read": True,
                    "has_attachments": False,
                    "body_preview": "p",
                }
            ],
            "method": "IMAP (Generic)",
            "has_more": False,
        }

        with patch(
            "outlook_web.controllers.emails.get_emails_imap_generic",
            return_value=fake_result,
        ):
            resp = client.get(f"/api/emails/{email_addr}?folder=inbox&skip=0&top=20")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), fake_result)

        delete_resp = client.post("/api/emails/delete", json={"email": email_addr, "ids": ["1"]})
        self.assertEqual(delete_resp.status_code, 400)
        delete_data = delete_resp.get_json()
        self.assertEqual(delete_data.get("success"), False)
        err = delete_data.get("error") or {}
        self.assertIsInstance(err, dict)
        self.assertIn("不支持远程删除", err.get("message", ""))

    def test_imap_generic_connect_error_does_not_leak_password(self):
        from outlook_web.services.imap_generic import get_emails_imap_generic

        secret_pwd = "top-secret-imap-password"
        result = get_emails_imap_generic(
            email_addr="u@example.com",
            imap_password=secret_pwd,
            imap_host="",  # 触发 ValueError -> connect failed
            imap_port=993,
            folder="inbox",
            provider="qq",
            skip=0,
            top=1,
        )
        self.assertEqual(result.get("success"), False)
        self.assertEqual(result.get("error_code"), "IMAP_CONNECT_FAILED")

        # 确保返回内容不包含明文密码
        self.assertNotIn(secret_pwd, str(result))

    def test_scheduler_skips_imap_accounts(self):
        from outlook_web.services.scheduler import scheduled_refresh_task

        unique = uuid.uuid4().hex
        outlook_email = f"out_{unique}@outlook.com"
        imap_email = f"imap_{unique}@example.com"
        legacy_cf_email = f"cf_{unique}@example.com"

        conn = self.module.create_sqlite_connection()
        try:
            conn.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, account_type, provider, group_id, remark, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outlook_email,
                    "",
                    "client_" + unique,
                    self.module.encrypt_data("rt_" + unique),
                    "outlook",
                    "outlook",
                    self._default_group_id(),
                    "",
                    "active",
                ),
            )
            conn.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, account_type, provider, group_id, remark, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    legacy_cf_email,
                    "",
                    "cf_client_" + unique,
                    self.module.encrypt_data("cf_rt_" + unique),
                    "outlook",
                    "cloudflare_temp_mail",
                    self._default_group_id(),
                    "",
                    "active",
                ),
            )
            conn.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, account_type, provider, imap_host, imap_port, imap_password, group_id, remark, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    imap_email,
                    "",
                    "",
                    "",
                    "imap",
                    "qq",
                    "imap.qq.com",
                    993,
                    self.module.encrypt_data("pw_" + unique),
                    self._default_group_id(),
                    "",
                    "active",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        called = []

        def fake_test_refresh_token(client_id, refresh_token, proxy_url):
            called.append((client_id, refresh_token, proxy_url))
            return True, "ok", "rt_new_" + unique

        with (
            patch("outlook_web.services.scheduler.time.sleep", return_value=None),
            patch(
                "outlook_web.services.scheduler.acquire_distributed_lock",
                return_value=(True, {}),
            ),
            patch("outlook_web.services.scheduler.release_distributed_lock", return_value=None),
        ):
            scheduled_refresh_task(self.app, fake_test_refresh_token)

        self.assertGreaterEqual(len(called), 1)
        self.assertTrue(any(cid == "client_" + unique for cid, _, _ in called))
        self.assertFalse(any(cid == "" for cid, _, _ in called))  # 不应包含 IMAP 账号（空 client_id）
        self.assertFalse(any(cid == "cf_client_" + unique for cid, _, _ in called))

        # 成功刷新时应写回滚动更新后的 refresh_token（加密存储）
        conn = self.module.create_sqlite_connection()
        try:
            row = conn.execute(
                "SELECT refresh_token, last_refresh_at FROM accounts WHERE email = ?", (outlook_email,)
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(self.module.decrypt_data(row["refresh_token"]), "rt_new_" + unique)
            self.assertTrue(row["last_refresh_at"])
        finally:
            conn.close()

    def test_export_format_outlook_first_then_imap_grouped(self):
        client = self.app.test_client()
        self._login(client)

        unique = uuid.uuid4().hex
        outlook_email = f"exp_out_{unique}@outlook.com"
        imap_email = f"exp_qq_{unique}@qq.com"

        conn = self.module.create_sqlite_connection()
        try:
            conn.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, account_type, provider, group_id, remark, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outlook_email,
                    self.module.encrypt_data("p_" + unique),
                    "cid_" + unique,
                    self.module.encrypt_data("rt_" + unique),
                    "outlook",
                    "outlook",
                    self._default_group_id(),
                    "",
                    "active",
                ),
            )
            conn.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, account_type, provider, imap_host, imap_port, imap_password, group_id, remark, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    imap_email,
                    "",
                    "",
                    "",
                    "imap",
                    "qq",
                    "imap.qq.com",
                    993,
                    self.module.encrypt_data("imap_pw_" + unique),
                    self._default_group_id(),
                    "",
                    "active",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        verify = client.post("/api/export/verify", json={"password": "testpass123"})
        self.assertEqual(verify.status_code, 200)
        verify_data = verify.get_json()
        self.assertEqual(verify_data.get("success"), True)
        token = verify_data.get("verify_token")
        self.assertTrue(token)

        export_resp = client.get("/api/accounts/export", headers={"X-Export-Token": token})
        self.assertEqual(export_resp.status_code, 200)
        content = export_resp.get_data(as_text=True)

        outlook_pos = content.find("# === Outlook 账号 ===")
        imap_pos = content.find("# === IMAP 账号（QQ 邮箱）===")
        self.assertNotEqual(outlook_pos, -1)
        self.assertNotEqual(imap_pos, -1)
        self.assertLess(outlook_pos, imap_pos)

        self.assertIn(outlook_email, content)
        self.assertIn(imap_email, content)
        self.assertIn("----qq", content)  # IMAP 行格式：email----imap_password----provider
