from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="JB_", extra="ignore")

    database_url: str = "postgresql+asyncpg://journal:journal@localhost:5433/journalbrowser"
    openalex_api_key: str = ""
    cors_origins: list[str] = ["http://localhost:3000"]

    # The browser's home institution. ROR + name are configuration, never
    # constants: another university sets these two values and nothing else.
    institution_name: str = "University of Twente"
    institution_ror: str = "https://ror.org/006hf6230"
    # Resolved OpenAlex institution id (I...). Empty = resolved from the ROR
    # on first harvest and stored in the institutions table.
    institution_openalex_id: str = ""

    # Permanent raw landing zone for downloaded files (CSVs, HTML, JSON).
    landing_dir: str = "landing"
    # Curation report output path (reconcile job).
    curation_report_path: str = "landing/reports/curation_report.html"

    # Feature flags. Both scaffolds stay OFF until explicitly enabled.
    enable_journal_citations: bool = False
    enable_jisc: bool = False
    jisc_api_key: str = ""

    @property
    def ror_id(self) -> str:
        """Bare ROR id ('006hf6230') from the full ROR URL."""
        return self.institution_ror.rstrip("/").rsplit("/", 1)[-1]


@lru_cache
def get_settings() -> Settings:
    return Settings()
