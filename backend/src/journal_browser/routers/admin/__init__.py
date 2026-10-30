"""/api/v1/admin: password-protected harvest inspection and configuration.

POST /admin/login exchanges the admin password for a stateless HMAC
bearer token (12 h; the MAC secret derives from the current settings, so a
password change invalidates old tokens immediately). GET endpoints show
recent harvest runs and deals flagged for curation. GET/PUT /settings read
and write the settings.yaml overlay (reloaded live, no restart) and
GET/PUT /institutions/{code} the per-university configuration rows.
/deals is the curation CRUD: edits are recorded as manual_overrides and
survive every re-harvest; removed deal journals are flagged, not deleted.
"""

from fastapi import APIRouter

from . import (
    auth,
    authors_admin,
    deals_admin,
    docs_admin,
    feedback_admin,
    runs,
    settings_admin,
)

# Each submodule router carries the /admin prefix itself: this FastAPI
# version bakes a router's own prefix into its stored route paths, so the
# route walk over nested original_routers matches the pre-split snapshot.
router = APIRouter()
# Include order matches the original admin.py registration order.
router.include_router(auth.router)
router.include_router(runs.router)
router.include_router(settings_admin.router)
router.include_router(deals_admin.router)
router.include_router(feedback_admin.router)
router.include_router(docs_admin.router)
router.include_router(authors_admin.router)
