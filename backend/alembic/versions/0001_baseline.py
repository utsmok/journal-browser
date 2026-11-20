"""Baseline schema: the full history of 0002..0069 squashed into one revision.

Fresh installs apply this single migration; existing databases (created with
the pre-squash chain, head 0069) must stamp this revision instead of
upgrading — see DEPLOYMENT.md "Migrations".
"""

from typing import Sequence, Union

import pgvector
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public")
    op.create_table('cache_epoch',
    sa.Column('id', sa.SmallInteger(), nullable=False),
    sa.Column('bumped_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.CheckConstraint('id = 1', name='cache_epoch_single_row')
    )
    op.create_table('doc_edits',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('doc_slug', sa.Text(), nullable=False),
    sa.Column('block_key', sa.Text(), nullable=False),
    sa.Column('original_hash', sa.Text(), nullable=False),
    sa.Column('replacement', sa.Text(), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('doc_slug', 'block_key', name='uq_doc_edits_block')
    )
    op.create_table('feedback_items',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('category', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default='todo', nullable=False),
    sa.Column('priority', sa.Text(), server_default='normal', nullable=False),
    sa.Column('page_url', sa.Text(), nullable=True),
    sa.Column('page_data', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('resolution_notes', sa.Text(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.CheckConstraint("category IN ('bug', 'data', 'feature', 'improvement', 'other')", name='ck_feedback_items_category'),
    sa.CheckConstraint("priority IN ('low', 'normal', 'high', 'critical')", name='ck_feedback_priority'),
    sa.CheckConstraint("status IN ('todo', 'in_progress', 'done', 'wontfix')", name='ck_feedback_status'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('institutions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('ror', sa.Text(), nullable=True),
    sa.Column('openalex_id', sa.Text(), nullable=True),
    sa.Column('code', sa.Text(), nullable=True),
    sa.Column('short_name', sa.Text(), nullable=True),
    sa.Column('pure_oai_base_url', sa.Text(), nullable=True),
    sa.Column('openaire_org_id', sa.Text(), nullable=True),
    sa.Column('external_works_dsn', sa.Text(), nullable=True),
    sa.Column('data_window_start', sa.Integer(), server_default=sa.text('2020'), nullable=False),
    sa.Column('data_window_end', sa.Integer(), nullable=True),
    sa.Column('library_url', sa.Text(), nullable=True),
    sa.Column('oa_guide_url', sa.Text(), nullable=True),
    sa.Column('support_email', sa.Text(), nullable=True),
    sa.Column('admin_contact', sa.Text(), nullable=True),
    sa.Column('research_portal_url', sa.Text(), nullable=True),
    sa.Column('active', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('require_confirmed_affiliation', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code', name='uq_institutions_code'),
    sa.UniqueConstraint('name'),
    sa.UniqueConstraint('ror')
    )
    op.create_table('issn_map',
    sa.Column('issn', sa.String(length=9), nullable=False),
    sa.Column('issn_l', sa.String(length=9), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('issn')
    )
    op.create_table('jisc_funder_groups',
    sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('funders', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('date_modified', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('harvested_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('jisc_funders',
    sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('country', sa.String(length=2), nullable=True),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('identifiers', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('publications_policy', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('data_archiving_policy', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('date_modified', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('harvested_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ror', sa.Text(), nullable=True),
    sa.Column('fundref', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('jisc_policies',
    sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('publisher_id', sa.Integer(), nullable=True),
    sa.Column('open_access_prohibited', sa.Boolean(), nullable=True),
    sa.Column('internal_moniker', sa.Text(), nullable=True),
    sa.Column('urls', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('workflow_dates', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('permitted_oa', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('publication_count', sa.Integer(), nullable=True),
    sa.Column('date_modified', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('harvested_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('jisc_publications',
    sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('pub_type', sa.Text(), nullable=True),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('listed_in_doaj', sa.Boolean(), nullable=True),
    sa.Column('issns', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('publisher_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('policy_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('issn_l', sa.String(length=9), nullable=True),
    sa.Column('date_modified', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('harvested_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('jisc_publishers',
    sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('country', sa.String(length=2), nullable=True),
    sa.Column('ror', sa.Text(), nullable=True),
    sa.Column('publication_count', sa.Integer(), nullable=True),
    sa.Column('imprint_of_id', sa.Integer(), nullable=True),
    sa.Column('date_modified', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('harvested_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('jisc_repositories',
    sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('type', sa.Text(), nullable=True),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('oai_url', sa.Text(), nullable=True),
    sa.Column('software', sa.Text(), nullable=True),
    sa.Column('content_subjects', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('content_types', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('full_text_record_count', sa.Integer(), nullable=True),
    sa.Column('metadata_record_count', sa.Integer(), nullable=True),
    sa.Column('date_modified', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('harvested_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('journal_apc_aggregates',
    sa.Column('issn_l', sa.String(length=9), nullable=False),
    sa.Column('period', sa.Integer(), nullable=False),
    sa.Column('source', sa.Text(), server_default='openapc', nullable=False),
    sa.Column('article_count', sa.Integer(), nullable=False),
    sa.Column('euro_min', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('euro_max', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('euro_mean', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.PrimaryKeyConstraint('issn_l', 'period')
    )
    op.create_table('limitations',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('scope', sa.Text(), nullable=False),
    sa.Column('hint', sa.Text(), nullable=False),
    sa.Column('severity', sa.Text(), server_default='info', nullable=False),
    sa.Column('url', sa.Text(), nullable=True),
    sa.CheckConstraint("severity IN ('info', 'warning')", name='ck_limitations_severity'),
    sa.PrimaryKeyConstraint('code')
    )
    op.create_table('manual_overrides',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('table_name', sa.Text(), nullable=False),
    sa.Column('row_key', sa.Text(), nullable=False),
    sa.Column('field', sa.Text(), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=True),
    sa.Column('set_by', sa.Text(), nullable=True),
    sa.Column('set_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('table_name', 'row_key', 'field', name='uq_manual_overrides')
    )
    op.create_table('openaire_funders',
    sa.Column('openaire_id', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('short_name', sa.Text(), nullable=True),
    sa.Column('website_url', sa.Text(), nullable=True),
    sa.Column('jurisdiction', sa.Text(), nullable=True),
    sa.Column('ror', sa.Text(), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('openaire_id')
    )
    op.create_table('openalex_funders',
    sa.Column('openalex_id', sa.Text(), nullable=False),
    sa.Column('ror', sa.Text(), nullable=True),
    sa.Column('fundref', sa.Text(), nullable=True),
    sa.Column('display_name', sa.Text(), nullable=True),
    sa.Column('country_code', sa.Text(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('grant_count', sa.Integer(), nullable=True),
    sa.Column('works_count', sa.Integer(), nullable=True),
    sa.Column('cited_by_count', sa.Integer(), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('openalex_id')
    )
    op.create_table('openalex_publishers',
    sa.Column('openalex_id', sa.Text(), nullable=False),
    sa.Column('display_name', sa.Text(), nullable=True),
    sa.Column('lineage', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('canonical_id', sa.Text(), nullable=True),
    sa.Column('canonical_name', sa.Text(), nullable=True),
    sa.Column('fetched_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('openalex_id')
    )
    op.create_table('publishers',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('openaccess_nl_slug', sa.Text(), nullable=True),
    sa.Column('aliases', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name'),
    sa.UniqueConstraint('openaccess_nl_slug')
    )
    op.create_table('scimagojr_metrics',
    sa.Column('issn_l', sa.String(length=9), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('sjr', sa.Numeric(precision=12, scale=6), nullable=True),
    sa.Column('best_quartile', sa.Text(), nullable=True),
    sa.Column('h_index', sa.Integer(), nullable=True),
    sa.Column('extras', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('issn_l', 'year')
    )
    op.create_table('status_changes',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('table_name', sa.Text(), nullable=False),
    sa.Column('row_key', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('field', sa.Text(), server_default='status', nullable=False),
    sa.Column('old_value', sa.Text(), nullable=True),
    sa.Column('new_value', sa.Text(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('changed_by', sa.Text(), nullable=True),
    sa.Column('changed_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_status_changes_table_time', 'status_changes', ['table_name', 'changed_at'], unique=False)
    op.create_table('usage_events',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('ts', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('session_id', sa.Text(), nullable=False),
    sa.Column('event_type', sa.Text(), nullable=False),
    sa.Column('path', sa.Text(), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('query', sa.Text(), nullable=True),
    sa.Column('results_count', sa.Integer(), nullable=True),
    sa.Column('search_scope', sa.Text(), nullable=True),
    sa.Column('filters', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('ref_type', sa.Text(), nullable=True),
    sa.Column('ref_id', sa.Text(), nullable=True),
    sa.Column('source', sa.Text(), nullable=True),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.Column('status', sa.Integer(), nullable=True),
    sa.Column('referrer', sa.Text(), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('country', sa.Text(), nullable=True),
    sa.Column('user_agent', sa.Text(), nullable=True),
    sa.Column('tz', sa.Text(), nullable=True),
    sa.Column('locale', sa.Text(), nullable=True),
    sa.Column('is_browse', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.CheckConstraint("event_type IN ('page_view', 'search', 'error')", name='ck_usage_event_type'),
    sa.CheckConstraint("ref_type IN ('journal', 'funder', 'author', 'orgunit', 'publisher')", name='ck_usage_ref_type'),
    sa.CheckConstraint("search_scope IN ('journals', 'funders', 'authors', 'publishers', 'orgunits')", name='ck_usage_search_scope'),
    sa.CheckConstraint("source IN ('js_error', 'unhandled_rejection', 'api_status')", name='ck_usage_source'),
    sa.CheckConstraint('(ref_type IS NULL) = (ref_id IS NULL)', name='ck_usage_ref_pair'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_usage_events_session', 'usage_events', ['session_id'], unique=False)
    op.create_index('ix_usage_events_ts', 'usage_events', ['ts'], unique=False)
    op.create_index('ix_usage_events_type_ts', 'usage_events', ['event_type', 'ts'], unique=False)
    op.create_table('author_identities',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('author_pure_uuid', sa.Text(), nullable=False),
    sa.Column('source', sa.Text(), server_default='openalex', nullable=False),
    sa.Column('external_id', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default='candidate', nullable=False),
    sa.Column('method', sa.Text(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('n_works', sa.Integer(), server_default='0', nullable=False),
    sa.Column('orcid_corroborated', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("source IN ('openalex', 'openaire', 'people')", name='ck_author_identities_source'),
    sa.CheckConstraint("status IN ('confirmed', 'candidate', 'rejected')", name='ck_author_identities_status'),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('institution_id', 'author_pure_uuid', 'source', 'external_id')
    )
    op.create_index('ix_author_identities_inst_author', 'author_identities', ['institution_id', 'author_pure_uuid'], unique=False)
    op.create_index('ix_author_identities_inst_status', 'author_identities', ['institution_id', 'status'], unique=False)
    op.create_table('authors',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('pure_uuid', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('orcid', sa.Text(), nullable=True),
    sa.Column('openalex_author_id', sa.Text(), nullable=True),
    sa.Column('openaire_person_id', sa.Text(), nullable=True),
    sa.Column('crossref_orcid', sa.Text(), nullable=True),
    sa.Column('faculty', sa.Text(), nullable=True),
    sa.Column('research_group', sa.Text(), nullable=True),
    sa.Column('orgs', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('n_works', sa.Integer(), server_default='0', nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('confirmed', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('last_pub_year', sa.Integer(), nullable=True),
    sa.Column('primary_topic', sa.Text(), nullable=True),
    sa.Column('openalex_ids', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('institute', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('institution_id', 'pure_uuid')
    )
    op.create_table('deals',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('publisher_id', sa.Integer(), nullable=True),
    sa.Column('esac_id', sa.Text(), nullable=True),
    sa.Column('consortium', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default='current', nullable=False),
    sa.Column('start_year', sa.Integer(), nullable=True),
    sa.Column('end_year', sa.Integer(), nullable=True),
    sa.Column('duration_text', sa.Text(), nullable=True),
    sa.Column('corresponding_authors_only', sa.Boolean(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('conditions_text', sa.Text(), nullable=True),
    sa.Column('workflow_text', sa.Text(), nullable=True),
    sa.Column('article_types_text', sa.Text(), nullable=True),
    sa.Column('cap_text', sa.Text(), nullable=True),
    sa.Column('cap_numbers', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('contract_url', sa.Text(), nullable=True),
    sa.Column('openaccess_nl_url', sa.Text(), nullable=True),
    sa.Column('jct_data_url', sa.Text(), nullable=True),
    sa.Column('per_year_oa_counts', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('provenance', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('needs_curation', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('needs_curation_reason', sa.Text(), nullable=True),
    sa.Column('last_reviewed', sa.Date(), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('links', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('curation_resolved_reason', sa.Text(), nullable=True),
    sa.Column('cap_usage', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.CheckConstraint("status IN ('current', 'archive')", name='ck_deals_status'),
    sa.CheckConstraint('needs_curation = false OR curation_resolved_reason IS NULL', name='ck_deals_curation_resolved'),
    sa.CheckConstraint('needs_curation = true OR needs_curation_reason IS NULL', name='ck_deals_curation_reason'),
    sa.ForeignKeyConstraint(['publisher_id'], ['publishers.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('esac_id')
    )
    op.create_index('ix_deals_publisher', 'deals', ['publisher_id', 'status'], unique=False)
    op.create_table('funder_links',
    sa.Column('funder_id', sa.Integer(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('source_id', sa.Text(), nullable=False),
    sa.Column('via', sa.Text(), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['funder_id'], ['jisc_funders.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('funder_id', 'source', 'source_id')
    )
    op.create_table('harvest_runs',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('entity_type', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default='running', nullable=False),
    sa.Column('started_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('config_fingerprint', sa.Text(), nullable=False),
    sa.Column('stats', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('institution_id', sa.Integer(), nullable=True),
    sa.CheckConstraint("status IN ('running', 'completed', 'failed', 'superseded')", name='ck_harvest_runs_status'),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_harvest_runs_institution', 'harvest_runs', ['institution_id', 'id'], unique=False)
    op.create_table('institution_trends',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('works_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('corresponding_count', sa.Integer(), nullable=True),
    sa.Column('oa_gold', sa.Integer(), server_default='0', nullable=False),
    sa.Column('oa_hybrid', sa.Integer(), server_default='0', nullable=False),
    sa.Column('oa_green', sa.Integer(), server_default='0', nullable=False),
    sa.Column('oa_bronze', sa.Integer(), server_default='0', nullable=False),
    sa.Column('oa_diamond', sa.Integer(), server_default='0', nullable=False),
    sa.Column('oa_closed', sa.Integer(), server_default='0', nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ),
    sa.PrimaryKeyConstraint('institution_id', 'year')
    )
    op.create_table('institution_works_stats',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('issn_l', sa.String(length=9), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('works_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('oa_gold', sa.Integer(), server_default='0', nullable=False),
    sa.Column('oa_hybrid', sa.Integer(), server_default='0', nullable=False),
    sa.Column('oa_green', sa.Integer(), server_default='0', nullable=False),
    sa.Column('oa_bronze', sa.Integer(), server_default='0', nullable=False),
    sa.Column('oa_diamond', sa.Integer(), server_default='0', nullable=False),
    sa.Column('oa_closed', sa.Integer(), server_default='0', nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('source', sa.Text(), server_default='openalex_institution_filter', nullable=False),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ),
    sa.PrimaryKeyConstraint('institution_id', 'source', 'issn_l', 'year')
    )
    op.create_table('journals',
    sa.Column('issn_l', sa.String(length=9), nullable=False),
    sa.Column('openalex_id', sa.Text(), nullable=True),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('publisher_name', sa.Text(), nullable=True),
    sa.Column('publisher_id', sa.Integer(), nullable=True),
    sa.Column('type', sa.Text(), nullable=True),
    sa.Column('is_oa', sa.Boolean(), nullable=True),
    sa.Column('is_in_doaj', sa.Boolean(), nullable=True),
    sa.Column('homepage_url', sa.Text(), nullable=True),
    sa.Column('country_code', sa.Text(), nullable=True),
    sa.Column('issns', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('alternate_titles', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('topics', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('apc_prices', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('summary_stats', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('counts_by_year', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('works_count', sa.Integer(), nullable=True),
    sa.Column('cited_by_count', sa.Integer(), nullable=True),
    sa.Column('openaire_meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('harvested_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('search_text', sa.Text(), nullable=True),
    sa.Column('search_vector', postgresql.TSVECTOR(), sa.Computed("to_tsvector('english', coalesce(search_text, ''))", persisted=True), nullable=True),
    sa.Column('last_active_year', sa.Integer(), nullable=True),
    sa.Column('in_scimago', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('works_2020_plus', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('latest_quartile', sa.String(length=4), nullable=True),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
    sa.Column('latest_apc_euro', sa.Numeric(), nullable=True),
    sa.Column('publisher_canonical', sa.Text(), nullable=True),
    sa.Column('oa_status_observed', sa.String(length=16), nullable=True),
    sa.Column('doaj_in_doaj', sa.Boolean(), nullable=True),
    sa.Column('doaj_has_apc', sa.Boolean(), nullable=True),
    sa.Column('doaj_apc_max', sa.Numeric(), nullable=True),
    sa.Column('doaj_apc_currency', sa.String(length=3), nullable=True),
    sa.Column('doaj_homepage_url', sa.Text(), nullable=True),
    sa.Column('doaj_harvested_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('jisc_in_opf', sa.Boolean(), nullable=True),
    sa.Column('jisc_oa_prohibited', sa.Boolean(), nullable=True),
    sa.Column('jisc_sherpa_id', sa.Integer(), nullable=True),
    sa.Column('jisc_allows_sa_submitted', sa.Boolean(), nullable=True),
    sa.Column('jisc_allows_sa_accepted', sa.Boolean(), nullable=True),
    sa.Column('jisc_allows_sa_published', sa.Boolean(), nullable=True),
    sa.Column('jisc_embargo_accepted_months', sa.Integer(), nullable=True),
    sa.Column('jisc_policy', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('jisc_harvested_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('language', sa.String(length=8), nullable=True),
    sa.ForeignKeyConstraint(['publisher_id'], ['publishers.id'], ),
    sa.PrimaryKeyConstraint('issn_l'),
    sa.UniqueConstraint('openalex_id')
    )
    op.create_table('openaire_funder_streams',
    sa.Column('funder_openaire_id', sa.Text(), nullable=False),
    sa.Column('level0_id', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('n_projects', sa.Integer(), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['funder_openaire_id'], ['openaire_funders.openaire_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('funder_openaire_id', 'level0_id')
    )
    op.create_table('openalex_work_authors',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('author_id', sa.Text(), nullable=False),
    sa.Column('w_id', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('institution_id', 'author_id', 'w_id')
    )
    op.create_table('openalex_work_parents',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('parent_w_id', sa.Text(), nullable=False),
    sa.Column('doi_normalized', sa.Text(), nullable=True),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('work_type', sa.Text(), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('institution_id', 'parent_w_id')
    )
    op.create_table('openalex_works',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('w_id', sa.Text(), nullable=False),
    sa.Column('doi_normalized', sa.Text(), nullable=True),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('year', sa.Integer(), nullable=True),
    sa.Column('work_type', sa.Text(), nullable=True),
    sa.Column('oa_status', sa.Text(), nullable=True),
    sa.Column('venue_issn_l', sa.Text(), nullable=True),
    sa.Column('venue_name', sa.Text(), nullable=True),
    sa.Column('authorships', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('cited_by_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('fwci', sa.Float(), nullable=True),
    sa.Column('is_retracted', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('source', sa.Text(), server_default='works_stats', nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('language', sa.Text(), nullable=True),
    sa.Column('source_type', sa.Text(), nullable=True),
    sa.Column('parent_works', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('is_part', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('parts_checked_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('publication_date', sa.Text(), nullable=True),
    sa.Column('pdf_url', sa.Text(), nullable=True),
    sa.Column('landing_page_url', sa.Text(), nullable=True),
    sa.Column('institution_rors', sa.Text(), nullable=True),
    sa.CheckConstraint("oa_status IN ('gold', 'hybrid', 'green', 'bronze', 'diamond', 'closed')", name='ck_openalex_works_oa_status'),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('institution_id', 'w_id')
    )
    op.create_index('ix_openalex_works_inst_doi', 'openalex_works', ['institution_id', 'doi_normalized'], unique=False, postgresql_where=sa.text('doi_normalized IS NOT NULL'))
    op.create_index('ix_openalex_works_inst_issn', 'openalex_works', ['institution_id', 'venue_issn_l'], unique=False, postgresql_where=sa.text('venue_issn_l IS NOT NULL'))
    op.create_index('ix_openalex_works_inst_year', 'openalex_works', ['institution_id', 'year'], unique=False, postgresql_where=sa.text('year IS NOT NULL'))
    op.create_table('pure_orgs',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('uuid', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('org_type', sa.Text(), nullable=True),
    sa.Column('identifiers', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('institution_id', 'uuid')
    )
    op.create_table('pure_persons',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('uuid', sa.Text(), nullable=False),
    sa.Column('orcid', sa.Text(), nullable=True),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('institution_id', 'uuid')
    )
    op.create_index('ix_pure_persons_inst_orcid', 'pure_persons', ['institution_id', 'orcid'], unique=False, postgresql_where=sa.text('orcid IS NOT NULL'))
    op.create_table('deal_institutions',
    sa.Column('deal_id', sa.Integer(), nullable=False),
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('first_seen', sa.Text(), nullable=True),
    sa.Column('last_seen', sa.Text(), nullable=True),
    sa.Column('participation', sa.Text(), nullable=True),
    sa.Column('participation_note', sa.Text(), nullable=True),
    sa.Column('journal_override', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.CheckConstraint("participation IN ('named', 'consortium')", name='ck_deal_institutions_participation'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ),
    sa.PrimaryKeyConstraint('deal_id', 'institution_id')
    )
    op.create_table('deal_journals',
    sa.Column('deal_id', sa.Integer(), nullable=False),
    sa.Column('issn', sa.String(length=9), nullable=False),
    sa.Column('issn_l', sa.String(length=9), nullable=True),
    sa.Column('journal_name', sa.Text(), nullable=True),
    sa.Column('first_seen', sa.Text(), nullable=True),
    sa.Column('last_seen', sa.Text(), nullable=True),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('needs_curation', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('institution_id', sa.Integer(), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('excluded', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('needs_curation_reason', sa.Text(), nullable=True),
    sa.CheckConstraint("source IN ('jct', 'manual', 'publisher-pattern')", name='ck_deal_journals_source'),
    sa.CheckConstraint('needs_curation = true OR needs_curation_reason IS NULL', name='ck_deal_journals_curation_reason'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_deal_journals_issn_l'), 'deal_journals', ['issn_l'], unique=False)
    op.create_index('uq_deal_journals_scoped', 'deal_journals', ['deal_id', 'issn', 'institution_id'], unique=True, postgresql_where=sa.text('institution_id IS NOT NULL'))
    op.create_index('uq_deal_journals_shared', 'deal_journals', ['deal_id', 'issn'], unique=True, postgresql_where=sa.text('institution_id IS NULL'))
    op.create_table('harvest_state',
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('entity_type', sa.Text(), nullable=False),
    sa.Column('filter_set', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=True),
    sa.Column('stats', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('last_run_id', sa.BigInteger(), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('institution_id', sa.Integer(), nullable=True),
    sa.CheckConstraint("status IN ('running', 'completed', 'failed', 'superseded')", name='ck_harvest_state_status'),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ),
    sa.ForeignKeyConstraint(['last_run_id'], ['harvest_runs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('uq_harvest_state_global', 'harvest_state', ['source', 'entity_type', 'filter_set'], unique=True, postgresql_where=sa.text('institution_id IS NULL'))
    op.create_index('uq_harvest_state_scoped', 'harvest_state', ['source', 'entity_type', 'filter_set', 'institution_id'], unique=True, postgresql_where=sa.text('institution_id IS NOT NULL'))
    op.create_table('journal_flags',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('issn_l', sa.String(length=9), nullable=False),
    sa.Column('works_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('deal_covered', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('works_window_plus', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('browse_excluded', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('deal_cap_reached', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('openaire_diamond', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['issn_l'], ['journals.issn_l'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('institution_id', 'issn_l')
    )
    op.create_table('people_utwente_person_orgs',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('person_uuid', sa.Text(), nullable=False),
    sa.Column('org_uuid', sa.Text(), nullable=False),
    sa.Column('people_slug', sa.Text(), nullable=False),
    sa.Column('org_abbr', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['institution_id', 'org_uuid'], ['pure_orgs.institution_id', 'pure_orgs.uuid'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['institution_id', 'person_uuid'], ['pure_persons.institution_id', 'pure_persons.uuid'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('institution_id', 'person_uuid', 'org_uuid')
    )
    op.create_table('people_utwente_persons',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('person_uuid', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default='missed', nullable=False),
    sa.Column('slug', sa.Text(), nullable=True),
    sa.Column('canonical_name', sa.Text(), nullable=True),
    sa.Column('email', sa.Text(), nullable=True),
    sa.Column('orgs', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('faculty_abbr', sa.Text(), nullable=True),
    sa.Column('portal_person_url', sa.Text(), nullable=True),
    sa.Column('photo_url', sa.Text(), nullable=True),
    sa.Column('photo_media_type', sa.Text(), nullable=True),
    sa.Column('photo_bytes', sa.LargeBinary(), nullable=True),
    sa.Column('match_method', sa.Text(), nullable=True),
    sa.Column('match_confidence', sa.Float(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('synced_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('matched', 'candidate', 'missed')", name='ck_people_utwente_persons_status'),
    sa.ForeignKeyConstraint(['institution_id', 'person_uuid'], ['pure_persons.institution_id', 'pure_persons.uuid'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('institution_id', 'person_uuid')
    )
    op.create_index('ux_people_utwente_persons_inst_slug', 'people_utwente_persons', ['institution_id', 'slug'], unique=True, postgresql_where=sa.text('slug IS NOT NULL'))
    op.create_table('pure_org_parents',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('org_uuid', sa.Text(), nullable=False),
    sa.Column('parent_uuid', sa.Text(), nullable=False),
    sa.Column('parent_name', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['institution_id', 'org_uuid'], ['pure_orgs.institution_id', 'pure_orgs.uuid'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('institution_id', 'org_uuid', 'parent_uuid')
    )
    op.create_table('pure_person_orgs',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('person_uuid', sa.Text(), nullable=False),
    sa.Column('org_uuid', sa.Text(), nullable=False),
    sa.Column('role', sa.Text(), nullable=True),
    sa.Column('portal_person_slug', sa.Text(), nullable=False),
    sa.Column('portal_org_slug', sa.Text(), nullable=False),
    sa.Column('listing_kinds', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.ForeignKeyConstraint(['institution_id', 'org_uuid'], ['pure_orgs.institution_id', 'pure_orgs.uuid'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['institution_id', 'person_uuid'], ['pure_persons.institution_id', 'pure_persons.uuid'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('institution_id', 'person_uuid', 'org_uuid')
    )
    op.create_table('raw_files',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('entity_type', sa.Text(), nullable=False),
    sa.Column('source_pk', sa.Text(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('content_hash', sa.Text(), nullable=False),
    sa.Column('path', sa.Text(), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('fetched_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('harvest_run_id', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['harvest_run_id'], ['harvest_runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'entity_type', 'source_pk', 'content_hash', name='uq_raw_files_version')
    )
    op.create_table('source_records',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('entity_type', sa.Text(), nullable=False),
    sa.Column('source_pk', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('content_hash', sa.Text(), nullable=False),
    sa.Column('harvested_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('harvest_run_id', sa.BigInteger(), nullable=False),
    sa.Column('publication_year', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['harvest_run_id'], ['harvest_runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'entity_type', 'source_pk', 'content_hash', name='uq_source_records_version')
    )
    op.create_index('ix_source_records_lookup', 'source_records', ['source', 'entity_type', 'source_pk', sa.literal_column('harvested_at DESC')], unique=False)
    op.create_table('works',
    sa.Column('pure_uuid', sa.Text(), nullable=False),
    sa.Column('doi_normalized', sa.Text(), nullable=True),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('norm_title', sa.Text(), nullable=False),
    sa.Column('year', sa.SmallInteger(), nullable=False),
    sa.Column('work_type', sa.Text(), nullable=True),
    sa.Column('publisher', sa.Text(), nullable=True),
    sa.Column('cerif_issn', sa.Text(), nullable=True),
    sa.Column('oa_status', sa.Text(), nullable=True),
    sa.Column('first_seen_run', sa.BigInteger(), nullable=False),
    sa.Column('last_seen_run', sa.BigInteger(), nullable=False),
    sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('journal_issn_l', sa.Text(), nullable=True),
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('funders_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("oa_status IN ('gold', 'hybrid', 'green', 'bronze', 'diamond', 'closed')", name='ck_works_oa_status'),
    sa.ForeignKeyConstraint(['first_seen_run'], ['harvest_runs.id'], name='ut_works_first_seen_run_fkey'),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ),
    sa.ForeignKeyConstraint(['journal_issn_l'], ['journals.issn_l'], name='ut_works_journal_issn_l_fkey'),
    sa.ForeignKeyConstraint(['last_seen_run'], ['harvest_runs.id'], name='ut_works_last_seen_run_fkey'),
    sa.PrimaryKeyConstraint('institution_id', 'pure_uuid')
    )
    op.create_index('ix_works_inst_journal', 'works', ['institution_id', 'journal_issn_l'], unique=False, postgresql_where=sa.text('journal_issn_l IS NOT NULL'))
    op.create_index('uq_works_inst_doi', 'works', ['institution_id', 'doi_normalized'], unique=True, postgresql_where=sa.text('doi_normalized IS NOT NULL'))
    op.create_table('apc_evidence',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('doi', sa.Text(), nullable=True),
    sa.Column('period', sa.Integer(), nullable=True),
    sa.Column('euro', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('is_hybrid', sa.Boolean(), nullable=True),
    sa.Column('agreement', sa.Text(), nullable=True),
    sa.Column('group_id', sa.Text(), nullable=True),
    sa.Column('issn_l', sa.String(length=9), nullable=True),
    sa.Column('institution_id', sa.Integer(), nullable=True),
    sa.Column('source', sa.Text(), server_default='openapc', nullable=False),
    sa.Column('source_record_id', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ),
    sa.ForeignKeyConstraint(['source_record_id'], ['source_records.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_apc_evidence_doi'), 'apc_evidence', ['doi'], unique=False)
    op.create_index('ix_apc_evidence_issn_period', 'apc_evidence', ['issn_l', 'period'], unique=False)
    op.create_table('author_works',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('author_pure_uuid', sa.Text(), nullable=False),
    sa.Column('work_pure_uuid', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['institution_id', 'author_pure_uuid'], ['authors.institution_id', 'authors.pure_uuid'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['institution_id', 'work_pure_uuid'], ['works.institution_id', 'works.pure_uuid'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('institution_id', 'author_pure_uuid', 'work_pure_uuid')
    )
    op.create_table('openaire_work_facts',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('pure_uuid', sa.Text(), nullable=False),
    sa.Column('source_pk', sa.Text(), nullable=False),
    sa.Column('views', sa.Integer(), nullable=True),
    sa.Column('downloads', sa.Integer(), nullable=True),
    sa.Column('diamond', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('oa_color', sa.Text(), nullable=True),
    sa.Column('license', sa.Text(), nullable=True),
    sa.Column('oa_url', sa.Text(), nullable=True),
    sa.Column('embargo_end', sa.Date(), nullable=True),
    sa.Column('fos', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('projects', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['institution_id', 'pure_uuid'], ['works.institution_id', 'works.pure_uuid'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('institution_id', 'pure_uuid')
    )
    op.create_table('work_funders',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('pure_uuid', sa.Text(), nullable=False),
    sa.Column('funder_openalex_id', sa.Text(), nullable=False),
    sa.Column('funder_name', sa.Text(), nullable=True),
    sa.Column('award', sa.Text(), nullable=True),
    sa.Column('harvested_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['institution_id', 'pure_uuid'], ['works.institution_id', 'works.pure_uuid'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('institution_id', 'pure_uuid', 'funder_openalex_id')
    )
    op.create_table('work_identity',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('source_pk', sa.Text(), nullable=False),
    sa.Column('work_id', sa.Text(), nullable=False),
    sa.Column('matched_by', sa.Text(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('status', sa.Text(), server_default='candidate', nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.CheckConstraint("matched_by ~ '^(doi|verbatim|trgm:.+)$'", name='ck_work_identity_matched_by'),
    sa.CheckConstraint("status IN ('confirmed', 'missing', 'candidate')", name='ck_work_identity_status'),
    sa.ForeignKeyConstraint(['institution_id', 'work_id'], ['works.institution_id', 'works.pure_uuid'], name='work_identity_work_fkey', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('institution_id', 'source', 'source_pk', name='uq_work_identity_source')
    )
    op.create_index('ix_work_identity_inst_work', 'work_identity', ['institution_id', 'work_id'], unique=False)
    op.create_table('work_pure_authors',
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('work_pure_uuid', sa.Text(), nullable=False),
    sa.Column('person_uuid', sa.Text(), nullable=False),
    sa.Column('position', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('first_names', sa.Text(), nullable=True),
    sa.Column('family_names', sa.Text(), nullable=True),
    sa.Column('affiliations', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.ForeignKeyConstraint(['institution_id', 'work_pure_uuid'], ['works.institution_id', 'works.pure_uuid'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('institution_id', 'work_pure_uuid', 'person_uuid')
    )
    op.create_index('ix_work_pure_authors_inst_person', 'work_pure_authors', ['institution_id', 'person_uuid'], unique=False)
    # Not declared on the model, so autogenerate cannot see them; carried
    # over verbatim from the pre-squash chain (0008, 0012, 0015, 0018, 0020).
    op.execute("ALTER TABLE journal_flags SET (fillfactor = 70)")
    op.execute("CREATE INDEX ix_funder_links_source ON public.funder_links USING btree (source, source_id)")
    op.execute("CREATE INDEX ix_issn_map_issn_l ON public.issn_map USING btree (issn_l)")
    op.execute("CREATE INDEX ix_issn_map_issn_norm ON public.issn_map USING btree (upper(replace((issn)::text, '-'::text, ''::text)))")
    op.execute("CREATE INDEX ix_journals_embedding ON public.journals USING hnsw (embedding public.vector_cosine_ops) WHERE (embedding IS NOT NULL)")
    op.execute("CREATE INDEX ix_journals_embedding_hnsw ON public.journals USING hnsw (embedding public.vector_cosine_ops)")
    op.execute("CREATE INDEX ix_journals_issn_l_corpus ON public.journals USING btree (issn_l) WHERE ((works_2020_plus > 3) AND (type = 'journal'::text) AND (issn_l IS NOT NULL))")
    op.execute("CREATE INDEX ix_journals_publisher_name_trgm ON public.journals USING gin (publisher_name public.gin_trgm_ops)")
    op.execute("CREATE INDEX ix_journals_search_text_trgm ON public.journals USING gin (search_text public.gin_trgm_ops)")
    op.execute("CREATE INDEX ix_journals_search_vector ON public.journals USING gin (search_vector)")
    op.execute("CREATE INDEX ix_journals_topics_gin ON public.journals USING gin (topics jsonb_path_ops)")
    op.execute("CREATE INDEX ix_journals_topics_text_trgm ON public.journals USING gin (((topics)::text) public.gin_trgm_ops)")
    op.execute("CREATE INDEX ix_journals_works_2020_plus ON public.journals USING btree (works_2020_plus) WHERE (works_2020_plus > 3)")
    op.execute("CREATE INDEX ix_source_records_sources_issn_l ON public.source_records USING btree (((payload ->> 'issn_l'::text)), harvested_at DESC) WHERE ((source = 'openalex'::text) AND (entity_type = 'sources'::text))")
    op.execute("CREATE INDEX ix_source_records_works_issn_l ON public.source_records USING btree (((((payload -> 'primary_location'::text) -> 'source'::text) ->> 'issn_l'::text)), source_pk, harvested_at DESC) WHERE ((source = 'openalex'::text) AND (entity_type = 'works_stats'::text))")
    op.execute("CREATE INDEX ix_source_records_works_year ON public.source_records USING btree (publication_year, source_pk, harvested_at DESC) WHERE ((source = 'openalex'::text) AND (entity_type = 'works_stats'::text))")
    op.execute("CREATE INDEX ix_ut_works_norm_title ON public.works USING btree (norm_title)")
    op.execute("CREATE INDEX ix_ut_works_norm_title_trgm ON public.works USING gin (norm_title public.gin_trgm_ops)")
    op.execute("CREATE INDEX ix_ut_works_year ON public.works USING btree (year)")
    op.execute("CREATE INDEX ix_work_identity_status ON public.work_identity USING btree (status)")
    op.execute("CREATE INDEX ix_work_identity_ut_work ON public.work_identity USING btree (work_id)")


def downgrade() -> None:
    op.drop_index('ix_work_pure_authors_inst_person', table_name='work_pure_authors')
    op.drop_table('work_pure_authors')
    op.drop_index('ix_work_identity_inst_work', table_name='work_identity')
    op.drop_table('work_identity')
    op.drop_table('work_funders')
    op.drop_table('openaire_work_facts')
    op.drop_table('author_works')
    op.drop_index('ix_apc_evidence_issn_period', table_name='apc_evidence')
    op.drop_index(op.f('ix_apc_evidence_doi'), table_name='apc_evidence')
    op.drop_table('apc_evidence')
    op.drop_index('uq_works_inst_doi', table_name='works', postgresql_where=sa.text('doi_normalized IS NOT NULL'))
    op.drop_index('ix_works_inst_journal', table_name='works', postgresql_where=sa.text('journal_issn_l IS NOT NULL'))
    op.drop_table('works')
    op.drop_index('ix_source_records_lookup', table_name='source_records')
    op.drop_table('source_records')
    op.drop_table('raw_files')
    op.drop_table('pure_person_orgs')
    op.drop_table('pure_org_parents')
    op.drop_index('ux_people_utwente_persons_inst_slug', table_name='people_utwente_persons', postgresql_where=sa.text('slug IS NOT NULL'))
    op.drop_table('people_utwente_persons')
    op.drop_table('people_utwente_person_orgs')
    op.drop_table('journal_flags')
    op.drop_index('uq_harvest_state_scoped', table_name='harvest_state', postgresql_where=sa.text('institution_id IS NOT NULL'))
    op.drop_index('uq_harvest_state_global', table_name='harvest_state', postgresql_where=sa.text('institution_id IS NULL'))
    op.drop_table('harvest_state')
    op.drop_index('uq_deal_journals_shared', table_name='deal_journals', postgresql_where=sa.text('institution_id IS NULL'))
    op.drop_index('uq_deal_journals_scoped', table_name='deal_journals', postgresql_where=sa.text('institution_id IS NOT NULL'))
    op.drop_index(op.f('ix_deal_journals_issn_l'), table_name='deal_journals')
    op.drop_table('deal_journals')
    op.drop_table('deal_institutions')
    op.drop_index('ix_pure_persons_inst_orcid', table_name='pure_persons', postgresql_where=sa.text('orcid IS NOT NULL'))
    op.drop_table('pure_persons')
    op.drop_table('pure_orgs')
    op.drop_index('ix_openalex_works_inst_year', table_name='openalex_works', postgresql_where=sa.text('year IS NOT NULL'))
    op.drop_index('ix_openalex_works_inst_issn', table_name='openalex_works', postgresql_where=sa.text('venue_issn_l IS NOT NULL'))
    op.drop_index('ix_openalex_works_inst_doi', table_name='openalex_works', postgresql_where=sa.text('doi_normalized IS NOT NULL'))
    op.drop_table('openalex_works')
    op.drop_table('openalex_work_parents')
    op.drop_table('openalex_work_authors')
    op.drop_table('openaire_funder_streams')
    op.drop_table('journals')
    op.drop_table('institution_works_stats')
    op.drop_table('institution_trends')
    op.drop_index('ix_harvest_runs_institution', table_name='harvest_runs')
    op.drop_table('harvest_runs')
    op.drop_table('funder_links')
    op.drop_index('ix_deals_publisher', table_name='deals')
    op.drop_table('deals')
    op.drop_table('authors')
    op.drop_index('ix_author_identities_inst_status', table_name='author_identities')
    op.drop_index('ix_author_identities_inst_author', table_name='author_identities')
    op.drop_table('author_identities')
    op.drop_index('ix_usage_events_type_ts', table_name='usage_events')
    op.drop_index('ix_usage_events_ts', table_name='usage_events')
    op.drop_index('ix_usage_events_session', table_name='usage_events')
    op.drop_table('usage_events')
    op.drop_index('ix_status_changes_table_time', table_name='status_changes')
    op.drop_table('status_changes')
    op.drop_table('scimagojr_metrics')
    op.drop_table('publishers')
    op.drop_table('openalex_publishers')
    op.drop_table('openalex_funders')
    op.drop_table('openaire_funders')
    op.drop_table('manual_overrides')
    op.drop_table('limitations')
    op.drop_table('journal_apc_aggregates')
    op.drop_table('jisc_repositories')
    op.drop_table('jisc_publishers')
    op.drop_table('jisc_publications')
    op.drop_table('jisc_policies')
    op.drop_table('jisc_funders')
    op.drop_table('jisc_funder_groups')
    op.drop_table('issn_map')
    op.drop_table('institutions')
    op.drop_table('feedback_items')
    op.drop_table('doc_edits')
    op.drop_table('cache_epoch')
    op.execute("DROP EXTENSION IF EXISTS vector")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
