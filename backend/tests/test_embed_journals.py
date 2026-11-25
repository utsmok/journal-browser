"""jobs/embed_journals.py: the token-budget batching and the streamed run."""

import numpy as np
from jobs import embed_journals
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.models import HarvestRun, Journal
from journal_browser.services.embeddings import DIMENSION, embed_text

CELLS = 256 * 160**2


def test_token_slices_bound_texts_times_longest_squared():
    """Texts short enough fill a slice of `batch` texts; a text that would
    take its slice over the budget (texts x longest text in tokens,
    squared) opens the next one."""
    assert [(s.start, s.stop) for s in embed_journals.token_slices([10] * 550, 256, CELLS)] == [
        (0, 256),
        (256, 512),
        (512, 550),
    ]

    # The 512-token text would take its batch over the budget, so the batch
    # closes before it; its own batch then holds 25 texts (25 x 512^2 is the
    # budget exactly), and the short rest fills one batch again.
    lengths = [10] * 100 + [512] + [10] * 60
    parts = embed_journals.token_slices(lengths, 256, CELLS)
    assert [(p.start, p.stop) for p in parts] == [(0, 100), (100, 125), (125, 161)]
    # nothing dropped or reordered: the slices walk the texts in order
    assert [lengths[i] for p in parts for i in range(p.start, p.stop)] == lengths
    # a single text always fits, however long
    assert [(p.start, p.stop) for p in embed_journals.token_slices([100_000], 256, 1)] == [(0, 1)]


class _FakeModel:
    """Stands in for fastembed's TextEmbedding: tokens count as characters,
    and a text's raw vector is built from its characters."""

    def token_count(self, text: str) -> int:
        return len(text)

    def embed(self, texts, batch_size):
        for text in texts:
            yield _raw(text)


def _raw(text: str) -> np.ndarray:
    return np.array([ord(text[i % len(text)]) for i in range(DIMENSION)], dtype=np.float32)


def _stored_vector(title, topics) -> list[float]:
    """The job normalizes each batch as one (n, 384) matrix; same here."""
    text = embed_text(title, topics, None)
    assert text is not None
    raw = _raw(text)[None, :]
    return (raw / np.linalg.norm(raw, axis=1, keepdims=True))[0].tolist()


def _read_vector(journal) -> list[float] | None:
    """pgvector returns each float4 as its shortest decimal, read as float64;
    rounding to float32 again gives back the stored value."""
    if journal.embedding is None:
        return None
    return np.asarray(journal.embedding, dtype=np.float32).tolist()


@requires_db
async def test_embed_run_streams_batches_and_retires_stale_vectors(db, db_engine, monkeypatch):
    """Every journal with text gets its vector, including the last partial
    model batch and the last partial storage chunk; a journal without text
    is skipped, and a full run clears the vector of one whose text is
    gone. The run closes with the counts."""
    stale = [0.5] * DIMENSION
    db.add_all(
        [
            journal_factory("0000-0001", title="Alpha"),
            journal_factory("0000-0002", title="Beta", embedding=stale),
            journal_factory("0000-0003", title=None, topics=[{"display_name": "Topology"}]),
            journal_factory("0000-0004", title=None),
            journal_factory("0000-0006", title=None, embedding=stale),  # no text left
            journal_factory("0000-0005", title="Gamma"),
            journal_factory("0000-0007", title="Delta"),
        ]
    )
    await db.commit()
    monkeypatch.setattr(embed_journals, "_load_model", _FakeModel)
    monkeypatch.setattr(embed_journals, "DB_CHUNK", 2)

    # The job builds this from the settings; bound to the test database here.
    await embed_journals.embed(async_sessionmaker(db_engine, expire_on_commit=False), None, 2)
    db.expire_all()

    rows = {
        r.issn_l: _read_vector(r)
        for r in (await db.execute(select(Journal).order_by(Journal.issn_l))).scalars()
    }
    assert rows["0000-0001"] == _stored_vector("Alpha", None)
    assert rows["0000-0002"] == _stored_vector("Beta", None)
    assert rows["0000-0003"] == _stored_vector(None, [{"display_name": "Topology"}])
    assert rows["0000-0005"] == _stored_vector("Gamma", None)
    assert rows["0000-0007"] == _stored_vector("Delta", None)
    assert rows["0000-0004"] is None
    assert rows["0000-0006"] is None
    run = (
        await db.execute(select(HarvestRun).where(HarvestRun.entity_type == "journal_embeddings"))
    ).scalar_one()
    assert (run.status, run.stats["embedded"], run.stats["skipped_no_text"]) == ("completed", 5, 2)
    assert run.stats["cleared_stale"] == 1
