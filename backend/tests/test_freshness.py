"""Per-source data freshness: the status rules in services/freshness.py and
the two endpoints that serve them (/{inst}/meta/freshness, /admin/ops/status)."""

from datetime import UTC, datetime, timedelta

import pytest

from conftest import requires_db
from journal_browser.config import get_settings, reset_settings_cache
from journal_browser.models import HarvestRun, Institution
from journal_browser.schemas import SourceFreshness
from journal_browser.services.freshness import (
    ORPHAN_AFTER,
    SOURCES,
    NewestRun,
    data_updated_at,
    newest_runs,
    rows_for,
)
from journal_browser.vocab import FreshnessSchedule, FreshnessStatus, HarvestStatus

NOW = datetime(2026, 11, 25, 6, tzinfo=UTC)
HOME_ROR = "https://ror.org/home"
DAY = timedelta(days=1)
PASSWORD = "freshness-admin-pw"

OK = FreshnessStatus.OK
OVERDUE = FreshnessStatus.OVERDUE
FAILED = FreshnessStatus.FAILED
COMPLETED = HarvestStatus.COMPLETED


def _done(at: datetime) -> NewestRun:
    """A run that started and succeeded at `at`."""
    return NewestRun(COMPLETED, at, at)


def _other(
    status: HarvestStatus, *, started: datetime, success: datetime | None = None
) -> NewestRun:
    """A run that did not succeed (failed, running); `success` is the last
    success before it."""
    return NewestRun(status, started, success)


def _runs(key: str, **parts: NewestRun) -> dict[tuple[str, str, int | None], NewestRun]:
    """The newest run per part of one source, harvested for institution 1
    (which the shared sources ignore)."""
    source = next(source for source in SOURCES if source.key == key)
    scope = 1 if source.scoped else None
    harvest = source.harvest
    assert harvest is not None  # only the ROR refresh records no run
    return {(harvest, entity, scope): run for entity, run in parts.items()}


def _rows(
    runs: dict[tuple[str, str, int | None], NewestRun],
    stamps: dict[str, datetime | None] | None = None,
    *,
    public_only: bool = False,
) -> list:
    institution = Institution(id=1, code="ut", name="University of Twente", ror=HOME_ROR)
    return rows_for(
        [institution], runs, stamps or {}, now=NOW, home_ror=HOME_ROR, public_only=public_only
    )


def _row(rows: list, key: str):
    return next(row for row in rows if row.source == key)


def _harvest_run(source: str, entity: str, status: str, institution_id=None, *, at: datetime):
    return HarvestRun(
        source=source,
        entity_type=entity,
        status=status,
        institution_id=institution_id,
        config_fingerprint="t",
        started_at=at,
        finished_at=at if status == COMPLETED else None,
    )


# ── Status rules ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("key", "entity", "still_fresh", "too_old"),
    [
        # Nightly: one day plus half a day of slack for a slow wave.
        (
            "openalex-oa",
            "works",
            timedelta(days=1, hours=12),
            timedelta(days=1, hours=12, seconds=1),
        ),
        # Weekly: seven days plus one.
        ("crossref", "work", timedelta(days=8), timedelta(days=8, seconds=1)),
    ],
)
def test_overdue_once_the_last_success_is_older_than_interval_plus_slack(
    key, entity, still_fresh, too_old
):
    fresh = _row(_rows(_runs(key, **{entity: _done(NOW - still_fresh)})), key)
    stale = _row(_rows(_runs(key, **{entity: _done(NOW - too_old)})), key)
    assert fresh.status is OK
    assert (stale.status, stale.last_success_at) == (OVERDUE, NOW - too_old)


def test_scheduled_source_without_any_success_is_overdue():
    first_run_in_progress = _other(HarvestStatus.RUNNING, started=NOW - timedelta(hours=1))
    row = _row(_rows(_runs("crossref", work=first_run_in_progress)), "crossref")
    assert (row.status, row.last_success_at) == (OVERDUE, None)


def test_failed_part_is_named_and_wins_over_a_recent_success():
    row = _row(
        _rows(
            _runs(
                "openaire",
                work=_done(NOW - DAY),
                facts=_other(HarvestStatus.FAILED, started=NOW - timedelta(hours=2)),
            )
        ),
        "openaire",
    )
    assert (row.status, row.failed_parts) == (FAILED, ["facts"])
    # One of the two parts never succeeded, so the source has no date.
    assert row.last_success_at is None
    assert row.last_run_status is HarvestStatus.FAILED


