"""Collaboration partners: partner_institutions (ROR canon) and
work_partners (per-work partner links derived from stored payloads).

Revision ID: 0002_collaborations
Revises: 0001_baseline
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_collaborations"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('partner_institutions',
    sa.Column('ror', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('org_type', sa.Text(), nullable=True),
    sa.Column('country_code', sa.Text(), nullable=True),
    sa.Column('city', sa.Text(), nullable=True),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lng', sa.Float(), nullable=True),
    sa.Column('parent_ror', sa.Text(), nullable=True),
    sa.Column('parent_name', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=True),
    sa.Column('openalex_id', sa.Text(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('ror')
    )
    op.create_table('work_partners',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('work_pure_uuid', sa.Text(), nullable=False),
    sa.Column('partner_ror', sa.Text(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('partner_openalex_id', sa.Text(), nullable=True),
    sa.Column('corresponding', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('authorships', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['institution_id', 'work_pure_uuid'], ['works.institution_id', 'works.pure_uuid'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('institution_id', 'work_pure_uuid', 'partner_ror'),
    sa.CheckConstraint("source in ('openalex', 'openaire')", name='work_partners_source_check')
    )
    op.create_index('ix_work_partners_partner', 'work_partners', ['partner_ror', 'institution_id'])

    op.create_table('funder_aliases',
    sa.Column('funder_name', sa.Text(), nullable=False),
    sa.Column('funder_openalex_id', sa.Text(), nullable=False),
    sa.Column('rule', sa.Text(), nullable=False),
    sa.Column('works', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('funder_name'),
    sa.CheckConstraint("rule in ('grant', 'name')", name='funder_aliases_rule_check')
    )

    # Limitations the collaboration pages cite through SourceNote.
    limitations = sa.table(
        'limitations',
        sa.column('code', sa.Text()),
        sa.column('source', sa.Text()),
        sa.column('scope', sa.Text()),
        sa.column('hint', sa.Text()),
        sa.column('severity', sa.Text()),
        sa.column('url', sa.Text()),
    )
    op.bulk_insert(
        limitations,
        [
            {
                'code': 'collaboration-partners',
                'source': 'openalex',
                'scope': 'collaborations.partners',
                'hint': (
                    'A partner is an institution identified by its ROR id. OpenAlex supplies the '
                    'institutions on a work from its authorship affiliations; a work with no OpenAlex '
                    'institution takes its partners from OpenAIRE. Works whose affiliations name an '
                    'institution without a ROR id have no partner.'
                ),
                'severity': 'warning',
                'url': 'https://docs.openalex.org/about-the-data/authors',
            },
            {
                'code': 'openaire-partners',
                'source': 'openaire',
                'scope': 'collaborations.partners',
                'hint': (
                    'OpenAIRE supplies partners only for works that have none in OpenAlex. It reads '
                    'the affiliation strings of the work and keeps the institutions whose ROR id it '
                    'resolves.'
                ),
                'severity': 'info',
                'url': 'https://openaire.eu',
            },
            {
                'code': 'ror-record',
                'source': 'ror',
                'scope': 'collaborations.partners',
                'hint': (
                    'Names, types, countries and coordinates come from the Research Organization '
                    'Registry (ROR, CC0). A partner without a ROR record shows the name from the '
                    'work payload and has no type, country or map position.'
                ),
                'severity': 'info',
                'url': 'https://ror.org',
            },
            {
                'code': 'openalex-awards',
                'source': 'openalex',
                'scope': 'collaborations.funders',
                'hint': (
                    'Funders and grants come from the grants OpenAlex lists on a work. OpenAlex '
                    'records a grant only when it knows the funder or the award id, so a funded '
                    'work can show no funder.'
                ),
                'severity': 'info',
                'url': 'https://docs.openalex.org/about-the-data/works',
            },
            {
                'code': 'openaire-projects',
                'source': 'openaire',
                'scope': 'collaborations.projects',
                'hint': (
                    'Projects and their funders come from the OpenAIRE Graph projects linked to '
                    'a work. Codes and acronyms are shown as OpenAIRE gives them.'
                ),
                'severity': 'info',
                'url': 'https://openaire.eu',
            },
        ],
    )
    # The collaboration pages log their searches under their own scope.
    op.drop_constraint('ck_usage_search_scope', 'usage_events', type_='check')
    op.create_check_constraint(
        'ck_usage_search_scope',
        'usage_events',
        "search_scope IN ('journals', 'funders', 'authors', 'publishers', 'orgunits', "
        "'collaborations')",
    )


def downgrade() -> None:
    # The old constraint rejects the new scope, so its rows go first.
    op.execute("DELETE FROM usage_events WHERE search_scope = 'collaborations'")
    op.drop_constraint('ck_usage_search_scope', 'usage_events', type_='check')
    op.create_check_constraint(
        'ck_usage_search_scope',
        'usage_events',
        "search_scope IN ('journals', 'funders', 'authors', 'publishers', 'orgunits')",
    )
    op.execute(
        "DELETE FROM limitations WHERE code IN ('collaboration-partners', 'openaire-partners', "
        "'ror-record', 'openalex-awards', 'openaire-projects')"
    )
    op.drop_table('funder_aliases')
    op.drop_index('ix_work_partners_partner', table_name='work_partners')
    op.drop_table('work_partners')
    op.drop_table('partner_institutions')
