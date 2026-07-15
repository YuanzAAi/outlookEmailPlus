from __future__ import annotations

import unittest

from outlook_web.services import verification_code_extraction as core
from outlook_web.services import verification_extractor as compat


class VerificationCodeExtractionModuleTests(unittest.TestCase):
    def test_unified_module_preserves_mixed_case_and_matches_compat_entrypoint(self):
        email = {
            "subject": "Your verification code",
            "body": "Your verification code is Ab12Cd.",
            "body_html": "",
        }
        policy = core.VerificationPolicy(code_length="6-6", code_source="all")

        module_result = core.extract_verification(core.VerificationInput.from_email(email), policy)
        compat_result = compat.extract_verification_info_with_options(email, code_length="6-6", code_source="all")

        self.assertEqual(module_result.get("verification_code"), "Ab12Cd")
        self.assertEqual(module_result.get("verification_code"), compat_result.get("verification_code"))
        self.assertEqual(module_result.get("code_confidence"), compat_result.get("code_confidence"))

    def test_unified_module_ignores_css_color_and_extracts_context_hyphenated_code(self):
        email = {
            "subject": "Validate your email",
            "body": "",
            "body_html": (
                "<html><head><style>.title { color: #333333; }</style></head><body>"
                "<p>Please use the code below to validate your email address.</p>"
                "<p>84A-KMN</p>"
                "</body></html>"
            ),
        }
        result = core.extract_verification(
            core.VerificationInput.from_email(email),
            core.VerificationPolicy(code_source="all"),
        )

        self.assertEqual(result.get("verification_code"), "84A-KMN")
        self.assertEqual(result.get("code_confidence"), "high")


if __name__ == "__main__":
    unittest.main()
