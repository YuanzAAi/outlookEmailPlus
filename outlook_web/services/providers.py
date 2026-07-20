from __future__ import annotations

from typing import Any, Dict, List, Optional

# 对齐：PRD-00005 / FD-00005 / TDD-00005 / PRD-00006 / FD-00006
# 职责：集中维护“邮箱提供商”元数据与 IMAP 文件夹映射，避免前后端重复维护默认 host/port 与 folder 兼容策略。

# 邮箱提供商配置（用于前端选择与默认 IMAP host/port）
MAIL_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "outlook": {
        "label": "Outlook",
        "imap_host": "outlook.live.com",
        "imap_port": 993,
        "account_type": "outlook",
        "note": "使用 OAuth2 认证（client_id + refresh_token）",
    },
    "gmail": {
        "label": "Gmail",
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "account_type": "imap",
        "note": "需开启 IMAP，并使用应用专用密码（非登录密码）",
    },
    "icloud": {
        "label": "iCloud",
        "imap_host": "imap.mail.me.com",
        "imap_port": 993,
        "account_type": "imap",
        "note": "需为 Apple ID 生成应用专用密码（非 Apple ID 登录密码）",
    },
    "qq": {
        "label": "QQ 邮箱",
        "imap_host": "imap.qq.com",
        "imap_port": 993,
        "account_type": "imap",
        "note": "需开启 IMAP 服务，使用授权码（非 QQ 密码）",
    },
    "163": {
        "label": "163 邮箱",
        "imap_host": "imap.163.com",
        "imap_port": 993,
        "account_type": "imap",
        "note": "需开启 IMAP 服务，使用授权码",
    },
    "126": {
        "label": "126 邮箱",
        "imap_host": "imap.126.com",
        "imap_port": 993,
        "account_type": "imap",
        "note": "需开启 IMAP 服务，使用授权码",
    },
    "yahoo": {
        "label": "Yahoo 邮箱",
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
        "account_type": "imap",
        "note": "需在账号安全设置中生成应用密码",
    },
    "aliyun": {
        "label": "阿里邮箱",
        "imap_host": "imap.aliyun.com",
        "imap_port": 993,
        "account_type": "imap",
        "note": "使用阿里邮箱登录密码",
    },
    "custom": {
        "label": "自定义 IMAP",
        "imap_host": "",
        "imap_port": 993,
        "account_type": "imap",
        "note": "请手动填写 IMAP 服务器地址和端口",
    },
}

# FD-00006: 域名 → provider 反向映射（用于 auto 模式域名推断）
DOMAIN_PROVIDER_MAP: Dict[str, str] = {
    # Gmail
    "gmail.com": "gmail",
    "googlemail.com": "gmail",
    # iCloud
    "icloud.com": "icloud",
    "me.com": "icloud",
    "mac.com": "icloud",
    # QQ
    "qq.com": "qq",
    "foxmail.com": "qq",
    # 163
    "163.com": "163",
    # 126
    "126.com": "126",
    # Yahoo
    "yahoo.com": "yahoo",
    "yahoo.co.jp": "yahoo",
    "yahoo.co.uk": "yahoo",
    "ymail.com": "yahoo",
    "rocketmail.com": "yahoo",
    "yahoo.ca": "yahoo",
    "yahoo.com.au": "yahoo",
    "yahoo.de": "yahoo",
    "yahoo.fr": "yahoo",
    "yahoo.it": "yahoo",
    "yahoo.es": "yahoo",
    "yahoo.in": "yahoo",
    "yahoo.co.in": "yahoo",
    # 阿里云
    "aliyun.com": "aliyun",
    "alimail.com": "aliyun",
    # 微软（2段格式按 IMAP 兜底处理，OAuth 至少4段）
    "outlook.com": "outlook",
    "hotmail.com": "outlook",
    "live.com": "outlook",
    "live.cn": "outlook",
}

# FD-00006: provider → 自动分组名映射
PROVIDER_GROUP_NAME: Dict[str, str] = {
    "outlook": "Outlook",
    "gmail": "Gmail",
    "icloud": "iCloud",
    "qq": "QQ邮箱",
    "163": "163邮箱",
    "126": "126邮箱",
    "yahoo": "Yahoo",
    "aliyun": "阿里云邮箱",
    "custom": "自定义IMAP",
    "temp_mail": "临时邮箱",
    "gptmail": "临时邮箱",
}

# FD-00006: 已知 provider key 集合（用于 3 段格式校验）
KNOWN_PROVIDER_KEYS: set = set(MAIL_PROVIDERS.keys())


def infer_provider_from_email(email: str) -> Optional[str]:
    """从邮箱地址推断 provider。返回 provider key 或 None。"""
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[-1].strip().lower()
    return DOMAIN_PROVIDER_MAP.get(domain)


