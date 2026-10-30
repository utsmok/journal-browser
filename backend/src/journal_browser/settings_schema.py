"""Schema of the admin-editable settings: one FieldDef per editable knob.

GET/PUT /api/v1/admin/settings serve the global section; entries with
section="institution" describe per-university values that live in the
institutions table (exposed via /admin/institutions/{code}) — they render
on each institution's admin page and are never part of the global values
dict. database_url is intentionally absent: the boot dependency must not
be editable at runtime.
"""

from typing import Any, Literal

from pydantic import BaseModel

from .config import Settings

FieldSection = Literal["global", "institution"]
FieldType = Literal["string", "number", "bool", "secret", "list"]

_MASK = "********"
_SECRETS = (
    "admin_password",
    "openalex_api_key",
    "jisc_api_key",
    "ut_metadata_dsn",
)


class FieldDef(BaseModel):
    key: str
    section: FieldSection
    type: FieldType
    label: str
    help: str
    default: Any


_DEFAULTS = Settings.model_fields


def _f(key: str, section: FieldSection, ftype: FieldType, label: str, help: str) -> FieldDef:
    """FieldDef with the declared Settings default (not the env value)."""
    return FieldDef(
        key=key, section=section, type=ftype, label=label, help=help, default=_DEFAULTS[key].default
    )


#: Institution-table-backed knobs: seeded from these Settings fields on
#: first boot, then the row is authoritative.
INSTITUTION_KEYS = (
    "institution_code",
    "institution_name",
    "institution_short",
    "institution_ror",
    "institution_openalex_id",
    "openaire_org_id",
    "data_window_start",
    "data_window_end",
    "library_url",
    "oa_guide_url",
    "support_email",
    "admin_contact",
    "research_portal_url",
)

SETTINGS_REGISTRY: list[FieldDef] = [
    # ── Global (settings.yaml, PUT /admin/settings) ────────────────────────
    _f("admin_password", "global", "secret", "Admin panel password",
       "Password for /admin and the admin API; empty disables the panel. "
       f"Send '{_MASK}' (or empty) to keep the current value."),
    _f("openalex_api_key", "global", "secret", "OpenAlex API key",
       "Free-tier key for OpenAlex harvests; single-entity lookups stay keyless."),
    _f("jisc_api_key", "global", "secret", "JISC API key",
       "Credentials for the JISC integration (feature currently off)."),
    _f("contact_email", "global", "string", "Contact email",
       "Sent to OpenAlex for polite-pool identification."),
    _f("cors_origins", "global", "list", "CORS origins",
       "Browser origins allowed to call the API. Applied at startup, so a "
       "restart is needed."),
    _f("ignored_issns", "global", "list", "Ignored ISSNs",
       "ISSN-Ls treated as nonexistent: excluded from search, facets, "
       "similar, semantic search and author venue lists; journal detail "
       "returns 404. One per line, XXXX-XXXX; applied live."),
    _f("pure_oai_base_url", "global", "string", "Pure OAI-PMH endpoint",
       "Default institutional-repository OAI-PMH endpoint (first-boot seed)."),
    _f("pure_oai_min_spacing", "global", "number", "Pure request spacing (s)",
       "Minimum seconds between OAI-PMH requests."),
    _f("landing_dir", "global", "string", "Landing directory",
       "Raw landing zone for downloaded source artifacts; in compose this is "
       "the bind-mounted landing volume."),
    _f("curation_report_path", "global", "string", "Curation report path",
       "Where the reconcile job writes its HTML curation report."),
    _f("bootstrap", "global", "string", "Bootstrap mode",
       "auto (harvest only on an empty DB), always, or off."),
    _f("enable_journal_citations", "global", "bool", "Journal citations",
       "Citation feature scaffold; stays off until explicitly enabled."),
    _f("enable_jisc", "global", "bool", "JISC integration",
       "JISC feature scaffold; stays off until explicitly enabled."),
    # ── Institution-backed (institutions table, PUT /admin/institutions/{code})
    _f("institution_code", "institution", "string", "Code",
       "URL path segment ([a-z0-9-]+), e.g. ut."),
    _f("institution_name", "institution", "string", "Name",
       "Full institution name."),
    _f("institution_short", "institution", "string", "Short name",
       "Compact form for UI labels (\"Twente works\")."),
    _f("institution_ror", "institution", "string", "ROR",
       "Research Organization Registry identifier URL."),
    _f("institution_openalex_id", "institution", "string", "OpenAlex id",
       "Resolved OpenAlex institution id (I...); empty resolves on first harvest."),
    _f("openaire_org_id", "institution", "string", "OpenAIRE org id",
       "openorgs____::... id for the product harvest; required for a new institution."),
    _f("data_window_start", "institution", "number", "Data window start",
       "First publication year harvested and shown (inclusive)."),
    _f("data_window_end", "institution", "number", "Data window end",
       "Last publication year (inclusive); empty = open (to now)."),
    _f("library_url", "institution", "string", "Library URL",
       "Link to the university library."),
    _f("oa_guide_url", "institution", "string", "OA guide URL",
       "Link to the open-access publishing guide."),
    _f("support_email", "institution", "string", "Support email",
       "Open-access support mailbox shown in the UI."),
    _f("admin_contact", "institution", "string", "Admin contact",
       "Personal contact in the footer; empty hides the row."),
    _f("research_portal_url", "institution", "string", "Research portal URL",
       "Link to the research portal (publication discovery)."),
]


def value_for_response(ftype: str, value: Any) -> Any:
    """Response shape for a settings value: secrets are masked, everything
    else is returned as stored."""
    if ftype != "secret":
        return value
    return _MASK if value else None
