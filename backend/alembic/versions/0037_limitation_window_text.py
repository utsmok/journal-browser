"""Limitations registry: make the two window-phrased hints institution-aware.

The seeded texts hardcoded "2020" while the window is per-institution
(ut = 2010 via env, rug = 2025). Serve time now substitutes
"{window_start}" with the scoped institution's data_window_start; this
migration rewrites the seeded rows to use the placeholder and states the
import nuance (the works corpus itself can reach earlier years).

Revision ID: 0037_limitation_window_text
Revises: 0036_author_openaire_source
Create Date: 2026-10-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0037_limitation_window_text"
down_revision: Union[str, None] = "0036_author_openaire_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_HINTS = {
    # code -> original seeded hint (for downgrade)
    "window-2020": (
        "All publication statistics on this site cover publication years "
        "2020 and later only."
    ),
    "corpus-cutoff": (
        "The search lists journals with more than 3 publications since 2020. "
        "OpenAlex tracks more journals than the browser shows; quiet journals "
        "stay in the database but out of search and statistics."
    ),
}

NEW_HINTS = {
    "window-2020": (
        "Journal-level statistics and search coverage use publication years "
        "{window_start} and later (this institution's statistics window). "
        "The works corpus itself can include earlier imported publications."
    ),
    "corpus-cutoff": (
        "The search lists journals with more than 3 publications since "
        "{window_start} (this institution's statistics window). OpenAlex "
        "tracks more journals than the browser shows; quiet journals stay in "
        "the database but out of search and statistics."
    ),
}


def upgrade() -> None:
    for code, hint in NEW_HINTS.items():
        op.execute(
            sa.text("UPDATE limitations SET hint = :hint WHERE code = :code").bindparams(
                hint=hint, code=code
            )
        )


def downgrade() -> None:
    for code, hint in OLD_HINTS.items():
        op.execute(
            sa.text("UPDATE limitations SET hint = :hint WHERE code = :code").bindparams(
                hint=hint, code=code
            )
        )
