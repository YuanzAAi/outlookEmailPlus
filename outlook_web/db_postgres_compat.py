from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterable, Iterator
from typing import Any, Optional

_ORIGINAL_SQLITE_CONNECT = sqlite3.connect
_INSTALLED = False
_ACTIVE_DATABASE_URL = ""

_POSTGRES_SCHEMES = ("postgres://", "postgresql://")
_SQLITE_SCHEMES = ("sqlite://", "sqlite3://", "file:")
_RETURNING_ID_TABLES = {
    "account_claim_logs",
    "account_project_usage",
    "account_refresh_logs",
    "accounts",
    "audit_logs",
    "external_api_consumer_usage_daily",
    "external_api_keys",
    "external_api_rate_limits",
    "external_upstream_probes",
    "groups",
    "notification_delivery_logs",
    "schema_migrations",
    "tags",
    "temp_email_messages",
    "temp_emails",
    "verification_extract_logs",
}
_TEMP_EMAIL_MESSAGES_CREATE_SQL = """
CREATE TABLE temp_email_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL,
    email_address TEXT NOT NULL,
    from_address TEXT,
    subject TEXT,
    content TEXT,
    html_content TEXT,
    has_html INTEGER DEFAULT 0,
    timestamp INTEGER,
    raw_content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(email_address, message_id)
)
"""


def get_database_url_from_env() -> str:
    return (os.getenv("DATABASE_URL") or "").strip()


def is_postgres_database_url(database_url: str | None) -> bool:
    return str(database_url or "").strip().lower().startswith(_POSTGRES_SCHEMES)


def install_postgres_sqlite_compat(database_url: str | None = None) -> bool:
    """Install a sqlite3.connect shim when DATABASE_URL points at Postgres.

    The application still defaults to the existing SQLite path. This shim is
    only activated for postgresql:// or postgres:// URLs, including Neon URLs.
    """

    global _ACTIVE_DATABASE_URL, _INSTALLED

    url = (database_url or get_database_url_from_env()).strip()
    if not url:
        return False

    normalized = url.lower()
    if normalized.startswith(_SQLITE_SCHEMES):
        return False

    if not normalized.startswith(_POSTGRES_SCHEMES):
        raise RuntimeError("DATABASE_URL only supports postgresql:// or postgres:// for third-party database mode.")

    if _INSTALLED and _ACTIVE_DATABASE_URL == url:
        return True

    try:
        import psycopg  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "DATABASE_URL is set to a PostgreSQL URL, but psycopg is not installed. "
            "Install dependencies with `pip install -r requirements.txt`."
        ) from exc

    def _connect(_database: Any = None, *args: Any, **kwargs: Any) -> "PostgresCompatConnection":
        return PostgresCompatConnection(url)

    sqlite3.connect = _connect  # type: ignore[assignment]
    _ACTIVE_DATABASE_URL = url
    _INSTALLED = True
    return True


class CompatRow:
    """sqlite3.Row-like wrapper supporting both numeric and name lookup."""

    def __init__(self, names: Iterable[str], values: Iterable[Any]):
        self._names = list(names)
        self._values = tuple(values)
        self._index = {name: idx for idx, name in enumerate(self._names)}

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._values[self._index[key]]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def keys(self) -> list[str]:
        return list(self._names)

    def items(self):
        for name in self._names:
            yield name, self[name]

    def values(self):
        return iter(self._values)

    def __contains__(self, key: object) -> bool:
        return key in self._index


class _StaticCursor:
    def __init__(self, rows: list[CompatRow] | None = None, *, rowcount: int = -1):
        self._rows = rows or []
        self._offset = 0
        self.rowcount = rowcount
        self.lastrowid = None

    def fetchone(self) -> Optional[CompatRow]:
        if self._offset >= len(self._rows):
            return None
        row = self._rows[self._offset]
        self._offset += 1
        return row

    def fetchall(self) -> list[CompatRow]:
        rows = self._rows[self._offset :]
        self._offset = len(self._rows)
        return rows


