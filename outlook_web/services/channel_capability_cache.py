"""通道能力缓存 — 记忆每个账号各渠道的可用/不可用状态。进程级内存缓存，TTL 1 小时。"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

_DEFAULT_TTL = 3600
_UNAVAILABLE_TTL = 5
_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}
_lock = threading.Lock()


def set_status(email: str, channel: str, *, available: bool) -> None:
    with _lock:
        if email not in _cache:
            _cache[email] = {}
        _cache[email][channel] = {
            "status": "available" if available else "unavailable",
            # 读取失败可能只是短暂的上游抖动，不能让 URL 取码整小时跳过该渠道。
            "expires_at": time.monotonic() + (_DEFAULT_TTL if available else _UNAVAILABLE_TTL),
        }


def get_status(email: str, channel: str) -> Optional[str]:
    with _lock:
        account_cache = _cache.get(email)
        if not account_cache:
            return None
        entry = account_cache.get(channel)
        if not entry:
            return None
        if time.monotonic() >= entry["expires_at"]:
            del account_cache[channel]
            return None
        return entry["status"]


def filter_channel_plan(email: str, channel_plan: List[str]) -> List[str]:
    with _lock:
        account_cache = _cache.get(email)
        if not account_cache:
            return list(channel_plan)

        now = time.monotonic()
        status_snapshot: Dict[str, str] = {}
        expired_channels: List[str] = []
        for ch, entry in account_cache.items():
            if now >= entry["expires_at"]:
                expired_channels.append(ch)
                continue
            status_snapshot[ch] = str(entry.get("status") or "")

        for ch in expired_channels:
            account_cache.pop(ch, None)

    return [ch for ch in channel_plan if status_snapshot.get(ch) != "unavailable"]


def clear_for_account(email: str) -> None:
    with _lock:
        _cache.pop(email, None)


def clear_all() -> None:
    with _lock:
        _cache.clear()
