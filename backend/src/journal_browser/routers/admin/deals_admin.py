from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, constr, model_validator
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...harvest.common import get_institution_by_code, normalize_issn
from ...models import (
    Deal,
    DealInstitution,
    DealJournal,
    Institution,
    IssnMap,
    Journal,
    ManualOverride,
    Publisher,
)
from ...schemas import AdminDealDetail, AdminDealOut
from ...services.flags_refresh import _schedule_flags_refresh
from ...vocab import DealStatus
from .auth import AdminDep, SessionDep

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Deals: curation CRUD ────────────────────────────────────────────────────
# Every accepted edit writes a manual_overrides row (table_name="deals",
# row_key=str(deal id)), which apply_overrides re-applies after each
# harvester upsert — that is what makes edits stick. Removing a deal
# journal sets excluded=true and keeps the row so the JCT upsert cannot
# resurrect it.

class DealUpdate(BaseModel):
    """PATCH-shaped PUT body: absent fields are untouched, explicit null
    clears nullable columns, and non-nullable columns reject null."""

    model_config = ConfigDict(extra="forbid")

    status: DealStatus | None = None
    start_year: int | None = Field(default=None, ge=1900, le=2100)
    end_year: int | None = Field(default=None, ge=1900, le=2100)
    corresponding_authors_only: StrictBool | None = None
    cap_numbers: dict[constr(pattern=r"^\d{4}$"), int] | None = None
    cap_text: str | None = None
    summary: str | None = None
    esac_id: str | None = None
    publisher_id: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_cleared_nonnullable(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for key in (
                "status",
                "start_year",
                "end_year",
                "corresponding_authors_only",
                "publisher_id",
            ):
                if key in data and data[key] is None:
                    raise ValueError(f"{key} must not be null")
        return data


def _deal_payload(
    deal: Deal, publisher: str | None, journal_count: int, participations: list[str]
) -> dict[str, Any]:
    return {
        "id": deal.id,
        "publisher_id": deal.publisher_id,
        "publisher": publisher,
        "esac_id": deal.esac_id,
        "status": deal.status,
        "start_year": deal.start_year,
        "end_year": deal.end_year,
        "corresponding_authors_only": deal.corresponding_authors_only,
        "capped": bool(deal.cap_numbers),
        "cap_numbers": deal.cap_numbers,
        "cap_text": deal.cap_text,
        "summary": deal.summary,
        "journal_count": journal_count,
        "participations": participations,
        "needs_curation": deal.needs_curation,
        "needs_curation_reason": deal.needs_curation_reason,
    }


async def _deal_detail(session: AsyncSession, deal_id: int) -> dict[str, Any]:
    row = (
        await session.execute(
            select(Deal, Publisher.name)
            .outerjoin(Publisher, Publisher.id == Deal.publisher_id)
            .where(Deal.id == deal_id)
        )
    ).first()
    if row is None:
        raise HTTPException(404, f"unknown deal: {deal_id}")
    deal, publisher = row
    journal_count = await session.scalar(
        select(func.count()).where(
            DealJournal.deal_id == deal_id, DealJournal.excluded.is_(False)
        )
    )
    codes = (
        (
            await session.execute(
                select(Institution.code)
                .join(DealInstitution, DealInstitution.institution_id == Institution.id)
                .where(
                    DealInstitution.deal_id == deal_id,
                    Institution.code.is_not(None),
                )
                .order_by(Institution.code)
            )
        )
        .scalars()
        .all()
    )
    journals = (
        (
            await session.execute(
                select(DealJournal)
                .where(DealJournal.deal_id == deal_id)
                .order_by(DealJournal.issn, DealJournal.institution_id)
            )
        )
        .scalars()
        .all()
    )
    return {
        **_deal_payload(deal, publisher, int(journal_count or 0), list(codes)),
        "journals": [
            {
                "issn": dj.issn,
                "issn_l": dj.issn_l,
                "journal_name": dj.journal_name,
                "source": dj.source,
                "excluded": dj.excluded,
            }
            for dj in journals
        ],
    }
async def _get_deal_or_404(session: AsyncSession, deal_id: int) -> Deal:
    deal = await session.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, f"unknown deal: {deal_id}")
    return deal


