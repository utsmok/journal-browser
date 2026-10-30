"""Multi-institution shared core: institutions as config, works rename,
per-institution journal flags, deal relation fields, harvest scoping.

One coordinated cutover: works/stats move from a single home institution to
institution-scoped rows, the journals denorm columns move to journal_flags,
and deals gain per-relation participation + override fields. Reversible on a
single-institution database; downgrade from a multi-institution database
keeps only the default institution's rows.

Revision ID: 0019_multi_institution
Revises: 0018_ut_works_journal_idx
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0019_multi_institution"
down_revision = "0018_ut_works_journal_idx"
branch_labels = None
depends_on = None

# Sources whose runs/states are per-institution (for the backfill stamp);
# everything else is global. Matches the harvest split in jobs/bootstrap.py.
PER_INSTITUTION_SOURCES = ("'pure'", "'openaire'")
PER_INSTITUTION_PREDICATE = (
    "source IN ('pure', 'openaire') "
    "OR (source = 'openalex' AND entity_type = 'works_stats') "
    "OR (source = 'crossref' AND entity_type = 'work')"
)


def _settings() -> dict:
    """Env-derived seed for the default institution (JB_* vars, no .env
    cache: compose runs alembic with the same env as the app)."""
    from journal_browser.config import Settings

    s = Settings()
    return {
        "code": s.institution_code,
        "name": s.institution_name,
        "short_name": s.institution_short,
        "ror": s.institution_ror,
        "pure_oai_base_url": s.pure_oai_base_url,
        "openaire_org_id": s.openaire_org_id or None,
        "external_works_dsn": s.ut_metadata_dsn or None,
        "data_window_start": s.data_window_start,
        # 0 = open until 0032 converts the sentinel to NULL; the column is
        # still NOT NULL at this point in the chain.
        "data_window_end": s.data_window_end if s.data_window_end is not None else 0,
        "library_url": s.library_url,
        "oa_guide_url": s.oa_guide_url,
        "support_email": s.support_email,
        "admin_contact": s.admin_contact or None,
        "research_portal_url": s.research_portal_url,
    }


def upgrade() -> None:
    conn = op.get_bind()

    # ── institutions: configuration carrier ────────────────────────────────
    op.add_column("institutions", sa.Column("code", pg.TEXT(), nullable=True))
    op.add_column("institutions", sa.Column("short_name", pg.TEXT(), nullable=True))
    op.add_column("institutions", sa.Column("pure_oai_base_url", pg.TEXT(), nullable=True))
    op.add_column("institutions", sa.Column("openaire_org_id", pg.TEXT(), nullable=True))
    op.add_column("institutions", sa.Column("external_works_dsn", pg.TEXT(), nullable=True))
    op.add_column(
        "institutions",
        sa.Column("data_window_start", sa.Integer(), nullable=False, server_default="2020"),
    )
    op.add_column(
        "institutions",
        sa.Column("data_window_end", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("institutions", sa.Column("library_url", pg.TEXT(), nullable=True))
    op.add_column("institutions", sa.Column("oa_guide_url", pg.TEXT(), nullable=True))
    op.add_column("institutions", sa.Column("support_email", pg.TEXT(), nullable=True))
    op.add_column("institutions", sa.Column("admin_contact", pg.TEXT(), nullable=True))
    op.add_column("institutions", sa.Column("research_portal_url", pg.TEXT(), nullable=True))
    op.add_column(
        "institutions",
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "institutions",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_unique_constraint("uq_institutions_code", "institutions", ["code"])

    # Seed the default institution from env (backfill-order footgun: this
    # row must exist before works rows are stamped). ON CONFLICT (ror)
    # updates the existing is_home row on a live database.
    seed = _settings()
    inst_id = conn.execute(
        sa.text(
            """
            INSERT INTO institutions (code, name, short_name, ror,
                pure_oai_base_url, openaire_org_id, external_works_dsn,
                data_window_start, data_window_end, library_url, oa_guide_url,
                support_email, admin_contact, research_portal_url,
                active, is_default)
            VALUES (:code, :name, :short_name, :ror, :pure_oai_base_url,
                :openaire_org_id, :external_works_dsn, :data_window_start,
                :data_window_end, :library_url, :oa_guide_url, :support_email,
                :admin_contact, :research_portal_url, true, true)
            ON CONFLICT (ror) DO UPDATE SET
                code = EXCLUDED.code, short_name = EXCLUDED.short_name,
                pure_oai_base_url = EXCLUDED.pure_oai_base_url,
                openaire_org_id = EXCLUDED.openaire_org_id,
                external_works_dsn = EXCLUDED.external_works_dsn,
                data_window_start = EXCLUDED.data_window_start,
                data_window_end = EXCLUDED.data_window_end,
                library_url = EXCLUDED.library_url,
                oa_guide_url = EXCLUDED.oa_guide_url,
                support_email = EXCLUDED.support_email,
                admin_contact = EXCLUDED.admin_contact,
                research_portal_url = EXCLUDED.research_portal_url,
                active = true, is_default = true
            RETURNING id
            """
        ),
        seed,
    ).scalar_one()

    # ── journal_flags: per-institution denorm state ────────────────────────
    op.create_table(
        "journal_flags",
        sa.Column(
            "institution_id",
            sa.Integer(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "issn_l", sa.String(9), sa.ForeignKey("journals.issn_l", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("works_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deal_covered", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("works_window_plus", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("browse_excluded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    # Backfill from the retiring journals denorm columns + the window cutoff
    # (same SQL shape as jobs/backfill_flags.py, evaluated once).
    ws, we = seed["data_window_start"], seed["data_window_end"] or 9999
    conn.execute(
        sa.text(
            """
            INSERT INTO journal_flags
                (institution_id, issn_l, works_count, deal_covered,
                 works_window_plus, browse_excluded)
            SELECT :iid, j.issn_l, coalesce(j.home_works_count, 0),
                   j.deal_covered_home,
                   coalesce((
                       SELECT sum((e->>'works_count')::int)
                       FROM jsonb_array_elements(j.counts_by_year) e
                       WHERE e->>'year' ~ '^[0-9]+$'
                         AND (e->>'year')::int BETWEEN :ws AND :we
                   ), 0),
                   j.browse_excluded
            FROM journals j
            """
        ),
        {"iid": inst_id, "ws": ws, "we": we},
    )

    # ── ut_works → works (rename, keep data) ───────────────────────────────
    op.rename_table("ut_works", "works")
    op.add_column(
        "works",
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
    )
    conn.execute(sa.text("UPDATE works SET institution_id = :iid"), {"iid": inst_id})
    op.alter_column("works", "institution_id", nullable=False)

    # work_identity's FK sits on ut_works_pkey: stamp + drop it before the
    # PK can be replaced by the composite one.
    op.add_column(
        "work_identity",
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
    )
    conn.execute(
        sa.text(
            "UPDATE work_identity wi SET institution_id = w.institution_id "
            "FROM works w WHERE w.pure_uuid = wi.ut_work_id"
        )
    )
    op.alter_column("work_identity", "institution_id", nullable=False)
    op.drop_constraint("work_identity_ut_work_id_fkey", "work_identity", type_="foreignkey")
    op.drop_constraint("ut_works_pkey", "works", type_="primary")
    op.create_primary_key("works_pkey", "works", ["institution_id", "pure_uuid"])
    op.drop_constraint("ut_works_doi_normalized_key", "works", type_="unique")
    op.create_index(
        "uq_works_inst_doi",
        "works",
        ["institution_id", "doi_normalized"],
        unique=True,
        postgresql_where=sa.text("doi_normalized IS NOT NULL"),
    )
    op.drop_index("ix_ut_works_journal_issn_l", table_name="works")
    op.create_index(
        "ix_works_inst_journal",
        "works",
        ["institution_id", "journal_issn_l"],
        postgresql_where=sa.text("journal_issn_l IS NOT NULL"),
    )
    op.alter_column("work_identity", "ut_work_id", new_column_name="work_id")
    op.create_foreign_key(
        "work_identity_work_fkey",
        "work_identity",
        "works",
        ["institution_id", "work_id"],
        ["institution_id", "pure_uuid"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_work_identity_source", "work_identity", type_="unique")
    op.create_unique_constraint(
        "uq_work_identity_source", "work_identity", ["institution_id", "source", "source_pk"]
    )
    op.create_index("ix_work_identity_inst_work", "work_identity", ["institution_id", "work_id"])

    # ── deals: per-relation participation + override coverage ──────────────
    op.add_column("deal_institutions", sa.Column("participation", pg.TEXT(), nullable=True))
    op.add_column("deal_institutions", sa.Column("participation_note", pg.TEXT(), nullable=True))
    op.add_column(
        "deal_institutions",
        sa.Column("journal_override", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "deal_journals",
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
    )
    conn.execute(sa.text("ALTER TABLE deal_journals ADD COLUMN id BIGSERIAL"))
    op.drop_constraint("deal_journals_pkey", "deal_journals", type_="primary")
    op.create_primary_key("deal_journals_pkey", "deal_journals", ["id"])
    op.create_index(
        "uq_deal_journals_shared",
        "deal_journals",
        ["deal_id", "issn"],
        unique=True,
        postgresql_where=sa.text("institution_id IS NULL"),
    )
    op.create_index(
        "uq_deal_journals_scoped",
        "deal_journals",
        ["deal_id", "issn", "institution_id"],
        unique=True,
        postgresql_where=sa.text("institution_id IS NOT NULL"),
    )

    # ── harvest bookkeeping: institution scope ─────────────────────────────
    op.add_column(
        "harvest_runs",
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
    )
    conn.execute(sa.text("ALTER TABLE harvest_state ADD COLUMN id BIGSERIAL"))
    op.add_column(
        "harvest_state",
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
    )
    conn.execute(
        sa.text(f"UPDATE harvest_runs SET institution_id = :iid WHERE {PER_INSTITUTION_PREDICATE}"),
        {"iid": inst_id},
    )
    conn.execute(
        sa.text(
            f"UPDATE harvest_state SET institution_id = :iid WHERE {PER_INSTITUTION_PREDICATE}"
        ),
        {"iid": inst_id},
    )
    op.drop_constraint("harvest_state_pkey", "harvest_state", type_="primary")
    op.create_primary_key("harvest_state_pkey", "harvest_state", ["id"])
    op.create_index(
        "uq_harvest_state_global",
        "harvest_state",
        ["source", "entity_type", "filter_set"],
        unique=True,
        postgresql_where=sa.text("institution_id IS NULL"),
    )
    op.create_index(
        "uq_harvest_state_scoped",
        "harvest_state",
        ["source", "entity_type", "filter_set", "institution_id"],
        unique=True,
        postgresql_where=sa.text("institution_id IS NOT NULL"),
    )
    op.create_index("ix_harvest_runs_institution", "harvest_runs", ["institution_id", "id"])

    # ── retire the single-home columns ─────────────────────────────────────
    op.drop_column("journals", "deal_covered_home")
    op.drop_column("journals", "home_works_count")
    op.drop_column("journals", "browse_excluded")
    op.drop_column("institutions", "is_home")


def downgrade() -> None:
    conn = op.get_bind()
    inst_id = conn.execute(
        sa.text("SELECT id FROM institutions WHERE is_default ORDER BY id LIMIT 1")
    ).scalar()
    if inst_id is None:  # no seeded default; keep downgrade usable on bare DBs
        inst_id = conn.execute(sa.text("SELECT min(id) FROM institutions")).scalar()

    # Single-home columns return, refilled from journal_flags for the
    # default institution; other institutions' state is dropped.
    op.add_column(
        "institutions",
        sa.Column("is_home", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "journals",
        sa.Column(
            "deal_covered_home", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column("journals", sa.Column("home_works_count", sa.Integer(), nullable=True))
    op.add_column(
        "journals",
        sa.Column("browse_excluded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    if inst_id is not None:
        conn.execute(
            sa.text(
                """
                UPDATE journals j SET
                    deal_covered_home = f.deal_covered,
                    home_works_count = f.works_count,
                    browse_excluded = f.browse_excluded
                FROM journal_flags f
                WHERE f.issn_l = j.issn_l AND f.institution_id = :iid
                """
            ),
            {"iid": inst_id},
        )
        conn.execute(
            sa.text("UPDATE institutions SET is_home = true WHERE id = :iid"), {"iid": inst_id}
        )

    op.drop_index("ix_harvest_runs_institution", table_name="harvest_runs")
    op.drop_index("uq_harvest_state_scoped", table_name="harvest_state")
    op.drop_index("uq_harvest_state_global", table_name="harvest_state")
    op.drop_constraint("harvest_state_pkey", "harvest_state", type_="primary")
    op.execute("ALTER TABLE harvest_state DROP COLUMN id")
    op.drop_column("harvest_state", "institution_id")
    op.drop_column("harvest_runs", "institution_id")
    op.create_primary_key("harvest_state_pkey", "harvest_state", ["source", "entity_type", "filter_set"])

    op.drop_index("uq_deal_journals_scoped", table_name="deal_journals")
    op.drop_index("uq_deal_journals_shared", table_name="deal_journals")
    # Institution-scoped override rows have no single-home meaning.
    conn.execute(sa.text("DELETE FROM deal_journals WHERE institution_id IS NOT NULL"))
    op.drop_constraint("deal_journals_pkey", "deal_journals", type_="primary")
    op.execute("ALTER TABLE deal_journals DROP COLUMN id")
    op.create_primary_key("deal_journals_pkey", "deal_journals", ["deal_id", "issn"])
    op.drop_column("deal_journals", "institution_id")
    op.drop_column("deal_institutions", "journal_override")
    op.drop_column("deal_institutions", "participation_note")
    op.drop_column("deal_institutions", "participation")

    op.drop_index("ix_work_identity_inst_work", table_name="work_identity")
    op.drop_constraint("uq_work_identity_source", "work_identity", type_="unique")
    op.drop_constraint("work_identity_work_fkey", "work_identity", type_="foreignkey")
    op.alter_column("work_identity", "work_id", new_column_name="ut_work_id")
    # FK is recreated after the works→ut_works rename below (it must
    # reference the final table name).
    op.create_unique_constraint("uq_work_identity_source", "work_identity", ["source", "source_pk"])
    op.drop_column("work_identity", "institution_id")

    # works → ut_works: keep the default institution's rows only, so the
    # restored single-column DOI unique cannot collide across institutions.
    if inst_id is not None:
        conn.execute(
            sa.text(
                "DELETE FROM works WHERE institution_id IS NOT NULL AND institution_id <> :iid"
            ),
            {"iid": inst_id},
        )
    op.drop_index("ix_works_inst_journal", table_name="works")
    # Constraint/index operations happen under the current name `works`;
    # the rename carries them over.
    op.create_index(
        "ix_ut_works_journal_issn_l",
        "works",
        ["journal_issn_l"],
        postgresql_where=sa.text("journal_issn_l IS NOT NULL"),
    )
    op.drop_index("uq_works_inst_doi", table_name="works")
    op.create_unique_constraint("ut_works_doi_normalized_key", "works", ["doi_normalized"])
    op.drop_constraint("works_pkey", "works", type_="primary")
    op.create_primary_key("ut_works_pkey", "works", ["pure_uuid"])
    op.drop_column("works", "institution_id")
    op.rename_table("works", "ut_works")
    op.create_foreign_key(
        "work_identity_ut_work_id_fkey",
        "work_identity",
        "ut_works",
        ["ut_work_id"],
        ["pure_uuid"],
        ondelete="CASCADE",
    )

    op.drop_table("journal_flags")

    op.drop_constraint("uq_institutions_code", "institutions", type_="unique")
    op.drop_column("institutions", "is_default")
    op.drop_column("institutions", "active")
    op.drop_column("institutions", "research_portal_url")
    op.drop_column("institutions", "admin_contact")
    op.drop_column("institutions", "support_email")
    op.drop_column("institutions", "oa_guide_url")
    op.drop_column("institutions", "library_url")
    op.drop_column("institutions", "data_window_end")
    op.drop_column("institutions", "data_window_start")
    op.drop_column("institutions", "external_works_dsn")
    op.drop_column("institutions", "openaire_org_id")
    op.drop_column("institutions", "pure_oai_base_url")
    op.drop_column("institutions", "short_name")
    op.drop_column("institutions", "code")
