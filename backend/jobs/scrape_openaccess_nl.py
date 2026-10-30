"""Scrape openaccess.nl publisher deals into the landing store + deals table."""

import logging

from journal_browser.harvest.openaccess_nl import harvest
from journal_browser.jobrunner import run_job


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
