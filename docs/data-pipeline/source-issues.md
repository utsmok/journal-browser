# Upstream source issues

This document lists data problems whose root cause sits in an upstream source. Each entry says what is wrong, gives example identifiers, and states how the browser handles it today. The long-term goal is to report each issue upstream and remove our workaround once the source is correct. Do not add one-off per-record patches to the code; handle a problem with a general rule and record it here.

Status values: `open` (not reported upstream), `reported` (link to the report), `fixed upstream` (workaround can go).

## JCT (cOAlition S Journal Checker Tool)

### The JCT index links the Emerald deal to the Elsevier sheet
- Status: open (found 2026-11-24).
- What happens: the JCT index links `eme2025ukb` (Emerald, 2025 to 2027) to the Elsevier UKB sheet (`gid=684626521`), the same sheet as `els2025ukb`. Our ingest attached 2,572 Elsevier journals to the Emerald deal (deal 363).
- Handling: openaccess.nl is the primary source for NL deals. The ingest withholds a sheet whose journals mostly belong to another publisher, keeps its URL in provenance, and flags the deal for curation. The Emerald contract list (311 journals) stays as the deal's coverage.

### Deal facts that disagree with openaccess.nl
- Status: open.
- What happens: JCT gives `els2025ukb` an end date of 2026-12-31, while openaccess.nl says 2025 to 2027. JCT names publishers by code (`EME`, `ELS`) instead of a publisher name.
- Handling: openaccess.nl wins for publisher, period, status, conditions, caps and links.

### One publisher under several codes
- Status: open.
- What happens: De Gruyter appears as both `degruy` and `dgb`. An older duplicate guard in our reconcile treated these as duplicates and emptied four `degruy*` deals (1772, 2177, 2237, 2452).
- Handling: the guard is removed; the next ingest restores their journal lists.

### Missing column in one agreement sheet
- Status: open.
- What happens: the sheet for `asme2025delft` has no `Journal Name` column, so every JCT run reports `agreements_failed: 1`.
- Handling: the agreement is skipped and logged.

## OpenAPC

### Deal-paid and missing amounts in the same rows as paid amounts
- Status: open (by design upstream; not an error in OpenAPC).
- What happens: articles paid centrally under an agreement appear with cost €0, and other rows have no amount (`NA`). On 2026-11-24, 304 journal periods had a highest amount of €0, 36,142 had no amount, and 54 mixed paid and €0 rows. Using the latest OpenAPC value as "the APC" made 239 journals look free, for example Journal of Membrane Science (ISSN-L 0376-7388), whose list price is €4,460.
- Handling: the list price now comes from OpenAlex `apc_prices`, else the DOAJ maximum. OpenAPC amounts are shown as "paid", and €0 and missing amounts are counted separately and left out of the mean and range.

## OpenAlex: APC prices

### Undated prices in many currencies
- Status: open.
- What happens: `apc_prices` carries no date. 9,695 of 15,623 priced journals list more than one currency, and 8,630 priced journals are not flagged `is_oa`. 19 of the 43 currencies seen have no ECB reference rate (for example UAH, PKR, EGP), covering 334 price entries.
- Handling: we prefer the EUR price, show the harvest year, and convert others at the 1 January ECB rate. Prices without an ECB rate are shown in their own currency and stay out of EUR filters.

## DOAJ

### APC is a maximum, not a typical price
- Status: open (by design upstream).
- What happens: DOAJ publishes the highest APC a journal charges.
- Handling: used only when OpenAlex has no price, and labelled "DOAJ".

## Jisc Open Policy Finder

### Misspelled requirement value
- Status: open.
- What happens: funder policy fields use the value `does_no_mention` instead of `does_not_mention` (37 stored values, for example funder 1387).
- Handling: normalised to `does_not_mention` at ingest and in the API reader.

