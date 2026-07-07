"""tests/test_domain_provider_map.py — FD-00006 域名推断单元测试"""

import unittest


class TestDomainProviderMap(unittest.TestCase):
    def test_infer_gmail(self):
        from outlook_web.services.providers import infer_provider_from_email

        self.assertEqual(infer_provider_from_email("user@gmail.com"), "gmail")
        self.assertEqual(infer_provider_from_email("user@googlemail.com"), "gmail")

    def test_infer_qq(self):
        from outlook_web.services.providers import infer_provider_from_email

        self.assertEqual(infer_provider_from_email("user@qq.com"), "qq")
        self.assertEqual(infer_provider_from_email("user@foxmail.com"), "qq")

    def test_infer_163(self):
        from outlook_web.services.providers import infer_provider_from_email

        self.assertEqual(infer_provider_from_email("user@163.com"), "163")

    def test_infer_126(self):
        from outlook_web.services.providers import infer_provider_from_email

        self.assertEqual(infer_provider_from_email("user@126.com"), "126")

    def test_infer_yahoo(self):
        from outlook_web.services.providers import infer_provider_from_email

        self.assertEqual(infer_provider_from_email("user@yahoo.com"), "yahoo")
        self.assertEqual(infer_provider_from_email("user@yahoo.co.jp"), "yahoo")

    def test_infer_aliyun(self):
        from outlook_web.services.providers import infer_provider_from_email

        self.assertEqual(infer_provider_from_email("user@aliyun.com"), "aliyun")
        self.assertEqual(infer_provider_from_email("user@alimail.com"), "aliyun")

    def test_infer_outlook(self):
        from outlook_web.services.providers import infer_provider_from_email

        self.assertEqual(infer_provider_from_email("user@outlook.com"), "outlook")
        self.assertEqual(infer_provider_from_email("user@hotmail.com"), "outlook")
        self.assertEqual(infer_provider_from_email("user@live.com"), "outlook")
        self.assertEqual(infer_provider_from_email("user@live.cn"), "outlook")

    def test_infer_unknown_domain(self):
        from outlook_web.services.providers import infer_provider_from_email

        self.assertIsNone(infer_provider_from_email("user@unknown.org"))
        self.assertIsNone(infer_provider_from_email("user@company.co"))

    def test_infer_invalid_input(self):
        from outlook_web.services.providers import infer_provider_from_email

        self.assertIsNone(infer_provider_from_email(""))
        self.assertIsNone(infer_provider_from_email(None))
        self.assertIsNone(infer_provider_from_email("no-at-sign"))

    def test_extract_and_normalize_email_domain(self):
        from outlook_web.services.providers import extract_email_domain, normalize_email_domain

        self.assertEqual(extract_email_domain("User@HotMail.COM"), "hotmail.com")
        self.assertEqual(normalize_email_domain(" HotMail.COM "), "hotmail.com")
        self.assertEqual(normalize_email_domain("user@live.com"), "live.com")

    def test_provider_supports_email_domain(self):
        from outlook_web.services.providers import provider_supports_email_domain

        self.assertTrue(provider_supports_email_domain("outlook", "hotmail.com"))
        self.assertTrue(provider_supports_email_domain("outlook", "HotMail.COM"))
        self.assertFalse(provider_supports_email_domain("gmail", "hotmail.com"))

    def test_known_provider_keys(self):
        from outlook_web.services.providers import KNOWN_PROVIDER_KEYS, MAIL_PROVIDERS

        self.assertEqual(KNOWN_PROVIDER_KEYS, set(MAIL_PROVIDERS.keys()))
        self.assertIn("outlook", KNOWN_PROVIDER_KEYS)
        self.assertIn("gmail", KNOWN_PROVIDER_KEYS)
        self.assertIn("custom", KNOWN_PROVIDER_KEYS)

    def test_provider_group_name(self):
        from outlook_web.services.providers import PROVIDER_GROUP_NAME

        self.assertEqual(PROVIDER_GROUP_NAME["outlook"], "Outlook")
        self.assertEqual(PROVIDER_GROUP_NAME["temp_mail"], "临时邮箱")

    def test_get_provider_list_has_auto_first(self):
        from outlook_web.services.providers import get_provider_list

        providers = get_provider_list()
        self.assertGreater(len(providers), 0)
        self.assertEqual(providers[0]["key"], "auto")
        self.assertEqual(providers[0]["account_type"], "mixed")
        # auto 不应出现在第二个及以后的位置
        keys = [p["key"] for p in providers]
        self.assertEqual(keys.count("auto"), 1)

    # ── PR#27 新增：provider_supports_email_domain / extract_email_domain 测试 ──

    def test_extract_email_domain_basic(self):
        from outlook_web.services.providers import extract_email_domain

        self.assertEqual(extract_email_domain("user@outlook.com"), "outlook.com")
        self.assertEqual(extract_email_domain("USER@GMAIL.COM"), "gmail.com")
        self.assertEqual(extract_email_domain("x@a.b.c"), "a.b.c")
        self.assertEqual(extract_email_domain("no-at-sign"), "")
        self.assertEqual(extract_email_domain(""), "")

    def test_provider_supports_email_domain_public_domains(self):
        from outlook_web.services.providers import provider_supports_email_domain

        self.assertTrue(provider_supports_email_domain("outlook", "outlook.com"))
        self.assertTrue(provider_supports_email_domain("outlook", "hotmail.com"))
        self.assertTrue(provider_supports_email_domain("gmail", "gmail.com"))
        self.assertTrue(provider_supports_email_domain("qq", "qq.com"))
        self.assertTrue(provider_supports_email_domain("qq", "foxmail.com"))
        self.assertFalse(provider_supports_email_domain("gmail", "outlook.com"))
        self.assertFalse(provider_supports_email_domain("qq", "gmail.com"))

    def test_provider_supports_email_domain_enterprise_outlook(self):
        from outlook_web.services.providers import provider_supports_email_domain

        # 企业 onmicrosoft.com 应被 outlook provider 支持
        self.assertTrue(provider_supports_email_domain("outlook", "myorg.onmicrosoft.com"))
        self.assertTrue(provider_supports_email_domain("outlook", "corp.onmicrosoft.com"))
        # 非 outlook provider 不支持
        self.assertFalse(provider_supports_email_domain("gmail", "myorg.onmicrosoft.com"))

    def test_provider_supports_email_domain_edge_cases(self):
        from outlook_web.services.providers import provider_supports_email_domain

        self.assertFalse(provider_supports_email_domain("", "outlook.com"))
        self.assertFalse(provider_supports_email_domain("outlook", ""))
        self.assertFalse(provider_supports_email_domain("outlook", None))

    def test_get_provider_domains(self):
        from outlook_web.services.providers import get_provider_domains

        outlook_domains = get_provider_domains("outlook")
        self.assertIn("outlook.com", outlook_domains)
        self.assertIn("hotmail.com", outlook_domains)
        gmail_domains = get_provider_domains("gmail")
        self.assertIn("gmail.com", gmail_domains)
        unknown_domains = get_provider_domains("nonexistent")
        self.assertEqual(unknown_domains, [])


if __name__ == "__main__":
    unittest.main()
