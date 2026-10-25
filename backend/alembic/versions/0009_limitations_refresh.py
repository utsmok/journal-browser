"""Limitations registry: add Pure/OpenAIRE/Crossref/corpus rows, refresh texts.

Revision ID: 0009_limitations_refresh
Revises: 0008_search_denorm
Create Date: 2026-10-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_limitations_refresh"
down_revision: Union[str, None] = "0008_search_denorm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_ROWS = [
    (
        "pure-canon-primary",
        "pure",
        "stats.works",
        "Publication counts per journal come from Pure, the university's research "
        "information system, and are the primary figure. The OpenAlex institution "
        "filter count is shown as a cross-check and can differ, because OpenAlex "
        "relies on affiliation matching.",
        "info",
        "https://research.utwente.nl",
    ),
    (
        "openaire-enrichment",
        "openaire",
        "works.enrichment",
        "OpenAIRE supplies alternative records and open access links for individual "
        "UT works during enrichment. It does not change journal-level counts.",
        "info",
        "https://openaire.eu",
    ),
    (
        "crossref-enrichment",
        "crossref",
        "works.enrichment",
        "Crossref resolves DOIs that OpenAlex does not return, so more UT works can "
        "be matched to a journal. It contributes metadata for matching only, not "
        "extra counts.",
        "info",
        "https://www.crossref.org",
    ),
    (
        "corpus-cutoff",
        "project",
        "search.corpus",
        "The search lists journals with more than 3 publications since 2020. OpenAlex "
        "tracks more journals than the browser shows; quiet journals stay in the "
        "database but out of search.",
        "info",
        "https://openalex.org",
    ),
]

# The deal register is owner-curated since 2026-10-23; the JCT dump is one
# historic input, not the source of truth.
JCT_HINT = (
    "The deal register is maintained by hand by the library. Journal lists were "
    "built from the owner-reviewed openaccess.nl snapshot and from the cOAlition S "
    "Journal Checker Tool dump, which only covers reviewed Plan S agreements. A deal "
    "can exist without a machine-readable journal list."
)

# Every registry row must carry at least one link (About page rule).
URLS = {
    "window-2020": "https://openalex.org",
    "openalex-coverage": "https://docs.openalex.org/",
    "openalex-corresponding": "https://docs.openalex.org/about-the-data/authors",
    "institution-affiliation": "https://docs.openalex.org/about-the-data/authors",
    "openapc-fallback": "https://github.com/OpenAPC/openapc-de",
    "issn-mapping": "https://portal.issn.org/",
}


def upgrade() -> None:
    stmt = sa.text(
        "INSERT INTO limitations (code, source, scope, hint, severity, url) "
        "VALUES (:code, :source, :scope, :hint, :severity, :url) "
        "ON CONFLICT (code) DO NOTHING"
    )
    for row in NEW_ROWS:
        op.execute(
            stmt.bindparams(
                code=row[0], source=row[1], scope=row[2], hint=row[3],
                severity=row[4], url=row[5],
            )
        )
    op.execute(
        sa.text("UPDATE limitations SET hint = :hint WHERE code = 'jct-coverage'")
        .bindparams(hint=JCT_HINT)
    )
    for code, url in URLS.items():
        op.execute(
            sa.text("UPDATE limitations SET url = :url WHERE code = :code AND url IS NULL")
            .bindparams(url=url, code=code)
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM limitations WHERE code IN "
        "('pure-canon-primary', 'openaire-enrichment', 'crossref-enrichment', 'corpus-cutoff')"
    )
