"""Verify Settings env vars stay aligned with .env.example and docker-compose.yml."""

from pathlib import Path

from journal_browser.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

# Settings intentionally omitted from docker-compose.yml / .env.example with reasons.
_ALLOWLIST_COMPOSE = frozenset(
    {
        # Harvest/test-only or compose-mounted overrides:
        "JB_AUTHOR_SOURCE",
        "JB_CORS_ORIGINS",
        "JB_CURATION_REPORT_PATH",
        "JB_INSTITUTION_OPENALEX_ID",
        # Pinned via ./backend/landing:/app/landing bind mount in compose:
        "JB_LANDING_DIR",
        "JB_OPENALEX_AUTHOR_SWEEP_MAX_AUTHORS",
        "JB_PURE_OAI_MIN_SPACING",
    }
)
_ALLOWLIST_ENV_EXAMPLE = frozenset(
    {
        "JB_AUTHOR_SOURCE",
        "JB_CORS_ORIGINS",
        "JB_CURATION_REPORT_PATH",
        "JB_INSTITUTION_OPENALEX_ID",
        "JB_OPENALEX_AUTHOR_SWEEP_MAX_AUTHORS",
        "JB_PURE_OAI_MIN_SPACING",
    }
)


def _env_var_name(field_name: str) -> str:
    if field_name == "openalex_api_key":
        return "OPENALEX_API_KEY"
    return f"JB_{field_name.upper()}"


def test_settings_fields_appear_in_compose_and_env_example():
    compose_text = COMPOSE.read_text(encoding="utf-8")
    env_example_text = ENV_EXAMPLE.read_text(encoding="utf-8")

    missing_compose = []
    missing_env_example = []
    for field_name in sorted(Settings.model_fields):
        var = _env_var_name(field_name)
        if var not in _ALLOWLIST_COMPOSE and var not in compose_text:
            missing_compose.append(var)
        if var not in _ALLOWLIST_ENV_EXAMPLE and var not in env_example_text:
            missing_env_example.append(var)

    assert not missing_compose, (
        f"Settings fields missing from docker-compose.yml: {missing_compose}"
    )
    assert not missing_env_example, (
        f"Settings fields missing from .env.example: {missing_env_example}"
    )
