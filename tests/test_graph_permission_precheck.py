"""
B 层：Graph API 权限预检测试

验证 graph.py 的 scope 解析和无权限跳过逻辑。
对应 TDD 矩阵 G-01 ~ G-06。

注意：权限预检功能尚未实现，本测试先行编写（TDD 红灯阶段）。
实现时需在 graph.py 新增 has_mail_read_permission() 并修改 get_access_token_graph_result 返回 scope。
"""

import unittest
from unittest.mock import MagicMock, patch


def _make_graph_token_response(access_token: str, scope: str = "", refresh_token: str = None):
    """构造 MS Graph token endpoint 的 mock Response"""
    resp = MagicMock()
    resp.status_code = 200
    body = {
        "access_token": access_token,
        "scope": scope,
        "token_type": "Bearer",
        "expires_in": 3599,
    }
    if refresh_token:
        body["refresh_token"] = refresh_token
    resp.json.return_value = body
    return resp


def _make_error_response(status: int = 400):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {"error": "invalid_grant"}
    resp.text = '{"error":"invalid_grant"}'
    resp.headers = {}
    return resp


def _make_aadsts90023_response():
    resp = MagicMock()
    resp.status_code = 400
    resp.json.return_value = {
        "error": "invalid_request",
        "error_description": "AADSTS90023: No applicable permissions were found for this user.",
        "error_codes": [90023],
    }
    resp.text = "AADSTS90023"
    resp.headers = {}
    return resp


def _make_aadsts9002313_response():
    resp = MagicMock()
    resp.status_code = 400
    resp.json.return_value = {
        "error": "invalid_grant",
        "error_description": "AADSTS9002313: Invalid request. Request is malformed or invalid.",
        "error_codes": [9002313],
    }
    resp.text = "AADSTS9002313"
    resp.headers = {}
    return resp


