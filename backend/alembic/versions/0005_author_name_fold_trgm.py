"""authors: trigram GIN index over the diacritic-folded lower(name), so
q search stays index-accelerated now that the predicate is substring OR
trigram word similarity (services/authors.py _q_cond: the folded
expression serves both the LIKE arm and the %> similarity arm).

Revision ID: 0005_author_name_fold_trgm
Revises: 0004_journal_listed_in
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_author_name_fold_trgm"
down_revision: str | None = "0004_journal_listed_in"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Must stay byte-identical to _FOLD_SRC/_FOLD_DST in
#: services/authors.py; the index serves the query only when the
#: expression matches exactly.
_FOLD_SRC = "áàâäãåéèêëíìîïóòôöõúùûüýÿñçšž"
_FOLD_DST = "aaaaaaeeeeiiiioooooouuuuyyncsz"


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_authors_name_fold_trgm ON authors "
        f"USING gin ((translate(lower(name), '{_FOLD_SRC}', '{_FOLD_DST}')) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_authors_name_fold_trgm", table_name="authors")
