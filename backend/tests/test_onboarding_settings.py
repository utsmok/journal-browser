"""Fresh-clone onboarding: empty compose env values and the seeded
settings.yaml must both boot (2026-11-19 sweep, F1 and F2).

F1: compose injects empty strings for unset JB_* variables; with
env_ignore_empty those must parse as the built-in defaults.
F2: the entrypoint seeds settings.yaml from settings.yaml.example; YAML
nulls (bare `key:`) must mean "use the default", not crash validation and
not shadow the JB_* env fallback.
"""

from pathlib import Path

import pytest

from journal_browser.config import get_settings, reset_settings_cache

REPO_EXAMPLE = Path(__file__).resolve().parents[1] / "settings.yaml.example"


@pytest.fixture
def overlay_path(monkeypatch, tmp_path):
    """A hermetic overlay location and a clean cache per test, so results
    never leak into later tests. chdir keeps the developer checkout's
    backend/.env (env_file is cwd-relative) out of the settings."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "settings.yaml"))
    reset_settings_cache()
    yield tmp_path / "settings.yaml"
    reset_settings_cache()


def test_empty_env_values_parse_to_defaults(monkeypatch, tmp_path):
    """Compose passes unset variables through as ""; that must mean "use
    the default", not an empty list / int / bool parse error (F1)."""
    monkeypatch.chdir(tmp_path)  # keep a checkout .env out of the settings
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("JB_IGNORED_ISSNS", "")
    monkeypatch.setenv("JB_USAGE_RETENTION_DAYS", "")
    monkeypatch.setenv("JB_ENABLE_USAGE_TRACKING", "")
    s = get_settings()
    assert s.ignored_issns == []
    assert s.usage_retention_days == 90
    assert s.enable_usage_tracking is True


def test_null_overlay_keys_use_defaults(overlay_path, monkeypatch):
    """Bare keys (YAML null) keep the defaults and the env fallback: a null
    admin_password must not disable a JB_ADMIN_PASSWORD-set panel (F2)."""
    overlay_path.write_text(
        "admin_password:\njisc_api_key:\ncontact_email:\nut_metadata_dsn: postgresql://x\n",
        encoding="utf-8",
    )
    for var in ("JB_ADMIN_PASSWORD", "JB_CONTACT_EMAIL", "JB_JISC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("JB_ADMIN_PASSWORD", "envpw")
    monkeypatch.setenv("JB_CONTACT_EMAIL", "env@example.com")
    s = get_settings()
    assert s.admin_password == "envpw"
    assert s.contact_email == "env@example.com"
    assert s.jisc_api_key == ""
    assert s.ut_metadata_dsn == "postgresql://x"  # non-null values still win


def test_repo_example_yaml_boots(overlay_path):
    """The shipped settings.yaml.example (what the entrypoint copies on
    first boot) must load without a settings validation error (F2)."""
    overlay_path.write_bytes(REPO_EXAMPLE.read_bytes())
    s = get_settings()
    assert s.institution_code == "ut"
    assert s.data_window_end is None  # example's `0` = open-ended window
    assert s.admin_contact == ""
