"""Add the `superseded` harvest status.

Every 'failed' harvest run since 2026-11-01 was a supersede mark
(stats.error = "stale: superseded by a newer run of the same job"),
not a failure; the admin dashboard counted them into failed_24h and
showed red after any overlapping re-run. start_run now writes
status='superseded', and this migration moves the historical rows to
the same status while widening both check constraints
(ck_harvest_runs_status, ck_harvest_state_status — same vocabulary by
contract, even though only harvest_runs rows carry it today).

Downgrade restores the old three-value constraints and folds
superseded rows back to 'failed' with their stats intact.

Revision ID: 0066_superseded_run_status
Revises: 0065_prune_flags_inactive
Create Date: 2026-11-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0066_superseded_run_status"
down_revision: str | None = "0065_prune_flags_inactive"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_VALUES = ("running", "completed", "failed")
NEW_VALUES = ("running", "completed", "failed", "superseded")


def _constraint(table: str, name: str, values: tuple[str, ...]) -> None:
    quoted = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(name, table, f"status IN ({quoted})")


def upgrade() -> None:
    # Widen the constraints first: the reclassification below writes
    # 'superseded', which the old checks reject.
    for table, name in (
        ("harvest_runs", "ck_harvest_runs_status"),
        ("harvest_state", "ck_harvest_state_status"),
    ):
        op.drop_constraint(name, table)
        _constraint(table, name, NEW_VALUES)
    op.execute(
        """
        UPDATE harvest_runs SET status = 'superseded'
        WHERE status = 'failed'
          AND stats->>'error' LIKE 'stale: superseded%'
        """
    )


def downgrade() -> None:
    op.execute("UPDATE harvest_runs SET status = 'failed' WHERE status = 'superseded'")
    for table, name in (
        ("harvest_runs", "ck_harvest_runs_status"),
        ("harvest_state", "ck_harvest_state_status"),
    ):
        op.drop_constraint(name, table)
        _constraint(table, name, OLD_VALUES)
