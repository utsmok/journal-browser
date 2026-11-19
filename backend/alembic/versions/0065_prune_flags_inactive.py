"""Prune journal_flags to active institutions.

The table is documented as one row per journal per hosted institution, but
the seeding history materialized a full journal copy (177,737 rows) for
every one of the 3,905 institutions rows; only 2 are active, so 694 M rows
(94 GB heap + indexes, ~75% of the database) serve nobody. Rebuild the
heap from the active institutions only: a plain INSERT SELECT needs no
temp space beyond the kept rows (~355k on live), and the drop/rename swap
is transactional.

Staying pruned: every denorm loop (bootstrap, reconcile, flags_refresh)
already iterates active institutions only, the single-institution jobs
resolve an active institution or fail, and the admin PUT now drops rows on
deactivation and skips the stats rebuild for inactive ones.

Downgrade recreates the empty table shape. journal_flags is derived state:
the stats/reconcile jobs re-materialize rows for active institutions on
their next run.

Revision ID: 0065_prune_flags_inactive
Revises: 0064_work_parents
Create Date: 2026-11-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0065_prune_flags_inactive"
down_revision: str | None = "0064_work_parents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The definition the table has at this revision: 0019 created it, 0061 and
# 0062 appended deal_cap_reached and openaire_diamond, 0039 set fillfactor
# 70 so nightly refreshes stay HOT. Constraint names match what the old
# table carried (Postgres names them <table>_<column>_<type>; the rename
# back happens explicitly after the table rename).
SHAPE = """
    CREATE TABLE {table} (
        institution_id integer NOT NULL,
        issn_l varchar(9) NOT NULL,
        works_count integer NOT NULL DEFAULT '0',
        deal_covered boolean NOT NULL DEFAULT false,
        works_window_plus integer NOT NULL DEFAULT '0',
        browse_excluded boolean NOT NULL DEFAULT false,
        deal_cap_reached boolean NOT NULL DEFAULT false,
        openaire_diamond boolean NOT NULL DEFAULT false,
        CONSTRAINT {pkey} PRIMARY KEY (institution_id, issn_l),
        CONSTRAINT {inst_fk} FOREIGN KEY (institution_id)
            REFERENCES institutions(id) ON DELETE CASCADE,
        CONSTRAINT {issn_fk} FOREIGN KEY (issn_l)
            REFERENCES journals(issn_l) ON DELETE CASCADE
    )
"""

NEW_NAMES = {
    "table": "journal_flags_new",
    "pkey": "journal_flags_new_pkey",
    "inst_fk": "journal_flags_new_institution_id_fkey",
    "issn_fk": "journal_flags_new_issn_l_fkey",
}
OLD_NAMES = {
    "table": "journal_flags",
    "pkey": "journal_flags_pkey",
    "inst_fk": "journal_flags_institution_id_fkey",
    "issn_fk": "journal_flags_issn_l_fkey",
}


def upgrade() -> None:
    op.execute(SHAPE.format(**NEW_NAMES))
    # Sequential scan of the old heap, write of the kept rows only.
    op.execute(
        """
        INSERT INTO journal_flags_new
        SELECT * FROM journal_flags
        WHERE institution_id IN (SELECT id FROM institutions WHERE active)
        """
    )
    op.execute("DROP TABLE journal_flags")
    op.execute("ALTER TABLE journal_flags_new RENAME TO journal_flags")
    for old, new in (
        ("journal_flags_new_pkey", "journal_flags_pkey"),
        ("journal_flags_new_institution_id_fkey", "journal_flags_institution_id_fkey"),
        ("journal_flags_new_issn_l_fkey", "journal_flags_issn_l_fkey"),
    ):
        op.execute(f"ALTER TABLE journal_flags RENAME CONSTRAINT {old} TO {new}")
    op.execute("ALTER TABLE journal_flags SET (fillfactor = 70)")
    op.execute("ANALYZE journal_flags")


def downgrade() -> None:
    # Derived table: rebuild empty; the denorm job re-materializes active
    # institutions' rows on its next run. The old PK index keeps its name
    # through the table rename, so move it out of the way first (index
    # names are schema-wide, unlike constraint names).
    op.execute("ALTER TABLE journal_flags RENAME TO journal_flags_old")
    op.execute("ALTER INDEX journal_flags_pkey RENAME TO journal_flags_old_pkey")
    op.execute(SHAPE.format(**OLD_NAMES))
    op.execute("ALTER TABLE journal_flags SET (fillfactor = 70)")
    op.execute("DROP TABLE journal_flags_old")
