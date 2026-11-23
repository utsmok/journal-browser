# Collaboration partners: ROR identifiers, OpenAlex first, OpenAIRE fallback

The Partners page lists the organisations a university published with, where they are, which funders and projects appear on the shared works, and the works themselves. This page explains how the pipeline finds a partner, how it counts, and where the data stops.

## What counts as a partner

A partner is an organisation with a ROR identifier that is named as an institution on one of the university's works. Matching uses identifiers only. The job `derive_work_partners` reads the newest stored payload of every confirmed work identity (see [pure.md](pure.md) for the identity match on DOI and other identifiers) and builds the links in two passes:

1. **OpenAlex first.** Every institution on the work's OpenAlex authorships that carries a ROR id becomes a partner of the work. The university itself and the organisations in its OpenAlex lineage are left out, so the university is never its own partner. The corresponding-author flag comes from the same authorships.
2. **OpenAIRE fallback.** A work that the first pass gave no partner takes its partners from its OpenAIRE Graph record: the linked organisations that carry a ROR id, again without the university's own ROR ids.

An affiliation that resolves to no ROR id produces no partner. The page therefore shows fewer partners for works whose affiliations are incomplete or whose organisation has no ROR record. Name matching is not used.

## Where names, countries and map positions come from

The job `harvest_ror` downloads the ROR record (https://ror.org, data under CC0) of every partner that the pipeline only knows from a work payload, and fetches each record again once it is 30 days old, because ROR publishes a new release about once a month. A partner that ROR does not know is tried again after the same 30 days. The record supplies the name, organisation type, country, city, coordinates, parent organisation, other names, profile links and related organisations. When ROR gives an organisation several types, the page shows the most specific one, so a university hospital that also funds research counts as healthcare, not as a funder. The request names the configured contact address in its User-Agent, and the pace stays under ROR's limit of 2000 requests per 5 minutes. A partner without a ROR record keeps the name from the work payload and has no type, country or map position. The map counts those partners separately below itself.

The map tiles come from OpenFreeMap (https://openfreemap.org), which serves OpenStreetMap data without a key or cookies.

## How the numbers are built

The server counts over the whole filter set on every request. Paging and sorting never change the numbers.

| Number on the page | Definition |
|---|---|
| Shared works | Works of the university in the selected years that name the partner |
| Corresponding author | Shared works where the partner lists a corresponding author |
| Author positions | Author positions affiliated with the partner, added over the shared works |
| Share | Shared works divided by all works of the university in the selected years |
| Partners, works with a partner | Distinct partners, and distinct works with at least one partner, in the filter set |
| Circle size on the map | Grows with the logarithm of the shared works, so one very large partner does not shrink all others to dots |

A partner linked only by OpenAIRE carries a note in the list, because its works have no OpenAlex institution to confirm the link.

## Funders and projects

Two sources supply the credits on the shared works:

- **OpenAlex grants.** The funders and awards that OpenAlex lists on a work. OpenAlex records a grant only when it knows the funder or the award id, so a funded work can show no funder.
- **OpenAIRE projects.** The projects of the OpenAIRE Graph linked to a work, with their code, acronym and funder.

OpenAIRE names a project's funder in free text and gives no funder id, while OpenAlex gives an id. The job `derive_funder_aliases` resolves each OpenAIRE funder name to an OpenAlex funder by two rules. The first rule takes the OpenAlex funder whose display name equals the OpenAIRE name, ignoring case. When no name matches, the second rule looks for grant numbers that both sources credit on the same work. The OpenAlex funder with the most such grants wins when it has at least three of them and at least half of all the name's matches. On the UT works the two rules resolve 43 of the 61 OpenAIRE funder names, among them the European Commission by name and NWO through its grant numbers.

A resolved funder is one entry. It shows the OpenAlex name, lists both sources, and counts each work once, even when both sources credit it. An OpenAIRE name that neither rule resolves stays a separate entry marked as OpenAIRE. Projects stay one entry per source. The funder and project filters narrow the shared works to those carrying the selected credit, so opening a partner under a selected funder shows only the works that funder paid for.

## Years

Without a range in the year control at the top of the page, partners are counted from 2020 to the current year. The year control sets any other range.

## Tables and jobs

| Object | Role |
|---|---|
| `work_partners` | One row per work and partner: institution, work, partner ROR id, source payload, corresponding flag, author positions |
| `partner_institutions` | One row per partner ROR id: stub from the payload, completed by the ROR record |
| `funder_aliases` | One row per OpenAIRE funder name that resolves to an OpenAlex funder, with the rule that resolved it |
| `derive_work_partners` | Nightly refresh wave. Rebuilds `work_partners` from the stored payloads for every hosted institution. A rerun gives the same rows |
| `derive_funder_aliases` | Nightly refresh wave, after the partner derive. Rebuilds `funder_aliases` from the stored OpenAlex grants and OpenAIRE projects. Makes no API calls |
| `harvest_ror` | Nightly refresh wave, after the derive jobs. Fetches the ROR records of new partners and refreshes records older than 30 days. `--refresh` re-fetches every record |

The nightly wave ends with the usual prewarm requests, which include the partner list and map so the first visit finds the counts cached.

## Known limits

The limitations registry lists these caveats, and the page shows each one with its source.

| Code | Limit |
|---|---|
| `collaboration-partners` | Works whose affiliations name no ROR id have no partner |
| `openaire-partners` | OpenAIRE supplies partners only for works without an OpenAlex institution |
| `ror-record` | A partner without a ROR record has no type, country or map position |
| `openalex-awards` | OpenAlex records a grant only when it knows the funder or the award id |
| `openaire-projects` | Codes and acronyms are shown as OpenAIRE gives them |

## Adding a facet, filter or column

The list, the map, the partner page and the CSV exports share one filter object, so a new facet needs three small changes:

1. A facet function in `FACETS` in `backend/src/journal_browser/services/collaborations.py`, and the matching field on the filters object and the API parameters. A facet function counts under the other filters but not under its own, so the user can widen the selection.
2. A message with the facet label in `frontend/messages/en/collaborations.json`.
3. One entry in `groups` in `frontend/components/collaborations/facets.tsx`.

A new number on the partner follows the same path: compute it in the service, add it to the `CollaborationPartner` schema, run the API type pipeline described in AGENTS.md, and add the column in `partner-list.tsx`.
