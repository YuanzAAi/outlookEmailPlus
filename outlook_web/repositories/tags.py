from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional

from outlook_web.db import get_db


def get_tags() -> List[Dict]:
    """获取所有标签"""
    db = get_db()
    cursor = db.execute("SELECT * FROM tags ORDER BY created_at DESC")
    return [dict(row) for row in cursor.fetchall()]


def add_tag(name: str, color: str) -> Optional[int]:
    """添加标签"""
    db = get_db()
    try:
        cursor = db.execute("INSERT INTO tags (name, color) VALUES (?, ?)", (name, color))
        db.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None


def delete_tag(tag_id: int) -> bool:
    """删除标签"""
    db = get_db()
    db.execute("DELETE FROM temp_email_tags WHERE tag_id = ?", (tag_id,))
    cursor = db.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    db.commit()
    return cursor.rowcount > 0


def get_account_tags(account_id: int) -> List[Dict]:
    """获取账号的标签"""
    db = get_db()
    cursor = db.execute(
        """
        SELECT t.*
        FROM tags t
        JOIN account_tags at ON t.id = at.tag_id
        WHERE at.account_id = ?
        ORDER BY t.created_at DESC
        """,
        (account_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def add_account_tag(account_id: int, tag_id: int) -> bool:
    """给账号添加标签"""
    db = get_db()
    try:
        db.execute(
            "INSERT OR IGNORE INTO account_tags (account_id, tag_id) VALUES (?, ?)",
            (account_id, tag_id),
        )
        db.commit()
        return True
    except Exception:
        return False


def remove_account_tag(account_id: int, tag_id: int) -> bool:
    """移除账号标签"""
    db = get_db()
    db.execute(
        "DELETE FROM account_tags WHERE account_id = ? AND tag_id = ?",
        (account_id, tag_id),
    )
    db.commit()
    return True
