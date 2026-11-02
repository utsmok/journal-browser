"""Green-route repository name -> jisc_repositories url matching:
normalized equality, word-boundary containment, and the detail payload."""

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.harvest.denorm import MATERIALIZE_SQL
from journal_browser.main import app
from journal_browser.models import Institution, JiscRepository
from journal_browser.services.repo_links import match_repositories

HARVESTED_AT = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)

CANON = [
    ("RePEc: Research Papers in Economics", "https://repec.example"),
    ("arXiv.org", "https://arxiv.example"),
    ("PubMed Central", "https://pmc.example"),
    ("Dryad Digital Repository", "https://dryad.example"),
]


def test_exact_normalized_match():
    # Case, punctuation and whitespace differences still match exactly.
    links = match_repositories(["PubMed Central", "pubmed  central", "ARXIV.ORG!"], CANON)
    assert links == {
        "PubMed Central": "https://pmc.example",
        "pubmed  central": "https://pmc.example",
        "ARXIV.ORG!": "https://arxiv.example",
    }


def test_exact_match_first_canon_row_wins():
    canon = [("PubMed Central", "first"), ("PubMed  Central", "second")]
    assert match_repositories(["PubMed Central"], canon) == {"PubMed Central": "first"}


def test_containment_match():
    # Canon name contains the full route name as a word ("RePEc" inside
    # "RePEc: Research Papers in Economics"; "arXiv" inside "arXiv.org").
    links = match_repositories(["RePEc", "arXiv", "Dryad"], CANON)
    assert links == {
        "RePEc": "https://repec.example",
        "arXiv": "https://arxiv.example",
        "Dryad": "https://dryad.example",
    }


def test_containment_needs_word_boundaries():
    # "repo" is not a word inside "Repository"; "Xiv" is not inside "arXiv".
    assert match_repositories(["repo", "Xiv"], CANON) == {}


def test_unmatched_names_absent():
    assert match_repositories(["Cosis", "EathArXiv"], CANON) == {}


@requires_db
@pytest.fixture
async def repo_api(client, db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        session.add_all(
            [
                JiscRepository(
                    id=1,
                    name="RePEc: Research Papers in Economics",
                    url="https://repec.example",
                ),
                # No url: never linkable, even on a name match.
                JiscRepository(id=2, name="Cosis", url=None),
                # "arXiv" must not word-contain "arXivSpace".
                JiscRepository(id=3, name="arXivSpace", url="https://wrong.example"),
            ]
        )
        session.add(
            journal_factory(
                "1111-2222",
                title="Repo Route Journal",
                search_text=None,
                jisc_in_opf=True,
                jisc_allows_sa_submitted=True,
                jisc_policy={
                    "routes": {
                        "submitted": {
                            "locations": ["named_repo"],
                            "repositories": ["RePEc", "arXiv", "Cosis", "Nowhere"],
                        }
                    },
                    "open_access_prohibited": False,
                    "urls": [],
                    "policy_uri": "https://openpolicyfinder.jisc.ac.uk/publication/1",
                },
                jisc_harvested_at=HARVESTED_AT,
            )
        )
        home = Institution(name="University of Twente", code="ut", active=True)
        session.add(home)
        await session.flush()
        await session.execute(MATERIALIZE_SQL, {"iid": home.id})
        await session.execute(
            text("UPDATE journal_flags SET works_window_plus = 10 WHERE institution_id = :iid"),
            {"iid": home.id},
        )
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client
    app.dependency_overrides.clear()


@requires_db
async def test_detail_repository_links(repo_api):
    r = await repo_api.get("/api/v1/ut/journals/1111-2222")
    assert r.status_code == 200
    links = r.json()["green_oa"]["repository_links"]
    # RePEc via containment; arXiv/Cosis/Nowhere stay plain (no word match,
    # no url, no canon row).
    assert links == {"RePEc": "https://repec.example"}
