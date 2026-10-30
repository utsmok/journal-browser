from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _tstamp


class Publisher(Base):
    __tablename__ = "publishers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    openalex_host_organization: Mapped[str | None] = mapped_column(Text, nullable=True)
    openaccess_nl_slug: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    aliases: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)


class OpenalexPublisher(Base):
    """OpenAlex publisher lineage cache (jobs/harvest_publishers.py).

    One row per publisher entity attempted; lineage is [self, ..., root]
    and canonical is the root (last element). A NULL lineage marks a fetch
    that failed (404 etc.), so re-runs skip it instead of retrying.
    """

    __tablename__ = "openalex_publishers"

    openalex_id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    lineage: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    canonical_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = _tstamp()


class Institution(Base):
    """Institution configuration carrier.

    Every row is a real-world institution (JCT sheets populate participation
    rows without a code); only hosted institutions carry `code` + `active`.
    Env vars seed the default row once; afterwards the table is
    authoritative.
    """

    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    short_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    ror: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    openalex_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-institution harvest sources.
    pure_oai_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    openaire_org_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional external canonical-works Postgres (ut-metadata style),
    # read-only. Empty = the enrichment degrades to works_stats-only.
    external_works_dsn: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Publication-year data window (inclusive); NULL end = open (to now).
    data_window_start: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("2020")
    )
    data_window_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Display fields served to the frontend via /meta/freshness.
    library_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    oa_guide_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    support_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_contact: Mapped[str | None] = mapped_column(Text, nullable=True)
    research_portal_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Hosted + served at /{code}/...; the env-seeded home institution resolves
    # by ROR, not by a flag.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Author search lists only authors whose Pure affiliation resolves to
    # this institution's ROR (authors.confirmed); profiles stay accessible.
    require_confirmed_affiliation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    @property
    def window_years(self) -> list[int]:
        """Inclusive publication-year window, capped at the current year."""
        import datetime as dt

        last = (
            self.data_window_end
            if self.data_window_end is not None
            else dt.date.today().year
        )
        return list(range(self.data_window_start, min(last, dt.date.today().year) + 1))


class IssnMap(Base):
    """ISSN → ISSN-L resolution index, harvested from OpenAlex sources."""

    __tablename__ = "issn_map"

    issn: Mapped[str] = mapped_column(String(9), primary_key=True)
    issn_l: Mapped[str] = mapped_column(String(9), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = _tstamp()


# ── Deals (the core) ────────────────────────────────────────────────────────
