"""Regression: a stale key in settings.yaml must not break get_settings()."""

from pathlib import Path

from journal_browser.config import get_settings, reset_settings_cache


def test_stale_overlay_key_is_ignored(monkeypatch, tmp_path: Path):
    # enable_jisc shipped, then was deleted from Settings (clean cutover).
    # Overlays written before the removal still carry it and the live stack
    # reloads settings.yaml on mtime, so an unknown key must be ignored
    # (SettingsConfigDict extra="ignore"), never raise on reload.
    overlay = tmp_path / "settings.yaml"
    overlay.write_text("enable_jisc: false\ncontact_email: overlay@example.com\n", encoding="utf-8")
    monkeypatch.setenv("JB_SETTINGS_YAML", str(overlay))
    monkeypatch.setenv("JB_CONTACT_EMAIL", "env@example.com")
    reset_settings_cache()
    try:
        s = get_settings()
        assert s.contact_email == "overlay@example.com"
        assert "enable_jisc" not in type(s).model_fields
    finally:
        reset_settings_cache()
