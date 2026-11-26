"""How fresh each data source is, and how fresh it should be.

Two waves run the harvest jobs (scripts/crontab): refresh_wave.sh every
night and source_wave.sh every Sunday night. A job in neither wave runs by
hand. SOURCES mirrors those two stage lists: per source it names the
schedule it is on and the harvest_runs rows that carry it. When a stage
moves between the waves, move its SOURCES entry with it.

A source is ok when one of its runs succeeded within the expected interval
plus slack, and overdue when none did. It is failed when its newest run
failed. A run still marked running ORPHAN_AFTER after it started counts as
failed: a killed process cannot close its row, and the reaper
(ingest.reap_orphaned_runs) runs only when a wave starts. Nothing in this
module writes to the database.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute

from ..config import get_settings
from ..models import HarvestRun, Institution, PartnerInstitution
from ..schemas import SourceFreshness
from ..vocab import FreshnessSchedule, FreshnessStatus, HarvestStatus

# A 'running' row older than this belongs to a process that died without
# closing it. No stage runs that long: the longest on record took about
# seven hours (the OpenAlex sources refresh of 2026-11-17).
ORPHAN_AFTER = timedelta(hours=24)


@dataclass(frozen=True)
class Expected:
    """What a schedule promises: a successful run at least every `every`,
    plus `slack` before a missing run counts as overdue. The slack covers a
    wave that starts on time but takes hours to reach a stage."""

    every: timedelta | None
    slack: timedelta


EXPECTED: Mapping[FreshnessSchedule, Expected] = {
    # refresh_wave.sh starts at 01:30 UTC, so a missed night shows in the
    # afternoon that follows it.
    FreshnessSchedule.NIGHTLY: Expected(timedelta(days=1), timedelta(hours=12)),
    # source_wave.sh starts on Sunday at 22:00 UTC and repeats the
    # per-institution stages for every institution.
    FreshnessSchedule.WEEKLY: Expected(timedelta(days=7), timedelta(days=1)),
    # Nothing is expected of a job that runs by hand.
    FreshnessSchedule.MANUAL: Expected(None, timedelta(0)),
}


@dataclass(frozen=True)
class Source:
    """One row of the freshness table."""

    # Stable id; the frontend holds the name and the description per key.
    key: str
    schedule: FreshnessSchedule
    # harvest_runs.source and the entity types that carry this source.
    harvest: str | None = None
    entities: tuple[str, ...] = ()
    # True: harvested per institution. False: one set of runs serves every
    # institution.
    scoped: bool = False
    # The nightly wave runs some stages for the home institution only.
    # `elsewhere` is the schedule the source is on for every other
    # institution.
    elsewhere: FreshnessSchedule | None = None
    # A job that records no run (it fetches only what is due): the column
    # whose newest timestamp stands in for a success.
    stamp: InstrumentedAttribute | None = None
    # Replaces EXPECTED[schedule] where the schedule overstates the promise.
    expected: Expected | None = None
    # False leaves the source out of the public table; only the admin
    # card lists it (an intermediate step nothing serves).
    public: bool = True
    # True for the sources behind the institution's own publication
    # figures. The oldest of them dates the footer.
    core: bool = False


SOURCES: tuple[Source, ...] = (
    # ── Harvested per institution ──────────────────────────────────────
    # source_wave.sh: pure, pure-cerif and pure-entities. The
    # "work_cerif_full" rows come from import_pure_export.py, a one-off
    # import, and are left out.
    Source(
        "pure",
        FreshnessSchedule.WEEKLY,
        harvest="pure",
        entities=("work", "work_cerif", "orgs", "persons"),
        scoped=True,
        core=True,
    ),
    # refresh_wave.sh runs harvest_stats for the home institution only;
    # source_wave.sh runs it weekly for every institution. The author-sweep
    # runs share the same key, so they are counted too.
    Source(
        "openalex-stats",
        FreshnessSchedule.NIGHTLY,
        harvest="openalex",
        entities=("works_stats",),
        scoped=True,
        elsewhere=FreshnessSchedule.WEEKLY,
        core=True,
    ),
    # source_wave.sh: enrich (OpenAlex by DOI, then Crossref).
    Source(
        "openalex-works",
        FreshnessSchedule.WEEKLY,
        harvest="openalex",
        entities=("work",),
        scoped=True,
    ),
    Source(
        "crossref",
        FreshnessSchedule.WEEKLY,
        harvest="crossref",
        entities=("work",),
        scoped=True,
    ),
    # source_wave.sh: openaire and openaire-facts.
    Source(
        "openaire",
        FreshnessSchedule.WEEKLY,
        harvest="openaire",
        entities=("work", "facts"),
        scoped=True,
    ),
    # refresh_wave.sh: resolve_author_ids, for every hosted institution.
    Source(
        "openalex-authors",
        FreshnessSchedule.NIGHTLY,
        harvest="openalex",
        entities=("authors",),
        scoped=True,
    ),
    # refresh_wave.sh: ingest_authors, home institution only.
    Source(
        "authors",
        FreshnessSchedule.NIGHTLY,
        harvest="local",
        entities=("authors",),
        scoped=True,
        elsewhere=FreshnessSchedule.MANUAL,
    ),
    Source(
        "journal-embeddings",
        FreshnessSchedule.NIGHTLY,
        harvest="local",
        entities=("journal_embeddings",),
        public=False,
    ),
    # ── Shared by all institutions ─────────────────────────────────────
    # harvest_journals.py is in neither wave.
    Source(
        "openalex-journals",
        FreshnessSchedule.MANUAL,
        harvest="openalex",
        entities=("sources",),
    ),
    # refresh_wave.sh: harvest_oa_colors, then harvest_work_funders.
    Source(
        "openalex-oa",
        FreshnessSchedule.NIGHTLY,
        harvest="openalex",
        entities=("works",),
    ),
    Source(
        "openalex-funders",
        FreshnessSchedule.NIGHTLY,
        harvest="openalex",
        entities=("work",),
    ),
    # source_wave.sh: deals-openaccess-nl, deals-jct, deals-oaforward, openapc and doaj.
    Source(
        "openaccess-nl",
        FreshnessSchedule.WEEKLY,
        harvest="openaccess.nl",
        entities=("deal",),
    ),
    Source("jct", FreshnessSchedule.WEEKLY, harvest="jct", entities=("deal",)),
    Source("oaforward", FreshnessSchedule.WEEKLY, harvest="oaforward", entities=("deal",)),
    Source("openapc", FreshnessSchedule.WEEKLY, harvest="openapc", entities=("apc_row",)),
    Source("doaj", FreshnessSchedule.WEEKLY, harvest="doaj", entities=("journal",)),
    # source_wave.sh: jisc lands the records. normalize_jisc.py, which
    # writes the tables the browser serves, is in neither wave.
    Source(
        "jisc-opf",
        FreshnessSchedule.WEEKLY,
        harvest="jisc_opf",
        entities=(
            "publication",
            "publisher",
            "publisher_policy",
            "funder",
            "funder_group",
            "repository",
        ),
        public=False,
    ),
    Source(
        "jisc-policies",
        FreshnessSchedule.MANUAL,
        harvest="jisc_opf",
        entities=("normalized",),
    ),
    Source("scimago", FreshnessSchedule.MANUAL, harvest="scimagojr", entities=("export",)),
    # refresh_wave.sh: harvest_ror. Records its run every night (even when 0
    # partners are due for 30-day refresh); falls back to PartnerInstitution
    # updated_at if no run row exists yet.
    Source(
        "ror",
        FreshnessSchedule.NIGHTLY,
        harvest="ror",
        entities=("partner",),
        stamp=PartnerInstitution.updated_at,
        expected=EXPECTED[FreshnessSchedule.WEEKLY],
    ),
)

CORE_SOURCES = frozenset(source.key for source in SOURCES if source.core)

RunKey = tuple[str, str, int | None]


@dataclass(frozen=True)
class NewestRun:
    """The newest run of one (source, entity type, institution), and the
    newest success under the same key."""

    status: str
    started_at: datetime
    last_success_at: datetime | None


async def newest_runs(session: AsyncSession) -> dict[RunKey, NewestRun]:
    """The newest run per key. Superseded rows are skipped: a newer run of
    the same key replaced each of them, so the newest row that is left says
    how the source stands."""
    key = (HarvestRun.source, HarvestRun.entity_type, HarvestRun.institution_id)
    newest = await session.execute(
        select(*key, HarvestRun.status, HarvestRun.started_at)
        .ext(distinct_on(*key))
        .where(HarvestRun.status != HarvestStatus.SUPERSEDED)
        .order_by(*key, HarvestRun.id.desc())
    )
    success = await session.execute(
        select(*key, HarvestRun.finished_at)
        .ext(distinct_on(*key))
        .where(HarvestRun.status == HarvestStatus.COMPLETED)
        .order_by(*key, HarvestRun.id.desc())
    )
    last_success = {(source, entity, inst): at for source, entity, inst, at in success}
    return {
        (source, entity, inst): NewestRun(
            status, started_at, last_success.get((source, entity, inst))
        )
        for source, entity, inst, status, started_at in newest
    }


def _earliest(stamps: list[datetime | None]) -> datetime | None:
    """The oldest timestamp; None when the list is empty or one is missing."""
    if not stamps or any(stamp is None for stamp in stamps):
        return None
    return min(stamp for stamp in stamps if stamp is not None)


def _age_status(
    last_success: datetime | None, expected: Expected, now: datetime
) -> FreshnessStatus:
    if expected.every is None:
        return FreshnessStatus.OK
    if last_success is None:
        return FreshnessStatus.OVERDUE
    overdue = now - last_success > expected.every + expected.slack
    return FreshnessStatus.OVERDUE if overdue else FreshnessStatus.OK


def _run_status(run: NewestRun, expected: Expected, now: datetime) -> FreshnessStatus:
    orphaned = run.status == HarvestStatus.RUNNING and now - run.started_at > ORPHAN_AFTER
    if run.status == HarvestStatus.FAILED or orphaned:
        return FreshnessStatus.FAILED
    # A run in progress is judged by the success before it.
    return _age_status(run.last_success_at, expected, now)


def rows_for(
    institutions: Sequence[Institution],
    runs: Mapping[RunKey, NewestRun],
    stamps: Mapping[str, datetime | None],
    *,
    now: datetime,
    home_ror: str,
    public_only: bool = False,
) -> list[SourceFreshness]:
    """The rows for each institution (its own sources, in SOURCES order),
    then one set of rows for the sources shared by all institutions.
    public_only leaves out the steps that are not for the public table."""
    sources = tuple(source for source in SOURCES if source.public) if public_only else SOURCES
    rows: list[SourceFreshness] = []
    for institution in institutions:
        scoped: Iterator[Source] = (source for source in sources if source.scoped)
        rows += _rows(
            scoped,
            runs,
            stamps,
            now=now,
            code=institution.code,
            institution_id=institution.id,
            is_home=institution.ror == home_ror,
        )
    shared: Iterator[Source] = (source for source in sources if not source.scoped)
    rows += _rows(shared, runs, stamps, now=now, code=None, institution_id=None, is_home=False)
    return rows


def _rows(
    sources: Iterable[Source],
    runs: Mapping[RunKey, NewestRun],
    stamps: Mapping[str, datetime | None],
    *,
    now: datetime,
    code: str | None,
    institution_id: int | None,
    is_home: bool,
) -> list[SourceFreshness]:
    rows = []
    for source in sources:
        schedule = source.schedule if is_home or source.elsewhere is None else source.elsewhere
        expected = source.expected or EXPECTED[schedule]
        row = _row(source, schedule, expected, runs, stamps, code, institution_id, now)
        if row is not None:
            rows.append(row)
    return rows


def _row(
    source: Source,
    schedule: FreshnessSchedule,
    expected: Expected,
    runs: Mapping[RunKey, NewestRun],
    stamps: Mapping[str, datetime | None],
    code: str | None,
    institution_id: int | None,
    now: datetime,
) -> SourceFreshness | None:
    """The row for one source in one scope (an institution, or None for the
    shared rows). None when nothing ever ran for it there."""

    def newest(entity: str) -> NewestRun | None:
        if source.harvest is None:
            return None
        scope = institution_id if source.scoped else None
        return runs.get((source.harvest, entity, scope))

    parts = [(entity, run) for entity in source.entities if (run := newest(entity)) is not None]
    failed: list[str] = []
    last_run_at: datetime | None = None
    last_run_status: str | None = None
    if parts:
        statuses = [(entity, _run_status(run, expected, now)) for entity, run in parts]
        failed = [entity for entity, status in statuses if status is FreshnessStatus.FAILED]
        # A source is as old as its oldest part, and only counts as loaded
        # once every part has succeeded.
        last_success = _earliest([run.last_success_at for _, run in parts])
        last_run_at = max(run.started_at for _, run in parts)
        if failed:
            last_run_status = HarvestStatus.FAILED
        elif any(run.status == HarvestStatus.RUNNING for _, run in parts):
            last_run_status = HarvestStatus.RUNNING
        else:
            last_run_status = HarvestStatus.COMPLETED
        overdue = any(status is FreshnessStatus.OVERDUE for _, status in statuses)
    else:
        last_success = stamps.get(source.key)
        if last_success is None:
            return None
        overdue = _age_status(last_success, expected, now) is FreshnessStatus.OVERDUE
    status = FreshnessStatus.OK
    if overdue:
        status = FreshnessStatus.OVERDUE
    if failed:
        status = FreshnessStatus.FAILED
    return SourceFreshness(
        source=source.key,
        institution_code=code,
        schedule=schedule,
        expected_interval_hours=(
            None if expected.every is None else expected.every // timedelta(hours=1)
        ),
        status=status,
        last_success_at=last_success,
        last_run_at=last_run_at,
        last_run_status=last_run_status,
        failed_parts=failed,
    )


async def source_freshness(
    session: AsyncSession,
    institutions: Sequence[Institution],
    *,
    now: datetime | None = None,
    public_only: bool = False,
) -> list[SourceFreshness]:
    """The freshness rows for these institutions and for the shared
    sources."""
    stamps = {
        source.key: await session.scalar(select(func.max(source.stamp)))
        for source in SOURCES
        if source.stamp is not None
    }
    return rows_for(
        institutions,
        await newest_runs(session),
        stamps,
        now=now or datetime.now(UTC),
        home_ror=get_settings().institution_ror,
        public_only=public_only,
    )


def data_updated_at(rows: Iterable[SourceFreshness]) -> datetime | None:
    """The oldest last success among the core sources, which is the date the
    footer shows. None when a core source has never succeeded, so the footer
    never dates data that is not there."""
    return _earliest([row.last_success_at for row in rows if row.source in CORE_SOURCES])