@router.get("/deals", response_model=list[AdminDealOut])
async def list_deals(session: SessionDep, _: AdminDep) -> list[dict[str, Any]]:
    counts = (
        select(DealJournal.deal_id, func.count().label("n"))
        .where(DealJournal.excluded.is_(False))
        .group_by(DealJournal.deal_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(Deal, Publisher.name, func.coalesce(counts.c.n, 0))
            .outerjoin(Publisher, Publisher.id == Deal.publisher_id)
            .outerjoin(counts, counts.c.deal_id == Deal.id)
            .order_by(Publisher.name, Deal.id)
        )
    ).all()
    participations: dict[int, list[str]] = {}
    for deal_id, code in (
        await session.execute(
            select(DealInstitution.deal_id, Institution.code)
            .join(Institution, Institution.id == DealInstitution.institution_id)
            # Registry institutions (no code) participate in JCT deals but
            # are not hosted here; a null code breaks the string[] contract.
            .where(Institution.code.is_not(None))
            .order_by(Institution.code)
        )
    ).all():
        participations.setdefault(deal_id, []).append(code)
    return [
        _deal_payload(deal, name, int(count), participations.get(deal.id, []))
        for deal, name, count in rows
    ]


@router.get("/deals/{deal_id}", response_model=AdminDealDetail)
async def get_deal(deal_id: int, session: SessionDep, _: AdminDep) -> dict[str, Any]:
    await _get_deal_or_404(session, deal_id)
    return await _deal_detail(session, deal_id)


class DealCreate(BaseModel):
    publisher_id: int | None = None
    publisher_name: str | None = None
    esac_id: str | None = None
    status: DealStatus = DealStatus.CURRENT
    start_year: int | None = None
    end_year: int | None = None
    corresponding_authors_only: bool | None = None


@router.post("/deals", status_code=201, response_model=AdminDealDetail)
async def create_deal(body: DealCreate, session: SessionDep, _: AdminDep) -> dict[str, Any]:
    if body.publisher_id is None and not body.publisher_name:
        raise HTTPException(422, "publisher_id or publisher_name is required")
    if body.esac_id is not None:
        clash = await session.scalar(select(Deal.id).where(Deal.esac_id == body.esac_id))
        if clash is not None:
            raise HTTPException(409, f"esac_id already in use by deal {clash}")
    publisher_id = body.publisher_id
    if publisher_id is None:
        pub = Publisher(name=body.publisher_name)
        session.add(pub)
        await session.flush()
        publisher_id = pub.id
    elif await session.get(Publisher, publisher_id) is None:
        raise HTTPException(404, f"unknown publisher: {publisher_id}")
    deal = Deal(
        publisher_id=publisher_id,
        esac_id=body.esac_id,
        status=body.status,
        start_year=body.start_year,
        end_year=body.end_year,
        corresponding_authors_only=body.corresponding_authors_only,
    )
    session.add(deal)
    await session.commit()
    _schedule_flags_refresh()
    return await _deal_detail(session, deal.id)


@router.put("/deals/{deal_id}", response_model=AdminDealDetail)
async def update_deal(
    deal_id: int, body: DealUpdate, session: SessionDep, _: AdminDep
) -> dict[str, Any]:
    deal = await _get_deal_or_404(session, deal_id)
    updates = body.model_dump(exclude_unset=True)
    if body.esac_id is not None and body.esac_id != deal.esac_id:
        clash = await session.scalar(
            select(Deal.id).where(Deal.esac_id == body.esac_id, Deal.id != deal_id)
        )
        if clash is not None:
            raise HTTPException(409, f"esac_id already in use by deal {clash}")
    if (
        body.publisher_id is not None
        and body.publisher_id != deal.publisher_id
        and await session.get(Publisher, body.publisher_id) is None
    ):
        raise HTTPException(404, f"unknown publisher: {body.publisher_id}")
    changed = {k: v for k, v in updates.items() if getattr(deal, k) != v}
    if not changed:
        return await _deal_detail(session, deal_id)
    for key, value in changed.items():
        setattr(deal, key, value)
    # A human reviewed the deal: clear the curation flag and pin the date.
    # (needs_curation sticks because the openaccess.nl harvester re-applies
    # overrides for it; last_reviewed stays JCT-owned by design.)
    if deal.needs_curation:
        changed["needs_curation"] = False
        changed["needs_curation_reason"] = None
        deal.needs_curation = False
        deal.needs_curation_reason = None
    deal.last_reviewed = date.today()
    for field, value in changed.items():
        await session.execute(
            pg_insert(ManualOverride)
            .values(table_name="deals", row_key=str(deal_id), field=field, value=value)
            .on_conflict_do_update(
                index_elements=["table_name", "row_key", "field"],
                set_={"value": value, "set_at": func.now()},
            )
        )
    await session.commit()
    _schedule_flags_refresh()
    return await _deal_detail(session, deal_id)


