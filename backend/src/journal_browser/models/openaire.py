"""OpenAIRE graph v3 canon entities."""

from datetime import datetime

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _tstamp


class OpenaireFunder(Base):
    """OpenAIRE graph v3 funder (jobs/harvest_openaire_funders.py).

    ror is the bare lowercase ROR id when the payload yields one, else
    NULL; joins openalex_funders.ror / jisc_funders.ror directly.
    """

    __tablename__ = "openaire_funders"

    openaire_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    short_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    website_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(Text, nullable=True)
    ror: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = _tstamp()
