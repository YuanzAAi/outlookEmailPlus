import json
import unittest
import uuid
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class RefreshOutlookOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

        from outlook_web.services import graph as graph_service

        cls.graph_service = graph_service

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
        self._deactivate_existing_accounts()

    def _login(self, client, password: str = "testpass123"):
        resp = client.post("/login", json={"password": password})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json().get("success"), True)

    def _default_group_id(self) -> int:
        conn = self.module.create_sqlite_connection()
        try:
            row = conn.execute("SELECT id FROM groups WHERE name = '默认分组' LIMIT 1").fetchone()
            return int(row["id"]) if row else 1
        finally:
            conn.close()

    def _deactivate_existing_accounts(self):
        conn = self.module.create_sqlite_connection()
        try:
            conn.execute("UPDATE accounts SET status = 'inactive' WHERE status = 'active'")
            conn.commit()
        finally:
            conn.close()

    def _insert_outlook_account(self, *, email_addr: str, unique: str) -> int:
        conn = self.module.create_sqlite_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, account_type, provider, group_id, remark, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email_addr,
                    "",
                    f"client_{unique}",
                    self.module.encrypt_data(f"rt_{unique}"),
                    "outlook",
                    "outlook",
                    self._default_group_id(),
                    "",
                    "active",
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def _insert_imap_account(self, *, email_addr: str, unique: str) -> int:
        conn = self.module.create_sqlite_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO accounts (
                    email, password, client_id, refresh_token, account_type, provider,
                    imap_host, imap_port, imap_password, group_id, remark, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email_addr,
                    "",
                    "",
                    self.module.encrypt_data(f"imap_rt_{unique}"),
                    "imap",
                    "qq",
                    "imap.qq.com",
                    993,
                    self.module.encrypt_data(f"imap_pw_{unique}"),
                    self._default_group_id(),
                    "",
                    "active",
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def _insert_legacy_outlook_account(self, *, email_addr: str, unique: str) -> int:
        conn = self.module.create_sqlite_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, account_type, provider, group_id, remark, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email_addr,
                    "",
                    f"legacy_client_{unique}",
                    self.module.encrypt_data(f"legacy_rt_{unique}"),
                    None,
                    "outlook",
                    self._default_group_id(),
                    "",
                    "active",
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def _insert_legacy_cf_account(self, *, email_addr: str, unique: str) -> int:
        conn = self.module.create_sqlite_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, account_type, provider, group_id, remark, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email_addr,
                    "",
                    f"cf_client_{unique}",
                    self.module.encrypt_data(f"cf_rt_{unique}"),
                    "outlook",
                    "cloudflare_temp_mail",
                    self._default_group_id(),
                    "",
                    "active",
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def _get_account_row(self, account_id: int):
        conn = self.module.create_sqlite_connection()
        try:
            return conn.execute(
                "SELECT id, email, refresh_token, last_refresh_at FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        finally:
            conn.close()

    def _get_refresh_logs(self, *, account_id: int, refresh_type: str):
        conn = self.module.create_sqlite_connection()
        try:
            return conn.execute(
                """
                SELECT account_id, account_email, refresh_type, status, error_message
                FROM account_refresh_logs
                WHERE account_id = ? AND refresh_type = ?
                ORDER BY id ASC
                """,
                (account_id, refresh_type),
            ).fetchall()
        finally:
            conn.close()

    def _set_refresh_delay_seconds(self, value: str = "0"):
        conn = self.module.create_sqlite_connection()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                ("refresh_delay_seconds", value),
            )
            conn.commit()
        finally:
            conn.close()

    def _parse_sse_events(self, payload: str):
        events = []
        for line in payload.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
        return events

    def test_manual_single_refresh_rejects_imap_without_graph_call_or_logs(self):
        client = self.app.test_client()
        self._login(client)

        unique = uuid.uuid4().hex
        account_id = self._insert_imap_account(email_addr=f"imap_{unique}@example.com", unique=unique)

        with patch.object(self.graph_service, "test_refresh_token_with_rotation") as mocked_refresh:
            resp = client.post(f"/api/accounts/{account_id}/refresh")

        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data.get("success"), False)
        self.assertEqual((data.get("error") or {}).get("code"), "ACCOUNT_REFRESH_UNSUPPORTED")
        mocked_refresh.assert_not_called()

        row = self._get_account_row(account_id)
        self.assertEqual(self.module.decrypt_data(row["refresh_token"]), f"imap_rt_{unique}")
        self.assertIsNone(row["last_refresh_at"])
        self.assertEqual(len(self._get_refresh_logs(account_id=account_id, refresh_type="manual")), 0)

    def test_manual_single_refresh_rejects_legacy_cf_provider_even_when_type_is_outlook(self):
        client = self.app.test_client()
        self._login(client)

        unique = uuid.uuid4().hex
        account_id = self._insert_legacy_cf_account(
            email_addr=f"legacy_cf_{unique}@example.com",
            unique=unique,
        )

        with patch.object(self.graph_service, "test_refresh_token_with_rotation") as mocked_refresh:
            resp = client.post(f"/api/accounts/{account_id}/refresh")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual((resp.get_json().get("error") or {}).get("code"), "ACCOUNT_REFRESH_UNSUPPORTED")
        mocked_refresh.assert_not_called()
        self.assertEqual(len(self._get_refresh_logs(account_id=account_id, refresh_type="manual")), 0)

    def test_manual_single_refresh_allows_outlook_and_rotates_refresh_token(self):
        client = self.app.test_client()
        self._login(client)

        unique = uuid.uuid4().hex
        account_id = self._insert_outlook_account(email_addr=f"out_{unique}@outlook.com", unique=unique)

        with patch.object(
            self.graph_service,
            "test_refresh_token_with_rotation",
            return_value=(True, None, f"rt_new_{unique}"),
        ) as mocked_refresh:
            resp = client.post(f"/api/accounts/{account_id}/refresh")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json().get("success"), True)
        mocked_refresh.assert_called_once()

        row = self._get_account_row(account_id)
        self.assertEqual(self.module.decrypt_data(row["refresh_token"]), f"rt_new_{unique}")
        self.assertTrue(row["last_refresh_at"])

        logs = self._get_refresh_logs(account_id=account_id, refresh_type="manual")
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["status"], "success")

    def test_manual_single_refresh_allows_legacy_null_account_type(self):
        client = self.app.test_client()
        self._login(client)

        unique = uuid.uuid4().hex
        account_id = self._insert_legacy_outlook_account(email_addr=f"legacy_{unique}@outlook.com", unique=unique)

        with patch.object(
            self.graph_service,
            "test_refresh_token_with_rotation",
            return_value=(True, None, f"legacy_rt_new_{unique}"),
        ) as mocked_refresh:
            resp = client.post(f"/api/accounts/{account_id}/refresh")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json().get("success"), True)
        mocked_refresh.assert_called_once()

        row = self._get_account_row(account_id)
        self.assertEqual(self.module.decrypt_data(row["refresh_token"]), f"legacy_rt_new_{unique}")
        self.assertTrue(row["last_refresh_at"])

    def test_refresh_all_only_processes_outlook_accounts(self):
        client = self.app.test_client()
        self._login(client)
        self._set_refresh_delay_seconds("0")

        unique = uuid.uuid4().hex
        outlook_id = self._insert_outlook_account(email_addr=f"all_out_{unique}@outlook.com", unique=unique)
        imap_id = self._insert_imap_account(email_addr=f"all_imap_{unique}@example.com", unique=unique)
        calls = []

        def fake_refresh(client_id, refresh_token, proxy_url):
            calls.append((client_id, refresh_token, proxy_url))
            return True, None, f"rt_rotated_{unique}"

        with (
            patch.object(
                self.graph_service,
                "test_refresh_token_with_rotation",
                side_effect=fake_refresh,
            ),
            patch(
                "outlook_web.services.refresh.acquire_distributed_lock",
                return_value=(True, {}),
            ),
            patch(
                "outlook_web.services.refresh.release_distributed_lock",
                return_value=None,
            ),
            patch("outlook_web.services.refresh.time.sleep", return_value=None),
        ):
            resp = client.get("/api/accounts/refresh-all")

        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))
        self.assertEqual(events[0].get("type"), "start")
        self.assertEqual(events[0].get("total"), 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], f"client_{unique}")
        self.assertEqual(calls[0][1], f"rt_{unique}")

        outlook_row = self._get_account_row(outlook_id)
        imap_row = self._get_account_row(imap_id)
        self.assertEqual(
            self.module.decrypt_data(outlook_row["refresh_token"]),
            f"rt_rotated_{unique}",
        )
        self.assertEqual(self.module.decrypt_data(imap_row["refresh_token"]), f"imap_rt_{unique}")
        self.assertIsNone(imap_row["last_refresh_at"])

        self.assertEqual(
            len(self._get_refresh_logs(account_id=outlook_id, refresh_type="manual_all")),
            1,
        )
        self.assertEqual(
            len(self._get_refresh_logs(account_id=imap_id, refresh_type="manual_all")),
            0,
        )

    def test_refresh_stats_excludes_account_backed_temp_mail_accounts(self):
        client = self.app.test_client()
        self._login(client)
        unique = uuid.uuid4().hex
        self._insert_outlook_account(email_addr=f"stats_out_{unique}@outlook.com", unique=unique)
        self._insert_imap_account(email_addr=f"stats_imap_{unique}@example.com", unique=unique)
        conn = self.module.create_sqlite_connection()
        try:
            conn.execute(
                """
                INSERT INTO accounts (
                    email, client_id, refresh_token, account_type, provider, status, group_id
                ) VALUES (?, '', '', 'temp_mail', 'cloudflare_temp_mail', 'active', ?)
                """,
                (f"stats_cf_{unique}@example.com", self._default_group_id()),
            )
            conn.commit()
        finally:
            conn.close()

        response = client.get("/api/accounts/refresh-stats")

        self.assertEqual(response.status_code, 200)
        stats = response.get_json()["stats"]
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["success_count"], 2)
        self.assertEqual(stats["failed_count"], 0)

    def test_refresh_all_includes_legacy_null_account_type(self):
        client = self.app.test_client()
        self._login(client)
        self._set_refresh_delay_seconds("0")

        unique = uuid.uuid4().hex
        legacy_id = self._insert_legacy_outlook_account(
            email_addr=f"legacy_all_{unique}@outlook.com",
            unique=unique,
        )
        calls = []

        def fake_refresh(client_id, refresh_token, proxy_url):
            calls.append((client_id, refresh_token, proxy_url))
            return True, None, f"legacy_rotated_{unique}"

        with (
            patch.object(
                self.graph_service,
                "test_refresh_token_with_rotation",
                side_effect=fake_refresh,
            ),
            patch(
                "outlook_web.services.refresh.acquire_distributed_lock",
                return_value=(True, {}),
            ),
            patch(
                "outlook_web.services.refresh.release_distributed_lock",
                return_value=None,
            ),
            patch("outlook_web.services.refresh.time.sleep", return_value=None),
        ):
            resp = client.get("/api/accounts/refresh-all")

        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))
        self.assertEqual(events[0].get("type"), "start")
        self.assertEqual(events[0].get("total"), 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], f"legacy_client_{unique}")
        self.assertEqual(calls[0][1], f"legacy_rt_{unique}")

        row = self._get_account_row(legacy_id)
        self.assertEqual(self.module.decrypt_data(row["refresh_token"]), f"legacy_rotated_{unique}")
        self.assertTrue(row["last_refresh_at"])
        self.assertEqual(
            len(self._get_refresh_logs(account_id=legacy_id, refresh_type="manual_all")),
            1,
        )

    def test_manual_trigger_scheduled_refresh_only_processes_outlook_accounts(self):
        client = self.app.test_client()
        self._login(client)
        self._set_refresh_delay_seconds("0")

        unique = uuid.uuid4().hex
        outlook_id = self._insert_outlook_account(email_addr=f"sch_out_{unique}@outlook.com", unique=unique)
        imap_id = self._insert_imap_account(email_addr=f"sch_imap_{unique}@example.com", unique=unique)
        calls = []

        def fake_refresh(client_id, refresh_token, proxy_url):
            calls.append((client_id, refresh_token, proxy_url))
            return True, None, f"rt_scheduled_{unique}"

        with (
            patch.object(
                self.graph_service,
                "test_refresh_token_with_rotation",
                side_effect=fake_refresh,
            ),
            patch(
                "outlook_web.services.refresh.acquire_distributed_lock",
                return_value=(True, {}),
            ),
            patch(
                "outlook_web.services.refresh.release_distributed_lock",
                return_value=None,
            ),
            patch("outlook_web.services.refresh.time.sleep", return_value=None),
        ):
            resp = client.get("/api/accounts/trigger-scheduled-refresh?force=true")

        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))
        self.assertEqual(events[0].get("type"), "start")
        self.assertEqual(events[0].get("total"), 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], f"client_{unique}")
        self.assertEqual(calls[0][1], f"rt_{unique}")

        outlook_row = self._get_account_row(outlook_id)
        imap_row = self._get_account_row(imap_id)
        self.assertEqual(
            self.module.decrypt_data(outlook_row["refresh_token"]),
            f"rt_scheduled_{unique}",
        )
        self.assertEqual(self.module.decrypt_data(imap_row["refresh_token"]), f"imap_rt_{unique}")
        self.assertIsNone(imap_row["last_refresh_at"])

        self.assertEqual(
            len(self._get_refresh_logs(account_id=outlook_id, refresh_type="scheduled")),
            1,
        )
        self.assertEqual(len(self._get_refresh_logs(account_id=imap_id, refresh_type="scheduled")), 0)

    def test_retry_failed_accounts_only_retries_outlook_accounts(self):
        client = self.app.test_client()
        self._login(client)

        unique = uuid.uuid4().hex
        outlook_id = self._insert_outlook_account(email_addr=f"retry_out_{unique}@outlook.com", unique=unique)
        imap_id = self._insert_imap_account(email_addr=f"retry_imap_{unique}@example.com", unique=unique)

        conn = self.module.create_sqlite_connection()
        try:
            conn.execute(
                """
                INSERT INTO account_refresh_logs (account_id, account_email, refresh_type, status, error_message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    outlook_id,
                    f"retry_out_{unique}@outlook.com",
                    "manual",
                    "failed",
                    "outlook failed",
                ),
            )
            conn.execute(
                """
                INSERT INTO account_refresh_logs (account_id, account_email, refresh_type, status, error_message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    imap_id,
                    f"retry_imap_{unique}@example.com",
                    "manual",
                    "failed",
                    "imap failed",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        calls = []

        def fake_refresh(client_id, refresh_token, proxy_url):
            calls.append((client_id, refresh_token, proxy_url))
            return True, None, f"rt_retry_{unique}"

        with (
            patch.object(
                self.graph_service,
                "test_refresh_token_with_rotation",
                side_effect=fake_refresh,
            ),
            patch(
                "outlook_web.services.refresh.acquire_distributed_lock",
                return_value=(True, {}),
            ),
            patch(
                "outlook_web.services.refresh.release_distributed_lock",
                return_value=None,
            ),
        ):
            resp = client.post("/api/accounts/refresh-failed")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("success"), True)
        self.assertEqual(data.get("total"), 1)
        self.assertEqual(data.get("success_count"), 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], f"client_{unique}")
        self.assertEqual(calls[0][1], f"rt_{unique}")

        outlook_row = self._get_account_row(outlook_id)
        imap_row = self._get_account_row(imap_id)
        self.assertEqual(self.module.decrypt_data(outlook_row["refresh_token"]), f"rt_retry_{unique}")
        self.assertEqual(self.module.decrypt_data(imap_row["refresh_token"]), f"imap_rt_{unique}")
        self.assertIsNone(imap_row["last_refresh_at"])

        self.assertEqual(len(self._get_refresh_logs(account_id=outlook_id, refresh_type="retry")), 1)
        self.assertEqual(len(self._get_refresh_logs(account_id=imap_id, refresh_type="retry")), 0)

    def test_manual_trigger_scheduled_refresh_conflict_returns_actionable_message(self):
        client = self.app.test_client()
        self._login(client)

        unique = uuid.uuid4().hex
        self._insert_outlook_account(email_addr=f"sch_conflict_{unique}@outlook.com", unique=unique)

        with (
            patch.object(self.graph_service, "test_refresh_token_with_rotation") as mocked_refresh,
            patch(
                "outlook_web.services.refresh.acquire_distributed_lock",
                return_value=(
                    False,
                    {
                        "owner_id": "another-task",
                        "acquired_at": 1776393136.5748198,
                        "expires_at": 1776400336.5748198,
                    },
                ),
            ),
        ):
            resp = client.get("/api/accounts/trigger-scheduled-refresh?force=true")

        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))
        self.assertGreaterEqual(len(events), 1)
        error_event = events[-1]
        self.assertEqual(error_event.get("type"), "error")
        error = error_event.get("error") or {}
        self.assertEqual(error.get("code"), "REFRESH_CONFLICT")
        self.assertIn("等待当前任务完成后再重试", error.get("message") or "")
        self.assertIn("Wait for it to finish and retry", error.get("message_en") or "")
        mocked_refresh.assert_not_called()

    def test_selected_refresh_conflict_returns_actionable_message(self):
        client = self.app.test_client()
        self._login(client)

        unique = uuid.uuid4().hex
        account_id = self._insert_outlook_account(email_addr=f"selected_conflict_{unique}@outlook.com", unique=unique)

        with (
            patch.object(self.graph_service, "test_refresh_token_with_rotation") as mocked_refresh,
            patch(
                "outlook_web.services.refresh.acquire_distributed_lock",
                return_value=(
                    False,
                    {
                        "owner_id": "another-task",
                        "acquired_at": 1776393136.5748198,
                        "expires_at": 1776400336.5748198,
                    },
                ),
            ),
        ):
            resp = client.post("/api/accounts/refresh/selected", json={"account_ids": [account_id]})

        self.assertEqual(resp.status_code, 200)
        events = self._parse_sse_events(resp.get_data(as_text=True))
        self.assertGreaterEqual(len(events), 1)
        error_event = events[-1]
        self.assertEqual(error_event.get("type"), "error")
        error = error_event.get("error") or {}
        self.assertEqual(error.get("code"), "REFRESH_CONFLICT")
        self.assertIn("等待当前任务完成后再重试", error.get("message") or "")
        self.assertIn("Wait for it to finish and retry", error.get("message_en") or "")
        mocked_refresh.assert_not_called()

    def test_retry_failed_accounts_conflict_returns_actionable_message(self):
        client = self.app.test_client()
        self._login(client)

        with patch(
            "outlook_web.services.refresh.acquire_distributed_lock",
            return_value=(
                False,
                {
                    "owner_id": "another-task",
                    "acquired_at": 1776393136.5748198,
                    "expires_at": 1776400336.5748198,
                },
            ),
        ):
            resp = client.post("/api/accounts/refresh-failed")

        self.assertEqual(resp.status_code, 409)
        data = resp.get_json() or {}
        self.assertEqual(data.get("success"), False)
        error = data.get("error") or {}
        self.assertEqual(error.get("code"), "REFRESH_CONFLICT")
        self.assertIn("等待当前任务完成后再重试", error.get("message") or "")
        self.assertIn("Wait for it to finish and retry", error.get("message_en") or "")
