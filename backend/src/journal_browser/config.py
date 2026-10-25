from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="JB_", extra="ignore")

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

    # The browser's home institution. ROR + name are configuration, never
    # constants: another university sets these two values and nothing else.
    institution_name: str = "University of Twente"
    institution_ror: str = "https://ror.org/006hf6230"
    # Resolved OpenAlex institution id (I...). Empty = resolved from the ROR
    # on first harvest and stored in the institutions table.
    institution_openalex_id: str = ""

    # OpenAIRE organization id (openorgs____::...) for the product harvest.
    # Not derivable from the ROR; empty = the Twente id hardcoded in
    # harvest/openaire.py stays the default.
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

    @property
    def window_years(self) -> list[int]:
        """Inclusive publication-year window, capped at the current year."""
        import datetime as dt

        last = self.data_window_end or dt.date.today().year
        return list(range(self.data_window_start, min(last, dt.date.today().year) + 1))

    @property
    def ror_id(self) -> str:
        return self.institution_ror.rstrip("/").rsplit("/", 1)[-1]


@lru_cache
def get_settings() -> Settings:
    return Settings()
