"""Ingest the cOAlition S Journal Checker Tool public dump into deals tables."""

try:
    from jobs._runner import run_job
except ImportError:  # direct `python jobs/ingest_jct.py` run: jobs/ is sys.path[0]
    from _runner import run_job
from journal_browser.harvest.jct import main

if __name__ == "__main__":
    run_job(main)
