"""Seed DOAJ limitations: the OA-model canon and its declared APC prices.

Revision ID: 0030_doaj_limitations
Revises: 0029_doaj_canon
Create Date: 2026-10-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0030_doaj_limitations"
down_revision: Union[str, None] = "0029_doaj_canon"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROWS = [
    (
        "doaj-canon",
        "doaj",
        "journals.oa_model",
        "The Directory of Open Access Journals is the authoritative registry "
        "for gold and diamond open access: journals listed with a declared "
        "article processing charge count as gold, listed without one as "
        "diamond. The DOAJ harvest overrides OpenAlex's own OA status.",
        "info",
        "https://doaj.org",
    ),
    (
        "doaj-apc-declared",
        "doaj",
        "apc.evidence",
        "DOAJ APC amounts are publisher-declared list prices in the "
        "journal's own currency, not observed costs; they can differ from "
        "OpenAPC payments and OpenAlex list prices.",
        "warning",
        "https://doaj.org",
    ),
]


def upgrade() -> None:
    stmt = sa.text(
        "INSERT INTO limitations (code, source, scope, hint, severity, url) "
        "VALUES (:code, :source, :scope, :hint, :severity, :url) "
        "ON CONFLICT (code) DO NOTHING"
    )
    for row in ROWS:
        op.execute(
            stmt.bindparams(
                code=row[0], source=row[1], scope=row[2], hint=row[3],
                severity=row[4], url=row[5],
            )
        )


def downgrade() -> None:
    op.execute("DELETE FROM limitations WHERE code IN ('doaj-canon', 'doaj-apc-declared')")
