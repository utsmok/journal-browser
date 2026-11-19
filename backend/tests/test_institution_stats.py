"""Institution stats budget gate: the works filter listing is
credit-priced, so a zero budget must skip the harvest cleanly instead of
429-crashing the wave."""

import json

from journal_browser.harvest.institution_stats import harvest_institution_stats


async def test_stats_skipped_at_zero_budget(db, institution_factory, monkeypatch):
    inst = await institution_factory()

    async def _zero():
        return 0.0

    monkeypatch.setattr(
        "journal_browser.harvest.institution_stats.openalex_credits_remaining", _zero
    )
    stats = await harvest_institution_stats(db, inst)
    assert stats["skipped"] is not None
    json.dumps(stats)  # the job layer prints this verbatim
