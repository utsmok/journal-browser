"""Route-precedence invariant: fixed prefixes are not shadowed by /{institution_code}.

The routers in main.py are included in a load-bearing order; these tests pin
it. Both endpoints below execute no SQL, so no database override is needed.
"""

import pytest

from conftest import requires_db
from journal_browser.config import reset_settings_cache
from journal_browser.main import app

FIXED_PREFIXES = ("/api/v1/admin", "/api/v1/feedback", "/api/v1/docs")
SCOPED_MARKER = "{institution_code}"


def _path_order() -> tuple[list[int], int]:
    paths = list(app.openapi()["paths"].keys())  # registration order
    fixed = [i for i, p in enumerate(paths) if p.startswith(FIXED_PREFIXES)]
    scoped = [i for i, p in enumerate(paths) if SCOPED_MARKER in p]
    return fixed, min(scoped)


def test_fixed_prefixes_register_before_institution_scope():
    fixed, first_scoped = _path_order()
    assert fixed, "no admin/feedback/docs routes found"
    assert first_scoped > max(fixed), (
        "a /{institution_code} route shadows a fixed prefix; "
        "router include order in main.py changed"
    )


@pytest.fixture
async def bare_client(client, monkeypatch):
    monkeypatch.setenv("JB_ADMIN_PASSWORD", "route-test-pw")
    reset_settings_cache()
    return client
    reset_settings_cache()


@requires_db
async def test_admin_not_shadowed_by_institution_scope(bare_client):
    res = await bare_client.get("/api/v1/admin/deals")
    assert res.status_code == 401


@requires_db
async def test_docs_not_shadowed_by_institution_scope(bare_client):
    res = await bare_client.get("/api/v1/docs")
    assert res.status_code == 200
