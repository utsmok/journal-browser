"""Operational indexes, LZ4 TOAST on source_records, Scimago '-' cleanup,
and rebuilt ix_authors_name_fold_trgm with corrected diacritic folding.

Revision ID: 0009_indexes_and_scimago_clean
Revises: 0008_author_name_fold_trgm
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_indexes_and_scimago_clean"
down_revision: str | None = "0008_author_name_fold_trgm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FOLD_SRC = "áàâäãåéèêëíìîïóòôöõúùûüýÿñçšž"
# Fixed mapping (29 chars matching _FOLD_SRC, matching services/authors.py).
_FOLD_DST = "aaaaaaeeeeiiiiooooouuuuyyncsz"
# 0008's 30-char string preserved solely for exact downgrade fidelity.
_FOLD_DST_0008 = "aaaaaaeeeeiiiioooooouuuuyyncsz"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_source_records_harvest_run_id ON source_records (harvest_run_id)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_apc_evidence_source_record_id ON apc_evidence (source_record_id) "
            "WHERE source_record_id IS NOT NULL"
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_authors_name_fold_trgm")
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_authors_name_fold_trgm ON authors "
            f"USING gin ((translate(lower(name), '{_FOLD_SRC}', '{_FOLD_DST}')) gin_trgm_ops)"
        )

    op.execute("ALTER TABLE source_records ALTER COLUMN payload SET COMPRESSION lz4")
    op.execute("UPDATE scimagojr_metrics SET best_quartile = NULL WHERE best_quartile = '-'")


def downgrade() -> None:
    op.execute("ALTER TABLE source_records ALTER COLUMN payload SET COMPRESSION pglz")
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_apc_evidence_source_record_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_source_records_harvest_run_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_authors_name_fold_trgm")
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_authors_name_fold_trgm ON authors "
            f"USING gin ((translate(lower(name), '{_FOLD_SRC}', '{_FOLD_DST_0008}')) gin_trgm_ops)"
        )
