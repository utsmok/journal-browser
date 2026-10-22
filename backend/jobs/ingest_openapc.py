"""Ingest OpenAPC: land release CSVs, journal APC aggregates, home-institution evidence.

Usage: uv run python jobs/ingest_openapc.py [--limit N]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jobs._runner import run_job  # noqa: E402
from journal_browser.harvest.openapc import main  # noqa: E402

if __name__ == "__main__":
    run_job(main)
