"""IngestSession — bookkeeping for one harvest run (ut-metadata idiom).

Append-only source_records versions (same payload re-harvested inserts
nothing), harvest_runs/harvest_state bookkeeping, per-page commits, and
per-record error isolation. `store_raw_file` keeps file-level artifacts
(CSVs, HTML) in the landing dir; `apply_overrides` re-applies curated
values after normalization so re-ingestion never overwrites them.
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, insert, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import CacheEpoch, HarvestRun, HarvestState, ManualOverride, RawFile, SourceRecord

logger = logging.getLogger(__name__)

BATCH_SIZE = 100


def content_hash(payload: Any) -> str:
    """Stable SHA-256 of a JSON-serializable payload."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def bump_cache_epoch(session: AsyncSession) -> None:
    """Advance the single-row cache epoch; callers commit.

    Upsert rather than UPDATE so the primitive also converges on a
    database whose seed row is missing (tests build schema with
    create_all, not alembic).
    """
    await session.execute(
        pg_insert(CacheEpoch)
        .values(id=1, bumped_at=func.now())
        .on_conflict_do_update(index_elements=["id"], set_={"bumped_at": func.now()})
    )


def _strip_nuls(value: Any) -> Any:
    """Recursively remove NUL bytes — Postgres JSONB rejects \\u0000."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: _strip_nuls(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_nuls(v) for v in value]
    return value


def _publication_year(payload: dict[str, Any]) -> int | None:
    """Projection column value: payload publication_year when it is an int
    (or an int-shaped string). NULL rows drop out of serving windows just
    like the old payload-text path."""
    year = payload.get("publication_year")
    if isinstance(year, bool):
        return None
    if isinstance(year, int):
        return year
    if isinstance(year, str) and year.isdigit():
        return int(year)
    return None


class IngestSession:
    """One harvest run against one (source, entity_type, filter_set)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.run_id: int | None = None
        self.source: str | None = None
        self.entity_type: str | None = None
        self.filter_set: str | None = None
        self.institution_id: int | None = None
        self.records_seen: int = 0
        self.parse_failures: int = 0
        self._pending: list[dict[str, Any]] = []
        self._seen_keys: set[tuple[str, str, str, str]] = set()

    async def start_run(
        self,
        source: str,
        entity_type: str,
        filter_set: str,
        config: dict[str, Any],
        institution_id: int | None = None,
    ) -> int:
        self.source = source
        self.entity_type = entity_type
        self.filter_set = filter_set
        self.institution_id = institution_id
        # Close stale 'running' rows for this key first. Only the
        # in-process exception path can mark a run 'failed', so a crashed
        # or killed process leaves its row running forever; a new start of
        # the same job is the one moment that state is provably dead.
        # Superseding also makes an accidental overlap visible: the older
        # row reads 'failed' with the marker instead of pretending both
        # completed.
        #
        # The runs table carries no filter_set, so the key here is
        # (source, entity_type, institution). Every current job finishes
        # one run before starting the next (harvest_state is
        # last-writer-wins across filter_sets anyway), so this cannot
        # close a sibling filter_set's row except in a same-instant
        # overlap that already corrupts the state table.
        stale = await self.session.execute(
            update(HarvestRun)
            .where(
                HarvestRun.source == source,
                HarvestRun.entity_type == entity_type,
                (
                    HarvestRun.institution_id.is_(None)
                    if institution_id is None
                    else HarvestRun.institution_id == institution_id
                ),
                HarvestRun.status == "running",
            )
            .values(
                status="failed",
                finished_at=datetime.now(UTC),
                stats={"error": "stale: superseded by a newer run of the same job"},
            )
            .returning(HarvestRun.id)
        )
        superseded = list(stale.scalars().all())
        if superseded:
            logger.warning(
                "Superseded stale running harvest run(s) %s for %s/%s",
                superseded,
                source,
                entity_type,
            )
        run = HarvestRun(
            source=source,
            entity_type=entity_type,
            institution_id=institution_id,
            status="running",
            config_fingerprint=content_hash(config),
            stats={},
        )
        self.session.add(run)
        await self.session.flush()
        assert run.id is not None
        self.run_id = run.id
        logger.info("Started harvest run %s for %s/%s", run.id, source, entity_type)
        return self.run_id

    async def ingest_record(self, source_pk: str, payload: dict[str, Any]) -> tuple[str, str]:
        """Store a record version if new. Returns (kind, content_hash)."""
        assert self.run_id is not None and self.source and self.entity_type, (
            "call start_run() first"
        )
        self.records_seen += 1
        payload = _strip_nuls(payload)
        h = content_hash(payload)
        key = (self.source, self.entity_type, source_pk, h)
        if key in self._seen_keys:
            return "duplicate", h
        exists = await self.session.scalar(
            select(SourceRecord.id).where(
                SourceRecord.source == self.source,
                SourceRecord.entity_type == self.entity_type,
                SourceRecord.source_pk == source_pk,
                SourceRecord.content_hash == h,
            )
        )
        if exists is not None:
            self._seen_keys.add(key)
            return "duplicate", h
        self._seen_keys.add(key)
        self._pending.append(
            {
                "source": self.source,
                "entity_type": self.entity_type,
                "source_pk": source_pk,
                "payload": payload,
                "publication_year": _publication_year(payload),
                "content_hash": h,
                "harvest_run_id": self.run_id,
            }
        )
        if len(self._pending) >= BATCH_SIZE:
            await self._flush()
        return "new", h

    async def ingest_records(self, records: list[tuple[str, dict[str, Any]]]) -> int:
        """Page-bulk ingest_record: one dedupe SELECT + one buffered INSERT
        set for the whole page. Same bookkeeping (records_seen, duplicate
        memo, pending store) as the per-record path."""
        assert self.run_id is not None and self.source and self.entity_type, (
            "call start_run() first"
        )
        self.records_seen += len(records)
        dedup: dict[tuple[str, str], dict[str, Any]] = {}
        for source_pk, payload in records:
            stripped = _strip_nuls(payload)
            key = (source_pk, content_hash(stripped))
            if key in self._seen_keys:
                continue
            dedup[key] = {
                "source": self.source,
                "entity_type": self.entity_type,
                "source_pk": source_pk,
                "payload": stripped,
                "publication_year": _publication_year(stripped),
                "content_hash": key[1],
                "harvest_run_id": self.run_id,
            }
        if not dedup:
            return 0
        existing = await self.session.execute(
            select(SourceRecord.source_pk, SourceRecord.content_hash).where(
                SourceRecord.source == self.source,
                SourceRecord.entity_type == self.entity_type,
                tuple_(SourceRecord.source_pk, SourceRecord.content_hash).in_(list(dedup)),
            )
        )
        for key in existing.all():
            dedup.pop(tuple(key), None)
        self._seen_keys.update(dedup)
        self._pending.extend(dedup.values())
        if len(self._pending) >= BATCH_SIZE:
            await self._flush()
        return len(dedup)

    async def record_parse_failure(self, detail: dict[str, Any]) -> None:
        """Count + log one record that could not be parsed/isolated."""
        assert self.run_id is not None, "call start_run() first"
        self.parse_failures += 1
        self.records_seen += 1
        logger.warning(
            "parse failure %s/%s: %s",
            self.source,
            detail.get("source_pk"),
            detail.get("reason"),
        )

    async def finish_run(self, status: str, stats: dict[str, Any] | None = None) -> dict:
        assert self.run_id is not None, "call start_run() first"
        await self._flush()
        final = dict(stats or {})
        final.setdefault("records_seen", self.records_seen)
        final.setdefault("parse_failures", self.parse_failures)
        final["records_stored"] = await self.session.scalar(
            select(func.count())
            .select_from(SourceRecord)
            .where(SourceRecord.harvest_run_id == self.run_id)
        )
        # Close only a run still marked running: a newer start_run of the
        # same job key may have superseded this one to failed while this
        # process was still working (production rows 47/50, 2026-10-26).
        # A zombie finish must not flip that row back to completed nor
        # rewrite harvest_state under a dead run id.
        closed = await self.session.scalar(
            update(HarvestRun)
            .where(HarvestRun.id == self.run_id, HarvestRun.status == "running")
            .values(status=status, finished_at=datetime.now(UTC), stats=final)
            .returning(HarvestRun.id)
        )
        if closed is None:
            logger.warning(
                "Run %s finished as %r after a newer run superseded it; "
                "discarding close (row stays failed, harvest_state untouched)",
                self.run_id,
                status,
            )
            return final
        # Every close invalidates epoch-keyed caches: per-page commits can
        # have changed serving state before the close, on either status.
        await bump_cache_epoch(self.session)
        await self.session.execute(
            pg_insert(HarvestState)
            .values(
                source=self.source,
                entity_type=self.entity_type,
                filter_set=self.filter_set,
                institution_id=self.institution_id,
                status=status,
                stats=final,
                last_run_id=self.run_id,
                updated_at=func.now(),
            )
            .on_conflict_do_update(
                # The two partial unique indexes have different column sets:
                # the global one has no institution_id column to name.
                **(
                    {
                        "index_elements": [
                            "source",
                            "entity_type",
                            "filter_set",
                            "institution_id",
                        ],
                        "index_where": text("institution_id IS NOT NULL"),
                    }
                    if self.institution_id is not None
                    else {
                        "index_elements": ["source", "entity_type", "filter_set"],
                        "index_where": text("institution_id IS NULL"),
                    }
                ),
                set_={
                    "status": status,
                    "stats": final,
                    "last_run_id": self.run_id,
                    "updated_at": func.now(),
                },
            )
        )
        logger.info("Finished harvest run %s as %s: %s", self.run_id, status, final)
        return final

    async def commit(self) -> None:
        """Flush pending writes and commit. Call after every page/batch so an
        interrupted run loses at most one page."""
        await self._flush()
        await self.session.commit()

    async def _flush(self) -> None:
        if self._pending:
            await self.session.execute(insert(SourceRecord), self._pending)
            self._pending.clear()


