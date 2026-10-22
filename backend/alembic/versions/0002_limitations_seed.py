"""Seed the limitations registry.

Revision ID: 0002_limitations
Revises: a67cb288af46
Create Date: 2026-10-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_limitations"
down_revision: Union[str, None] = "a67cb288af46"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Registry rows are data: every number the UI renders links back to one of
# these caveats via its scope. Seeds are idempotent (no-op on conflict).
ROWS = [
    (
        "window-2020",
        "project",
        "global",
        "All publication statistics on this site cover publication years 2020 and later only.",
        "info",
        None,
    ),
    (
        "openalex-metrics",
        "openalex",
        "journals.summary_stats",
        "2yr mean citedness, h-index and i10-index are OpenAlex's native, openly computed journal metrics. They are not the JCR Impact Factor, CiteScore or SJR and must not be compared to them directly.",
        "warning",
        "https://help.openalex.org/hc/en-us/articles/26611033839895",
    ),
    (
        "openalex-oa-status",
        "openalex",
        "works.oa_status",
        "Gold/hybrid/green/bronze/diamond/closed is OpenAlex's classification. Bronze means free to read on the publisher site without a detected license; diamond means a non-APC fully open access venue.",
        "info",
        "https://help.openalex.org/hc/en-us/articles/24347207191767",
    ),
    (
        "openalex-coverage",
        "openalex",
        "works.counts",
        "OpenAlex coverage of publications is near-complete but not exact: very recent months and small venues may undercount.",
        "info",
        None,
    ),
    (
        "openalex-corresponding",
        "openalex",
        "stats.corresponding",
        "The corresponding-author split uses OpenAlex authorships.is_corresponding, an approximation based on author position and affiliation data.",
        "warning",
        None,
    ),
    (
        "institution-affiliation",
        "openalex",
        "stats.institution",
        "Institution publication counts rely on OpenAlex authorship affiliations; works whose affiliation is missing or malformed in OpenAlex are missed.",
        "info",
        None,
    ),
    (
        "jct-coverage",
        "jct",
        "deals.journals",
        "Deal journal lists come from the cOAlition S Journal Checker Tool public dump, which only contains reviewed, Plan S-compliant agreements. Deals missing there are flagged 'needs curation' rather than silently left empty.",
        "warning",
        "https://journalcheckertool.org/transformative-agreements/",
    ),
    (
        "openaccess-nl-prose",
        "openaccess.nl",
        "deals.narrative",
        "Caps, workflow steps, article types and conditions are parsed from openaccess.nl prose, which changes without notice. The linked deal page is authoritative.",
        "warning",
        "https://www.openaccess.nl/en/publishing/publisher-deals",
    ),
    (
        "openapc-coverage",
        "openapc",
        "apc.evidence",
        "OpenAPC records article-level costs as reported by participating institutions. Absence of rows does not mean zero cost, and amounts reflect what reporting institutions actually paid.",
        "warning",
        "https://github.com/OpenAPC/openapc-de",
    ),
    (
        "openapc-fallback",
        "openapc",
        "apc.fallback",
        "Where a deal states no explicit price, the journal-level figures shown are aggregates of OpenAPC rows across all reporting institutions, not an official price list.",
        "info",
        None,
    ),
    (
        "scimagojr-lag",
        "scimagojr",
        "journals.sjr",
        "SJR and quartile come from scimagojr.com (Scopus-based, CC-BY). The latest available year typically lags one to two years behind.",
        "info",
        "https://www.scimagojr.com",
    ),
    (
        "issn-mapping",
        "project",
        "deals.journals",
        "Journals are keyed by ISSN-L. Deal-list ISSNs that could not be resolved to a linking ISSN are flagged for curation instead of being dropped.",
        "info",
        None,
    ),
]


def upgrade() -> None:
    stmt = sa.text(
        "INSERT INTO limitations (code, source, scope, hint, severity, url) "
        "VALUES (:code, :source, :scope, :hint, :severity, :url) "
        "ON CONFLICT (code) DO NOTHING"
    )
    for row in ROWS:
        op.execute(stmt.bindparams(
            code=row[0], source=row[1], scope=row[2], hint=row[3],
            severity=row[4], url=row[5],
        ))


def downgrade() -> None:
    op.execute("DELETE FROM limitations")
