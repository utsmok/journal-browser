
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import (
    Deal,
    DealInstitution,
    DealJournal,
    Work,
    WorkIdentity,
)

logger = logging.getLogger(__name__)


def _esc(text: str | None) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _conf(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "—"


async def render_curation_report(
    session: AsyncSession, data_guard_actions: list[dict[str, str]] | None = None
) -> Path:
    """Read-only HTML report for library staff."""
    # Deferred: reconcile re-exports this function (test import path), so a
    # module-level import of its helpers would cycle at import time.
    from .reconcile import _home_institution_id, _publisher_names

    publisher_names = await _publisher_names(session)
    deals = list((await session.execute(select(Deal))).scalars())
    oanl = [d for d in deals if d.openaccess_nl_url]
    flagged = [d for d in deals if d.needs_curation]
    unresolvable = list(
        (
            await session.execute(select(DealJournal).where(DealJournal.needs_curation.is_(True)))
        ).scalars()
    )

    sections: list[str] = []

    def deal_row(d: Deal) -> str:
        return (
            f"<li>#{d.id} <strong>{_esc(publisher_names.get(d.publisher_id, '?'))}</strong> "
            f"[{_esc(d.status)}] {_esc(d.duration_text)} — "
            f"{_esc(d.needs_curation_reason or '')} "
            f"<a href='{_esc(d.openaccess_nl_url)}'>openaccess.nl</a> "
            f"{f'<a href="{_esc(d.jct_data_url)}">JCT</a>' if d.jct_data_url else ''}</li>"
        )

    if flagged:
        sections.append(
            "<h2>Deals flagged for curation</h2><ul>"
            + "".join(deal_row(d) for d in flagged)
            + "</ul>"
        )
    no_list = [d for d in oanl if d.esac_id is None]
    if no_list:
        sections.append(
            "<h2>openaccess.nl deals without a JCT agreement (no journal list)</h2><ul>"
            + "".join(deal_row(d) for d in no_list)
            + "</ul>"
        )
    jct_only = [d for d in deals if d.esac_id and not d.openaccess_nl_url]
    home_id = await _home_institution_id(session)
    if home_id is not None:
        twente_deal_ids = set(
            (
                await session.execute(
                    select(DealInstitution.deal_id).where(
                        DealInstitution.institution_id == home_id
                    )
                )
            ).scalars()
        )
    else:
        twente_deal_ids = set()
    relevant = [d for d in jct_only if d.id in twente_deal_ids]
    skipped = len(jct_only) - len(relevant)
    if relevant:
        sections.append(
            f"<h2>{_esc(get_settings().institution_name)}-relevant JCT agreements "
            "with no openaccess.nl deal (publisher/duration unmatched)</h2><ul>"
            + "".join(
                f"<li>#{d.id} {_esc(publisher_names.get(d.publisher_id, '?'))} "
                f"{_esc(d.esac_id)} [{_esc(d.status)}] {_esc(d.duration_text)}</li>"
                for d in relevant
            )
            + "</ul>"
        )
    if skipped:
        sections.append(
            f"<p>{skipped} JCT agreements are not affiliated with "
            f"{_esc(get_settings().institution_name)} and are out of scope for this "
            "browser; they stay in the database for provenance.</p>"
        )
    # Duplicate-agreement guard: enforce_unique_agreement_data runs before
    # the report and returns the purge/flag actions it took.
    # Phase 10: trigram-matched work identities awaiting curation.
    candidate_rows = (
        await session.execute(
            select(
                WorkIdentity.source,
                WorkIdentity.source_pk,
                WorkIdentity.matched_by,
                WorkIdentity.confidence,
                WorkIdentity.note,
                Work.title,
            )
            .join(
                Work,
                (Work.institution_id == WorkIdentity.institution_id)
                & (Work.pure_uuid == WorkIdentity.work_id),
            )
            .where(WorkIdentity.status == "candidate")
            .order_by(WorkIdentity.confidence.desc())
            .limit(500)
        )
    ).all()
    if candidate_rows:
        sections.append(
            "<h2>Work-identity candidates needing curation</h2><ul>"
            + "".join(
                f"<li>{_esc(r.source)}/{_esc(r.source_pk)} → “{_esc((r.title or '')[:90])}” "
                f"[{_esc(r.matched_by)}, {_esc(_conf(r.confidence))}]"
                f"{(' — ' + _esc(r.note[:90])) if r.note else ''}</li>"
                for r in candidate_rows
            )
            + (
                f"<li>… and more (showing {len(candidate_rows)})</li>"
                if len(candidate_rows) == 500
                else ""
            )
            + "</ul>"
        )
    # Phase 9 spec: works that resolve to no journal land here with their
    # container string so a curator can decide (book series vs journal etc.).
    unresolved = (
        await session.execute(
            text("""
                SELECT w.doi_normalized AS doi, w.title,
                       COALESCE(
                           sr.payload->'primary_location'->'source'->>'display_name',
                           cr.payload->>'container-title'
                       ) AS container
                FROM works w
                LEFT JOIN LATERAL (
                    SELECT sr.payload
                    FROM source_records sr
                    WHERE sr.source='openalex' AND sr.entity_type='work'
                      AND EXISTS (SELECT 1 FROM work_identity wi
                                  WHERE wi.institution_id = w.institution_id
                                    AND wi.work_id = w.pure_uuid
                                    AND wi.source='openalex' AND wi.source_pk = sr.source_pk)
                    LIMIT 1
                ) sr ON sr.payload IS NOT NULL
                LEFT JOIN LATERAL (
                    SELECT cr.payload
                    FROM source_records cr
                    WHERE cr.source='crossref' AND cr.entity_type='work'
                      AND cr.source_pk = 'doi:' || w.doi_normalized
                    LIMIT 1
                ) cr ON cr.payload IS NOT NULL
                WHERE w.retired_at IS NULL AND w.doi_normalized IS NOT NULL
                  AND w.journal_issn_l IS NULL
                  AND COALESCE(
                      sr.payload->'primary_location'->'source'->>'display_name',
                      cr.payload->>'container-title') IS NOT NULL
                LIMIT 500
            """)
        )
    ).all()
    if unresolved:
        sections.append(
            "<h2>Works unresolved to a journal (have a container string)</h2><ul>"
            + "".join(
                f"<li>{_esc((r.doi or '')[:60])} — “{_esc((r.title or '')[:80])}” "
                f"in <em>{_esc(str(r.container)[:80])}</em></li>"
                for r in unresolved
            )
            + "</ul>"
        )
    if data_guard_actions:
        sections.append(
            "<h2>Duplicate agreement data (auto-guarded)</h2><ul>"
            + "".join(
                f"<li>{_esc(a['keeper'])} vs {_esc(a['loser'])}: "
                f"{_esc(a['overlap'])} identical ISSN sets — kept the former, "
                f"{_esc(a['action'])}. The loser's JCT CSV is an upstream index "
                "error; request the correct sheet from the JCT curators.</li>"
                for a in data_guard_actions
            )
            + "</ul>"
        )
    if unresolvable:
        sections.append(
            "<h2>Deal journals with unresolved ISSN-L</h2><ul>"
            + "".join(
                f"<li>deal #{r.deal_id}: {_esc(r.journal_name)} ISSN {_esc(r.issn)}</li>"
                for r in unresolvable[:200]
            )
            + (f"<li>… and {len(unresolvable) - 200} more</li>" if len(unresolvable) > 200 else "")
            + "</ul>"
        )
    counts = {
        "deals_total": len(deals),
        "deals_with_esac": sum(1 for d in deals if d.esac_id),
        "needs_curation": len(flagged),
        "unresolved_journal_issns": len(unresolvable),
    }
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Journal Browser — curation report</title>"
        "<style>body{font-family:system-ui;max-width:60rem;margin:2rem auto;padding:0 1rem}"
        "li{margin:.2rem 0}h2{border-bottom:1px solid #ddd}</style></head><body>"
        f"<h1>Curation report</h1><p>Generated {datetime.now(UTC).isoformat()}</p>"
        f"<pre>{_esc(str(counts))}</pre>" + "".join(sections) + "</body></html>"
    )
    path = Path(get_settings().curation_report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)
    logger.info("curation report written to %s", path)
    return path
