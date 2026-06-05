from __future__ import annotations

import os
import sqlite3
import sys
import types
import unittest
from unittest.mock import patch

from outlook_web import db_postgres_compat as compat


class FakeIntegrityError(Exception):
    pass


class FakePsycopg:
    IntegrityError = FakeIntegrityError


class FakePgCursor:
    def __init__(self, *, rows=None, description=None, rowcount=1, error=None):
        self.rows = list(rows or [])
        self.description = description
        self.rowcount = rowcount
        self.error = error
        self.executions = []
        self.closed = False

    def execute(self, sql, params=None):
        self.executions.append((sql, params))
        if self.error is not None:
            raise self.error

    def fetchall(self):
        return list(self.rows)

    def close(self):
        self.closed = True


class FakeRawConnection:
    def __init__(self, cursors=()):
        self._cursors = list(cursors)
        self.cursor_calls = 0
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def cursor(self):
        self.cursor_calls += 1
        if not self._cursors:
            raise AssertionError("No fake cursor queued")
        return self._cursors.pop(0)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


def make_connection(raw):
    connection = object.__new__(compat.PostgresCompatConnection)
    connection._psycopg = FakePsycopg
    connection._raw = raw
    connection._last_insert_id = None
    connection.row_factory = None
    return connection


class PostgresCompatSqlTranslationTests(unittest.TestCase):
    def tearDown(self) -> None:
        compat.restore_sqlite_connect_for_tests()

    def test_no_database_url_keeps_sqlite_connect(self):
        original = sqlite3.connect
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(compat.install_postgres_sqlite_compat())
        self.assertIs(sqlite3.connect, original)

    def test_unsupported_database_url_scheme_fails_before_patching(self):
        with patch.dict(os.environ, {"DATABASE_URL": "mysql://example"}, clear=True):
            with self.assertRaises(RuntimeError):
                compat.install_postgres_sqlite_compat()

    def test_sqlite_url_keeps_sqlite_connect_and_detection_is_precise(self):
        original = sqlite3.connect
        self.assertTrue(compat.is_postgres_database_url("postgres://example/db"))
        self.assertTrue(compat.is_postgres_database_url("postgresql://example/db"))
        self.assertFalse(compat.is_postgres_database_url("sqlite:///tmp/app.db"))
        self.assertFalse(compat.is_postgres_database_url(None))

        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///tmp/app.db"}, clear=True):
            self.assertFalse(compat.install_postgres_sqlite_compat())
        self.assertIs(sqlite3.connect, original)

    def test_postgres_url_installs_and_restores_connect_shim(self):
        original = sqlite3.connect
        fake_psycopg = types.SimpleNamespace()

        with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
            self.assertTrue(compat.install_postgres_sqlite_compat("postgresql://example/db"))
            self.assertIsNot(sqlite3.connect, original)
            self.assertTrue(compat.install_postgres_sqlite_compat("postgresql://example/db"))

        compat.restore_sqlite_connect_for_tests()
        self.assertIs(sqlite3.connect, original)

    def test_qmark_placeholders_ignore_string_literals(self):
        sql = compat.translate_sqlite_sql("SELECT * FROM settings WHERE key = ? AND value != '?' AND note = \"?\"")
        self.assertEqual(
            sql,
            "SELECT * FROM settings WHERE key = %s AND value != '?' AND note = \"?\"",
        )

    def test_insert_or_replace_settings_becomes_postgres_upsert(self):
        sql = compat.translate_sqlite_sql("""
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            """)
        self.assertIn("INSERT INTO settings", sql)
        self.assertIn("ON CONFLICT (key) DO UPDATE", sql)
        self.assertIn("VALUES (%s, %s, CURRENT_TIMESTAMP)", sql)

    def test_insert_or_replace_temp_messages_uses_message_unique_key(self):
        sql = compat.translate_sqlite_sql("""
            INSERT OR REPLACE INTO temp_email_messages
            (message_id, email_address, subject)
            VALUES (?, ?, ?)
            """)
        self.assertIn("INSERT INTO temp_email_messages", sql)
        self.assertIn("ON CONFLICT (email_address, message_id)", sql)
        self.assertIn("subject = EXCLUDED.subject", sql)

    def test_insert_or_ignore_becomes_do_nothing(self):
        sql = compat.translate_sqlite_sql("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)")
        self.assertEqual(
            sql,
            "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        )

    def test_sqlite_schema_fragments_become_postgres_compatible(self):
        sql = compat.translate_sqlite_sql("""
            CREATE TABLE IF NOT EXISTS sample (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_domain TEXT COLLATE NOCASE,
                created_at REAL DEFAULT (unixepoch('now'))
            )
            """)
        self.assertIn("INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY", sql)
        self.assertNotIn("COLLATE NOCASE", sql)
        self.assertIn("EXTRACT(EPOCH FROM NOW())", sql)

    def test_compat_row_behaves_like_sqlite_row_for_common_access(self):
        row = compat.CompatRow(["id", "subject"], [7, "Hello"])

        self.assertEqual(row[0], 7)
        self.assertEqual(row["subject"], "Hello")
        self.assertEqual(list(row), [7, "Hello"])
        self.assertEqual(len(row), 2)
        self.assertEqual(row.keys(), ["id", "subject"])
        self.assertEqual(dict(row.items()), {"id": 7, "subject": "Hello"})
        self.assertEqual(list(row.values()), [7, "Hello"])
        self.assertIn("id", row)
        self.assertNotIn("missing", row)

    def test_cursor_execute_translates_params_and_captures_returning_id(self):
        description = [types.SimpleNamespace(name="id"), types.SimpleNamespace(name="email")]
        pg_cursor = FakePgCursor(rows=[(42, "user@example.com")], description=description, rowcount=1)
        connection = make_connection(FakeRawConnection([pg_cursor]))

        cursor = connection.cursor()
        result = cursor.execute("INSERT INTO accounts (email) VALUES (?)", ["user@example.com"])

        self.assertIs(result, cursor)
        self.assertEqual(pg_cursor.executions[0][0], "INSERT INTO accounts (email) VALUES (%s) RETURNING id")
        self.assertEqual(pg_cursor.executions[0][1], ("user@example.com",))
        self.assertEqual(cursor.rowcount, 1)
        self.assertEqual(cursor.lastrowid, 42)
        self.assertEqual(connection._last_insert_id, 42)
        self.assertEqual(cursor.fetchone()["email"], "user@example.com")
        self.assertIsNone(cursor.fetchone())
        self.assertEqual(cursor.fetchall(), [])
        cursor.close()
        self.assertTrue(pg_cursor.closed)

    def test_cursor_execute_maps_postgres_integrity_errors_to_sqlite(self):
        raw = FakeRawConnection([FakePgCursor(error=FakeIntegrityError("duplicate key"))])
        connection = make_connection(raw)

        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO accounts (email) VALUES (?)", ("user@example.com",))

        self.assertEqual(raw.rollbacks, 1)

    def test_connection_executemany_sums_rowcount_and_lifecycle_delegates(self):
        raw = FakeRawConnection([FakePgCursor(rowcount=1), FakePgCursor(rowcount=2), FakePgCursor(rowcount=-1)])
        connection = make_connection(raw)

        cursor = connection.executemany(
            "UPDATE accounts SET email = ? WHERE id = ?",
            [("a@example.com", 1), ("b@example.com", 2), ("c@example.com", 3)],
        )
        connection.commit()
        connection.rollback()
        connection.close()

        self.assertEqual(cursor.rowcount, 3)
        self.assertEqual(raw.cursor_calls, 3)
        self.assertEqual(raw.commits, 1)
        self.assertEqual(raw.rollbacks, 1)
        self.assertEqual(raw.closes, 1)

    def test_special_statements_handle_transactions_pragmas_and_last_insert_id(self):
        connection = make_connection(FakeRawConnection())
        connection._last_insert_id = 99
        cursor = connection.cursor()

        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("COMMIT")
        cursor.execute("ROLLBACK")
        cursor.execute("SELECT last_insert_rowid() AS id")
        row = cursor.fetchone()
        cursor.execute("PRAGMA index_list(settings)")

        self.assertEqual(connection._raw.commits, 1)
        self.assertEqual(connection._raw.rollbacks, 1)
        self.assertEqual(row["id"], 99)
        self.assertEqual(cursor.fetchall(), [])

    def test_pragma_table_info_uses_information_schema_rows(self):
        pg_cursor = FakePgCursor(rows=[(0, "id", "integer", 1, None, 0)])
        connection = make_connection(FakeRawConnection([pg_cursor]))

        cursor = connection.cursor()
        cursor.execute('PRAGMA table_info("accounts")')
        rows = cursor.fetchall()

        self.assertEqual(pg_cursor.executions[0][1], ("accounts",))
        self.assertEqual(rows[0]["cid"], 0)
        self.assertEqual(rows[0]["name"], "id")
        self.assertEqual(rows[0]["type"], "integer")

    def test_helper_functions_cover_returning_params_and_sql_collapse(self):
        self.assertEqual(
            compat._append_returning_id_if_needed("INSERT INTO accounts (email) VALUES (%s);"),
            "INSERT INTO accounts (email) VALUES (%s) RETURNING id",
        )
        self.assertEqual(
            compat._append_returning_id_if_needed("INSERT INTO accounts (email) VALUES (%s) RETURNING id"),
            "INSERT INTO accounts (email) VALUES (%s) RETURNING id",
        )
        self.assertEqual(
            compat._append_returning_id_if_needed("INSERT INTO unknown_table (name) VALUES (%s)"),
            "INSERT INTO unknown_table (name) VALUES (%s)",
        )
        self.assertTrue(compat._returns_single_id("insert into accounts (email) values (%s) returning id"))
        self.assertEqual(compat._normalize_params(["a", "b"]), ("a", "b"))
        self.assertEqual(compat._normalize_params(("a", "b")), ("a", "b"))
        self.assertIsNone(compat._normalize_params(None))
        self.assertEqual(compat._normalize_params({"email": "user@example.com"}), {"email": "user@example.com"})
        self.assertEqual(compat._collapse_sql(" SELECT   1\n  FROM dual "), "SELECT 1 FROM dual")

    def test_placeholder_replacement_handles_escaped_quotes(self):
        sql = compat.translate_sqlite_sql("SELECT '?' AS literal, 'it''s ?' AS escaped, value FROM settings WHERE key = ?")

        self.assertEqual(
            sql,
            "SELECT '?' AS literal, 'it''s ?' AS escaped, value FROM settings WHERE key = %s",
        )


if __name__ == "__main__":
    unittest.main()
