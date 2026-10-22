"""Scrape openaccess.nl publisher deals into the landing store + deals table."""

import logging

try:
    from jobs._runner import run_job
except ImportError:  # direct `python jobs/scrape_openaccess_nl.py` run: jobs/ is sys.path[0]
    from _runner import run_job
from journal_browser.harvest.openaccess_nl import harvest


async def main(session, limit):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    stats = await harvest(session, limit=limit)
    print(
        f"openaccess.nl: {stats['publishers']} publishers, "
        f"{stats['deals_parsed']} deals parsed, "
        f"{stats['needs_curation']} need curation, "
        f"{stats.get('parse_failures', 0)} parse failures"
    )


if __name__ == "__main__":
    run_job(main)
