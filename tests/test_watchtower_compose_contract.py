"""Watchtower compose contract tests."""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class WatchtowerComposeContractTests(unittest.TestCase):
    def test_compose_sets_watchtower_docker_api_version_for_docker_29(self):
        content = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("DOCKER_API_VERSION=${WATCHTOWER_DOCKER_API_VERSION:-1.44}", content)

    def test_env_example_documents_watchtower_docker_api_override(self):
        content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("WATCHTOWER_DOCKER_API_VERSION=1.44", content)


if __name__ == "__main__":
    unittest.main()
