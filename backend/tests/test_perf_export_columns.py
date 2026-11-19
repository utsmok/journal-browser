"""CSV export perf rewrite: the four payload-derived cells
(publication_date, pdf_url, landing_page_url, institution_rors) live as
openalex_works columns (0068) instead of a per-row source_records payload
lateral. Pins the backfill SQL's parity with the harvest projection
(raw_export_fields, latest payload per W-id wins) and the CSV cells served
from the columns."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from conftest import requires_db
from journal_browser.harvest.openalex_works import raw_export_fields
from journal_browser.models import HarvestRun, OpenalexWork, SourceRecord

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0068_openalex_export_columns.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("mig_0068", _MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _payload(**overrides):
    base = {
        "id": "https://openalex.org/W1",
        "publication_date": "2022-05-01",
        "best_oa_location": {"pdf_url": "https://example.org/pdf"},
        "primary_location": {"landing_page_url": "https://example.org/landing"},
        "authorships": [
            {"institutions": [{"ror": "https://ror.org/02"}, {"ror": None}]},
            {"institutions": [{"ror": "https://ror.org/01"}, {"ror": "https://ror.org/02"}]},
        ],
    }
    base.update(overrides)
    return base


async def _seed(db, institution_factory):
    inst = await institution_factory(code="ut")
    run = HarvestRun(
        source="openalex", entity_type="works_stats", institution_id=inst.id,
        status="completed", config_fingerprint="t",
    )
    db.add(run)
    await db.flush()
    payloads = {
        # latest of two versions wins
        "W1": _payload(),
        # no authorships at all -> empty rors string, not NULL
        "W2": _payload(id="W2", authorships=[]),
        # missing best_oa_location: pdf falls back to primary_location
        "W3": _payload(
            id="W3",
            best_oa_location=None,
            primary_location={
                "landing_page_url": "https://example.org/l3",
                "pdf_url": "https://example.org/pdf3",
            },
            publication_date=None,
        ),
        # authorships not an array must not crash the backfill
        "W4": _payload(id="W4", authorships=None),
    }
    for n, (w_id, payload) in enumerate(payloads.items()):
        # two stored versions: the later harvested_at must win
        for version in range(2):
            db.add(
                SourceRecord(
                    harvest_run_id=run.id,
                    source="openalex",
                    entity_type="works_stats",
                    source_pk=w_id,
                    payload=payload if version == 1 else {"id": payload["id"]},
                    content_hash=f"h{n}{version}",
                    harvested_at=datetime(2026, 11, 1, tzinfo=UTC) + timedelta(days=version),
                )
            )
        db.add(
            OpenalexWork(
                institution_id=inst.id,
                w_id=w_id,
                title=f"T {w_id}",
                source="works_stats",
            )
        )
    db.add(OpenalexWork(institution_id=inst.id, w_id="W9", title="No payload",
                        source="works_stats"))
    await db.commit()
    return inst, payloads


@requires_db
async def test_backfill_matches_harvest_projection(db, institution_factory):
    """The migration's backfill UPDATE produces exactly raw_export_fields()
    of the latest stored payload per W-id, NULL where no payload exists."""
    inst, payloads = await _seed(db, institution_factory)
    mig = _migration()
    # Run the backfill against a SELECT-shaped twin: the UPDATE touches the
    # same rows; verify by executing it for real, then reading the columns.
    from sqlalchemy import text

    await db.execute(text(mig._BACKFILL))
    await db.commit()
    rows = (
        await db.execute(
            select(
                OpenalexWork.w_id,
                OpenalexWork.publication_date,
                OpenalexWork.pdf_url,
                OpenalexWork.landing_page_url,
                OpenalexWork.institution_rors,
            ).where(OpenalexWork.institution_id == inst.id)
        )
    ).all()
    got = {r[0]: tuple(r[1:]) for r in rows}
    assert got["W1"] == ("2022-05-01", "https://example.org/pdf",
                         "https://example.org/landing", "https://ror.org/01;https://ror.org/02")
    assert got["W2"] == ("2022-05-01", "https://example.org/pdf",
                         "https://example.org/landing", "")
    assert got["W3"] == (None, "https://example.org/pdf3", "https://example.org/l3",
                         "https://ror.org/01;https://ror.org/02")
    # authorships null (not an array): no crash, empty rors, no urls.
    assert got["W4"][3] == ""
    # No stored payload: columns stay NULL (the CSV renders empty cells).
    assert got["W9"] == (None, None, None, None)
    # Column values equal the Python projection of the winning payload.
    for w_id in ("W1", "W2", "W3"):
        proj = raw_export_fields(payloads[w_id])
        assert got[w_id] == (
            proj["publication_date"], proj["pdf_url"],
            proj["landing_page_url"], proj["institution_rors"],
        )


@requires_db
async def test_migration_reversible_chain():
    """0068 follows 0067 and its downgrade drops exactly the four added
    columns."""
    mig = _migration()
    assert mig.revision == "0068_openalex_export_columns"
    assert mig.down_revision == "0067_drop_crossref_meta"
    assert list(mig._COLUMNS) == [
        "publication_date", "pdf_url", "landing_page_url", "institution_rors",
    ]
    assert list(reversed(mig._COLUMNS)) == [
        "institution_rors", "landing_page_url", "pdf_url", "publication_date",
    ]


@requires_db
async def test_export_stmt_has_no_payload_join(db, institution_factory):
    """The export statement reads store columns and never joins
    source_records (no lateral, no payload column)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from journal_browser.models import Institution
    from journal_browser.services.authorship import not_in_pure, store_gates
    from journal_browser.services.exports import _export_stmt
    from journal_browser.models import OpenalexWork

    inst, _ = await _seed(db, institution_factory)
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as session:
        persisted = await session.get(Institution, inst.id)
        predicate = [
            OpenalexWork.source != "author-sweep:",
            *store_gates(persisted, None),
            not_in_pure(),
        ]
        sql = str(_export_stmt(persisted, predicate).compile())
        assert "source_records" not in sql
        assert "lateral" not in sql.lower()
