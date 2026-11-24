"""Zero-result search regressions: typo tolerance and the topic /
research-group fallback.

Authors: pg_trgm word similarity over the folded name (q >= 0.5), and
when no name matches, primary_topic then research_group passes reported
via q_match. Org units: the in-memory snapshot filter accepts fuzzy word
similarity (services.fuzzy), so "pilosophy" finds the Philosophy group.
The usage-log queries that motivated this ("philosophy", "pilosophy",
"phyloso", ...) are all asserted here.
"""

import pytest

from conftest import requires_db
from journal_browser.models import Author
from journal_browser.services import fuzzy

BMS = "Faculty of Behavioural, Management and Social Sciences"
TNW = "Faculty of Science and Technology"


@pytest.fixture
async def typo_api(client, db, institution_factory):
    """ut roster covering every q shape under test: exact (Loorbach,
    unconfirmed), typo (Vermeer), topic fallback (philosophy topics),
    group fallback (Quantum Matter group with physics topics), and
    org-unit levels with a Philosophy group under BMS."""
    ut = await institution_factory(code="ut", require_confirmed_affiliation=True)

    def _author(uuid, name, *, faculty=None, group=None, n_works=0, confirmed=True, **kw):
        return Author(
            institution_id=ut.id,
            pure_uuid=uuid,
            name=name,
            faculty=faculty,
            research_group=group,
            n_works=n_works,
            confirmed=confirmed,
            **kw,
        )

    db.add_all(
        [
            _author("loorb-uuid", "Nicole Loorbach", faculty=BMS, n_works=12, confirmed=False),
            # Confirmed trigram cousin of "Loorbach": without the rerun
            # extension it satisfies the confirmed gate and masks Nicole.
            _author("corbach-uuid", "Harmen van Corbach", faculty=BMS, n_works=0),
            _author("vermeer-uuid", "Jan Vermeer", faculty=TNW, n_works=8),
            _author(
                "weigold-uuid",
                "Stefanie Weigold",
                faculty=BMS,
                group="Philosophy",
                n_works=6,
                primary_topic="Philosophy",
            ),
            _author(
                "hillenbrink-uuid",
                "Robin Hillenbrink",
                faculty=BMS,
                n_works=5,
                primary_topic="History and Philosophy of Science",
            ),
            _author(
                "steinert-uuid",
                "Sibylle Steinert",
                faculty=BMS,
                group="Philosophy",
                n_works=4,
                primary_topic="Ethics",
            ),
            _author(
                "alice-uuid",
                "Alice Author",
                faculty=TNW,
                group="Quantum Matter",
                n_works=40,
                primary_topic="Physics",
            ),
        ]
    )
    await db.commit()
    return client, ut.id


@requires_db
async def test_author_typo_tolerant_name(typo_api):
    client, _ = typo_api
    body = (await client.get("/api/v1/ut/authors", params={"q": "vermoer"})).json()
    assert body["q_match"] == "name"
    assert [i["name"] for i in body["items"]] == ["Jan Vermeer"]


@requires_db
async def test_author_substring_and_gate_rerun(typo_api):
    """q=loorbach: the confirmed gate must not let a fuzzy-only confirmed
    hit (Harmen van Corbach) mask the unconfirmed exact-name person
    (Nicole Loorbach); the search reruns ungated, works order ranks
    Nicole first, and the fuzzy cousin stays as a lower hit."""
    client, _ = typo_api
    body = (await client.get("/api/v1/ut/authors", params={"q": "loorbach"})).json()
    assert body["q_match"] == "name"
    assert [i["name"] for i in body["items"]] == ["Nicole Loorbach", "Harmen van Corbach"]
    assert body["items"][0]["confirmed"] is False


@requires_db
async def test_author_gate_rerun_when_nothing_confirmed_matches(typo_api):
    """The original emptied-gate case: q matches only the unconfirmed
    author, no confirmed hit exists, the search reruns ungated."""
    client, _ = typo_api
    body = (await client.get("/api/v1/ut/authors", params={"q": "nicole"})).json()
    assert body["q_match"] == "name"
    assert [i["name"] for i in body["items"]] == ["Nicole Loorbach"]
    assert body["items"][0]["confirmed"] is False


@requires_db
async def test_author_topic_fallback_for_philosophy(typo_api):
    """The usage-log query: no author is named philosophy, so the topic
    pass answers and the response says so."""
    client, _ = typo_api
    body = (await client.get("/api/v1/ut/authors", params={"q": "philosophy"})).json()
    assert body["q_match"] == "topic"
    assert body["total"] > 0
    assert all("philosoph" in (i["primary_topic"] or "").lower() for i in body["items"])


