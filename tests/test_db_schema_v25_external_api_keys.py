from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests._import_app import import_web_app_module


class DbSchemaV25ExternalApiKeyTests(unittest.TestCase):
    """验证 v25 API Key 过期字段、索引升级和名称唯一约束。"""

    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()

    def _seed_legacy_v24_db(self, db_path: Path, *, duplicate_names: bool = False) -> None:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("""
                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """)
            conn.execute("INSERT INTO settings (key, value) VALUES ('db_schema_version', '24')")
            conn.execute("""
                CREATE TABLE external_api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    api_key_encrypted TEXT NOT NULL,
                    allowed_emails_json TEXT NOT NULL DEFAULT '[]',
                    pool_access INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_used_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """)
            conn.execute("""
                CREATE INDEX idx_external_api_keys_enabled
                ON external_api_keys(enabled, updated_at)
                """)
            conn.execute("""
                CREATE INDEX idx_external_api_keys_name
                ON external_api_keys(name)
                """)
            second_name = "partner" if duplicate_names else "secondary"
            conn.execute(
                "INSERT INTO external_api_keys (name, api_key_encrypted) VALUES (?, ?)",
                ("Partner", "encrypted-a"),
            )
            conn.execute(
                "INSERT INTO external_api_keys (name, api_key_encrypted) VALUES (?, ?)",
                (second_name, "encrypted-b"),
            )
            conn.commit()
        finally:
            conn.close()

    def test_v25_rebuilds_enabled_index_and_adds_atomic_name_uniqueness(self):
        with tempfile.TemporaryDirectory(prefix="outlookEmail-v25-") as tmp:
            db_path = Path(tmp) / "legacy_v24.db"
            self._seed_legacy_v24_db(db_path)

            from outlook_web.db import init_db

            init_db(database_path=str(db_path))
            init_db(database_path=str(db_path))

            conn = sqlite3.connect(str(db_path))
            try:
                columns = [row[1] for row in conn.execute("PRAGMA table_info(external_api_keys)").fetchall()]
                self.assertIn("expires_at", columns)

                enabled_index_columns = [
                    row[2] for row in conn.execute("PRAGMA index_info('idx_external_api_keys_enabled')").fetchall()
                ]
                self.assertEqual(enabled_index_columns, ["enabled", "expires_at", "updated_at"])

                index_rows = conn.execute("PRAGMA index_list('external_api_keys')").fetchall()
                index_flags = {row[1]: row[2] for row in index_rows}
                self.assertEqual(index_flags.get("idx_external_api_keys_name_unique"), 1)
                self.assertNotIn("idx_external_api_keys_name", index_flags)

                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        "INSERT INTO external_api_keys (name, api_key_encrypted) VALUES (?, ?)",
                        (" partner ", "encrypted-c"),
                    )
            finally:
                conn.close()

    def test_v25_aborts_when_legacy_key_names_conflict_case_insensitively(self):
        with tempfile.TemporaryDirectory(prefix="outlookEmail-v25-duplicate-") as tmp:
            db_path = Path(tmp) / "legacy_v24.db"
            self._seed_legacy_v24_db(db_path, duplicate_names=True)

            from outlook_web.db import init_db

            with self.assertRaises(Exception) as ctx:
                init_db(database_path=str(db_path))

            message = str(ctx.exception)
            self.assertIn("external_api_keys.name", message)
            self.assertIn("大小写不敏感的重复值", message)
            self.assertIn("SELECT LOWER(TRIM(name))", message)
            self.assertIn("UPDATE external_api_keys", message)

            conn = sqlite3.connect(str(db_path))
            try:
                migration = conn.execute(
                    "SELECT status, error FROM schema_migrations ORDER BY id DESC LIMIT 1"
                ).fetchone()
                self.assertIsNotNone(migration)
                self.assertEqual(migration[0], "failed")
                self.assertIn("external_api_keys.name", str(migration[1] or ""))

                unique_index = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'index' AND name = 'idx_external_api_keys_name_unique'"
                ).fetchone()
                self.assertIsNone(unique_index)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
