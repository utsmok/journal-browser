"""State constraints: CHECKs for the vocabularies the code already implies.

Step-1 audit found 2800 works rows carrying pre-canonical oa_status literals
(raw OpenAlex/Pure forms and COAR purl URIs; rows written before
harvest/pure.py canonical_access existed). Operator approved a mapped
backfill on 2026-10-30: this migration rewrites exactly those rows through
the same mapping _OA_MAP applies today, writing NULL where the producer
writes NULL. Unmapped values (e.g. COAR c_14cb) become NULL, never guessed.

Revision ID: 0033_state_constraints
Revises: 0032_data_window_open
Create Date: 2026-10-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0033_state_constraints"
down_revision: Union[str, None] = "0032_data_window_open"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors harvest/pure.py _OA_MAP (canonical_access): compact lowercase
# literal -> canonical oa_status; anything unmappable -> NULL.
_OA_BACKFILL = """
UPDATE works SET oa_status = CASE
    WHEN lower(oa_status) = 'openaccess' THEN 'green'
    WHEN lower(oa_status) IN (
        'closedaccess', 'embargoedaccess', 'restrictedaccess', 'metadataonly'
    ) THEN 'closed'
    WHEN oa_status LIKE '%c_abf2' THEN 'green'
    WHEN oa_status LIKE '%c_16ec' THEN 'closed'
    WHEN oa_status LIKE '%c_f1cf' THEN 'closed'
    WHEN oa_status LIKE '%c_998f' THEN 'closed'
    ELSE NULL
END
WHERE oa_status IS NOT NULL
  AND oa_status NOT IN ('gold', 'hybrid', 'green', 'bronze', 'diamond', 'closed')
"""


def upgrade() -> None:
    op.add_column(
        "deal_journals",
        sa.Column("needs_curation_reason", sa.Text(), nullable=True),
    )
    # Backfills must precede the constraints they unblock.
    op.execute(_OA_BACKFILL)
    op.execute(
        "UPDATE work_identity SET confidence = NULL "
        "WHERE status = 'missing' AND confidence = 0.0"
    )
    op.create_check_constraint(
        "ck_deals_curation_reason",
        "deals",
        "needs_curation = true OR needs_curation_reason IS NULL",
    )
    op.create_check_constraint(
        "ck_deal_journals_curation_reason",
        "deal_journals",
        "needs_curation = true OR needs_curation_reason IS NULL",
    )
    op.create_check_constraint(
        "ck_deal_institutions_participation",
        "deal_institutions",
        "participation IN ('named', 'consortium')",
    )
    op.create_check_constraint(
        "ck_works_oa_status",
        "works",
        "oa_status IN ('gold', 'hybrid', 'green', 'bronze', 'diamond', 'closed')",
    )
    op.create_check_constraint(
        "ck_work_identity_status",
        "work_identity",
        "status IN ('confirmed', 'missing', 'candidate')",
    )
    op.create_check_constraint(
        "ck_work_identity_matched_by",
        "work_identity",
        "matched_by ~ '^(doi|verbatim|trgm:.+)$'",
    )
    # Value list copied from ck_harvest_runs_status.
    op.create_check_constraint(
        "ck_harvest_state_status",
        "harvest_state",
        "status IN ('running', 'completed', 'failed')",
    )
    op.create_check_constraint(
        "ck_feedback_items_category",
        "feedback_items",
        "category IN ('bug', 'data', 'feature', 'improvement', 'other')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_feedback_items_category", "feedback_items")
    op.drop_constraint("ck_harvest_state_status", "harvest_state")
    op.drop_constraint("ck_work_identity_matched_by", "work_identity")
    op.drop_constraint("ck_work_identity_status", "work_identity")
    op.drop_constraint("ck_works_oa_status", "works")
    op.drop_constraint("ck_deal_institutions_participation", "deal_institutions")
    op.drop_constraint("ck_deal_journals_curation_reason", "deal_journals")
    op.drop_constraint("ck_deals_curation_reason", "deals")
    # The oa_status backfill is not reversible: canonical values stay.
    op.drop_column("deal_journals", "needs_curation_reason")
