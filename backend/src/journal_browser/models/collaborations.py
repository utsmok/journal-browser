"""Collaboration partners: the ROR institution canon and per-work links.

PartnerInstitution holds one row per partner ROR id. Rows the ROR harvest
filled carry the ROR record in payload; rows only a work payload named so
far (stub) leave payload null and keep the name that payload gave.

WorkPartner links an institution work to a partner ROR id. It is a derived
store: harvest.work_partners rebuilds it from the stored OpenAlex and
OpenAIRE work payloads, so nothing else writes to it.

FunderAlias resolves an OpenAIRE funder name to the OpenAlex funder it
names. harvest.funder_aliases rebuilds it from the stored OpenAlex awards
and OpenAIRE projects.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _tstamp

PARTNER_SOURCES = ("openalex", "openaire")


class PartnerInstitution(Base):
    """Partner canon keyed on the bare lowercase ROR id ("038v7xb98")."""

    __tablename__ = "partner_institutions"

    ror: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The most preferred ROR type (education, healthcare, facility,
    # government, company, nonprofit, archive, funder, other); null on stubs
    # that OpenAlex typed "unknown".
    org_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    country_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    parent_ror: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ROR status: active, inactive or withdrawn; null on stubs.
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    openalex_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The ROR record verbatim; null until the ROR harvest fetched this id.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = _tstamp()


class WorkPartner(Base):
    """One partner of one institution work.

    One work and one partner ROR id meet once, whatever the number of
    authorships or OpenAlex institution entries involved. source names the
    payload that supplied the link; openalex wins when both do.
    """

    __tablename__ = "work_partners"

    institution_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    work_pure_uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    # No foreign key: the derive runs before the ROR harvest fills the
    # canon, so a link can name a ROR id partner_institutions lacks.
    partner_ror: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    # Bare OpenAlex institution id of the entry that named the partner
    # ("I4210122839"); null for OpenAIRE links.
    partner_openalex_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # At least one authorship at this partner is a corresponding authorship.
    corresponding: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Author positions at this partner on the work.
    authorships: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    updated_at: Mapped[datetime] = _tstamp()

    __table_args__ = (
        ForeignKeyConstraint(
            ["institution_id", "work_pure_uuid"],
            ["works.institution_id", "works.pure_uuid"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            f"source in ({', '.join(repr(s) for s in PARTNER_SOURCES)})",
            name="work_partners_source_check",
        ),
        Index("ix_work_partners_partner", "partner_ror", "institution_id"),
    )


class FunderAlias(Base):
    """One OpenAIRE funder name resolved to the OpenAlex funder it names.

    OpenAIRE projects carry a funder name and no funder id, so the credit
    queries could not tell that an OpenAIRE name and an OpenAlex funder are
    one funder. Two rules give the OpenAlex funder: grant numbers the two
    sources share on the same works (grant), else a display name that
    matches (name). harvest.funder_aliases rebuilds the table.
    """

    __tablename__ = "funder_aliases"

    # The name as the project payload gives it.
    funder_name: Mapped[str] = mapped_column(Text, primary_key=True)
    # Bare OpenAlex funder id ("F4320321800").
    funder_openalex_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule: Mapped[str] = mapped_column(Text, nullable=False)
    # Works whose grant number both sources credit; 0 for a name match.
    works: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = _tstamp()

    __table_args__ = (
        CheckConstraint("rule in ('grant', 'name')", name="funder_aliases_rule_check"),
    )
