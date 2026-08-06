import json
import unittest
import uuid

from tests._import_app import import_web_app_module


class PoolFlowSuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app
        cls.client = cls.app.test_client()
        from outlook_web.db import create_sqlite_connection

        cls.create_conn = staticmethod(lambda: create_sqlite_connection())

    def setUp(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.repositories import settings as settings_repo

            db = get_db()
            account_columns = [row[1] for row in db.execute("PRAGMA table_info(accounts)").fetchall()]
            if "claimed_project_key" not in account_columns:
                db.execute("ALTER TABLE accounts ADD COLUMN claimed_project_key TEXT DEFAULT NULL")
            usage_columns = [row[1] for row in db.execute("PRAGMA table_info(account_project_usage)").fetchall()]
            if "first_success_at" not in usage_columns:
                db.execute("ALTER TABLE account_project_usage ADD COLUMN first_success_at TEXT DEFAULT NULL")
            if "last_success_at" not in usage_columns:
                db.execute("ALTER TABLE account_project_usage ADD COLUMN last_success_at TEXT DEFAULT NULL")
            if "success_count" not in usage_columns:
                db.execute("ALTER TABLE account_project_usage ADD COLUMN success_count INTEGER NOT NULL DEFAULT 0")
            db.execute("DELETE FROM account_claim_logs")
            db.execute("DELETE FROM account_project_usage")
            db.execute("DELETE FROM accounts")
            db.execute("DELETE FROM external_api_keys")
            db.execute("DELETE FROM external_api_rate_limits")
            db.commit()
            settings_repo.set_setting("external_api_key", "abc123")
            settings_repo.set_setting("pool_external_enabled", "true")
            settings_repo.set_setting("external_api_public_mode", "false")
            settings_repo.set_setting("external_api_ip_whitelist", "[]")
            settings_repo.set_setting("external_api_rate_limit_per_minute", "60")
            settings_repo.set_setting("external_api_disable_pool_claim_random", "false")
            settings_repo.set_setting("external_api_disable_pool_claim_release", "false")
            settings_repo.set_setting("external_api_disable_pool_claim_complete", "false")
            settings_repo.set_setting("external_api_disable_pool_stats", "false")

    @staticmethod
    def _auth_headers():
        return {"X-API-Key": "abc123"}

    def _make_pool_account(
        self,
        *,
        provider: str = "outlook",
        account_type: str = "outlook",
        pool_status: str = "available",
        email_domain: str = "poolflow.test",
    ) -> dict:
        conn = self.create_conn()
        try:
            email_addr = f"flow_{uuid.uuid4().hex}@{email_domain}"
            conn.execute(
                """
                INSERT INTO accounts (
                    email, client_id, refresh_token, status,
                    account_type, provider, group_id, pool_status, email_domain
                )
                VALUES (?, 'test_client', 'test_token', 'active', ?, ?, 1, ?, ?)
                """,
                (email_addr, account_type, provider, pool_status, email_domain),
            )
            conn.commit()
            row = conn.execute(
                "SELECT id, email, pool_status, provider, account_type, email_domain FROM accounts WHERE email = ?",
                (email_addr,),
            ).fetchone()
            return dict(row)
        finally:
            conn.close()

    def test_claim_complete_success_without_project_key_still_changes_status_to_used(self):
        self._make_pool_account()

        claim_resp = self.client.post(
            "/api/external/pool/claim-random",
            headers=self._auth_headers(),
            json={"caller_id": "suite_bot", "task_id": "success_flow"},
        )
        self.assertEqual(claim_resp.status_code, 200)
        claim_data = json.loads(claim_resp.data)
        self.assertTrue(claim_data["success"])

        complete_resp = self.client.post(
            "/api/external/pool/claim-complete",
            headers=self._auth_headers(),
            json={
                "account_id": claim_data["data"]["account_id"],
                "claim_token": claim_data["data"]["claim_token"],
                "caller_id": "suite_bot",
                "task_id": "success_flow",
                "result": "success",
                "detail": "manual suite success",
            },
        )
        self.assertEqual(complete_resp.status_code, 200)
        complete_data = json.loads(complete_resp.data)
        self.assertTrue(complete_data["success"])
        # 未传 project_key 时，旧行为仍为 success → used
        self.assertEqual(complete_data["data"]["pool_status"], "used")

        conn = self.create_conn()
        try:
            row = conn.execute(
                "SELECT pool_status, success_count, fail_count FROM accounts WHERE id = ?",
                (claim_data["data"]["account_id"],),
            ).fetchone()
            self.assertEqual(row["pool_status"], "used")
            self.assertEqual(row["success_count"], 1)
            self.assertEqual(row["fail_count"], 0)
        finally:
            conn.close()

    def test_claim_complete_success_with_project_key_on_long_lived_account_returns_available(self):
        account = self._make_pool_account(email_domain=f"reuse_{uuid.uuid4().hex[:8]}.test")

        claim_resp = self.client.post(
            "/api/external/pool/claim-random",
            headers=self._auth_headers(),
            json={
                "caller_id": "reuse_bot",
                "task_id": "reuse_success_1",
                "project_key": "project_alpha",
                "email_domain": account["email_domain"],
            },
        )
        self.assertEqual(claim_resp.status_code, 200)
        claim_data = json.loads(claim_resp.data)
        self.assertTrue(claim_data["success"])

        complete_resp = self.client.post(
            "/api/external/pool/claim-complete",
            headers=self._auth_headers(),
            json={
                "account_id": claim_data["data"]["account_id"],
                "claim_token": claim_data["data"]["claim_token"],
                "caller_id": "reuse_bot",
                "task_id": "reuse_success_1",
                "result": "success",
            },
        )
        self.assertEqual(complete_resp.status_code, 200)
        complete_data = json.loads(complete_resp.data)
        self.assertTrue(complete_data["success"])
        self.assertEqual(complete_data["data"]["pool_status"], "available")

        conn = self.create_conn()
        try:
            row = conn.execute(
                """
                SELECT pool_status, claimed_by, claim_token
                FROM accounts
                WHERE id = ?
                """,
                (claim_data["data"]["account_id"],),
            ).fetchone()
            self.assertEqual(row["pool_status"], "available")
            self.assertIsNone(row["claimed_by"])
            self.assertIsNone(row["claim_token"])
        finally:
            conn.close()

    def test_claim_complete_failure_changes_status_to_cooldown(self):
        self._make_pool_account()

        claim_resp = self.client.post(
            "/api/external/pool/claim-random",
            headers=self._auth_headers(),
            json={"caller_id": "suite_bot", "task_id": "cooldown_flow"},
        )
        self.assertEqual(claim_resp.status_code, 200)
        claim_data = json.loads(claim_resp.data)
        self.assertTrue(claim_data["success"])

        complete_resp = self.client.post(
            "/api/external/pool/claim-complete",
            headers=self._auth_headers(),
            json={
                "account_id": claim_data["data"]["account_id"],
                "claim_token": claim_data["data"]["claim_token"],
                "caller_id": "suite_bot",
                "task_id": "cooldown_flow",
                "result": "verification_timeout",
                "detail": "manual suite timeout",
            },
        )
        self.assertEqual(complete_resp.status_code, 200)
        complete_data = json.loads(complete_resp.data)
        self.assertTrue(complete_data["success"])
        self.assertEqual(complete_data["data"]["pool_status"], "cooldown")

        conn = self.create_conn()
        try:
            row = conn.execute(
                "SELECT pool_status, success_count, fail_count, last_result FROM accounts WHERE id = ?",
                (claim_data["data"]["account_id"],),
            ).fetchone()
            self.assertEqual(row["pool_status"], "cooldown")
            self.assertEqual(row["success_count"], 0)
            self.assertEqual(row["fail_count"], 1)
            self.assertEqual(row["last_result"], "verification_timeout")
        finally:
            conn.close()

    def test_multiple_consecutive_claims_do_not_repeat_accounts(self):
        # 使用唯一的 email_domain 隔离测试数据
        email_domain = f"multi_{uuid.uuid4().hex[:8]}.test"
        created_ids = []
        for _ in range(3):
            created = self._make_pool_account(email_domain=email_domain)
            created_ids.append(created["id"])

        claimed_ids = []
        claimed_tokens = []
        for idx in range(3):
            resp = self.client.post(
                "/api/external/pool/claim-random",
                headers=self._auth_headers(),
                json={
                    "caller_id": "suite_bot",
                    "task_id": f"batch_claim_{idx}",
                    "email_domain": email_domain,  # 使用 email_domain 过滤
                },
            )
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertTrue(data["success"])
            claimed_ids.append(data["data"]["account_id"])
            claimed_tokens.append(
                (
                    data["data"]["account_id"],
                    data["data"]["claim_token"],
                    f"batch_claim_{idx}",
                )
            )

        self.assertEqual(len(claimed_ids), len(set(claimed_ids)))
        self.assertTrue(set(claimed_ids).issubset(set(created_ids)))

        for account_id, claim_token, task_id in claimed_tokens:
            release_resp = self.client.post(
                "/api/external/pool/claim-release",
                headers=self._auth_headers(),
                json={
                    "account_id": account_id,
                    "claim_token": claim_token,
                    "caller_id": "suite_bot",
                    "task_id": task_id,
                    "reason": "suite cleanup",
                },
            )
            self.assertEqual(release_resp.status_code, 200)
            release_data = json.loads(release_resp.data)
            self.assertTrue(release_data["success"])
            self.assertEqual(release_data["data"]["pool_status"], "available")

        conn = self.create_conn()
        try:
            placeholders = ",".join(["?"] * len(created_ids))
            rows = conn.execute(
                f"SELECT id, pool_status, claim_token FROM accounts WHERE id IN ({placeholders})",
                created_ids,
            ).fetchall()
            self.assertEqual(len(rows), 3)
            for row in rows:
                self.assertEqual(row["pool_status"], "available")
                self.assertIsNone(row["claim_token"])
        finally:
            conn.close()

    def test_claim_response_includes_email_domain_and_claimed_at(self):
        """PR#27: claim-random 响应应包含 email_domain 和 claimed_at 字段。"""
        self._make_pool_account()
        resp = self.client.post(
            "/api/external/pool/claim-random",
            headers=self._auth_headers(),
            json={"caller_id": "domain_bot", "task_id": "domain_check"},
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data["success"])
        self.assertIn("email_domain", data["data"])
        self.assertIn("claimed_at", data["data"])
        self.assertIsNotNone(data["data"]["claimed_at"])

    def test_claim_domain_requires_email_domain(self):
        resp = self.client.post(
            "/api/external/pool/claim-domain",
            headers=self._auth_headers(),
            json={"caller_id": "domain_bot", "task_id": "domain_required"},
        )
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.data)
        self.assertFalse(data["success"])
        self.assertEqual(data["code"], "EMAIL_DOMAIN_REQUIRED")

    def test_claim_domain_filters_to_requested_domain(self):
        requested_domain = f"requested_{uuid.uuid4().hex[:8]}.test"
        other_domain = f"other_{uuid.uuid4().hex[:8]}.test"
        requested = self._make_pool_account(email_domain=requested_domain)
        other = self._make_pool_account(email_domain=other_domain)

        resp = self.client.post(
            "/api/external/pool/claim-domain",
            headers=self._auth_headers(),
            json={
                "caller_id": "domain_bot",
                "task_id": "domain_claim",
                "email_domain": requested_domain.upper(),
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["account_id"], requested["id"])
        self.assertEqual(data["data"]["email_domain"], requested_domain)
        self.assertNotEqual(data["data"]["account_id"], other["id"])

    def test_claim_with_project_key_prevents_same_project_reuse_without_manual_status_reset(self):
        """同 caller_id + project_key 下，新语义应原生阻止再次领取，无需手工改状态。"""
        # 使用唯一的 email_domain 隔离测试数据
        email_domain = f"proj_{uuid.uuid4().hex[:8]}.test"
        acct = self._make_pool_account(email_domain=email_domain)
        account_id = acct["id"]

        # 第一次领取
        resp1 = self.client.post(
            "/api/external/pool/claim-random",
            headers=self._auth_headers(),
            json={
                "caller_id": "proj_bot",
                "task_id": "proj_task_1",
                "email_domain": email_domain,  # 使用 email_domain 过滤
                "project_key": "project_alpha",
            },
        )
        self.assertEqual(resp1.status_code, 200)
        data1 = json.loads(resp1.data)
        self.assertTrue(data1["success"])
        self.assertEqual(data1["data"]["account_id"], account_id)

        # 标记完成后，应直接按新语义回到 available，无需手工 SQL 介入
        complete_resp = self.client.post(
            "/api/external/pool/claim-complete",
            headers=self._auth_headers(),
            json={
                "account_id": account_id,
                "claim_token": data1["data"]["claim_token"],
                "caller_id": "proj_bot",
                "task_id": "proj_task_1",
                "result": "success",
            },
        )
        self.assertEqual(complete_resp.status_code, 200)
        complete_data = json.loads(complete_resp.data)
        self.assertTrue(complete_data["success"])
        self.assertEqual(complete_data["data"]["pool_status"], "available")

        # 同 project_key 再次领取 → 应该拿不到（同 caller+project 的账号已被排除）
        resp2 = self.client.post(
            "/api/external/pool/claim-random",
            headers=self._auth_headers(),
            json={
                "caller_id": "proj_bot",
                "task_id": "proj_task_2",
                "email_domain": email_domain,  # 使用 email_domain 过滤
                "project_key": "project_alpha",
            },
        )
        self.assertEqual(resp2.status_code, 200)
        data2 = json.loads(resp2.data)
        # 池里只有这一个账号，同 project 应排除，预期 no_available_account
        self.assertFalse(data2["success"])
        self.assertEqual(data2["code"], "NO_AVAILABLE_ACCOUNT")

    def test_claim_with_different_project_key_allows_immediate_reuse_after_success(self):
        """不同 project_key 下，同一账号在 success 后应立即可再次领取。"""
        # 使用唯一的 email_domain 隔离测试数据
        email_domain = f"proj2_{uuid.uuid4().hex[:8]}.test"
        acct = self._make_pool_account(email_domain=email_domain)
        account_id = acct["id"]

        # 第一次领取（project_beta）
        resp1 = self.client.post(
            "/api/external/pool/claim-random",
            headers=self._auth_headers(),
            json={
                "caller_id": "proj_bot",
                "task_id": "pb_task_1",
                "email_domain": email_domain,  # 使用 email_domain 过滤
                "project_key": "project_beta",
            },
        )
        self.assertEqual(resp1.status_code, 200)
        data1 = json.loads(resp1.data)
        self.assertTrue(data1["success"])

        # 完成后按新语义应直接恢复 available
        complete_resp = self.client.post(
            "/api/external/pool/claim-complete",
            headers=self._auth_headers(),
            json={
                "account_id": account_id,
                "claim_token": data1["data"]["claim_token"],
                "caller_id": "proj_bot",
                "task_id": "pb_task_1",
                "result": "success",
            },
        )
        self.assertEqual(complete_resp.status_code, 200)
        complete_data = json.loads(complete_resp.data)
        self.assertTrue(complete_data["success"])
        self.assertEqual(complete_data["data"]["pool_status"], "available")

        # 第二次领取（project_gamma，不同 project_key）→ 应该能拿到
        resp2 = self.client.post(
            "/api/external/pool/claim-random",
            headers=self._auth_headers(),
            json={
                "caller_id": "proj_bot",
                "task_id": "pg_task_1",
                "email_domain": email_domain,  # 使用 email_domain 过滤
                "project_key": "project_gamma",
            },
        )
        self.assertEqual(resp2.status_code, 200)
        data2 = json.loads(resp2.data)
        self.assertTrue(data2["success"])
        self.assertEqual(data2["data"]["account_id"], account_id)

        # 清理
        self.client.post(
            "/api/external/pool/claim-release",
            headers=self._auth_headers(),
            json={
                "account_id": account_id,
                "claim_token": data2["data"]["claim_token"],
                "caller_id": "proj_bot",
                "task_id": "pg_task_1",
            },
        )

    def test_claim_complete_success_updates_stats_to_available_not_used(self):
        email_domain = f"stats_{uuid.uuid4().hex[:8]}.test"
        self._make_pool_account(email_domain=email_domain)

        claim_resp = self.client.post(
            "/api/external/pool/claim-random",
            headers=self._auth_headers(),
            json={
                "caller_id": "stats_bot",
                "task_id": "stats_task_1",
                "project_key": "project_stats",
                "email_domain": email_domain,
            },
        )
        self.assertEqual(claim_resp.status_code, 200)
        claim_data = json.loads(claim_resp.data)
        self.assertTrue(claim_data["success"])

        complete_resp = self.client.post(
            "/api/external/pool/claim-complete",
            headers=self._auth_headers(),
            json={
                "account_id": claim_data["data"]["account_id"],
                "claim_token": claim_data["data"]["claim_token"],
                "caller_id": "stats_bot",
                "task_id": "stats_task_1",
                "result": "success",
            },
        )
        self.assertEqual(complete_resp.status_code, 200)
        complete_data = json.loads(complete_resp.data)
        self.assertTrue(complete_data["success"])
        self.assertEqual(complete_data["data"]["pool_status"], "available")

        stats_resp = self.client.get(
            "/api/external/pool/stats",
            headers=self._auth_headers(),
        )
        self.assertEqual(stats_resp.status_code, 200)
        stats_data = json.loads(stats_resp.data)
        self.assertTrue(stats_data["success"])
        pool_counts = stats_data["data"]["pool_counts"]
        self.assertGreaterEqual(pool_counts["available"], 1)
        self.assertEqual(pool_counts["used"], 0)

    def test_same_project_verification_timeout_does_not_block_retry_after_recovery(self):
        email_domain = f"timeout_{uuid.uuid4().hex[:8]}.test"
        acct = self._make_pool_account(email_domain=email_domain)
        account_id = acct["id"]

        claim_resp = self.client.post(
            "/api/external/pool/claim-random",
            headers=self._auth_headers(),
            json={
                "caller_id": "timeout_bot",
                "task_id": "timeout_task_1",
                "project_key": "project_timeout",
                "email_domain": email_domain,
            },
        )
        self.assertEqual(claim_resp.status_code, 200)
        claim_data = json.loads(claim_resp.data)
        self.assertTrue(claim_data["success"])

        complete_resp = self.client.post(
            "/api/external/pool/claim-complete",
            headers=self._auth_headers(),
            json={
                "account_id": account_id,
                "claim_token": claim_data["data"]["claim_token"],
                "caller_id": "timeout_bot",
                "task_id": "timeout_task_1",
                "result": "verification_timeout",
            },
        )
        self.assertEqual(complete_resp.status_code, 200)
        complete_data = json.loads(complete_resp.data)
        self.assertTrue(complete_data["success"])
        self.assertEqual(complete_data["data"]["pool_status"], "cooldown")

        conn = self.create_conn()
        try:
            conn.execute("UPDATE accounts SET pool_status = 'available' WHERE id = ?", (account_id,))
            conn.commit()
        finally:
            conn.close()

        retry_resp = self.client.post(
            "/api/external/pool/claim-random",
            headers=self._auth_headers(),
            json={
                "caller_id": "timeout_bot",
                "task_id": "timeout_task_2",
                "project_key": "project_timeout",
                "email_domain": email_domain,
            },
        )
        self.assertEqual(retry_resp.status_code, 200)
        retry_data = json.loads(retry_resp.data)
        self.assertTrue(retry_data["success"])
        self.assertEqual(retry_data["data"]["account_id"], account_id)

    def test_same_project_manual_release_does_not_block_retry(self):
        email_domain = f"release_{uuid.uuid4().hex[:8]}.test"
        acct = self._make_pool_account(email_domain=email_domain)
        account_id = acct["id"]

        claim_resp = self.client.post(
            "/api/external/pool/claim-random",
            headers=self._auth_headers(),
            json={
                "caller_id": "release_bot",
                "task_id": "release_task_1",
                "project_key": "project_release",
                "email_domain": email_domain,
            },
        )
        self.assertEqual(claim_resp.status_code, 200)
        claim_data = json.loads(claim_resp.data)
        self.assertTrue(claim_data["success"])

        release_resp = self.client.post(
            "/api/external/pool/claim-release",
            headers=self._auth_headers(),
            json={
                "account_id": account_id,
                "claim_token": claim_data["data"]["claim_token"],
                "caller_id": "release_bot",
                "task_id": "release_task_1",
            },
        )
        self.assertEqual(release_resp.status_code, 200)
        release_data = json.loads(release_resp.data)
        self.assertTrue(release_data["success"])
        self.assertEqual(release_data["data"]["pool_status"], "available")

        retry_resp = self.client.post(
            "/api/external/pool/claim-random",
            headers=self._auth_headers(),
            json={
                "caller_id": "release_bot",
                "task_id": "release_task_2",
                "project_key": "project_release",
                "email_domain": email_domain,
            },
        )
        self.assertEqual(retry_resp.status_code, 200)
        retry_data = json.loads(retry_resp.data)
        self.assertTrue(retry_data["success"])
        self.assertEqual(retry_data["data"]["account_id"], account_id)

    def test_cloudflare_temp_mail_success_with_project_key_still_returns_old_status_semantics(self):
        email_domain = f"cf_{uuid.uuid4().hex[:8]}.test"
        self._make_pool_account(
            provider="cloudflare_temp_mail",
            account_type="temp_mail",
            email_domain=email_domain,
        )

        claim_resp = self.client.post(
            "/api/external/pool/claim-random",
            headers=self._auth_headers(),
            json={
                "caller_id": "cf_bot",
                "task_id": "cf_task_1",
                "provider": "cloudflare_temp_mail",
                "project_key": "project_cf",
                "email_domain": email_domain,
            },
        )
        self.assertEqual(claim_resp.status_code, 200)
        claim_data = json.loads(claim_resp.data)
        self.assertTrue(claim_data["success"])

        complete_resp = self.client.post(
            "/api/external/pool/claim-complete",
            headers=self._auth_headers(),
            json={
                "account_id": claim_data["data"]["account_id"],
                "claim_token": claim_data["data"]["claim_token"],
                "caller_id": "cf_bot",
                "task_id": "cf_task_1",
                "result": "success",
            },
        )
        self.assertEqual(complete_resp.status_code, 200)
        complete_data = json.loads(complete_resp.data)
        self.assertTrue(complete_data["success"])
        self.assertEqual(complete_data["data"]["pool_status"], "used")


if __name__ == "__main__":
    unittest.main()
