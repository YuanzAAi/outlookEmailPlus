"""ZER-90：统一验证码提取模块测试。"""

from __future__ import annotations

import unittest

from outlook_web.services.verification_code_extraction import (
    VerificationInput,
    VerificationPolicy,
    apply_confidence_gate,
    extract_verification,
    extract_verification_from_email_dict,
)


class VerificationCodeExtractionModuleTests(unittest.TestCase):
    def test_extract_lowercase_alphanumeric_code_with_policy_length(self):
        email = VerificationInput(subject="Your verification code", body="Your verification code is ab12cd")
        policy = VerificationPolicy(code_length="6-6", code_source="all")

        result = extract_verification(email, policy)

        self.assertEqual(result.get("verification_code"), "ab12cd")
        self.assertEqual(result.get("code_confidence"), "high")

    def test_extract_preserves_mixed_case(self):
        email = VerificationInput(body="Your verification code is Ab12Cd")
        policy = VerificationPolicy(code_length="6-6")

        result = extract_verification(email, policy)

        self.assertEqual(result.get("verification_code"), "Ab12Cd")

    def test_extract_japanese_chatgpt_code_from_body_preview(self):
        email = VerificationInput(
            subject="ChatGPT の一時的な認証コード",
            body_preview="この一時検証コードを入力して続行してください: 123456",
        )
        policy = VerificationPolicy(code_length="6-6", code_source="all")

        result = extract_verification(email, policy)

        self.assertEqual(result.get("verification_code"), "123456")
        self.assertEqual(result.get("code_confidence"), "high")

    def test_extract_unique_structured_code_without_language_keyword(self):
        email = VerificationInput(
            subject="إشعار تسجيل الدخول",
            body="أدخل الرقم المؤقت التالي للمتابعة: 654321. تنتهي صلاحيته قريبًا.",
        )
        policy = VerificationPolicy(code_length="6-6", code_source="all")

        result = extract_verification(email, policy)

        self.assertEqual(result.get("verification_code"), "654321")
        self.assertEqual(result.get("code_confidence"), "high")

    def test_extract_code_adjacent_to_non_latin_text(self):
        email = VerificationInput(subject="通知", body="临时号码123456")
        policy = VerificationPolicy(code_length="6-6", code_source="all")

        result = extract_verification(email, policy)

        self.assertEqual(result.get("verification_code"), "123456")
        self.assertEqual(result.get("code_confidence"), "high")

    def test_business_reference_number_remains_low_confidence(self):
        email = VerificationInput(subject="Order update", body="Order number: 445566.")
        policy = VerificationPolicy(code_length="6-6", code_source="all")

        result = extract_verification(email, policy)

        self.assertEqual(result.get("verification_code"), "445566")
        self.assertEqual(result.get("code_confidence"), "low")

    def test_plain_report_number_remains_low_confidence(self):
        email = VerificationInput(subject="System Report", body="There are 445566 active users this quarter.")
        policy = VerificationPolicy(code_length="6-6", code_source="all")

        result = extract_verification(email, policy)

        self.assertEqual(result.get("verification_code"), "445566")
        self.assertEqual(result.get("code_confidence"), "low")

    def test_multiple_structured_numbers_remain_low_confidence(self):
        email = VerificationInput(subject="إشعار", body="المرجع: 123456، والطلب: 654321.")
        policy = VerificationPolicy(code_length="6-6", code_source="all")

        result = extract_verification(email, policy)

        self.assertEqual(result.get("verification_code"), "123456")
        self.assertEqual(result.get("code_confidence"), "low")

    def test_url_token_remains_low_confidence(self):
        email = VerificationInput(
            subject="Account notice",
            body="Continue at https://example.com/session?token=AB1234",
        )
        policy = VerificationPolicy(code_length="6-6", code_source="all")

        result = extract_verification(email, policy)

        self.assertEqual(result.get("verification_code"), "AB1234")
        self.assertEqual(result.get("code_confidence"), "low")

    def test_extract_preview_when_graph_body_is_empty(self):
        result = extract_verification_from_email_dict(
            {
                "subject": "ChatGPT の一時的な認証コード",
                "bodyPreview": "この一時検証コードを入力してください: 123456",
            },
            code_length="6-6",
            code_source="all",
        )

        self.assertEqual(result.get("verification_code"), "123456")
        self.assertEqual(result.get("code_confidence"), "high")

    def test_extract_html_ignores_css_color_and_keeps_hyphen_code(self):
        email = VerificationInput(
            subject="Verification",
            body_html=(
                "<html><head><style>.title { color: #333333; }</style></head><body>"
                "<p>Your verification code is 84A-KMN</p>"
                "</body></html>"
            ),
        )
        policy = VerificationPolicy(code_length="6-6", code_source="all")

        result = extract_verification(email, policy)

        self.assertEqual(result.get("verification_code"), "84A-KMN")
        self.assertEqual(result.get("code_confidence"), "high")

    def test_apply_confidence_gate_strips_low_confidence_code(self):
        raw = {
            "verification_code": "123456",
            "verification_link": None,
            "code_confidence": "low",
            "link_confidence": "low",
        }
        gated = apply_confidence_gate(raw, enforce_mutual_exclusion=False)
        self.assertIsNone(gated.get("verification_code"))

    def test_expected_field_code_filters_link(self):
        email = VerificationInput(
            body="Your verification code is 123456 https://example.com/verify",
        )
        policy = VerificationPolicy(code_length="6-6", expected_field="code")

        result = extract_verification(email, policy)

        self.assertEqual(result.get("verification_code"), "123456")
        self.assertIsNone(result.get("verification_link"))
        self.assertEqual(result.get("formatted"), "123456")

    def test_legacy_wrapper_matches_unified_extractor(self):
        email = {
            "subject": "Validate your email",
            "body": "Please use the code below to validate your email address.\n\n84A-KMN",
        }

        unified = extract_verification(VerificationInput.from_email_dict(email), VerificationPolicy())
        legacy = extract_verification_from_email_dict(email)

        self.assertEqual(legacy.get("verification_code"), unified.get("verification_code"))
        self.assertEqual(legacy.get("code_confidence"), unified.get("code_confidence"))


if __name__ == "__main__":
    unittest.main()
