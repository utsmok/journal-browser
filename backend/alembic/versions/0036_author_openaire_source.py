"""Author identities: admit the openaire source namespace.

The identity cascade now runs against the OpenAIRE work store as a
second work-anchored arm; its person keys land in author_identities
with source='openaire' (a different id namespace that never feeds
authors.openalex_ids — the local source adapter filters to openalex).
This migration only widens the source CHECK; 0035's table shape is
unchanged.

Revision history: down_revision 0035.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0036_author_openaire_source"
down_revision: str | None = "0035_standalone_author_path"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "source IN ('openalex')"
_NEW = "source IN ('openalex', 'openaire')"


def upgrade() -> None:
    with op.batch_alter_table("author_identities") as batch:
        batch.drop_constraint("ck_author_identities_source", type_="check")
        batch.create_check_constraint("ck_author_identities_source", _NEW)


def downgrade() -> None:
    with op.batch_alter_table("author_identities") as batch:
        batch.drop_constraint("ck_author_identities_source", type_="check")
        batch.create_check_constraint("ck_author_identities_source", _OLD)
