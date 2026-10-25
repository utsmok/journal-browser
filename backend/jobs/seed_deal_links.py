"""Seed deals.links from the owner-reviewed deal snapshot (2026-10-22).

Read-only except for the links column. Matches each snapshot deal to its
register row exactly like apply_curation_2026_10_22.py: ESAC id first, then
the unique current openaccess.nl deal of the publisher. Snapshot deals
Twente does not participate in (no register row) are counted and skipped.

Usage: uv run python jobs/seed_deal_links.py
"""

import asyncio
import json
import re
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.models import Deal, Publisher

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_curation_2026_10_22 import ESAC_BY_SLUG  # noqa: E402

SNAPSHOT = (
    Path(__file__).resolve().parents[2]
    / "docs/research/openaccess-nl-current-deals-2026-10-22.json"
)

_EMAIL_PROTECTION = re.compile(r"cdn-cgi/l/email-protection#([0-9a-f]+)", re.I)


def _decode_cf_email(url: str) -> str | None:
    """openaccess.nl obfuscates mailto anchors (Cloudflare email-protection);
    the hex payload is key-XOR encoded and reversibly decodable."""
    m = _EMAIL_PROTECTION.search(url)
    if not m:
        return None
    data = bytes.fromhex(m.group(1))
    return "".join(chr(b ^ data[0]) for b in data[1:])


def clean_links(links: list[dict]) -> list[dict]:
    out: list[dict] = []
    for link in links:
        email = _decode_cf_email(link.get("url", ""))
        if email and "@" in email:
            out.append({"url": f"mailto:{email}", "text": email, "category": "contact"})
        elif "[email" in link.get("text", ""):
            continue  # undecodable obfuscation artifact; a dead cdn-cgi anchor
        else:
            out.append(link)
    return out


async def find_deal(session, slug: str) -> Deal | None:
    esac = ESAC_BY_SLUG.get(slug)
    if esac:
        deal = (
            await session.execute(select(Deal).where(Deal.esac_id == esac))
        ).scalar_one_or_none()
        if deal is not None:
            return deal
    pub = (
        await session.execute(select(Publisher).where(Publisher.openaccess_nl_slug == slug))
    ).scalar_one_or_none()
    if pub is None:
        return None
    rows = (
        (
            await session.execute(
                select(Deal).where(
                    Deal.publisher_id == pub.id,
                    Deal.status == "current",
                    Deal.openaccess_nl_url.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return rows[0] if len(rows) == 1 else None


async def main() -> None:
    deals = json.loads(SNAPSHOT.read_text())["deals"]
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    updated: list[str] = []
    skipped: list[str] = []
    async with maker() as session:
        for deal_json in deals:
            deal = await find_deal(session, deal_json["publisher_slug"])
            if deal is None:
                skipped.append(deal_json["publisher_slug"])
                continue
            deal.links = clean_links(deal_json["links"])
            updated.append(deal_json["publisher_slug"])
        await session.commit()
    await engine.dispose()
    print(json.dumps({"updated": updated, "skipped_not_in_register": skipped}, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
