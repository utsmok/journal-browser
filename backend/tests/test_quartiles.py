"""The journal quartile comes from Scimago's newest real quartile; the "-"
Scimago prints for a listed title without one is never a quartile."""

from sqlalchemy import select

from conftest import journal_factory, requires_db
from journal_browser.harvest.denorm import refresh_quartiles
from journal_browser.models import Journal, ScimagojrMetric


@requires_db
async def test_dash_is_not_a_quartile(db):
    db.add_all(
        [
            journal_factory("1111-1111", title="Keeps Q2"),
            journal_factory("2222-2222", title="Only a dash"),
            ScimagojrMetric(issn_l="1111-1111", year=2023, best_quartile="Q2"),
            ScimagojrMetric(issn_l="1111-1111", year=2024, best_quartile="-"),
            ScimagojrMetric(issn_l="2222-2222", year=2024, best_quartile="-"),
        ]
    )
    await db.flush()
    await refresh_quartiles(db)
    rows = dict((await db.execute(select(Journal.issn_l, Journal.latest_quartile))).all())
    assert rows == {"1111-1111": "Q2", "2222-2222": None}
