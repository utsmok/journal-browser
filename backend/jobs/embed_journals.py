"""Backfill 384-dim journal embeddings for similar-journal search.

Text per journal comes from services/embeddings.py: cleaned title + top
OpenAlex topic names + titles of the journal's 3 most cited works (from the
works_stats landing store, one pass). Vectors are L2-normalized, so the
API's cosine-distance ordering is a plain similarity ranking.

Runs on the host (GPU lives there, not in the API container):

  uv sync --extra embeddings
  uv run --extra embeddings python jobs/embed_journals.py [--limit N] [--batch 256]
"""

import argparse
import asyncio

import torch
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.models import Journal
from journal_browser.services.embeddings import MODEL_NAME, embed_text

#: Top cited works per journal for the text. Single pass over the ~28k
#: works_stats rows; journals without stored works simply skip this part.
WORKS_SQL = text(
    """
    WITH latest AS (
        SELECT DISTINCT ON (source_pk)
            source_pk, payload
        FROM source_records
        WHERE source = 'openalex' AND entity_type = 'works_stats'
        ORDER BY source_pk, harvested_at DESC
    ),
    ranked AS (
        SELECT
            payload -> 'primary_location' -> 'source' ->> 'issn_l' AS issn_l,
            payload ->> 'display_name' AS work_title,
            row_number() OVER (
                PARTITION BY payload -> 'primary_location' -> 'source' ->> 'issn_l'
                ORDER BY coalesce(payload ->> 'cited_by_count', '0')::int DESC
            ) AS rn
        FROM latest
        WHERE payload -> 'primary_location' -> 'source' ->> 'issn_l' IS NOT NULL
            AND coalesce(payload ->> 'display_name', '') <> ''
    )
    SELECT issn_l, array_agg(work_title ORDER BY rn) AS titles
    FROM ranked
    WHERE rn <= 3
    GROUP BY issn_l
    """
)

DB_CHUNK = 2000


async def main(limit: int | None, batch: int) -> None:
    engine = create_async_engine(get_settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        works = {row.issn_l: list(row.titles) for row in (await session.execute(WORKS_SQL)).all()}
        rows = (await session.execute(select(Journal.issn_l, Journal.title, Journal.topics))).all()
    if limit:
        rows = rows[:limit]

    texts, keys = [], []
    for issn_l, title, topics in rows:
        content = embed_text(title, topics, works.get(issn_l))
        if content:
            texts.append(content)
            keys.append(issn_l)
    skipped = len(rows) - len(texts)
    print(f"embedding {len(texts)} of {len(rows)} journals (skipped: {skipped} without text)")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"model={MODEL_NAME} device={device}")
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_NAME, device=device)
    vectors = model.encode(
        texts, batch_size=batch, normalize_embeddings=True, show_progress_bar=True
    )

    async with session_factory() as session:
        for start in range(0, len(keys), DB_CHUNK):
            chunk = keys[start : start + DB_CHUNK]
            await session.execute(
                update(Journal),
                [{"issn_l": k, "embedding": vectors[start + i]} for i, k in enumerate(chunk)],
                execution_options={"synchronize_session": False},
            )
            await session.commit()
            print(f"stored {min(start + DB_CHUNK, len(keys))}/{len(keys)}", flush=True)
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="embed only the first N journals")
    parser.add_argument("--batch", type=int, default=256, help="encode batch size")
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.batch))
