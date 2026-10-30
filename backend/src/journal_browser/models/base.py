from datetime import datetime

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _tstamp() -> Mapped[datetime]:
    return mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


# ── Harvest bookkeeping + landing store ────────────────────────────────────
