"""
验证码提取服务兼容入口

核心验证码抽取规则已收敛到 verification_code_extraction.py；本模块保留旧导入路径，
并继续承载验证码 AI fallback 相关逻辑。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, Optional

import requests

from outlook_web.repositories import settings as settings_repo
from outlook_web.services.verification_code_extraction import (
    CODE_CONTEXT_PHRASES,
    DEFAULT_LINK_KEYWORDS,
    HYPHENATED_VERIFICATION_PATTERN,
    HTMLTextExtractor,
    LINK_CONTEXT_PHRASES,
    LINK_PATTERN,
    VERIFICATION_KEYWORDS,
    VERIFICATION_PATTERN,
    VerificationInput,
    VerificationPolicy,
    _build_code_regex,
    _fallback_extract_code,
    _fallback_extract_hyphenated_verification_code,
    _find_hyphenated_code_in_text,
    _has_code_context,
    _is_valid_hyphenated_code,
    _parse_code_length,
    _pick_preferred_link,
    _smart_extract_code_by_keywords,
    _smart_extract_hyphenated_verification_code,
    apply_confidence_gate,
    extract_content_text_without_subject,
    extract_content_text_without_subject as _extract_content_text_without_subject,
    extract_email_text,
    extract_links,
    extract_verification,
    extract_verification_info,
    extract_verification_info_from_text,
    extract_verification_info_with_options,
    fallback_extract_verification_code,
    smart_extract_verification_code,
)

VERIFICATION_AI_SCHEMA_VERSION = "verification_ai_v1"
_LOGGER = logging.getLogger("outlook_web.services.verification_extractor")

__all__ = [
    "CODE_CONTEXT_PHRASES",
    "DEFAULT_LINK_KEYWORDS",
    "HYPHENATED_VERIFICATION_PATTERN",
    "HTMLTextExtractor",
    "LINK_CONTEXT_PHRASES",
    "LINK_PATTERN",
    "VERIFICATION_AI_SCHEMA_VERSION",
    "VERIFICATION_KEYWORDS",
    "VERIFICATION_PATTERN",
    "VerificationInput",
    "VerificationPolicy",
    "_build_code_regex",
    "extract_content_text_without_subject",
    "_extract_content_text_without_subject",
    "_fallback_extract_code",
    "_fallback_extract_hyphenated_verification_code",
    "_find_hyphenated_code_in_text",
    "_has_code_context",
    "_is_valid_hyphenated_code",
    "_parse_code_length",
    "_pick_preferred_link",
    "_smart_extract_code_by_keywords",
    "_smart_extract_hyphenated_verification_code",
    "apply_confidence_gate",
    "build_verification_ai_input_payload",
    "enhance_verification_with_ai_fallback",
    "extract_email_text",
    "extract_links",
    "extract_verification",
    "extract_verification_info",
    "extract_verification_info_from_text",
    "extract_verification_info_with_options",
    "fallback_extract_verification_code",
    "get_verification_ai_runtime_config",
    "is_verification_ai_config_complete",
    "probe_verification_ai_runtime",
    "smart_extract_verification_code",
]

def get_verification_ai_runtime_config() -> Dict[str, Any]:
    """读取系统级验证码 AI 配置。"""
    return {
        "enabled": settings_repo.get_verification_ai_enabled(),
        "base_url": settings_repo.get_verification_ai_base_url(),
        "api_key": settings_repo.get_verification_ai_api_key(),
        "model": settings_repo.get_verification_ai_model(),
    }


def is_verification_ai_config_complete(config: Dict[str, Any]) -> bool:
    return bool(
        (config or {}).get("enabled")
        and str((config or {}).get("base_url") or "").strip()
        and str((config or {}).get("api_key") or "").strip()
        and str((config or {}).get("model") or "").strip()
    )


def build_verification_ai_input_payload(
    email: Dict[str, Any],
    *,
    code_regex: str | None = None,
    code_length: str | None = None,
    code_source: str = "all",
) -> Dict[str, Any]:
    """构造固定 JSON 输入契约。"""
    return {
        "schema_version": VERIFICATION_AI_SCHEMA_VERSION,
        "task": "extract_verification",
        "mail": {
            "subject": str(email.get("subject") or ""),
            "text": extract_email_text(email),
            "html": str(email.get("body_html") or email.get("html_content") or ""),
        },
        "rules": {
            "code_regex": str(code_regex or ""),
            "code_length": str(code_length or ""),
        },
        "hints": {
            "code_source": str(code_source or "all"),
        },
    }


def _normalize_verification_ai_endpoint(base_url: str) -> str:
    value = str(base_url or "").strip()
    if not value:
        return ""
    if value.lower().endswith("/chat/completions"):
        return value
    return value.rstrip("/") + "/chat/completions"


def _parse_verification_ai_content(raw_content: str) -> Optional[Dict[str, Any]]:
    text = str(raw_content or "").strip()
    if not text:
        return None

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()

    try:
        payload = json.loads(text)
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None

    def _coerce_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value).strip()
        return ""

    def _normalize_confidence(value: Any) -> str:
        if isinstance(value, (int, float)):
            try:
                return "high" if float(value) >= 0.5 else "low"
            except Exception:
                return "low"
        if isinstance(value, bool):
            return "high" if value else "low"
        text = str(value or "").strip().lower()
        if text in {"high", "medium", "1", "true", "yes"}:
            return "high"
        return "low"

    verification_code = _coerce_text(payload.get("verification_code"))
    verification_link = _coerce_text(payload.get("verification_link"))
    if not verification_code and not verification_link:
        return None

    confidence = _normalize_confidence(payload.get("confidence"))
    reason_raw = payload.get("reason")
    reason = _coerce_text(reason_raw)
    if not reason and reason_raw not in (None, ""):
        try:
            reason = json.dumps(reason_raw, ensure_ascii=False)
        except Exception:
            reason = ""

    return {
        "schema_version": VERIFICATION_AI_SCHEMA_VERSION,
        "verification_code": verification_code,
        "verification_link": verification_link,
        "confidence": confidence,
        "reason": reason,
    }


def _call_verification_ai(ai_config: Dict[str, Any], ai_input: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    endpoint = _normalize_verification_ai_endpoint(str((ai_config or {}).get("base_url") or ""))
    api_key = str((ai_config or {}).get("api_key") or "").strip()
    model = str((ai_config or {}).get("model") or "").strip()
    if not endpoint or not api_key or not model:
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是验证码提取器。必须严格返回 JSON，且字段必须为："
                    "schema_version, verification_code, verification_link, confidence, reason。"
                    f"schema_version 固定为 {VERIFICATION_AI_SCHEMA_VERSION}。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(ai_input, ensure_ascii=False),
            },
        ],
    }

    try:
        response = requests.post(endpoint, headers=headers, json=body, timeout=6)
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not isinstance(choices, list) or not choices:
            return None
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            return None
        return _parse_verification_ai_content(content)
    except Exception as exc:
        _LOGGER.warning("verification_ai_call_failed: %s", exc)
        return None


def probe_verification_ai_runtime(
    *,
    ai_config: Dict[str, Any],
    sample_email: Optional[Dict[str, Any]] = None,
    code_regex: str | None = None,
    code_length: str | None = "6-6",
    code_source: str = "all",
    timeout_seconds: int = 8,
) -> Dict[str, Any]:
    """
    诊断用：主动探测系统级验证码 AI 配置是否可用。

    返回结构（不包含敏感信息）：
    - ok: bool
    - error: 错误类别（config_incomplete/http_error/request_failed/invalid_ai_output/invalid_response_format）
    - message: 人类可读说明
    - endpoint/model/http_status/latency_ms
    - parsed_output: 合法输出时返回固定 JSON 契约对象
    """
    endpoint = _normalize_verification_ai_endpoint(str((ai_config or {}).get("base_url") or ""))
    model = str((ai_config or {}).get("model") or "").strip()
    api_key = str((ai_config or {}).get("api_key") or "").strip()

    missing_fields: list[str] = []
    if not endpoint:
        missing_fields.append("verification_ai_base_url")
    if not api_key:
        missing_fields.append("verification_ai_api_key")
    if not model:
        missing_fields.append("verification_ai_model")
    if missing_fields:
        return {
            "ok": False,
            "error": "config_incomplete",
            "message": "验证码 AI 配置不完整",
            "missing_fields": missing_fields,
            "endpoint": endpoint,
            "model": model,
        }

    email_obj = sample_email or {
        "subject": "Verification test",
        "body": "Your verification code is 123456",
        "body_html": "<p>Your verification code is <b>123456</b></p>",
    }
    ai_input = build_verification_ai_input_payload(
        email_obj,
        code_regex=code_regex,
        code_length=code_length,
        code_source=code_source,
    )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是验证码提取器。必须严格返回 JSON，且字段必须为："
                    "schema_version, verification_code, verification_link, confidence, reason。"
                    f"schema_version 固定为 {VERIFICATION_AI_SCHEMA_VERSION}。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(ai_input, ensure_ascii=False),
            },
        ],
    }

    started = time.monotonic()
    try:
        response = requests.post(
            endpoint,
            headers=headers,
            json=body,
            timeout=max(1, int(timeout_seconds)),
        )
        latency_ms = int((time.monotonic() - started) * 1000)

        if response.status_code >= 400:
            response_preview = (response.text or "").strip()[:500]
            return {
                "ok": False,
                "error": "http_error",
                "message": f"AI 接口返回 HTTP {response.status_code}",
                "endpoint": endpoint,
                "model": model,
                "http_status": response.status_code,
                "latency_ms": latency_ms,
                "response_preview": response_preview,
            }

        try:
            payload = response.json()
        except Exception:
            response_preview = (response.text or "").strip()[:500]
            return {
                "ok": False,
                "error": "invalid_response_format",
                "message": "AI 接口返回非 JSON 响应",
                "endpoint": endpoint,
                "model": model,
                "http_status": response.status_code,
                "latency_ms": latency_ms,
                "response_preview": response_preview,
            }

        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not isinstance(choices, list) or not choices:
            return {
                "ok": False,
                "error": "invalid_response_format",
                "message": "AI 响应缺少 choices 字段",
                "endpoint": endpoint,
                "model": model,
                "http_status": response.status_code,
                "latency_ms": latency_ms,
            }

        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            return {
                "ok": False,
                "error": "invalid_response_format",
                "message": "AI 响应缺少 message.content",
                "endpoint": endpoint,
                "model": model,
                "http_status": response.status_code,
                "latency_ms": latency_ms,
            }

        parsed = _parse_verification_ai_content(content)
        if not parsed:
            return {
                "ok": False,
                "error": "invalid_ai_output",
                "message": "AI 输出不符合固定 JSON 契约",
                "endpoint": endpoint,
                "model": model,
                "http_status": response.status_code,
                "latency_ms": latency_ms,
                "response_preview": content.strip()[:500],
            }

        return {
            "ok": True,
            "message": "AI 配置测试成功",
            "endpoint": endpoint,
            "model": model,
            "http_status": response.status_code,
            "latency_ms": latency_ms,
            "parsed_output": parsed,
        }
    except Exception as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        return {
            "ok": False,
            "error": "request_failed",
            "message": f"AI 请求失败：{exc}",
            "endpoint": endpoint,
            "model": model,
            "latency_ms": latency_ms,
        }


def enhance_verification_with_ai_fallback(
    *,
    email: Dict[str, Any],
    extracted: Dict[str, Any],
    code_regex: str | None = None,
    code_length: str | None = None,
    code_source: str = "all",
    enforce_mutual_exclusion: bool = True,
) -> Dict[str, Any]:
    """
    规则优先、AI 回退：
    - 任一字段高置信即跳过 AI（方案 A：一个 high 就够了）
    - 仅在 code/link 均为 low 时才触发 AI
    - AI 无效/异常时快速回退规则结果
    """

    def _apply_output_policy(payload: Dict[str, Any]) -> Dict[str, Any]:
        """统一收口：强制 code/link 严格互斥并重算格式字段。"""
        normalized = dict(payload or {})

        # 产品策略：有 code（无论置信度）时，不返回 verification_link
        if enforce_mutual_exclusion and normalized.get("verification_code"):
            normalized["verification_link"] = None
            normalized["link_confidence"] = "low"

        parts = []
        if normalized.get("verification_code"):
            parts.append(str(normalized.get("verification_code")))
        if normalized.get("verification_link"):
            parts.append(str(normalized.get("verification_link")))
        normalized["formatted"] = " ".join(parts) if parts else None
        normalized["confidence"] = (
            "high" if normalized.get("code_confidence") == "high" or normalized.get("link_confidence") == "high" else "low"
        )
        return normalized

    result = dict(extracted or {})

    code_confidence = str(result.get("code_confidence") or "low").lower()
    link_confidence = str(result.get("link_confidence") or "low").lower()
    # 方案 A：任一 high 即跳过 AI，只有 both-low 才触发
    if code_confidence == "high" or link_confidence == "high":
        return _apply_output_policy(result)

    ai_config = get_verification_ai_runtime_config()
    if not is_verification_ai_config_complete(ai_config):
        return _apply_output_policy(result)

    ai_input = build_verification_ai_input_payload(
        email,
        code_regex=code_regex,
        code_length=code_length,
        code_source=code_source,
    )
    ai_output = _call_verification_ai(ai_config, ai_input)
    if not ai_output:
        return _apply_output_policy(result)

    ai_code = str(ai_output.get("verification_code") or "").strip()
    ai_link = str(ai_output.get("verification_link") or "").strip()
    ai_confidence = str(ai_output.get("confidence") or "low").strip().lower()
    ai_reason = str(ai_output.get("reason") or "").strip()

    updated = False
    if ai_code:
        result["verification_code"] = ai_code
        result["code_confidence"] = "high" if ai_confidence == "high" else "low"
        updated = True
    if ai_link:
        result["verification_link"] = ai_link
        result["link_confidence"] = "high" if ai_confidence == "high" else "low"
        links = result.get("links")
        links_list = links if isinstance(links, list) else []
        if ai_link not in links_list:
            links_list = list(links_list)
            links_list.append(ai_link)
        result["links"] = links_list
        updated = True

    if not updated:
        return _apply_output_policy(result)

    result["ai_schema_version"] = VERIFICATION_AI_SCHEMA_VERSION
    result["ai_reason"] = ai_reason
    result["ai_used"] = True

    return _apply_output_policy(result)