def test_failed_source_keeps_the_date_of_its_last_success():
    last_success = NOW - 2 * DAY
    row = _row(
        _rows(
            _runs(
                "crossref",
                work=_other(
                    HarvestStatus.FAILED, started=NOW - timedelta(hours=2), success=last_success
                ),
            )
        ),
        "crossref",
    )
    assert (row.status, row.last_success_at) == (FAILED, last_success)


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (ORPHAN_AFTER - timedelta(minutes=1), OVERDUE),
        (ORPHAN_AFTER + timedelta(minutes=1), FAILED),
    ],
)
def test_running_run_older_than_the_orphan_threshold_counts_as_failed(age, expected):
    """A killed process leaves its row on 'running'. ORPHAN_AFTER after it
    started, that row is a failed refresh, not one in progress."""
    dead = _other(HarvestStatus.RUNNING, started=NOW - age)
    row = _row(_rows(_runs("pure", work=dead)), "pure")
    assert row.status is expected
    assert row.failed_parts == (["work"] if expected is FAILED else [])


def test_running_run_in_progress_is_judged_by_its_previous_success():
    def pure_at(last_success: datetime) -> SourceFreshness:
        running = _other(
            HarvestStatus.RUNNING, started=NOW - timedelta(hours=1), success=last_success
        )
        return _row(_rows(_runs("pure", work=running)), "pure")

    assert pure_at(NOW - 2 * DAY).status is OK
    stale = pure_at(NOW - 20 * DAY)
    assert (stale.status, stale.last_success_at) == (OVERDUE, NOW - 20 * DAY)
    assert stale.last_run_status is HarvestStatus.RUNNING


def test_manual_source_is_never_overdue():
    row = _row(
        _rows(_runs("openalex-journals", sources=_done(NOW - 400 * DAY))), "openalex-journals"
    )
    assert (row.schedule, row.expected_interval_hours, row.status) == (
        FreshnessSchedule.MANUAL,
        None,
        OK,
    )


def test_source_is_as_old_as_its_oldest_part():
    runs = _runs("pure", work=_done(NOW - DAY), orgs=_done(NOW - 5 * DAY))
    assert _row(_rows(runs), "pure").last_success_at == NOW - 5 * DAY


def test_only_the_home_institution_expects_a_nightly_stats_refresh():
    """harvest_stats runs nightly for the home institution and weekly for
    every other one, so the same run age is judged by two intervals."""
    institutions = [
        Institution(id=1, code="home", name="Home", ror=HOME_ROR),
        Institution(id=2, code="rug", name="RUG", ror="https://ror.org/rug"),
    ]
    runs: dict[tuple[str, str, int | None], NewestRun] = {
        ("openalex", "works_stats", 1): _done(NOW - 3 * DAY),
        ("openalex", "works_stats", 2): _done(NOW - 3 * DAY),
    }
    home, rug = rows_for(institutions, runs, {}, now=NOW, home_ror=HOME_ROR)
    assert (home.institution_code, home.schedule, home.status) == (
        "home",
        FreshnessSchedule.NIGHTLY,
        OVERDUE,
    )
    assert (rug.institution_code, rug.schedule, rug.status, rug.expected_interval_hours) == (
        "rug",
        FreshnessSchedule.WEEKLY,
        OK,
        24 * 7,
    )


def test_shared_sources_follow_the_institution_rows_without_an_institution():
    runs = _runs("crossref", work=_done(NOW - DAY)) | _runs("jct", deal=_done(NOW - DAY))
    rows = _rows(runs)
    assert [(row.source, row.institution_code) for row in rows] == [
        ("crossref", "ut"),
        ("jct", None),
    ]


def test_source_without_any_run_has_no_row():
    keys = [row.source for row in _rows(_runs("crossref", work=_done(NOW - DAY)))]
    assert keys == ["crossref"]
    assert _rows({}, {}) == []


def test_public_rows_leave_out_steps_that_are_not_for_the_public_table():
    """The raw Jisc landing step feeds a job that runs by hand; the public
    table shows the policies it serves, the admin card shows both."""
    runs = _runs("jisc-opf", publication=_done(NOW - DAY)) | _runs("jct", deal=_done(NOW - DAY))
    assert [row.source for row in _rows(runs)] == ["jct", "jisc-opf"]
    assert [row.source for row in _rows(runs, public_only=True)] == ["jct"]


def test_source_that_records_no_run_is_dated_by_its_newest_record():
    fresh = _row(_rows({}, {"ror": NOW - 6 * DAY}), "ror")
    stale = _row(_rows({}, {"ror": NOW - 9 * DAY}), "ror")
    assert (fresh.status, fresh.last_success_at) == (OK, NOW - 6 * DAY)
    assert stale.status is OVERDUE


def test_data_updated_at_is_the_oldest_core_source():
    runs = _runs("pure", work=_done(NOW - 3 * DAY)) | _runs(
        "openalex-stats", works_stats=_done(NOW - DAY)
    )
    assert data_updated_at(_rows(runs)) == NOW - 3 * DAY
    # A core source that never succeeded leaves the date unset.
    runs[("pure", "work", 1)] = _other(HarvestStatus.RUNNING, started=NOW - timedelta(hours=1))
    assert data_updated_at(_rows(runs)) is None
    # An institution whose core sources never ran has no date either.
    assert data_updated_at(_rows({})) is None