class DealJournalAdd(BaseModel):
    issn: str
    journal_name: str | None = None


class DealJournalsBody(BaseModel):
    add: list[DealJournalAdd] = []
    remove: list[str] = []


class DealParticipationsBody(BaseModel):
    add: list[str] = []
    remove: list[str] = []


def _norm_issn_or_400(raw: str) -> str:
    issn = normalize_issn(raw)
    if issn is None:
        raise HTTPException(400, f"invalid ISSN: {raw!r}")
    return issn


async def _resolve_issn_l(session: AsyncSession, issn: str) -> str | None:
    issn_l = await session.scalar(select(Journal.issn_l).where(Journal.issn_l == issn))
    if issn_l is None:
        issn_l = await session.scalar(select(IssnMap.issn_l).where(IssnMap.issn == issn))
    return issn_l


@router.put("/deals/{deal_id}/journals", response_model=AdminDealDetail)
async def update_deal_journals(
    deal_id: int, body: DealJournalsBody, session: SessionDep, _: AdminDep
) -> dict[str, Any]:
    await _get_deal_or_404(session, deal_id)
    for add in body.add:
        issn = _norm_issn_or_400(add.issn)
        issn_l = await _resolve_issn_l(session, issn)
        updates: dict[str, Any] = {"excluded": False, "issn_l": issn_l}
        if add.journal_name:
            updates["journal_name"] = add.journal_name
        await session.execute(
            pg_insert(DealJournal)
            .values(
                deal_id=deal_id,
                issn=issn,
                issn_l=issn_l,
                journal_name=add.journal_name,
                source="manual",
                excluded=False,
            )
            .on_conflict_do_update(
                index_elements=["deal_id", "issn"],
                index_where=text("institution_id IS NULL"),
                set_=updates,
            )
        )
    if body.remove:
        # Flag, never delete: a deleted row would be re-inserted by the
        # next JCT harvest.
        await session.execute(
            update(DealJournal)
            .where(
                DealJournal.deal_id == deal_id,
                DealJournal.issn.in_([_norm_issn_or_400(raw) for raw in body.remove]),
            )
            .values(excluded=True)
        )
    await session.commit()
    _schedule_flags_refresh()
    return await _deal_detail(session, deal_id)


@router.put("/deals/{deal_id}/participations", response_model=AdminDealDetail)
async def update_deal_participations(
    deal_id: int, body: DealParticipationsBody, session: SessionDep, _: AdminDep
) -> dict[str, Any]:
    await _get_deal_or_404(session, deal_id)
    for code in body.remove:
        inst = await get_institution_by_code(session, code)
        if inst is None:
            raise HTTPException(404, f"unknown institution: {code}")
        await session.execute(
            delete(DealInstitution).where(
                DealInstitution.deal_id == deal_id, DealInstitution.institution_id == inst.id
            )
        )
        # Tombstone: the JCT harvester re-inserts sheet participations on every
        # run, so a removal is recorded as an override it must respect.
        await session.execute(
            pg_insert(ManualOverride)
            .values(
                table_name="deal_institutions",
                row_key=f"{deal_id}:{inst.id}",
                field="removed",
                value=True,
            )
            .on_conflict_do_update(
                index_elements=["table_name", "row_key", "field"], set_={"value": True}
            )
        )
    for code in body.add:
        inst = await get_institution_by_code(session, code)
        if inst is None:
            raise HTTPException(404, f"unknown institution: {code}")
        await session.execute(
            pg_insert(DealInstitution)
            .values(deal_id=deal_id, institution_id=inst.id)
            .on_conflict_do_nothing(index_elements=["deal_id", "institution_id"])
        )
        # Re-adding clears any removal tombstone so JCT can manage it again.
        await session.execute(
            delete(ManualOverride).where(
                ManualOverride.table_name == "deal_institutions",
                ManualOverride.row_key == f"{deal_id}:{inst.id}",
            )
        )
    await session.commit()
    _schedule_flags_refresh()
    return await _deal_detail(session, deal_id)