@requires_db
async def test_author_typo_topic_fallback(typo_api):
    client, _ = typo_api
    body = (await client.get("/api/v1/ut/authors", params={"q": "philosphy"})).json()
    assert body["q_match"] == "topic"
    assert body["total"] > 0


@requires_db
async def test_author_group_fallback_when_topic_misses(typo_api):
    """quantum never appears in a name or topic; the group pass answers."""
    client, _ = typo_api
    body = (await client.get("/api/v1/ut/authors", params={"q": "quantum"})).json()
    assert body["q_match"] == "group"
    assert [i["research_group"] for i in body["items"]] == ["Quantum Matter"]


@requires_db
async def test_author_no_match_reports_name_field(typo_api):
    client, _ = typo_api
    body = (await client.get("/api/v1/ut/authors", params={"q": "zzqqxxnomatch"})).json()
    assert body["total"] == 0
    assert body["q_match"] == "name"


@requires_db
async def test_author_philosophy_named_group_member_ranks(typo_api):
    """'philosophy' must also surface the group members whose topic does
    not say philosophy: they come from the topic pass (Weigold) or later
    the group pass; Steinert (topic Ethics) is excluded from topic results."""
    client, _ = typo_api
    body = (await client.get("/api/v1/ut/authors", params={"q": "philosophy"})).json()
    names = {i["name"] for i in body["items"]}
    assert "Stefanie Weigold" in names
    assert "Sibylle Steinert" not in names


@requires_db
async def test_orgunit_fuzzy_typos_find_philosophy_group(client, db, institution_factory):
    ut = await institution_factory(code="ut", require_confirmed_affiliation=True)
    db.add_all(
        [
            Author(
                institution_id=ut.id,
                pure_uuid="p1",
                name="Stefanie Weigold",
                faculty=BMS,
                research_group="Philosophy",
                n_works=3,
                confirmed=True,
            ),
            Author(
                institution_id=ut.id,
                pure_uuid="p2",
                name="Alice Author",
                faculty=TNW,
                research_group="Quantum Matter",
                n_works=9,
                confirmed=True,
            ),
        ]
    )
    await db.commit()
    for q in ("pilosophy", "philosophy", "philo", "phyloso", "phylosophy", "piloso"):
        body = (await client.get("/api/v1/ut/orgunits", params={"level": "group", "q": q})).json()
        assert [i["name"] for i in body["items"]] == ["Philosophy"], q
    body = (
        await client.get("/api/v1/ut/orgunits", params={"level": "group", "q": "zzqqxxnomatch"})
    ).json()
    assert body["total"] == 0


@requires_db
async def test_orgunit_level_scope_unchanged(client, db, institution_factory):
    """q still matches only the active level: the Philosophy group is not
    a faculty, so a faculty-level search stays empty (the UI suggests the
    other levels)."""
    ut = await institution_factory(code="ut", require_confirmed_affiliation=True)
    db.add(
        Author(
            institution_id=ut.id,
            pure_uuid="p1",
            name="Stefanie Weigold",
            faculty=BMS,
            research_group="Philosophy",
            n_works=3,
            confirmed=True,
        )
    )
    await db.commit()
    body = (
        await client.get("/api/v1/ut/orgunits", params={"level": "faculty", "q": "philosophy"})
    ).json()
    assert body["total"] == 0


def test_fuzzy_trigram_construction():
    assert fuzzy.word_trigrams("foo") == frozenset({"  f", " fo", "foo", "oo "})
    assert fuzzy.word_trigrams("a") == frozenset({"  a", " a "})
    assert fuzzy.word_trigrams("") == frozenset()


def test_fuzzy_similarity_bounds():
    assert fuzzy.similarity("", "") == 0.0
    assert fuzzy.similarity("philosophy", "philosophy") == 1.0
    assert fuzzy.similarity("zzqqxx", "philosophy") == 0.0


def test_fuzzy_word_similarity_matches_inside_words():
    assert fuzzy.word_similarity("quantum", "Quantum Matter") == 1.0
    assert fuzzy.word_similarity("quantom", "Quantum Matter") >= fuzzy.WORD_SIMILARITY_THRESHOLD
    assert fuzzy.word_similarity("philosophy", "Faculty of Behavioural") == 0.0
