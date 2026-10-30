"""Effective deal-journal coverage scoping, shared by the serving routers.

Semantics contract: harvest/denorm.py DEAL_FLAGS_SQL encodes the same rule
in raw SQL, and tests/test_deal_coverage.py pins the two to identical
results on one fixture. Change them together or not at all."""

from typing import Any

from sqlalchemy import case

from ..models import Deal, DealInstitution, DealJournal


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
