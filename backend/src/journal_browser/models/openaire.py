"""OpenAIRE graph v3 canon entities."""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _tstamp


class OpenaireFunder(Base):
    """OpenAIRE graph v3 funder (jobs/harvest_openaire_funders.py).

    ror is the bare lowercase ROR id when the payload yields one, else
    NULL; joins openalex_funders.ror / jisc_funders.ror directly.
    """

    __tablename__ = "openaire_funders"

    openaire_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    short_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    website_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(Text, nullable=True)
    ror: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = _tstamp()


class OpenaireFunderStream(Base):
    """Top funding streams (funding level 0) per OpenAIRE funder.

    Harvested from the explore backend's facetSearch (portal-search
    projects): the level-0 facet values with project counts for each
    OPENAIRE_FUNDER_CODES entry. Top 10 per funder (facet cap); grant
    amounts are NOT harvested — the payloads leave them zero/missing for
    most funders, so sums would mislead."""

    __tablename__ = "openaire_funder_streams"

    funder_openaire_id: Mapped[str] = mapped_column(
        Text, ForeignKey("openaire_funders.openaire_id", ondelete="CASCADE"), primary_key=True
    )
    level0_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    n_projects: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = _tstamp()
