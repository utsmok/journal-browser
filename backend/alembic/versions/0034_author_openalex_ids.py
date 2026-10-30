"""author.openalex_ids — all known openalex author A-ids per author.

The author page's openalex-only live merge (services.authors) must match
authorships against the author's primary id AND merged alternates (core
author profiles split across A-ids, e.g. 6 works under a5007012759 plus
newer works under a5122439104). core_author_link keeps them on the source
side; the JB copy rides along on Author so profile views need no source
connection.

Revision history: down_revision 0033.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0034_author_openalex_ids"
down_revision: str | None = "0033_state_constraints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE authors ADD COLUMN openalex_ids JSONB NOT NULL DEFAULT '[]'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE authors DROP COLUMN openalex_ids")
