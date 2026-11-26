"""Backfill 384-dim journal embeddings for similar-journal search.

Text per journal comes from services/embeddings.py: cleaned title + top
OpenAlex topic names + titles of the journal's 3 most cited works (from the
works_stats landing store, one pass). Vectors are L2-normalized, so the
API's cosine-distance ordering is a plain similarity ranking.

Uses fastembed (same ONNX model as query-time encoding, CPU-only, runs in
the bootstrap container):

  uv run python jobs/embed_journals.py [--limit N] [--batch 256]

Memory does not grow with the corpus. Journals stream out of the database
through a server-side cursor, and each DB_CHUNK of vectors is stored and
dropped before the next is computed. The one-shot run held every journal
row, every text and every vector at once, on top of the ONNX session's
largest call: 2.6 GB for 40k journals, and the scheduler killed it at
2 GB.

The model call is bounded too. Attention memory grows with texts x the
longest text in tokens, squared, and ONNX Runtime keeps the arena of the
largest calls for the life of the process: one call of 256 texts of 194
tokens took 1.8 GB on its own. A call therefore stops short of
ATTENTION_CELLS. A text's vector does not depend on the call it is
encoded in (whole batches, halves and single texts gave bitwise-equal
vectors), so the cut changes nothing but memory.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.ingest import IngestSession
from journal_browser.models import Journal
from journal_browser.services.embeddings import MODEL_NAME, embed_text

if TYPE_CHECKING:
    from fastembed import TextEmbedding

#: Top cited works per journal for the text. Single pass over the ~28k
#: works_stats rows; journals without stored works simply skip this part.
WORKS_SQL = text(
    """
    WITH latest AS (
        SELECT DISTINCT ON (source_pk)
            payload -> 'primary_location' -> 'source' ->> 'issn_l' AS issn_l,
            payload ->> 'display_name' AS work_title,
            coalesce(payload ->> 'cited_by_count', '0')::int AS cites
        FROM source_records
        WHERE source = 'openalex' AND entity_type = 'works_stats'
        ORDER BY source_pk, harvested_at DESC
    ),
    ranked AS (
        SELECT
            issn_l,
            work_title,
            row_number() OVER (
                PARTITION BY issn_l
                ORDER BY cites DESC
            ) AS rn
        FROM latest
        WHERE issn_l IS NOT NULL
            AND coalesce(work_title, '') <> ''
    )
    SELECT issn_l, array_agg(work_title ORDER BY rn) AS titles
    FROM ranked
    WHERE rn <= 3
    GROUP BY issn_l
    """
)

DB_CHUNK = 2000
#: Journal rows per fetch of the streaming cursor.
STREAM_ROWS = 2000
#: Attention cells (texts x longest text in tokens, squared) one model call
#: may hold. The model's 12 attention heads take about 200 bytes per cell
#: while a call runs, and ONNX Runtime's arena grows in doubling chunks
#: that it keeps for the life of the process, so the bound leaves room for
#: that as well. At this bound a call holds at most 256 texts of 32 tokens
#: (a 12 MB scores tensor) and the run peaks under 1 GB.
ATTENTION_CELLS = 256 * 32**2


def token_slices(lengths: Sequence[int], batch: int, cells: int = ATTENTION_CELLS) -> list[slice]:
    """Consecutive slices covering `lengths`, none longer than `batch` and
    none whose texts times its longest text squared passes `cells`: a
    slice closes before the text that would pass either. A single text
    always fits."""
    slices: list[slice] = []
    start = 0
    longest = 0
    for i, n in enumerate(lengths):
        if i > start and (i - start == batch or max(longest, n) ** 2 * (i - start + 1) > cells):
            slices.append(slice(start, i))
            start = i
            longest = 0
        longest = max(longest, n)
    if start < len(lengths):
        slices.append(slice(start, len(lengths)))
    return slices


def embed_batch(model: TextEmbedding, texts: Sequence[str], batch: int) -> np.ndarray:
    """Unit vectors of consecutive `texts`, one per row, one model call
    per token slice."""
    lengths = [model.token_count(content) for content in texts]
    vectors = np.concatenate(
        [
            np.stack(list(model.embed(texts[part], batch_size=batch)))
            for part in token_slices(lengths, batch)
        ]
    )
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors


async def _store(session: AsyncSession, vectors: list[tuple[str, np.ndarray]]) -> None:
    await session.execute(
        update(Journal),
        [{"issn_l": key, "embedding": vector.tolist()} for key, vector in vectors],
        execution_options={"synchronize_session": False},
    )


async def _stream_journals(
    session_factory: async_sessionmaker[AsyncSession], limit: int | None
) -> AsyncIterator[tuple[str, str | None, Any]]:
    """(issn_l, title, topics) per journal via keyset-paginated short read
    transactions, avoiding long-lived cursors across model inference."""
    last_issn: str | None = None
    yielded = 0
    while limit is None or yielded < limit:
        chunk_limit = STREAM_ROWS if limit is None else min(STREAM_ROWS, limit - yielded)
        stmt = (
            select(Journal.issn_l, Journal.title, Journal.topics)
            .order_by(Journal.issn_l)
            .limit(chunk_limit)
        )
        if last_issn is not None:
            stmt = stmt.where(Journal.issn_l > last_issn)
        async with session_factory() as reader:
            batch_rows = (await reader.execute(stmt)).all()
        if not batch_rows:
            break
        for issn_l, title, topics in batch_rows:
            last_issn = issn_l
            yielded += 1
            yield issn_l, title, topics
        if len(batch_rows) < chunk_limit:
            break


async def embed(
    session_factory: async_sessionmaker[AsyncSession], limit: int | None, batch: int
) -> None:
    """Embed the journals of the database `session_factory` connects to."""
    async with session_factory() as reader:
        works = {row.issn_l: list(row.titles) for row in (await reader.execute(WORKS_SQL)).all()}

    # Run bookkeeping: one harvest_runs/harvest_state pair per embed run
    # (source local / journal_embeddings), so the step shows up in
    # freshness like every other job; the run closes on every path,
    # including "nothing to embed" and errors.
    cleared = 0
    async with session_factory() as session:
        ingest = IngestSession(session)
        await ingest.start_run(
            "local", "journal_embeddings", "embed", {"limit": limit, "batch": batch}
        )
        keys: list[str] = []  # every journal with text, in row order
        texts: list[tuple[str, str]] = []  # the model batch in the making
        vectors: list[tuple[str, np.ndarray]] = []  # waiting for the next UPDATE
        model: TextEmbedding | None = None
        rows = skipped = stored = 0

        async def embed_texts() -> None:
            nonlocal model
            model = model or _load_model()
            embedded = embed_batch(model, [content for _key, content in texts], batch)
            vectors.extend(zip((key for key, _content in texts), embedded, strict=True))
            texts.clear()

        async def store_vectors() -> None:
            nonlocal stored
            await _store(session, vectors)
            await ingest.commit()
            stored += len(vectors)
            print(f"stored {stored}", flush=True)
            vectors.clear()

        try:
            async for issn_l, title, topics in _stream_journals(session_factory, limit):
                rows += 1
                content = embed_text(title, topics, works.get(issn_l))
                if not content:
                    skipped += 1
                    continue
                keys.append(issn_l)
                texts.append((issn_l, content))
                if len(texts) < batch:
                    continue
                await embed_texts()
                if len(vectors) >= DB_CHUNK:
                    await store_vectors()
            if texts:
                await embed_texts()
            if vectors:
                await store_vectors()
            print(
                f"embedded {len(keys)} of {rows} journals (skipped: {skipped} without text)",
                flush=True,
            )

            # Full runs also retire vectors whose text vanished (e.g. a journal
            # lost both title and topics): a stale vector would keep ranking it
            # in semantic results. --limit runs leave the rest of the DB alone.
            if limit is None:
                keyset = set(keys)
                embedded = (
                    (
                        await session.execute(
                            select(Journal.issn_l).where(Journal.embedding.is_not(None))
                        )
                    )
                    .scalars()
                    .all()
                )
                stale = [k for k in embedded if k not in keyset]
                for start in range(0, len(stale), DB_CHUNK):
                    await session.execute(
                        update(Journal)
                        .where(Journal.issn_l.in_(stale[start : start + DB_CHUNK]))
                        .values(embedding=None)
                    )
                if stale:
                    await session.commit()
                    print(f"cleared {len(stale)} stale embeddings", flush=True)
                cleared = len(stale)
            await ingest.finish_run(
                "completed",
                {"embedded": len(keys), "skipped_no_text": skipped, "cleared_stale": cleared},
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            await ingest.finish_run("failed", {"error": str(exc)})
            await session.commit()
            raise


def main(limit: int | None, batch: int) -> None:
    """The job: one engine from the settings, closed with the run."""

    async def run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            await embed(async_sessionmaker(engine, expire_on_commit=False), limit, batch)
        finally:
            await engine.dispose()

    asyncio.run(run())


def _load_model() -> TextEmbedding:
    from fastembed import TextEmbedding

    model = TextEmbedding(model_name=MODEL_NAME)
    print(f"model={MODEL_NAME} backend=fastembed", flush=True)
    return model


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="embed only the first N journals")
    parser.add_argument("--batch", type=int, default=256, help="most texts in one model call")
    args = parser.parse_args()
    main(args.limit, args.batch)