### One record per programme or assessment exercise, all with one ROR
- Status: open.
- What happens: the European Research Council has four records (31, 1387, 1388, 1389) that share ROR `0472cxd90`. Research England, SFC and DfE NI have one record per assessment exercise. Linking by ROR gave every record the same works, so ERC and "ERC (FP7)" both showed 1,303 Twente works.
- Handling: a record whose name ends in a bracketed programme label gets only the OpenAlex funders for that programme; an unlabelled record stands for the whole funder. Live counts become 1,303 (ERC), 324 (FP7), 1,219 (Horizon 2020) and 227 (Horizon Europe). Assessment-exercise records still show identical counts.

### ERC programme records carry the framework programme's Funder Registry id
- Status: open, not handled.
- What happens: records 1388 and 1389 use the Funder Registry id of the EU framework programme, so 591 of the 1,219 Horizon 2020 works are not ERC grants.

### Duplicate and test records
- Status: open, not handled.
- What happens: Cariplo (568, 1419) and Medr (881, 1428) appear twice. Record 1380 "Funder Test Record" shares its ROR and Funder Registry id with Alzheimer's Research UK (495).

## OpenAlex

### Funder ids in two formats
- Status: open (the variation comes from our own writers mixing OpenAlex fields).
- What happens: funder links stored some OpenAlex funder ids as bare ids (`F4320321800`) and some as full URLs (`https://openalex.org/F4320320300`).
- Handling: normalised to bare ids at write time, with a migration for existing rows.

### Award ids that are not grant numbers (OpenAlex, Crossref, OpenAIRE)
- Status: open.
- What happens: award ids include funding periods (`2007–2013`, 107 rows), programme labels (`HORIZON2020`, 1,012 rows; `H2020`; `France2030`), words without digits (`COMPETE`, `CONICET`, 136 rows), Funder Registry DOIs (`AEI//10.13039/501100011033`, 223 rows), and OpenAIRE placeholders (`unidentified`, 1,734 rows; `0000`).
- Handling: a shape rule in `_valid_project_code` rejects these shapes.

### No ERC funder for Horizon Europe
- Status: open.
- Handling: the Jisc record links to the framework programme funder instead.

### Works without a journal
- Status: open.
- What happens: about 11,400 of 57,200 UT institution works in OpenAlex have no journal venue (2026-11-24). Most are repository items such as theses and reports.
- Handling: shown on the CRIS gaps panels; no workaround.

## Pure (UT research information system)

### Real researcher stored as unconfirmed
- Status: open.
- What happens: "Nicole Renate Loorbach" (9 works, research-group lead profile) is stored with `confirmed=false`. Author search hides unconfirmed people, and the usage logs show visitors searching for her by name.
- Handling: when a query exactly matches an unconfirmed name, author search shows that person with the existing "not verified" hint. The Pure record should be confirmed upstream.

## Scimago

### Hyphen instead of a quartile
- Status: open.
- What happens: 1,597 journals carry the quartile "-" (1,297 journals, 214 conference proceedings, 85 book series), for example 2731-6203, 3005-0758 and 1994-1625.
- Handling: the ingest and the quartile denormalisation treat "-" as no quartile, so the journal shows its newest real quartile or none.

## OpenAlex: titles

### Two titles joined in one
- Status: open.
- What happens: some sources carry two titles joined by "/". Source S2737215817 (ISSN-L 1682-1750, Copernicus Publications) has two different titles; S4210238307 (ISSN-L 2470-0010) reads "Physical review. D/Physical review. D." (58 RUG works). It appears as the top guided finder match for some papers.
- Handling: shown as is.

## Jisc Open Policy Finder: embargoes

### Embargo only in free text
- Status: open.
- What happens: policy 15486 (Remote Sensing of Environment, 0034-4257) has `embargo_months` null on every route, while its note says "Hybrid with 24m acc/ sub except UK Funder 12 months".
- Handling: the journal page prints no embargo line. The page must never say "No embargo" when the field is empty.
