"""Jisc Open Policy Finder canon (harvest/jisc_opf.py).

Normalized Sherpa/OpenDOAR records: publication journals, publishers,
policies, funders, funder groups, repositories. Raw payloads live in
`source_records` (source `jisc_opf`); PKs are the provider's own ids.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _tstamp


class JiscPublication(Base):
    """OPF `publication` item: a journal with its publisher/policy links."""

    __tablename__ = "jisc_publications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    pub_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    listed_in_doaj: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    issns: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    publisher_ids: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    policy_ids: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    issn_l: Mapped[str | None] = mapped_column(String(9), nullable=True)
    date_modified: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    harvested_at: Mapped[datetime] = _tstamp()


class JiscPublisher(Base):
    """OPF `publisher` item; imprint_of_id mirrors the record's imprint link."""

    __tablename__ = "jisc_publishers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    ror: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imprint_of_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_modified: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    harvested_at: Mapped[datetime] = _tstamp()


class JiscPolicy(Base):
    """OPF `publisher_policy` item; permitted_oa kept as harvested JSON."""

    __tablename__ = "jisc_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    publisher_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_access_prohibited: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    internal_moniker: Mapped[str | None] = mapped_column(Text, nullable=True)
    urls: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    workflow_dates: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    permitted_oa: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    publication_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_modified: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    harvested_at: Mapped[datetime] = _tstamp()


class JiscFunder(Base):
    """OPF `funder` item with its OA policy blocks kept verbatim."""

    __tablename__ = "jisc_funders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    identifiers: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    publications_policy: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    data_archiving_policy: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    date_modified: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    harvested_at: Mapped[datetime] = _tstamp()


class JiscFunderGroup(Base):
    """OPF `funder_group` item; funders kept as the harvested JSON list."""

    __tablename__ = "jisc_funder_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    funders: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    date_modified: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    harvested_at: Mapped[datetime] = _tstamp()


class JiscRepository(Base):
    """OpenDOAR `repository` item (OPF `repository` type)."""

    __tablename__ = "jisc_repositories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    oai_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    software: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_subjects: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    content_types: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    full_text_record_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_record_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_modified: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    harvested_at: Mapped[datetime] = _tstamp()
