"""Separate the publisher list price from the amount actually paid.

journals.latest_apc_euro took the highest amount of the journal's newest
OpenAPC period that had any amount. Articles an agreement paid for arrive
as €0, so 239 priced journals read as free. latest_apc_euro is now the
mean of the newest period with an article paid above zero (that period is
stored in latest_apc_period), and the publisher list price (OpenAlex
apc_prices, else the DOAJ maximum APC) gets its own list_price_* columns.
Both are backfilled here from stored data and kept current by
harvest.denorm.refresh_apcs.

journal_apc_aggregates gains paid_count and zero_count, and its euro_*
figures come to cover paid articles only (amount above zero). The stored
figures split most rows exactly. Periods that mix paid articles with €0
ones keep their mean and highest amount, lose a lowest amount of €0, and
get NULL counts; the next OpenAPC ingest rebuilds the table exactly.

Revision ID: 0005_apc_list_price_vs_paid
Revises: 0004_journal_listed_in
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

from journal_browser.harvest.denorm import PAID_APC_SQL, refresh_list_prices

revision: str = "0005_apc_list_price_vs_paid"
down_revision: Union[str, None] = "0004_journal_listed_in"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("journal_apc_aggregates", sa.Column("paid_count", sa.Integer(), nullable=True))
    op.add_column("journal_apc_aggregates", sa.Column("zero_count", sa.Integer(), nullable=True))
    conn = op.get_bind()
    # A period without any amount has no paid and no €0 article: the old
    # figures included €0, so a NULL maximum means every article was unpriced.
    conn.execute(
        text(
            """
            UPDATE journal_apc_aggregates
            SET paid_count = 0, zero_count = 0
            WHERE euro_max IS NULL
            """
        )
    )
    # A period whose highest amount is €0 has nothing paid. How many of its
    # articles were €0 and how many unpriced is not stored: zero_count
    # stays NULL until the OpenAPC job rebuilds the row.
    conn.execute(
        text(
            """
            UPDATE journal_apc_aggregates
            SET paid_count = 0, euro_min = NULL, euro_max = NULL, euro_mean = NULL
            WHERE euro_max = 0
            """
        )
    )
    # Paid articles only: every amount of the period is above zero.
    conn.execute(
        text(
            """
            UPDATE journal_apc_aggregates
            SET paid_count = article_count, zero_count = 0
            WHERE euro_min > 0
            """
        )
    )
    # Paid articles next to €0 ones: the mean keeps counting the €0 ones
    # and the lowest amount was €0. The highest amount and the mean are
    # still usable; the lowest amount is not, so it becomes unknown.
    conn.execute(
        text(
            """
            UPDATE journal_apc_aggregates
            SET euro_min = NULL
            WHERE euro_min = 0 AND euro_max > 0
            """
        )
    )
    op.add_column("journals", sa.Column("latest_apc_period", sa.Integer(), nullable=True))
    op.add_column("journals", sa.Column("list_price_source", sa.Text(), nullable=True))
    op.add_column("journals", sa.Column("list_price_currency", sa.String(3), nullable=True))
    op.add_column("journals", sa.Column("list_price_amount", sa.Numeric(), nullable=True))
    op.add_column("journals", sa.Column("list_price_year", sa.Integer(), nullable=True))
    op.add_column("journals", sa.Column("list_price_euro", sa.Numeric(12, 2), nullable=True))
    conn.execute(PAID_APC_SQL)
    refresh_list_prices(conn)


def downgrade() -> None:
    conn = op.get_bind()
    # Old figures again: €0 articles count in the lowest amount and the mean.
    conn.execute(
        text(
            """
            UPDATE journal_apc_aggregates
            SET euro_min = 0,
                euro_mean = round(euro_mean * paid_count / (paid_count + zero_count), 2)
            WHERE paid_count > 0 AND zero_count > 0
            """
        )
    )
    conn.execute(
        text(
            "UPDATE journal_apc_aggregates SET euro_min = 0 "
            "WHERE euro_min IS NULL AND euro_max > 0"
        )
    )
    # Old figures again: a period with €0 articles and nothing paid reads €0.
    conn.execute(
        text(
            """
            UPDATE journal_apc_aggregates
            SET euro_min = 0, euro_max = 0, euro_mean = 0
            WHERE paid_count = 0 AND coalesce(zero_count, 1) > 0
            """
        )
    )
    # The old rule: highest amount of the newest period with any amount.
    conn.execute(
        text(
            """
            UPDATE journals j SET latest_apc_euro = a.euro_max
            FROM (
                SELECT DISTINCT ON (issn_l) issn_l, euro_max
                FROM journal_apc_aggregates
                WHERE euro_max IS NOT NULL
                ORDER BY issn_l, period DESC
            ) a
            RIGHT JOIN journals jj ON jj.issn_l = a.issn_l
            WHERE j.issn_l = jj.issn_l
            """
        )
    )
    op.drop_column("journals", "list_price_euro")
    op.drop_column("journals", "list_price_year")
    op.drop_column("journals", "list_price_amount")
    op.drop_column("journals", "list_price_currency")
    op.drop_column("journals", "list_price_source")
    op.drop_column("journals", "latest_apc_period")
    op.drop_column("journal_apc_aggregates", "zero_count")
    op.drop_column("journal_apc_aggregates", "paid_count")
