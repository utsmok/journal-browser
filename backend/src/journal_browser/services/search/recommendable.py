"""Eligibility rule for journals offered as recommendations.

Browse and search list every OpenAlex venue above the corpus cutoff, but the
recommendation surfaces (journal-detail similar lists, author similar lists
and alternatives, the guided journal finder) only suggest a journal when it
passes both checks below. Measured on the live Twente corpus (2026-11-24):
144,869 browsable journals, 113,037 active, 61,325 recommendable.

- Active: OpenAlex counts at least one work in the current or previous
  calendar year (journals.last_active_year). Inactive titles are mostly
  ceased or renamed journals, for example Journal of Petroleum Science and
  Engineering (last works 2022) and SN Applied Sciences (2023).
- Vouched for: at least one curated source lists the journal. Scimago, DOAJ,
  a deal covering it for this institution, or an OpenAlex ``listed_in``
  entry (CWTS core, national lists such as Norway, JUFO, ANVUR, ERIH PLUS,
  MEDLINE, SciELO). Active journals without any listing are dominated by
  high-volume multidisciplinary titles such as International Journal For
  Multidisciplinary Research (20k works in 2025 and 2026, no listing).

Non-journal venues (book series, conferences) skip the listing check: the
curated lists cover journals only, and base_query already limits those
venues to ones with institution works.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, func, literal, or_
from sqlalchemy.dialects.postgresql import JSONB

from ...models import Journal

#: Calendar years that count as "active": the current and the previous one.
#: January data for the current year is thin, so one year alone is too strict.
ACTIVE_YEARS = 2

#: OpenAlex ``listed_in`` entries that do not vouch for a journal on their
#: own: the two lowest SINTA (Indonesian accreditation) tiers admit nearly
#: every applicant. Top single-listed titles in these tiers publish
#: thousands of works a year with no other listing.
WEAK_LISTINGS: tuple[str, ...] = ("sinta-s5", "sinta-s6")


def active_since(now: datetime | None = None) -> int:
    """Earliest last_active_year that still counts as active."""
    return (now or datetime.now(UTC)).year - (ACTIVE_YEARS - 1)


def recommendable_clause(deal_covered: Any) -> ColumnElement[bool]:
    """SQL condition: the Journal row may appear in a recommendation list.

    ``deal_covered`` is the institution-scoped coverage column (journal_flags)."""
    J = Journal
    weak = literal(list(WEAK_LISTINGS), type_=JSONB)
    listed = and_(
        func.jsonb_array_length(J.listed_in) > 0,
        ~J.listed_in.contained_by(weak),
    )
    return and_(
        J.last_active_year >= active_since(),
        or_(
            J.type != "journal",
            deal_covered.is_(True),
            J.in_scimago.is_(True),
            J.doaj_in_doaj.is_(True),
            J.is_in_doaj.is_(True),
            listed,
        ),
    )
