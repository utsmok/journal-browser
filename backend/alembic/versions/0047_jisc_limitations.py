"""Seed JISC Open Policy Finder limitations: policy currency + CC BY-NC-ND.

Revision ID: 0047_jisc_limitations
Revises: 0046_jisc_policy
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from alembic import op

revision = "0047_jisc_limitations"
down_revision = "0046_jisc_policy"
branch_labels = None
depends_on = None

ROWS = [
    (
        "jisc-policy-currency",
        "jisc-opf",
        "journals.green_oa",
        "Publisher self-archiving policies are curated by Jisc Open Policy "
        "Finder and reviewed periodically; always confirm with the publisher "
        "before relying on them.",
        "info",
        "https://openpolicyfinder.jisc.ac.uk",
    ),
    (
        "jisc-cc-by-nc-nd",
        "jisc-opf",
        "journals.green_oa",
        "Policy text is Jisc content under CC BY-NC-ND 4.0: shown verbatim, never paraphrased.",
        "info",
        "https://creativecommons.org/licenses/by-nc-nd/4.0/",
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
                code=row[0],
                source=row[1],
                scope=row[2],
                hint=row[3],
                severity=row[4],
                url=row[5],
            )
        )


def downgrade() -> None:
    op.execute("DELETE FROM limitations WHERE code IN ('jisc-policy-currency', 'jisc-cc-by-nc-nd')")
