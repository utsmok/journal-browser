"""Limitations registry: rename the window caveat code.

"window-2020" hardcodes a year in a user-visible identifier while the
window is per institution (ut=2010, rug=2025) and the hint text already
substitutes {window_start} (0037). Rename the code to "stats-window";
references live in the journals router caveat_codes and two frontend
SourceNote props.

Revision ID: 0038_limitation_code_rename
Revises: 0037_limitation_window_text
Create Date: 2026-10-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0038_limitation_code_rename"
down_revision: Union[str, None] = "0037_limitation_window_text"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_CODE = "window-2020"
NEW_CODE = "stats-window"


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE limitations SET code = :new WHERE code = :old").bindparams(
            new=NEW_CODE, old=OLD_CODE
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE limitations SET code = :old WHERE code = :new").bindparams(
            old=OLD_CODE, new=NEW_CODE
        )
    )
