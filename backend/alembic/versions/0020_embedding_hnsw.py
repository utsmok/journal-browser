"""HNSW index on journals.embedding for semantic search + similar cuts.

The exact cosine scan over ~134k vectors costs ~0.8 s per ranking query;
pgvector 0.8's iterative scans (strict_order) let the index serve filtered,
ordered, paged rankings with exact ordering. Query paths set
hnsw.iterative_scan = strict_order and scale hnsw.ef_search to paging depth.

Building the index takes a few minutes on ~134k rows; the CONCURRENTLY form
would avoid blocking writes, but harvests are batch jobs and the standard
form also can't run inside the transaction alembic provides.

Revision ID: 0020_embedding_hnsw
Revises: 0019_multi_institution
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_embedding_hnsw"
down_revision = "0019_multi_institution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_journals_embedding_hnsw",
        "journals",
        [sa.text("embedding vector_cosine_ops")],
        postgresql_using="hnsw",
    )


def downgrade() -> None:
    op.drop_index("ix_journals_embedding_hnsw", table_name="journals")
