"""Pure CERIF entity tables: the standalone canon for author pages.

Soft ids throughout (Pure uuids as plain Text, no FK onto them) — the same
owner ruling as ut-metadata's core layer. These tables make the author
path work from journal-browser's own Pure OAI harvest: org tree (roots +
parents), person roster (parsed CERIF payloads), and work-level pure
authorship edges with their work affiliations.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _tstamp


class PureOrg(Base):
    """One orgunit of the institution's Pure org tree
    (openaire_cris_orgunits). identifiers keeps the CERIF identifier list
    verbatim — the institution ROR lives there, mirroring ut-metadata's
    org.ror."""

    __tablename__ = "pure_orgs"

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    org_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    identifiers: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    updated_at: Mapped[datetime] = _tstamp()


class PureOrgParent(Base):
    """Parent edge of one orgunit (the CERIF PartOf ref). parent_uuid is
    soft: a parent record can be absent (harvest order) without breaking
    the edge."""

    __tablename__ = "pure_org_parents"

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    org_uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    parent_uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    parent_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["institution_id", "org_uuid"],
            ["pure_orgs.institution_id", "pure_orgs.uuid"],
            ondelete="CASCADE",
        ),
    )


class PurePerson(Base):
    """One person of the institution's Pure roster (openaire_cris_persons).

    payload keeps the parsed CERIF person under {"cerif": …} — the same
    shape ut-metadata's person payloads use — so the shared identity
    derivation (faculty / research group / confirmed) runs unchanged on
    either source adapter."""

    __tablename__ = "pure_persons"

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    orcid: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = _tstamp()

    __table_args__ = (
        Index(
            "ix_pure_persons_inst_orcid",
            "institution_id",
            "orcid",
            postgresql_where=text("orcid IS NOT NULL"),
        ),
    )


class WorkPureAuthor(Base):
    """Pure's own author list of one local work: (work, person) edges over
    the stored CERIF Publication XML, with the person's work-level
    affiliation org uuids in payload order (the work-level arm of the
    roster/confirmation derivation) and the work-entry name spellings the
    identity cascade matches on."""

    __tablename__ = "work_pure_authors"

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    work_pure_uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    person_uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    # Position among the work's authors (0-based, CERIF payload order).
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    first_names: Mapped[str | None] = mapped_column(Text, nullable=True)
    family_names: Mapped[str | None] = mapped_column(Text, nullable=True)
    affiliations: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["institution_id", "work_pure_uuid"],
            ["works.institution_id", "works.pure_uuid"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_work_pure_authors_inst_person",
            "institution_id",
            "person_uuid",
        ),
    )
