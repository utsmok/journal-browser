from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _tstamp


class Author(Base):
    """Per-institution researcher, ingested from an external
    canonical-publications database (ut-metadata core_author_link).

    Faculty / research_group / orgs are derived at ingest time (pure person
    CERIF affiliations, canonical-person augmentation as fallback); n_works
    counts stored edges to the institution's non-retired works. confirmed
    marks a CERIF affiliation resolving to the institution's ROR;
    last_pub_year and primary_topic derive from the stored work edges."""

    __tablename__ = "authors"

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    pure_uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    orcid: Mapped[str | None] = mapped_column(Text, nullable=True)
    openalex_author_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    openaire_person_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    crossref_orcid: Mapped[str | None] = mapped_column(Text, nullable=True)
    faculty: Mapped[str | None] = mapped_column(Text, nullable=True)
    research_group: Mapped[str | None] = mapped_column(Text, nullable=True)
    orgs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    # All known openalex author A-ids (primary + merged alternates) for the
    # author; the openalex-only live merge (services.authors) matches
    # authorships against this list.
    openalex_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    n_works: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    last_pub_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    primary_topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = _tstamp()


class AuthorWork(Base):
    """Author ↔ work membership, resolved via the external canonical work
    ids (work_authors) onto local works.pure_uuid. Full-replace per
    institution at ingest; retired works drop out on the next run."""

    __tablename__ = "author_works"

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    author_pure_uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    work_pure_uuid: Mapped[str] = mapped_column(Text, primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["institution_id", "author_pure_uuid"],
            ["authors.institution_id", "authors.pure_uuid"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["institution_id", "work_pure_uuid"],
            ["works.institution_id", "works.pure_uuid"],
            ondelete="CASCADE",
        ),
    )