class PostgresCompatCursor:
    def __init__(self, connection: "PostgresCompatConnection"):
        self._connection = connection
        self._cursor = None
        self._rows: list[CompatRow] = []
        self._offset = 0
        self.rowcount = -1
        self.lastrowid = None

    def execute(self, sql: str, params: Any = None) -> "PostgresCompatCursor":
        self._rows = []
        self._offset = 0
        self.lastrowid = None

        special = self._execute_special(sql, params)
        if special is not None:
            self._rows = special._rows
            self.rowcount = special.rowcount
            self.lastrowid = special.lastrowid
            return self

        translated = translate_sqlite_sql(sql)
        translated = _append_returning_id_if_needed(translated)
        bound_params = _normalize_params(params)

        try:
            pg_cursor = self._connection._raw.cursor()
            # Queries come from existing app statements; params remain bound.
            pg_cursor.execute(translated, bound_params)  # NOSONAR
            self._cursor = pg_cursor
            self.rowcount = pg_cursor.rowcount
            if pg_cursor.description:
                names = [desc.name for desc in pg_cursor.description]
                fetched = pg_cursor.fetchall()
                self._rows = [CompatRow(names, row) for row in fetched]
                if _returns_single_id(translated) and self._rows:
                    self.lastrowid = self._rows[0]["id"]
                    self._connection._last_insert_id = self.lastrowid
            return self
        except self._connection._psycopg.IntegrityError as exc:
            self._connection.rollback()
            raise sqlite3.IntegrityError(str(exc)) from exc

    def executemany(self, sql: str, seq_of_params: Iterable[Any]) -> "PostgresCompatCursor":
        total_rowcount = 0
        self.lastrowid = None
        for params in seq_of_params:
            self.execute(sql, params)
            if self.rowcount and self.rowcount > 0:
                total_rowcount += self.rowcount
        self.rowcount = total_rowcount
        return self

    def fetchone(self) -> Optional[CompatRow]:
        if self._offset >= len(self._rows):
            return None
        row = self._rows[self._offset]
        self._offset += 1
        return row

    def fetchall(self) -> list[CompatRow]:
        rows = self._rows[self._offset :]
        self._offset = len(self._rows)
        return rows

    def close(self) -> None:
        if self._cursor is not None:
            self._cursor.close()

    def _execute_special(self, sql: str, params: Any = None) -> _StaticCursor | None:
        normalized = _collapse_sql(sql)
        upper = normalized.upper()

        if upper.startswith("PRAGMA "):
            return self._execute_pragma(normalized)

        sqlite_master_table = _sqlite_master_table_name(normalized)
        if sqlite_master_table == "temp_email_messages":
            row = CompatRow(["sql"], [_TEMP_EMAIL_MESSAGES_CREATE_SQL])
            return _StaticCursor([row], rowcount=1)
        if sqlite_master_table:
            return _StaticCursor([], rowcount=0)

        if upper in {"BEGIN", "BEGIN IMMEDIATE", "BEGIN EXCLUSIVE"}:
            return _StaticCursor([])
        if upper == "COMMIT":
            self._connection.commit()
            return _StaticCursor([])
        if upper == "ROLLBACK":
            self._connection.rollback()
            return _StaticCursor([])
        if re.match(r"SELECT\s+last_insert_rowid\(\)\s+AS\s+id", normalized, re.I):
            row = CompatRow(["id"], [self._connection._last_insert_id])
            return _StaticCursor([row], rowcount=1)

        return None

    def _execute_pragma(self, normalized: str) -> _StaticCursor:
        table_info = re.match(r"PRAGMA\s+table_info\((?:'|\")?([^'\")]+)(?:'|\")?\)", normalized, re.I)
        if table_info:
            table_name = table_info.group(1)
            return _StaticCursor(self._connection._table_info(table_name))

        index_list = re.match(r"PRAGMA\s+index_list\((?:'|\")?([^'\")]+)(?:'|\")?\)", normalized, re.I)
        if index_list:
            return _StaticCursor([])

        return _StaticCursor([])


