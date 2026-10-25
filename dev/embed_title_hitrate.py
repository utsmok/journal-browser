"""Experiment: if we embed a UT publication's title and rank journals by
cosine distance (same candidate set as semantic_search), how often does the
journal it was actually published in appear in the top 10?

Run: cd backend && uv run python ../dev/embed_title_hitrate.py
"""

import asyncio
import time

import asyncpg
import numpy as np
from fastembed import TextEmbedding
from pgvector.asyncpg import register_vector

DSN = "postgresql://journal:journal@localhost:5433/journalbrowser"
N_SAMPLE = 10_000
TOP_K = 10
SEED = 0.42

# Candidate set mirrors services/search.py semantic_search:
# WORKS_CUTOFF + type journal + proceedings exclusion + has embedding.
CANDIDATE_SQL = """
    SELECT issn_l, embedding FROM journals
    WHERE embedding IS NOT NULL
      AND works_2020_plus > 3
      AND type = 'journal'
      AND browse_excluded IS NOT TRUE
"""

# "Published after 2020" taken literally: year > 2020. retired_at IS NULL
# keeps to currently-shown works.
WORKS_SQL = """
    SELECT title, journal_issn_l FROM ut_works
    WHERE year > 2020 AND journal_issn_l IS NOT NULL AND retired_at IS NULL
    ORDER BY random() LIMIT $1
"""


def normalize(m: np.ndarray) -> np.ndarray:
    return m / np.linalg.norm(m, axis=1, keepdims=True)


async def main() -> None:
    conn = await asyncpg.connect(DSN)
    await register_vector(conn)
    await conn.execute(f"SELECT setseed({SEED})")

    works = await conn.fetch(WORKS_SQL, N_SAMPLE)
    print(f"sampled {len(works)} works (2021+, journal known)")

    t0 = time.time()
    journals = await conn.fetch(CANDIDATE_SQL)
    j_issns = np.array([r["issn_l"] for r in journals])
    j_emb = normalize(
        np.vstack([r["embedding"].to_numpy() for r in journals]).astype(np.float32)
    )
    print(f"loaded {len(journals)} candidate journal embeddings in {time.time() - t0:.1f}s")

    issn_to_row = {issn: i for i, issn in enumerate(j_issns.tolist())}

    t0 = time.time()
    model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    titles = [r["title"] for r in works]
    # query_embed applies the BGE query prompt, same as encode_query().
    q_emb = np.vstack([e.astype(np.float32) for e in model.query_embed(titles)])
    print(f"encoded {len(titles)} titles in {time.time() - t0:.1f}s")

    t0 = time.time()
    hits = misses = unrankable = top1 = 0
    ranks: list[int] = []
    chunk = 512
    for start in range(0, len(q_emb), chunk):
        q = normalize(q_emb[start : start + chunk])
        sims = q @ j_emb.T
        top = np.argpartition(-sims, TOP_K, axis=1)[:, :TOP_K]
        for row, work in enumerate(works[start : start + chunk]):
            target = work["journal_issn_l"]
            trow = issn_to_row.get(target)
            if trow is None:
                unrankable += 1  # target journal not in the ranked corpus
                continue
            order = top[row][np.argsort(-sims[row, top[row]])]
            rank = int(np.flatnonzero(order == trow)[0]) + 1 if trow in order else None
            if rank is not None:
                hits += 1
                ranks.append(rank)
                top1 += rank == 1
            else:
                misses += 1
    print(f"ranked in {time.time() - t0:.1f}s")

    rankable = hits + misses
    print(f"\ntop-1 hits:      {top1}/{rankable} ({top1 / rankable:.1%})")
    print(f"top-{TOP_K} hits:    {hits}/{rankable} ({hits / rankable:.1%}) of rankable works")
    if ranks:
        r = np.array(ranks)
        print(f"hit rank median: {np.median(r):.0f}, mean: {r.mean():.1f}")
    print(
        f"excluded from denominator: {unrankable} works whose journal is not in the "
        "candidate set (no embedding / cutoff / proceedings-excluded)"
    )
    print(f"\nstrict count (auto-fails included): {hits}/{len(works)} ({hits / len(works):.1%})")
    await conn.close()


asyncio.run(main())
