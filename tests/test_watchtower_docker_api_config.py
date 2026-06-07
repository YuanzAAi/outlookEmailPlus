"""Watchtower Docker API compatibility config regression tests."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_watchtower_sets_docker_api_version_for_docker_29():
    """Watchtower must not use its lower default API version against Docker 29+."""
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "DOCKER_API_VERSION=${WATCHTOWER_DOCKER_API_VERSION:-1.44}" in compose


def test_env_example_documents_watchtower_docker_api_version():
    """The optional override is documented for operators who need to tune it."""
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "WATCHTOWER_DOCKER_API_VERSION=1.44" in env_example
