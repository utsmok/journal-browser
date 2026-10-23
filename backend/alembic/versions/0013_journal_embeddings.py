"""pgvector embedding column + HNSW index for similar-journal search.

Revision ID: 0013_journal_embeddings
Revises: 0012_detail_jsonb_issn_indexes
Create Date: 2026-10-23
"""

from alembic import op

revision = "0013_journal_embeddings"
down_revision = "0012_detail_jsonb_issn_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Requires the pgvector-aware db image (db/Dockerfile).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE journals ADD COLUMN embedding vector(384)")
    op.execute(
        "CREATE INDEX ix_journals_embedding ON journals "
        "USING hnsw (embedding vector_cosine_ops) WHERE embedding IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_journals_embedding")
    op.execute("ALTER TABLE journals DROP COLUMN IF EXISTS embedding")
    op.execute("DROP EXTENSION IF EXISTS vector")