def test_source_keys_are_unique():
    """The frontend looks up each row's name and description by key."""
    keys = [source.key for source in SOURCES]
    assert len(set(keys)) == len(keys)


# ── Database: the run query and the two endpoints ──────────────────────────


@requires_db
async def test_newest_runs_skips_superseded_rows_and_keeps_institutions_apart(
    db, institution_factory
):
    ut = await institution_factory(code="ut")
    rug = await institution_factory(code="rug")
    db.add_all(
        [
            _harvest_run("openalex", "works_stats", "completed", ut.id, at=NOW - 3 * DAY),
            _harvest_run("openalex", "works_stats", "failed", ut.id, at=NOW - timedelta(hours=2)),
            _harvest_run(
                "openalex", "works_stats", "completed", rug.id, at=NOW - timedelta(hours=2)
            ),
            # A superseded row is never the newest run, even when it is the latest one.
            _harvest_run("pure", "work", "completed", ut.id, at=NOW - 5 * DAY),
            _harvest_run("pure", "work", "superseded", ut.id, at=NOW - timedelta(hours=1)),
            _harvest_run("crossref", "work", "superseded", ut.id, at=NOW - timedelta(hours=1)),
        ]
    )
    await db.commit()

    runs = await newest_runs(db)
    stats = runs[("openalex", "works_stats", ut.id)]
    assert (stats.status, stats.last_success_at) == ("failed", NOW - 3 * DAY)
    assert runs[("openalex", "works_stats", rug.id)].status == "completed"
    assert runs[("pure", "work", ut.id)].status == "completed"
    assert ("crossref", "work", ut.id) not in runs


@requires_db
async def test_freshness_endpoint_lists_own_sources_then_the_shared_ones(
    client, db, institution_factory
):
    """Each institution sees its own runs, then the shared ones. The same
    stats run three days old is overdue for the home institution (nightly
    schedule) and fine for any other (weekly)."""
    ut = await institution_factory(code="ut", ror=get_settings().institution_ror)
    rug = await institution_factory(code="rug", ror="https://ror.org/02rrdwm37")
    three_days_ago = NOW - 3 * DAY
    db.add_all(
        [
            _harvest_run("pure", "work", "completed", ut.id, at=NOW - 2 * DAY),
            _harvest_run("openalex", "works_stats", "completed", ut.id, at=three_days_ago),
            _harvest_run("openalex", "works_stats", "completed", rug.id, at=three_days_ago),
            _harvest_run("doaj", "journal", "failed", at=NOW - DAY),
        ]
    )
    await db.commit()

    rug_body = (await client.get("/api/v1/rug/meta/freshness")).json()
    stats, doaj = rug_body["sources"]
    assert (stats["source"], stats["institution_code"], stats["schedule"]) == (
        "openalex-stats",
        "rug",
        "weekly",
    )
    assert (stats["status"], stats["expected_interval_hours"]) == ("ok", 168)
    assert datetime.fromisoformat(stats["last_success_at"]) == three_days_ago
    assert (doaj["source"], doaj["institution_code"], doaj["status"]) == ("doaj", None, "failed")
    assert doaj["failed_parts"] == ["journal"]
    assert datetime.fromisoformat(rug_body["data_updated_at"]) == three_days_ago
    assert "tables" not in rug_body

    ut_body = (await client.get("/api/v1/ut/meta/freshness")).json()
    assert [(row["source"], row["status"]) for row in ut_body["sources"]] == [
        ("pure", "ok"),
        ("openalex-stats", "overdue"),
        ("doaj", "failed"),
    ]
    assert datetime.fromisoformat(ut_body["data_updated_at"]) == three_days_ago


@requires_db
async def test_ops_status_lists_the_sources_of_every_active_institution(
    client, db, institution_factory, monkeypatch, tmp_path
):
    monkeypatch.setenv("JB_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "settings.yaml"))
    reset_settings_cache()
    try:
        ut = await institution_factory(code="ut")
        rug = await institution_factory(code="rug")
        retired = await institution_factory(code=None)
        db.add_all(
            [
                _harvest_run("pure", "work", "completed", ut.id, at=NOW - DAY),
                _harvest_run("pure", "work", "failed", rug.id, at=NOW - timedelta(hours=1)),
                _harvest_run("pure", "work", "completed", retired.id, at=NOW - DAY),
                _harvest_run("doaj", "journal", "failed", at=NOW - DAY),
            ]
        )
        await db.commit()
        login = await client.post("/api/v1/admin/login", json={"password": PASSWORD})
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        body = (await client.get("/api/v1/admin/ops/status", headers=headers)).json()
    finally:
        reset_settings_cache()

    sources = body["sources"]
    assert [(row["source"], row["institution_code"], row["status"]) for row in sources] == [
        ("pure", "ut", "ok"),
        ("pure", "rug", "failed"),
        ("doaj", None, "failed"),
    ]
    assert "journals" in body["tables"]