# provider -> 逻辑文件夹名（inbox/junkemail/deleteditems）-> 候选 IMAP 文件夹名列表
PROVIDER_FOLDER_MAP: Dict[str, Dict[str, List[str]]] = {
    "gmail": {
        "inbox": ["INBOX"],
        "junkemail": ["[Gmail]/Spam", "[Gmail]/垃圾邮件"],
        "deleteditems": ["[Gmail]/Trash", "[Gmail]/已删除邮件"],
    },
    "icloud": {
        "inbox": ["INBOX"],
        "junkemail": ["Junk", "Junk E-mail"],
        "deleteditems": ["Deleted Messages", "Trash"],
    },
    "qq": {
        "inbox": ["INBOX"],
        "junkemail": ["Junk", "&V4NXPpCuTvY-"],
        "deleteditems": ["Deleted Messages", "&XfJT0ZABkK5O9g-"],
    },
    "163": {
        "inbox": ["INBOX"],
        "junkemail": ["&V4NXPpCuTvY-"],
        "deleteditems": ["&XfJT0ZABkK5O9g-"],
    },
    "yahoo": {
        "inbox": ["INBOX"],
        "junkemail": ["Bulk Mail"],
        "deleteditems": ["Trash"],
    },
    "_default": {
        "inbox": ["INBOX"],
        "junkemail": ["Junk", "Junk Email", "Spam", "SPAM", "Bulk Mail"],
        "deleteditems": ["Trash", "Deleted", "Deleted Messages"],
    },
}


def get_imap_folder_candidates(provider: str, folder: str) -> List[str]:
    """
    根据 provider 和逻辑文件夹名（inbox/junkemail/deleteditems），
    返回候选 IMAP 文件夹名列表（按优先级排序）。
    不存在的 provider 退回 _default。
    """
    provider_key = (provider or "").strip() or "_default"
    folder_key = (folder or "").strip().lower() or "inbox"

    folder_map = PROVIDER_FOLDER_MAP.get(provider_key, PROVIDER_FOLDER_MAP["_default"])
    return folder_map.get(folder_key, PROVIDER_FOLDER_MAP["_default"].get(folder_key, ["INBOX"]))


# FD-00009 / PR#27：provider 家族域名（用于 email_domain 级别邮箱过滤）
# 每个 provider 下列出所有常见公共域名；企业 onmicrosoft.com 通过前缀匹配额外处理。
PROVIDER_FAMILY_DOMAINS: Dict[str, List[str]] = {
    "outlook": ["outlook.com", "hotmail.com", "live.com", "live.cn"],
    "gmail": ["gmail.com", "googlemail.com"],
    "icloud": ["icloud.com", "me.com", "mac.com"],
    "qq": ["qq.com", "foxmail.com"],
    "163": ["163.com"],
    "126": ["126.com"],
    "yahoo": [
        "yahoo.com",
        "yahoo.co.jp",
        "yahoo.co.uk",
        "ymail.com",
        "rocketmail.com",
        "yahoo.ca",
        "yahoo.com.au",
        "yahoo.de",
        "yahoo.fr",
        "yahoo.it",
        "yahoo.es",
        "yahoo.in",
        "yahoo.co.in",
    ],
    "aliyun": ["aliyun.com", "alimail.com"],
}


def extract_email_domain(email: str) -> str:
    """从邮箱地址提取域名部分（小写）。"""
    if not email or "@" not in email:
        return ""
    return email.rsplit("@", 1)[-1].strip().lower()


def normalize_email_domain(domain: str) -> str:
    """规范化域名：去除空白、转小写。"""
    return (domain or "").strip().lower()


def provider_supports_email_domain(provider: str, email_domain: str) -> bool:
    """
    判断 provider 是否支持指定邮箱域名。

    覆盖两种情况：
    1. 公共域名：在 PROVIDER_FAMILY_DOMAINS 中直接命中。
    2. 企业 Outlook 域名：outlook provider 下以 .onmicrosoft.com 结尾的域名。
    """
    provider = (provider or "").strip().lower()
    domain = normalize_email_domain(email_domain)
    if not provider or not domain:
        return False
    known = PROVIDER_FAMILY_DOMAINS.get(provider, [])
    if domain in known:
        return True
    # 企业 Outlook 账号兜底
    if provider == "outlook" and domain.endswith(".onmicrosoft.com"):
        return True
    return False


def get_provider_domains(provider: str) -> List[str]:
    """返回指定 provider 的已知公共域名列表（不含企业域名）。"""
    return list(PROVIDER_FAMILY_DOMAINS.get((provider or "").strip().lower(), []))


def get_provider_list() -> List[Dict[str, Any]]:
    """返回供前端展示的 provider 列表（auto 在最前，outlook 其次，custom 在后）"""
    result: List[Dict[str, Any]] = [
        {
            "key": "auto",
            "label": "🔍 智能识别（混合导入）",
            "account_type": "mixed",
            "note": "自动识别每行的账号类型，支持混合文件一键导入",
        }
    ]
    order = ["outlook", "gmail", "icloud", "qq", "163", "126", "yahoo", "aliyun", "custom"]
    for key in order:
        if key not in MAIL_PROVIDERS:
            continue
        p = MAIL_PROVIDERS[key]
        result.append(
            {
                "key": key,
                "label": p.get("label", key),
                "account_type": p.get("account_type", "imap" if key != "outlook" else "outlook"),
                "note": p.get("note", ""),
            }
        )
    return result
