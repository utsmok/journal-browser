"""Effective deal-journal coverage scoping, shared by the serving routers.

Semantics contract: harvest/denorm.py DEAL_FLAGS_SQL encodes the same rule
in raw SQL, and tests/test_deal_coverage.py pins the two to identical
results on one fixture. Change them together or not at all."""

from typing import Any

from sqlalchemy import case, func, select

from ..models import ApcEvidence, Deal, DealInstitution, DealJournal, Work
from ..schemas import DealOut
from ..services.works_query import work_type_not_excluded, work_window

#: DealOut fields that map 1:1 onto Deal columns (the detail path getattrs
#: them); excludes the computed register extras. Set-equal to the column
#: list, verified against Deal.__table__.columns 2026-10-30.
_DEAL_OUT_EXTRAS = {"publisher_name", "covers_in_group", "journal_count", "apc_euro_total", "apc_n"}
DEAL_FIELDS = [k for k in DealOut.model_fields if k not in _DEAL_OUT_EXTRAS]


def dj_scope(institution_id: int) -> Any:
    """This institution's effective deal_journals rows: the shared sheet
    (institution_id NULL) unless the participation row opts into a scoped
    override list."""
    return DealJournal.institution_id.is_not_distinct_from(
        case((DealInstitution.journal_override.is_(True), institution_id), else_=None)
    )


def deal_institution_join(institution_id: int) -> Any:
    """Participation join condition from Deal to this institution."""
    return (DealInstitution.deal_id == Deal.id) & (DealInstitution.institution_id == institution_id)


def covered_join(institution_id: int):
    """JOIN clauses: participation row + effective (override-aware) list."""

    def covered(q):
        return (
            q.join(DealInstitution, deal_institution_join(institution_id))
            # LEFT JOIN: a participating deal shows even when its
            # effective journal list is empty (count 0). Admin-excluded
            # journals stay out of counts and membership everywhere.
            .outerjoin(
                DealJournal,
                (DealJournal.deal_id == Deal.id)
                & dj_scope(institution_id)
                & DealJournal.excluded.is_not(True),
            )
        )

    return covered


def apc_agg(institution: Any):
    """Per-deal APC spend subquery: the institution's works in the deal's
    effective journal list, latest-period evidence per DOI (mirror of the
    orgunit APC aggregation). Gated like every sibling works population:
    retired rows dropped, data-window years only."""
    institution_id = institution.id
    # djs needs this institution's participation row in scope: dj_scope
    # reads its journal_override to pick shared vs scoped rows.
    djs = (
        select(DealJournal.deal_id, DealJournal.issn_l)
        .select_from(DealJournal)
        .join(
            DealInstitution,
            (DealInstitution.deal_id == DealJournal.deal_id)
            & (DealInstitution.institution_id == institution_id),
        )
        .where(dj_scope(institution_id), DealJournal.excluded.is_not(True))
        .subquery()
    )
    win_lo, win_hi = work_window(institution)
    ranked = (
        select(
            djs.c.deal_id,
            ApcEvidence.euro.label("euro"),
            func.row_number()
            .over(
                partition_by=(djs.c.deal_id, ApcEvidence.doi),
                order_by=(ApcEvidence.period.desc().nulls_last(), ApcEvidence.id.desc()),
            )
            .label("rn"),
        )
        .select_from(djs)
        .join(
            Work,
            (Work.institution_id == institution_id)
            & (Work.journal_issn_l == djs.c.issn_l)
            & Work.doi_normalized.is_not(None)
            & Work.retired_at.is_(None)
            # APC euros match works, so the matched set must describe the
            # same population as every other works count.
            & work_type_not_excluded(Work.work_type)
            & win_lo
            & win_hi,
        )
        .join(
            ApcEvidence,
            (ApcEvidence.institution_id == institution_id)
            & (ApcEvidence.doi == Work.doi_normalized),
        )
        .subquery()
    )
    return (
        select(
            ranked.c.deal_id,
            func.coalesce(func.sum(ranked.c.euro), 0).label("apc_euro_total"),
            func.count(ranked.c.euro).label("apc_n"),
        )
        .where(ranked.c.rn == 1)
        .group_by(ranked.c.deal_id)
        .subquery()
    )
