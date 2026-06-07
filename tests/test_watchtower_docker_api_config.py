"""Watchtower Docker API compatibility config regression tests."""

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class WatchtowerDockerApiConfigTests(unittest.TestCase):
    def test_watchtower_sets_docker_api_version_for_docker_29(self):
        """Watchtower must not use its lower default API version against Docker 29+."""
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("DOCKER_API_VERSION=${WATCHTOWER_DOCKER_API_VERSION:-1.44}", compose)

    def test_env_example_documents_watchtower_docker_api_version(self):
        """The optional override is documented for operators who need to tune it."""
        env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

        self.assertIn("WATCHTOWER_DOCKER_API_VERSION=1.44", env_example)


if __name__ == "__main__":
    unittest.main()
