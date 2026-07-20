import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class ReleaseWorkflowContractTests(unittest.TestCase):
    def test_publish_workflow_uses_stable_fork_image_name_and_quality_gates(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "docker-build-push.yml").read_text(encoding="utf-8")

        self.assertIn('ghcr.io/${GITHUB_REPOSITORY_OWNER,,}/outlook-email-plus"', workflow)
        self.assertNotIn("outlook-email-plus-patch", workflow)
        self.assertIn("needs: [quality-gate, image-smoke]", workflow)
        self.assertIn("report-publish-status:", workflow)
        self.assertIn("if: always()", workflow)

    def test_upstream_sync_pushes_only_after_candidate_verification_without_manual_duplicate_build(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "upstream-sync.yml").read_text(encoding="utf-8")

        self.assertIn("docker build --pull -t outlook-email-plus:upstream-sync .", workflow)
        self.assertIn("Push verified merge", workflow)
        self.assertIn("git push origin HEAD:main", workflow)
        self.assertNotIn("gh workflow run docker-build-push.yml", workflow)
        self.assertIn("report-sync-status:", workflow)

    def test_sonar_workflow_skips_cleanly_when_fork_secrets_are_missing(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "sonar.yml").read_text(encoding="utf-8")

        self.assertIn("Check Sonar configuration", workflow)
        self.assertIn("SONAR_TOKEN or SONAR_HOST_URL is not configured for this fork.", workflow)
        self.assertIn("if: steps.config.outputs.enabled == 'true'", workflow)


if __name__ == "__main__":
    unittest.main()
