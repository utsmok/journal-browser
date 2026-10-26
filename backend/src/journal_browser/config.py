import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # populate_by_name: the admin API revalidates a model_dump() (field
    # names) through model_validate; alias-only lookup would reject those.
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="JB_", extra="ignore", populate_by_name=True
    )

    database_url: str = "postgresql+asyncpg://journal:journal@localhost:5433/journalbrowser"

    # ut-metadata Postgres (canonical Twente publications). Empty = the
    # feature is off: every endpoint keeps its works_stats-only behavior.
    # Connection is lazy and read-only; the app boots fine when unset or
    # unreachable.
    ut_metadata_dsn: str = ""
    # Reads the JB_-prefixed name or the common bare export in ~/.zshrc.
    openalex_api_key: str = Field(
        "", validation_alias=AliasChoices("JB_OPENALEX_API_KEY", "OPENALEX_API_KEY")
    )
    contact_email: str = Field(
        "s.f.abma@utwente.nl",
        validation_alias=AliasChoices("JB_CONTACT_EMAIL", "CONTACT_EMAIL"),
    )
    cors_origins: list[str] = ["http://localhost:3000"]

    # The browser's home institution (first-boot seed for the default
    # institutions row; afterwards the table is authoritative). Another
    # university sets these values and nothing else; display strings in the
    # frontend come from /meta. institution_code is the URL path segment
    # ([a-z0-9-]+), e.g. ut or rug.
    institution_code: str = "ut"
    institution_name: str = "University of Twente"
    institution_short: str = "Twente"
    institution_ror: str = "https://ror.org/006hf6230"
    library_url: str = "https://www.utwente.nl/library"
    oa_guide_url: str = (
        "https://www.utwente.nl/en/service-portal/university-library/"
        "publication-archiving/open-access"
    )
    support_email: str = "open-access@utwente.nl"
    # Personal contact shown in the footer; empty = row hidden.
    admin_contact: str | None = "s.mok@utwente.nl"
    research_portal_url: str = "https://research.utwente.nl"
    # Resolved OpenAlex institution id (I...). Empty = resolved from the ROR
    # on first harvest and stored in the institutions table.
    institution_openalex_id: str = ""

    # OpenAIRE organization id (openorgs____::...) for the product harvest.
    # Not derivable from the ROR; REQUIRED for another institution.
    openaire_org_id: str | None = None

    # Permanent raw landing zone for downloaded files (CSVs, HTML, JSON).
    landing_dir: str = "landing"

    # Admin panel password (/api/v1/admin + /admin). Empty = panel disabled.
    admin_password: str = ""

    # Curation report output path (reconcile job).
    curation_report_path: str = "landing/reports/curation_report.html"

    # Publication-year data window (inclusive). JB_DATA_WINDOW_START shrinks
    # a deployment's harvest (e.g. 2025); end 0 = open (to now).
    data_window_start: int = 2020
    data_window_end: int = 0

    # Bootstrap job mode: auto = only on an empty DB, always, off.
    bootstrap: str = "auto"

    # Feature flags. Both scaffolds stay OFF until explicitly enabled.
    enable_journal_citations: bool = False
    enable_jisc: bool = False
    jisc_api_key: str = ""

    # Pure OAI-PMH endpoint (anonymous) and request pacing.
    pure_oai_base_url: str = "https://ris.utwente.nl/ws/oai"
    pure_oai_min_spacing: float = 1.0

    # Admin-curated ISSN ignore-list (registry scaffold; consumed by
    # nothing yet).
    ignored_issns: list[str] = []

    @property
    def window_years(self) -> list[int]:
        """Inclusive publication-year window, capped at the current year."""
        import datetime as dt

        last = self.data_window_end or dt.date.today().year
        return list(range(self.data_window_start, min(last, dt.date.today().year) + 1))

    @property
    def ror_id(self) -> str:
        return self.institution_ror.rstrip("/").rsplit("/", 1)[-1]


# Settings overlay file: the admin panel's PUT writes here and every
# get_settings() call picks up edits live (mtime check). Env stays the
# fallback; YAML values win. Path override: JB_SETTINGS_YAML.
SETTINGS_YAML_ENV = "JB_SETTINGS_YAML"

_cache: dict[str, Any] = {}


def settings_yaml_path() -> Path:
    return Path(os.environ.get(SETTINGS_YAML_ENV, "settings.yaml"))


def load_settings_yaml() -> dict[str, Any]:
    """The overlay doc, {} when the file is missing or unreadable. YAML
    syntax errors still raise: a typo'd file must be visible, not silently
    dropped."""
    try:
        raw = settings_yaml_path().read_text(encoding="utf-8")
    except OSError:
        return {}
    data = yaml.safe_load(raw)
    return data if isinstance(data, dict) else {}


def get_settings() -> Settings:
    """Env-built Settings with settings.yaml merged over it. Reloads when
    the file's mtime changes, so admin edits land without a restart; with
    no file this is exactly the env behavior."""
    path = settings_yaml_path()
    try:
        mtime: float | None = path.stat().st_mtime
    except OSError:
        mtime = None
    if _cache.get("mtime") != mtime or "settings" not in _cache:
        base = Settings()
        overlay = load_settings_yaml() if mtime is not None else {}
        merged = {**base.model_dump(), **overlay}
        try:
            _cache["settings"] = Settings.model_validate(merged)
            # Only pin the mtime on success: a partial-file read retries.
            _cache["mtime"] = mtime
        except Exception:
            # In-place writes are not atomic: a concurrent read can catch a
            # truncated file. Keep the last good overlay until the write is
            # done (the next mtime check re-reads).
            if "settings" not in _cache:
                raise
    return _cache["settings"]


def reset_settings_cache() -> None:
    """Drop the cached Settings (the admin PUT after writing YAML; tests)."""
    _cache.clear()
