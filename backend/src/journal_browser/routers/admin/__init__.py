"""/api/v1/admin: password-protected harvest inspection and configuration.

POST /admin/login exchanges the admin password for a stateless HMAC
bearer token (12 h; the MAC secret derives from the current settings, so a
password change invalidates old tokens immediately). GET /admin/runs show
recent harvest runs, /admin/flagged the deals flagged for curation, and
/admin/author-identities + /admin/work-identities the review queues;
every admin status flip appends to status_changes (read via
/admin/status-changes). GET/PUT /settings read
and write the settings.yaml overlay (reloaded live, no restart) and
GET/PUT /institutions/{code} the per-university configuration rows.
/deals is the curation CRUD: edits are recorded as manual_overrides and
survive every re-harvest; removed deal journals are flagged, not deleted.
"""

from fastapi import APIRouter, Depends

from . import (
    audit_admin,
    auth,
    authors_admin,
    deals_admin,
    docs_admin,
    feedback_admin,
    ops_admin,
    runs,
    settings_admin,
    usage_admin,
    work_identity_admin,
)

# Each submodule router carries the /admin prefix itself: this FastAPI
# version bakes a router's own prefix into its stored route paths, so the
# route walk over nested original_routers matches the pre-split snapshot.
router = APIRouter()
# Include order matches the original admin.py registration order.
router.include_router(auth.router)
# Every route except /admin/login requires the bearer token at the router
# level too, so a new endpoint that forgets its AdminDep is still closed.
_guarded = [Depends(auth.require_admin)]
for sub in (
    runs,
    settings_admin,
    deals_admin,
    feedback_admin,
    docs_admin,
    authors_admin,
    work_identity_admin,
    audit_admin,
    ops_admin,
    usage_admin,
):
    router.include_router(sub.router, dependencies=_guarded)