class PostgresCompatConnection:
    def __init__(self, database_url: str):
        import psycopg

        self._psycopg = psycopg
        # The URL is provided by deployment configuration for the selected database backend.
        self._raw = psycopg.connect(database_url)  # NOSONAR
        self._last_insert_id = None
        self.row_factory = None

    def execute(self, sql: str, params: Any = None) -> PostgresCompatCursor:
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor

    def executemany(self, sql: str, seq_of_params: Iterable[Any]) -> PostgresCompatCursor:
        cursor = self.cursor()
        cursor.executemany(sql, seq_of_params)
        return cursor

    def cursor(self) -> PostgresCompatCursor:
        return PostgresCompatCursor(self)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()

    def _table_info(self, table_name: str) -> list[CompatRow]:
        cursor = self._raw.cursor()
        # Fixed metadata query; the table name stays bound as a parameter.
        cursor.execute(  # NOSONAR
            """
            SELECT
                ordinal_position - 1 AS cid,
                column_name AS name,
                data_type AS type,
                CASE WHEN is_nullable = 'NO' THEN 1 ELSE 0 END AS notnull,
                column_default AS dflt_value,
                0 AS pk
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table_name,),
        )
        names = ["cid", "name", "type", "notnull", "dflt_value", "pk"]
        return [CompatRow(names, row) for row in cursor.fetchall()]


def translate_sqlite_sql(sql: str) -> str:
    translated = sql.strip()
    translated = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
        translated,
        flags=re.I,
    )
    translated = re.sub(r" COLLATE NOCASE\b", "", translated, flags=re.I)
    translated = translated.replace("unixepoch('now')", "EXTRACT(EPOCH FROM NOW())")
    translated = translated.replace("strftime('%s','now')", "EXTRACT(EPOCH FROM NOW())")
    translated = translated.replace('strftime("%s","now")', "EXTRACT(EPOCH FROM NOW())")
    translated = re.sub(
        r"strftime\(\s*['\"]%Y-%m-%dT%H:%M:%S['\"]\s*,\s*['\"]now['\"]\s*\)",
        "TO_CHAR(CURRENT_TIMESTAMP, 'YYYY-MM-DD\"T\"HH24:MI:SS')",
        translated,
        flags=re.I,
    )
    translated = translated.replace("datetime('now')", "CURRENT_TIMESTAMP")
    translated = _translate_email_sqlite_functions(translated)
    translated = _translate_insert_or_replace(translated)
    translated = _translate_insert_or_ignore(translated)
    translated = _replace_qmark_placeholders(translated)
    return translated


def _translate_email_sqlite_functions(sql: str) -> str:
    translated = re.sub(
        r"\bLOWER\s*\(\s*SUBSTR\s*\(\s*email\s*,\s*INSTR\s*\(\s*email\s*,\s*['\"]@['\"]\s*\)\s*\+\s*1\s*\)\s*\)",
        "LOWER(SPLIT_PART(email, '@', 2))",
        sql,
        flags=re.I,
    )
    translated = re.sub(
        r"\bSUBSTR\s*\(\s*email\s*,\s*1\s*,\s*INSTR\s*\(\s*email\s*,\s*['\"]@['\"]\s*\)\s*-\s*1\s*\)",
        "SPLIT_PART(email, '@', 1)",
        translated,
        flags=re.I,
    )
    translated = re.sub(
        r"\bSUBSTR\s*\(\s*email\s*,\s*INSTR\s*\(\s*email\s*,\s*['\"]@['\"]\s*\)\s*\+\s*1\s*\)",
        "SPLIT_PART(email, '@', 2)",
        translated,
        flags=re.I,
    )
    return re.sub(
        r"\bINSTR\s*\(\s*email\s*,\s*['\"]@['\"]\s*\)",
        "POSITION('@' IN email)",
        translated,
        flags=re.I,
    )


def _translate_insert_or_replace(sql: str) -> str:
    if re.match(r"\s*INSERT\s+OR\s+REPLACE\s+INTO\s+temp_email_messages\b", sql, flags=re.I):
        translated = re.sub(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", "INSERT INTO", sql, count=1, flags=re.I)
        if re.search(r"\bON\s+CONFLICT\b", translated, flags=re.I):
            return translated
        return translated.rstrip().rstrip(";") + """
            ON CONFLICT (email_address, message_id)
            DO UPDATE SET
                from_address = EXCLUDED.from_address,
                subject = EXCLUDED.subject,
                content = EXCLUDED.content,
                html_content = EXCLUDED.html_content,
                has_html = EXCLUDED.has_html,
                timestamp = EXCLUDED.timestamp,
                raw_content = EXCLUDED.raw_content
            """

    if not re.match(r"\s*INSERT\s+OR\s+REPLACE\s+INTO\s+settings\b", sql, flags=re.I):
        return re.sub(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", "INSERT INTO", sql, flags=re.I)

    translated = re.sub(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", "INSERT INTO", sql, count=1, flags=re.I)
    if re.search(r"\bON\s+CONFLICT\b", translated, flags=re.I):
        return translated
    return (
        translated.rstrip().rstrip(";")
        + " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at"
    )


def _translate_insert_or_ignore(sql: str) -> str:
    if not re.match(r"\s*INSERT\s+OR\s+IGNORE\s+INTO\b", sql, flags=re.I):
        return sql
    translated = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", sql, count=1, flags=re.I)
    if re.search(r"\bON\s+CONFLICT\b", translated, flags=re.I):
        return translated
    return translated.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"


def _replace_qmark_placeholders(sql: str) -> str:
    result: list[str] = []
    in_single = False
    in_double = False
    i = 0

    while i < len(sql):
        char = sql[i]
        next_char = sql[i + 1] if i + 1 < len(sql) else ""

        if char == "'" and not in_double:
            result.append(char)
            if in_single and next_char == "'":
                result.append(next_char)
                i += 2
                continue
            in_single = not in_single
            i += 1
            continue

        if char == '"' and not in_single:
            result.append(char)
            in_double = not in_double
            i += 1
            continue

        if char == "?" and not in_single and not in_double:
            result.append("%s")
        else:
            result.append(char)
        i += 1

    return "".join(result)


def _append_returning_id_if_needed(sql: str) -> str:
    if re.search(r"\bRETURNING\b", sql, flags=re.I):
        return sql
    match = re.match(r"\s*INSERT\s+INTO\s+([a-zA-Z_][a-zA-Z0-9_]*)\b", sql, flags=re.I)
    if not match:
        return sql
    table_name = match.group(1).lower()
    if table_name not in _RETURNING_ID_TABLES:
        return sql
    return sql.rstrip().rstrip(";") + " RETURNING id"


def _returns_single_id(sql: str) -> bool:
    return bool(re.search(r"\bRETURNING\s+id\b", sql, flags=re.I))


def _normalize_params(params: Any) -> Any:
    if params is None:
        return None
    if isinstance(params, tuple):
        return params
    if isinstance(params, list):
        return tuple(params)
    return params


def _collapse_sql(sql: str) -> str:
    return " ".join(str(sql or "").strip().split())


def _sqlite_master_table_name(sql: str) -> str | None:
    match = re.match(
        r"\s*SELECT\s+sql\s+FROM\s+sqlite_master\s+WHERE\s+type\s*=\s*['\"]table['\"]\s+AND\s+name\s*=\s*['\"]([^'\"]+)['\"]",
        sql,
        flags=re.I,
    )
    return match.group(1) if match else None


def restore_sqlite_connect_for_tests() -> None:
    global _ACTIVE_DATABASE_URL, _INSTALLED
    sqlite3.connect = _ORIGINAL_SQLITE_CONNECT  # type: ignore[assignment]
    _ACTIVE_DATABASE_URL = ""
    _INSTALLED = False
