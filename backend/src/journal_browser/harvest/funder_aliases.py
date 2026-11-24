"""Funder names to OpenAlex funders: derive_funder_aliases.

OpenAIRE credits a work with projects that name their funder in free text
("Netherlands Organisation for Scientific Research (NWO)") and carry no
funder id, while OpenAlex credits funders by id. The Partners view shows
the credits of both sources under one funder, so every OpenAIRE name needs
the OpenAlex funder it means. Two rules give it, the first that applies:

1. name. The name equals the display name of an OpenAlex funder, case
   aside. When several share the name, the one with the most works.
2. grant. The same grant number is an OpenAlex award on one work and an
   OpenAIRE project code on that work. The OpenAlex funder that shares the
   most grant numbers with a name is that name's funder when it has at
   least MIN_WORKS shared works and at least half of the name's shared
   works.

The name rule runs first because the grant rule could land a name on one
part of a funder: OpenAlex credits a grant to the research council that
made it (EPSRC), OpenAIRE to the council's parent (UK Research and
Innovation). A name neither rule covers stays a funder of its own, keyed by
name and source. The derive reads stored data only and rebuilds the table in
one transaction, so a rerun gives the same rows.
"""

import logging
from typing import Any

from sqlalchemy import and_, delete, func, insert, select
from sqlalchemy import cast as sql_cast
from sqlalchemy.dialects.postgresql import JSONB, distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from ..identifiers import bare_openalex_id
from ..models import FunderAlias, OpenaireWorkFacts, OpenalexFunder, WorkFunder

logger = logging.getLogger(__name__)

#: shared works a grant match needs before it is trusted
MIN_WORKS = 3


def project_credits() -> Any:
    """One row per OpenAIRE project credit on a stored work: institution_id,
    work, funder_name (the name, or null), code, acronym, pid, each trimmed
    and null when empty."""
    elements = (
        select(
            OpenaireWorkFacts.institution_id.label("institution_id"),
            OpenaireWorkFacts.pure_uuid.label("work"),
            sql_cast(func.jsonb_array_elements(OpenaireWorkFacts.projects), JSONB).label("project"),
        )
        .where(OpenaireWorkFacts.projects.is_not(None))
        .subquery()
    )
    project = elements.c.project

    def value(key: str) -> Any:
        return func.nullif(func.btrim(project[key].astext), "")

    return select(
        elements.c.institution_id,
        elements.c.work,
        value("funder").label("funder_name"),
        value("code").label("code"),
        value("acronym").label("acronym"),
        value("id").label("pid"),
    ).subquery()


async def _by_name(session: AsyncSession, names: Any) -> Any:
    """(funder_name, funder_openalex_id) for every name in `names` that is
    the display name of an OpenAlex funder. OpenAlex stores an id in both
    its bare and its full form, so a funder can match twice; the pick
    keeps one row per name, the funder with the most works."""
    openalex_funders = (
        select(
            func.lower(OpenalexFunder.display_name).label("name"),
            bare_openalex_id(OpenalexFunder.openalex_id).label("funder_openalex_id"),
            OpenalexFunder.works_count.label("works_count"),
        )
        .where(OpenalexFunder.display_name.is_not(None))
        .subquery()
    )
    stmt = (
        select(names.c.funder_name, openalex_funders.c.funder_openalex_id)
        .join(openalex_funders, openalex_funders.c.name == func.lower(names.c.funder_name))
        .ext(distinct_on(names.c.funder_name))
        .order_by(
            names.c.funder_name,
            openalex_funders.c.works_count.desc().nulls_last(),
            openalex_funders.c.funder_openalex_id,
        )
    )
    return (await session.execute(stmt)).all()


def _by_grant(credits: Any, names: Any) -> Any:
    """Statement for (funder_name, funder_openalex_id, works) of the grant
    matches among `names`."""
    award = func.nullif(func.btrim(WorkFunder.award), "")
    pairs = (
        select(
            credits.c.funder_name.label("funder_name"),
            bare_openalex_id(WorkFunder.funder_openalex_id).label("funder_openalex_id"),
            func.count(func.distinct(WorkFunder.pure_uuid)).label("works"),
        )
        .join(
            WorkFunder,
            and_(
                WorkFunder.institution_id == credits.c.institution_id,
                WorkFunder.pure_uuid == credits.c.work,
                award == credits.c.code,
            ),
        )
        .where(credits.c.funder_name.is_not(None), award.is_not(None))
        .group_by(credits.c.funder_name, bare_openalex_id(WorkFunder.funder_openalex_id))
        .subquery()
    )
    ranked = select(
        pairs.c.funder_name,
        pairs.c.funder_openalex_id,
        pairs.c.works,
        func.row_number()
        .over(
            partition_by=pairs.c.funder_name,
            order_by=(pairs.c.works.desc(), pairs.c.funder_openalex_id),
        )
        .label("rank"),
        func.sum(pairs.c.works).over(partition_by=pairs.c.funder_name).label("total"),
    ).subquery()
    return select(ranked.c.funder_name, ranked.c.funder_openalex_id, ranked.c.works).where(
        ranked.c.rank == 1,
        ranked.c.works >= MIN_WORKS,
        ranked.c.works * 2 >= ranked.c.total,
        ranked.c.funder_name.in_(select(names.c.funder_name)),
    )


async def derive_funder_aliases(session: AsyncSession) -> dict[str, int]:
    """Rebuild funder_aliases from the stored OpenAlex awards and OpenAIRE
    projects of every institution."""
    credits = project_credits()
    all_names = (
        select(func.distinct(credits.c.funder_name).label("funder_name"))
        .where(credits.c.funder_name.is_not(None))
        .subquery()
    )
    name_rows = await _by_name(session, all_names)
    rest = (
        select(all_names.c.funder_name)
        .where(all_names.c.funder_name.not_in([row.funder_name for row in name_rows]))
        .subquery()
    )
    grant_rows = (await session.execute(_by_grant(credits, rest))).all()
    total = int((await session.execute(select(func.count()).select_from(all_names))).scalar_one())
    rows = [
        {
            "funder_name": row.funder_name,
            "funder_openalex_id": row.funder_openalex_id,
            "rule": rule,
            "works": int(row.works) if rule == "grant" else 0,
        }
        for rule, found in (("name", name_rows), ("grant", grant_rows))
        for row in found
    ]
    await session.execute(delete(FunderAlias))
    if rows:
        await session.execute(insert(FunderAlias).values(rows))
    stats = {
        "names": total,
        "by_name": len(name_rows),
        "by_grant": len(grant_rows),
        "unresolved": total - len(name_rows) - len(grant_rows),
    }
    logger.info("derive_funder_aliases: %s", stats)
    return stats