class TestGraphPermissionPrecheck(unittest.TestCase):
    """Graph API 权限预检测试"""

    # ------------------------------------------------------------------
    # has_mail_read_permission 工具函数测试
    # ------------------------------------------------------------------

    def test_has_mail_read_permission_true(self):
        """G-01: scope 含 Mail.Read → True"""
        from outlook_web.services.graph import has_mail_read_permission

        self.assertTrue(has_mail_read_permission("User.Read Mail.Read profile"))

    def test_has_mail_readwrite_permission_true(self):
        """G-02: scope 含 Mail.ReadWrite → True"""
        from outlook_web.services.graph import has_mail_read_permission

        self.assertTrue(has_mail_read_permission("Mail.ReadWrite User.Read"))

    def test_no_mail_permission_returns_false(self):
        """G-03: scope 无邮件权限 → False"""
        from outlook_web.services.graph import has_mail_read_permission

        self.assertFalse(has_mail_read_permission("User.Read profile openid email"))

    def test_empty_scope_returns_false(self):
        """G-04: scope 为空 → False"""
        from outlook_web.services.graph import has_mail_read_permission

        self.assertFalse(has_mail_read_permission(""))
        self.assertFalse(has_mail_read_permission(None))

    def test_scope_case_sensitive(self):
        """G-06: MS scope 区分大小写"""
        from outlook_web.services.graph import has_mail_read_permission

        self.assertFalse(has_mail_read_permission("mail.read user.read"))
        self.assertFalse(has_mail_read_permission("MAIL.READ"))

    # ------------------------------------------------------------------
    # get_access_token_graph_result 返回 scope 字段
    # ------------------------------------------------------------------

    @patch("outlook_web.services.graph.requests.post")
    def test_token_result_includes_scope(self, mock_post):
        """token 结果应包含 scope 字段"""
        from outlook_web.services.graph import get_access_token_graph_result

        mock_post.return_value = _make_graph_token_response("at-123", scope="User.Read Mail.Read profile")

        result = get_access_token_graph_result("cid", "rt", proxy_url=None)
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("scope"), "User.Read Mail.Read profile")

    @patch("outlook_web.services.graph.requests.post")
    def test_token_refresh_failure_returns_auth_expired(self, mock_post):
        """G-05: token 刷新失败 → 正常返回错误，不检查 scope"""
        from outlook_web.services.graph import get_access_token_graph_result

        mock_post.return_value = _make_error_response(400)

        result = get_access_token_graph_result("cid", "rt", proxy_url=None)
        self.assertFalse(result.get("success"))
        self.assertIsNone(result.get("scope"))

    @patch("outlook_web.services.graph.requests.post")
    def test_aadsts90023_retries_with_named_graph_scope(self, mock_post):
        """历史委托 token 遇到 90023 时应自动改用 Mail.Read scope。"""
        from outlook_web.services.graph import DEFAULT_GRAPH_NAMED_SCOPE, get_access_token_graph_result

        mock_post.side_effect = [
            _make_aadsts90023_response(),
            _make_graph_token_response("at-named", scope="Mail.Read offline_access"),
        ]

        result = get_access_token_graph_result("cid", "rt", proxy_url=None)

        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("access_token"), "at-named")
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(mock_post.call_args_list[1].kwargs["data"]["scope"], DEFAULT_GRAPH_NAMED_SCOPE)

    @patch("outlook_web.services.graph.requests.post")
    def test_aadsts9002313_does_not_retry_as_aadsts90023(self, mock_post):
        """其它 invalid_grant 错误不能误触发命名 scope 重试。"""
        from outlook_web.services.graph import get_access_token_graph_result

        mock_post.return_value = _make_aadsts9002313_response()

        result = get_access_token_graph_result("cid", "rt", proxy_url=None)

        self.assertFalse(result.get("success"))
        self.assertEqual(mock_post.call_count, 1)

    @patch("outlook_web.services.graph.requests.post")
    def test_refresh_rotation_retries_with_named_graph_scope(self, mock_post):
        """批量刷新与单账号刷新共用同一 scope 兼容策略。"""
        from outlook_web.services.graph import DEFAULT_GRAPH_NAMED_SCOPE, test_refresh_token_with_rotation

        mock_post.side_effect = [
            _make_aadsts90023_response(),
            _make_graph_token_response("at-named", scope="Mail.Read offline_access", refresh_token="rt-new"),
        ]

        success, error, new_refresh_token = test_refresh_token_with_rotation("cid", "rt", max_retries=0)

        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertEqual(new_refresh_token, "rt-new")
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(mock_post.call_args_list[1].kwargs["data"]["scope"], DEFAULT_GRAPH_NAMED_SCOPE)

    # ------------------------------------------------------------------
    # get_emails_graph 跳过无权限调用
    # ------------------------------------------------------------------

    @patch("outlook_web.services.graph.requests.get")
    @patch("outlook_web.services.graph.requests.post")
    def test_get_emails_graph_skips_api_when_no_permission(self, mock_post, mock_get):
        """无 Mail.Read 权限时不发起 Graph messages API 请求"""
        from outlook_web.services.graph import get_emails_graph

        mock_post.return_value = _make_graph_token_response("at-123", scope="User.Read profile openid email")

        result = get_emails_graph("cid", "rt", folder="inbox", skip=0, top=1)

        self.assertFalse(result.get("success"))
        self.assertTrue(result.get("no_mail_permission"))
        # Graph messages API 不应被调用
        mock_get.assert_not_called()

    @patch("outlook_web.services.graph.requests.get")
    @patch("outlook_web.services.graph.requests.post")
    def test_get_emails_graph_calls_api_when_has_permission(self, mock_post, mock_get):
        """有 Mail.Read 权限时正常调用 Graph API"""
        from outlook_web.services.graph import get_emails_graph

        mock_post.return_value = _make_graph_token_response("at-123", scope="User.Read Mail.Read profile")
        # Graph messages API 返回
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.json.return_value = {"value": []}
        mock_get.return_value = mock_get_resp

        result = get_emails_graph("cid", "rt", folder="inbox", skip=0, top=1)

        # Graph messages API 应被调用
        mock_get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
