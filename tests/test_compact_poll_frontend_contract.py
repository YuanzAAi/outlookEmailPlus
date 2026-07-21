"""tests/test_compact_poll_frontend_contract.py — B 类：前端契约测试

目标：验证简洁模式自动轮询功能所需的前端代码已正确存在：
  - main.js 变量声明与函数调用
  - i18n 属性（运行时 UI 文本）
  - JS 变量声明与函数定义
  - CSS 样式类
  - 事件监听
  注：简洁模式轮询拥有独立的设置面板（开关 + 间隔 + 最多次数）。
"""

from __future__ import annotations

import unittest

from tests._import_app import import_web_app_module


class CompactPollFrontendContractTests(unittest.TestCase):
    """B 类：前端契约测试 — 简洁模式自动轮询"""

    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def _login(self, client, password: str = "testpass123"):
        resp = client.post("/login", json={"password": password})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))

    def _get_text(self, client, path: str) -> str:
        resp = client.get(path)
        try:
            return resp.data.decode("utf-8")
        finally:
            resp.close()

    # ──────────────────────────────────────────────────────
    # TC-B01：index.html 包含简洁模式独立轮询设置面板
    # ──────────────────────────────────────────────────────

    def test_index_html_contains_compact_poll_settings_panel(self):
        """[Phase 3] 简洁模式独立面板已合并到标准轮询面板，compact 独立面板不再存在"""
        client = self.app.test_client()
        self._login(client)
        html = self._get_text(client, "/")

        # Phase 3: compact 独立面板已删除
        self.assertNotIn('id="enableCompactAutoPoll"', html)
        self.assertNotIn('id="compactPollInterval"', html)
        self.assertNotIn('id="compactPollMaxCount"', html)

        # 标准轮询面板仍然存在，范围已调整为 3-300
        self.assertIn('id="enableAutoPolling"', html)
        self.assertIn('id="pollingInterval"', html)
        self.assertIn('id="pollingCount"', html)
        self.assertIn('min="3" max="300"', html)

    # ──────────────────────────────────────────────────────
    # TC-B02：i18n.js 包含简洁模式运行时 UI 文本（按钮文本、Toast 等）
    # ──────────────────────────────────────────────────────

    def test_settings_panel_contains_i18n_attributes(self):
        """i18n.js 应包含简洁模式运行时所需的翻译词条（按钮/Toast 文本）"""
        client = self.app.test_client()
        js = self._get_text(client, "/static/js/i18n.js")

        self.assertIn("停止监听", js)
        self.assertIn("监听超时", js)
        self.assertIn("发现新邮件", js)
        self.assertIn("检测到验证码", js)

    # ──────────────────────────────────────────────────────
    # TC-B03：main.js 包含 3 个设置变量声明
    # ──────────────────────────────────────────────────────

    def test_main_js_declares_compact_poll_variables(self):
        """[Phase 3] compact 独立变量已废弃，main.js 只保留标准轮询变量"""
        client = self.app.test_client()
        js = self._get_text(client, "/static/js/main.js")

        # Phase 3: compact 独立变量已删除
        self.assertNotIn("let compactPollEnabled = false;", js)
        self.assertNotIn("let compactPollInterval = 10;", js)
        self.assertNotIn("let compactPollMaxCount = 5;", js)

        # 标准轮询变量仍然存在
        self.assertIn("let autoPollingEnabled = false;", js)
        self.assertIn("let maxPollingCount = 5;", js)
        self.assertIn("let pollingInterval = 10;", js)

    # ──────────────────────────────────────────────────────
    # TC-B04：main.js 包含 applyCompactPollSettings 调用
    # ──────────────────────────────────────────────────────

    def test_main_js_calls_apply_compact_poll_settings(self):
        """[Phase 3] main.js 通过 applyPollingSettings 统一调用引擎的 applyPollSettings"""
        client = self.app.test_client()
        js = self._get_text(client, "/static/js/main.js")

        # Phase 3: 不再直接调用 applyCompactPollSettings
        self.assertNotIn("applyCompactPollSettings", js)

        # 统一通过 applyPollingSettings → applyPollSettings 路径
        self.assertIn("applyPollingSettings", js)
        self.assertIn("applyPollSettings", js)

    # ──────────────────────────────────────────────────────
    # TC-B05：emails.js 包含 email-copied 事件派发
    # ──────────────────────────────────────────────────────

    def test_emails_js_dispatches_email_copied_event(self):
        """emails.js 的 copyEmail 函数中应派发 email-copied CustomEvent"""
        client = self.app.test_client()
        js = self._get_text(client, "/static/js/features/emails.js")

        self.assertIn("email-copied", js)
        self.assertIn("CustomEvent", js)

    # ──────────────────────────────────────────────────────
    # TC-B06：mailbox_compact.js 包含 email-copied 事件监听
    # ──────────────────────────────────────────────────────

    def test_mailbox_compact_js_listens_email_copied_event(self):
        """mailbox_compact.js 应监听 email-copied 事件以启动轮询"""
        client = self.app.test_client()
        js = self._get_text(client, "/static/js/features/mailbox_compact.js")

        self.assertIn("addEventListener('email-copied'", js)

    # ──────────────────────────────────────────────────────
    # TC-B07：mailbox_compact.js 包含核心函数声明
    # ──────────────────────────────────────────────────────

    def test_mailbox_compact_js_contains_core_functions(self):
        """mailbox_compact.js 应包含简洁模式 UI 函数，poll-engine.js 应包含核心引擎函数"""
        client = self.app.test_client()
        compact_js = self._get_text(client, "/static/js/features/mailbox_compact.js")
        engine_js = self._get_text(client, "/static/js/features/poll-engine.js")

        # 简洁模式 UI 函数（在 mailbox_compact.js 中）
        compact_funcs = [
            "startCompactAutoPoll",
            "stopCompactAutoPoll",
            "stopAllCompactAutoPolls",
            "updateSingleRowFromCache",
            "reapplyAllCompactPollUI",
            "applyCompactPollSettings",
            "applyCompactPollSettingsToRunningPolls",
            "findCompactAccountRow",
            "updateCompactPollUI",
        ]
        for func in compact_funcs:
            self.assertIn(
                f"function {func}",
                compact_js,
                f"mailbox_compact.js 缺少函数声明: {func}",
            )

        # 核心引擎函数（在 poll-engine.js 中）
        engine_funcs = [
            "startPoll",
            "pollSingleEmail",
            "stopPoll",
            "stopAllPolls",
            "startGlobalCountdown",
            "applyPollSettings",
        ]
        for func in engine_funcs:
            self.assertIn(
                f"function {func}",
                engine_js,
                f"poll-engine.js 缺少函数声明: {func}",
            )

    def test_standard_mailbox_reuses_initial_load_as_poll_baseline(self):
        client = self.app.test_client()
        accounts_js = self._get_text(client, "/static/js/features/accounts.js")
        engine_js = self._get_text(client, "/static/js/features/poll-engine.js")

        self.assertIn("baselineEmails: Array.isArray(currentEmails) ? currentEmails : []", accounts_js)
        self.assertIn("skipInitialFetch: true", accounts_js)
        self.assertIn("if (opts && opts.skipInitialFetch)", engine_js)

    def test_poll_toasts_are_short_and_transient_toasts_are_deduplicated(self):
        client = self.app.test_client()
        main_js = self._get_text(client, "/static/js/main.js")
        engine_js = self._get_text(client, "/static/js/features/poll-engine.js")
        compact_js = self._get_text(client, "/static/js/features/mailbox_compact.js")

        self.assertIn("var POLL_TOAST_DURATION = 1800", engine_js)
        self.assertIn("typeof persistent === 'number'", main_js)
        self.assertIn("item.dataset.toastKey === toastKey", main_js)
        self.assertIn("transientToasts.length - 4", main_js)
        self.assertNotIn("translateCompactText('开始监听') + ' ' + email", compact_js)

    # ──────────────────────────────────────────────────────
    # TC-B08：mailbox_compact.js 使用正确的行选择器 .mail-row
    # ──────────────────────────────────────────────────────

    def test_mailbox_compact_uses_mail_row_selector(self):
        """findCompactAccountRow 应使用 .mail-row 而非错误的 .compact-account-row"""
        client = self.app.test_client()
        js = self._get_text(client, "/static/js/features/mailbox_compact.js")

        # 不应出现错误的旧选择器
        self.assertNotIn(".compact-account-row", js)
        # 应使用正确的选择器
        self.assertIn(".mail-row", js)

    # ──────────────────────────────────────────────────────
    # TC-B09：mailbox_compact.js 不在 onclick 属性选择器中使用 CSS.escape
    # ──────────────────────────────────────────────────────

    def test_mailbox_compact_no_css_escape_in_attr_selector(self):
        """findCompactAccountRow 不应在 [onclick*=...] 中使用 CSS.escape(email)"""
        client = self.app.test_client()
        js = self._get_text(client, "/static/js/features/mailbox_compact.js")

        # [onclick*="..."] 是 HTML 属性子串匹配，不需要 CSS.escape
        self.assertNotIn("CSS.escape(email)", js)

    # ──────────────────────────────────────────────────────
    # TC-B10：i18n.js 包含所有新翻译词条
    # ──────────────────────────────────────────────────────

    def test_i18n_contains_compact_poll_translations(self):
        """i18n.js 应包含简洁模式自动轮询所需的所有中英文翻译词条"""
        client = self.app.test_client()
        js = self._get_text(client, "/static/js/i18n.js")

        required_translations = [
            # 运行状态类
            "停止监听",
            "监听超时，未检测到新邮件",
            "检测到验证码",
            "已复制到剪贴板",
            "发现新邮件",
            "拉取失败，已停止监听",
            "已停止监听",
            "账号已被删除，已停止监听",
            "页面元素丢失，已停止监听",
            # 英文对应词条
            "Stop Listening",
            "Monitoring timeout, no new email detected",
            "Verification code detected",
            "New email detected",
            # UI 面板类词条
            "Compact Mode Auto Polling",
            "Auto-monitor after copying email",
            "Range: 3-60 seconds",
            "Range: 0-100 times",
            "Max Poll Count",
        ]
        for text in required_translations:
            self.assertIn(text, js, f"i18n.js 缺少翻译词条: {text!r}")

    # ──────────────────────────────────────────────────────
    # TC-B11：main.css 包含轮询相关样式类
    # ──────────────────────────────────────────────────────

    def test_main_css_contains_compact_poll_styles(self):
        """main.css 应包含脉冲圆点与激活态按钮的轮询相关 CSS 类"""
        client = self.app.test_client()
        css = self._get_text(client, "/static/css/main.css")

        self.assertIn(".compact-poll-dot", css)
        self.assertIn(".compact-poll-active", css)
        self.assertIn("pulse-dot", css)

    # ──────────────────────────────────────────────────────
    # TC-B12：main.css 包含暗色模式适配
    # ──────────────────────────────────────────────────────

    def test_main_css_contains_dark_mode_compact_poll(self):
        """main.css 应包含暗色主题下轮询激活态按钮的覆盖样式"""
        client = self.app.test_client()
        css = self._get_text(client, "/static/css/main.css")

        self.assertIn('[data-theme="dark"] .pull-button.compact-poll-active', css)

    # ──────────────────────────────────────────────────────
    # TC-B13：mailbox_compact.js 包含 COMPACT_POLL_TOAST_DURATION 常量
    # ──────────────────────────────────────────────────────

    def test_mailbox_compact_has_toast_duration_constant(self):
        """mailbox_compact.js 应定义 COMPACT_POLL_TOAST_DURATION = 5000 常量"""
        client = self.app.test_client()
        js = self._get_text(client, "/static/js/features/mailbox_compact.js")

        self.assertIn("COMPACT_POLL_TOAST_DURATION", js)
        self.assertIn("5000", js)

    # ──────────────────────────────────────────────────────
    # TC-B14：poll-engine.js 包含 visibilitychange 监听
    #   注：visibilitychange 逻辑已从 mailbox_compact.js
    #   迁移至统一轮询引擎 poll-engine.js
    # ──────────────────────────────────────────────────────

    def test_mailbox_compact_listens_visibility_change(self):
        """poll-engine.js 应监听 visibilitychange 事件以支持后台暂停/恢复轮询"""
        client = self.app.test_client()
        js = self._get_text(client, "/static/js/features/poll-engine.js")

        self.assertIn("visibilitychange", js)
        self.assertIn("document.hidden", js)
