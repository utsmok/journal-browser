"""openalex_funders and funder_links: one spelling per OpenAlex funder id.

The first OpenAlex funder harvest stored each id as the API sends it, with
the https://openalex.org/ prefix. From 2026-11-08 the harvest writes the
bare id ("F4320320300"), but the gap-fill only adds ids it does not know,
so the prefixed rows stayed. The 2026-11-18 refresh then upserted a bare
row next to every prefixed one. refresh_funder_links copied both spellings
into funder_links, so every Jisc funder linked each OpenAlex twin twice and
the API returned either spelling as openalex_funder_id.

Keeps the bare row, the form the harvest writes. A prefixed row that has
no bare twin is renamed, not dropped.

Revision ID: 0005_bare_openalex_funder_ids
Revises: 0004_journal_listed_in
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0005_bare_openalex_funder_ids"
down_revision: Union[str, None] = "0004_journal_listed_in"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PREFIXED = r"~ '^https://openalex\.org/'"
BARE = "regexp_replace({}, '^https://openalex.org/', '')"


def upgrade() -> None:
    # openalex_funders: the prefixed twin of a bare row is the stale copy.
    op.execute(
        f"""
        DELETE FROM openalex_funders u
        WHERE u.openalex_id {PREFIXED}
          AND EXISTS (
              SELECT 1 FROM openalex_funders b
              WHERE b.openalex_id = {BARE.format("u.openalex_id")}
          )
        """
    )
    op.execute(
        f"""
        UPDATE openalex_funders
        SET openalex_id = {BARE.format("openalex_id")}
        WHERE openalex_id {PREFIXED}
        """
    )
    # funder_links: same twins, keyed by (funder_id, source, source_id).
    op.execute(
        f"""
        DELETE FROM funder_links u
        WHERE u.source = 'openalex' AND u.source_id {PREFIXED}
          AND EXISTS (
              SELECT 1 FROM funder_links b
              WHERE b.funder_id = u.funder_id AND b.source = 'openalex'
                AND b.source_id = {BARE.format("u.source_id")}
          )
        """
    )
    op.execute(
        f"""
        UPDATE funder_links
        SET source_id = {BARE.format("source_id")}
        WHERE source = 'openalex' AND source_id {PREFIXED}
        """
    )


def downgrade() -> None:
    # Puts the prefixed twin of every bare row back, with the bare row's
    # values: the stale ones the upgrade dropped are gone.
    op.execute(
        """
        INSERT INTO openalex_funders (
            openalex_id, ror, fundref, display_name, country_code, description,
            grant_count, works_count, cited_by_count, updated_at
        )
        SELECT 'https://openalex.org/' || openalex_id, ror, fundref, display_name,
               country_code, description, grant_count, works_count, cited_by_count,
               updated_at
        FROM openalex_funders
        WHERE openalex_id !~ '^https://'
        """
    )
    op.execute(
        """
        INSERT INTO funder_links (funder_id, source, source_id, via, updated_at)
        SELECT funder_id, source, 'https://openalex.org/' || source_id, via, updated_at
        FROM funder_links
        WHERE source = 'openalex'
        """
    )
