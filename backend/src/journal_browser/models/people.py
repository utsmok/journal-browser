"""people.utwente.nl person profiles, matched to authors (jobs/harvest_people_utwente.py).

One row per author the people-pages harvest attempted, keyed by the
author's pure uuid (= pure_persons.uuid). A match is uuid-verified: the
scraped profile page links the person's public Pure portal profile
(research.utwente.nl/en/persons/<pure uuid>) and that uuid must equal the
author's. Name-only matches that cannot be uuid-verified land as
'candidate' for admin review (author_identities source='people'); a page
whose portal uuid differs from the author's is a different person —
'missed'. Statuses ride one row so re-runs skip attempted authors.

Scraped orgs are also resolved onto pure_orgs and stored in
people_utwente_person_orgs — gap-fill evidence only, mirroring
pure_person_orgs: the derive pipeline reads it through dedicated arms
after native CERIF resolution and never overrides a native result.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _tstamp


class PeopleUtwentePerson(Base):
    """One people.utwente.nl harvest outcome for an author.

    status 'matched' = uuid-verified (served on the author page);
    'candidate' = name-matched but unverifiable (admin review via
    author_identities source='people', promoted rows are served too);
    'missed' = no page, or every same-named page belongs to someone else
    (portal uuid mismatch). Misses keep their row so re-runs skip them.
    """

    __tablename__ = "people_utwente_persons"

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    person_uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="missed")
    # The people page slug (data-link / email local part); None on misses.
    slug: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Scraped org linklist: [{"name": ..., "abbr": ...}], faculty first.
    orgs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    faculty_abbr: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The profile's public Pure portal link — the match oracle and the
    # author page's "Research portal" link when no people row exists.
    portal_person_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_media_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    # AVIF/PNG/JPEG bytes, magic-byte sniffed, ≤1 MB (avatar cap).
    photo_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    match_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Why a run produced no match ("no_candidates", "uuid_mismatch", ...).
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime] = _tstamp()

    __table_args__ = (
        ForeignKeyConstraint(
            ["institution_id", "person_uuid"],
            ["pure_persons.institution_id", "pure_persons.uuid"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('matched', 'candidate', 'missed')",
            name="ck_people_utwente_persons_status",
        ),
        Index(
            "ux_people_utwente_persons_inst_slug",
            "institution_id",
            "slug",
            unique=True,
            postgresql_where=text("slug IS NOT NULL"),
        ),
    )


class PeopleUtwentePersonOrg(Base):
    """One people-page org resolved onto a pure_org.

    Gap-fill evidence only, exactly like pure_person_orgs: the derive
    arms consult it after native CERIF resolution; profiles, the roster,
    and ROR confirmation are never overridden. people_slug records the
    source page; org_abbr the scraped abbreviation ("BMS-HBE-ETM").
    """

    __tablename__ = "people_utwente_person_orgs"

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    person_uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    org_uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    people_slug: Mapped[str] = mapped_column(Text, nullable=False)
    org_abbr: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["institution_id", "person_uuid"],
            ["pure_persons.institution_id", "pure_persons.uuid"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["institution_id", "org_uuid"],
            ["pure_orgs.institution_id", "pure_orgs.uuid"],
            ondelete="CASCADE",
        ),
    )