async def store_raw_file(
    session: AsyncSession,
    source: str,
    entity_type: str,
    url: str,
    data: bytes,
    suffix: str,
    source_pk: str = "",
    harvest_run_id: int | None = None,
) -> tuple[Path, str, bool]:
    """Write bytes to the landing dir unless this exact version exists.

    Returns (path, sha256, is_new_version). Files are content-addressed:
    landing/<source>/<entity_type>/<sha256><suffix>.
    """
    h = sha256_bytes(data)
    landing = Path(get_settings().landing_dir) / source / entity_type
    landing.mkdir(parents=True, exist_ok=True)
    path = landing / f"{h}{suffix}"
    is_new = not path.exists()
    if is_new:
        path.write_bytes(data)
    await session.execute(
        pg_insert(RawFile)
        .values(
            source=source,
            entity_type=entity_type,
            source_pk=source_pk,
            url=url,
            content_hash=h,
            path=str(path),
            size_bytes=len(data),
            harvest_run_id=harvest_run_id,
        )
        .on_conflict_do_nothing(
            index_elements=["source", "entity_type", "source_pk", "content_hash"]
        )
    )
    return path, h, is_new


async def apply_overrides(
    session: AsyncSession, table_name: str, row_key: str, obj: Any, fields: list[str]
) -> int:
    """Apply ManualOverride values onto a normalized ORM object.

    Called by every normalizer AFTER its upsert; overrides win over any
    re-ingested value. Returns the number of fields applied.
    """
    rows = (
        (
            await session.execute(
                select(ManualOverride).where(
                    ManualOverride.table_name == table_name,
                    ManualOverride.row_key == row_key,
                    ManualOverride.field.in_(fields),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        setattr(obj, row.field, row.value)
    return len(rows)
