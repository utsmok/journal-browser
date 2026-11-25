# Design plan for comparing journals

Status: this document is a plan and contains no code. It was written on 2026-11-25 against `main` at `1603dc1` and the shortlist branch `fix/shortlist` at `7655d1d`. Figures marked as estimates were not measured.

## Summary of decisions

| Topic | Decision |
|---|---|
| Route | `/{inst}/compare?j=`, with the same parameter as a shortlist share link |
| Number of journals | 2 to 4 |
| Where the selection is stored | A compare tray in `sessionStorage`, one per institution and browser tab |
| Entry points | Browse rows, the shortlist page, the journal page, the finder results, and a shared link |
| Desktop layout | Journals as columns and attributes as rows, in seven groups |
| Phone layout | One block per attribute, with every journal on its own line under the label |
| Differences | A "Best" marker only in rows where an order is meaningful, and a "Can block" marker only for values that can stop open access publishing |
| Indicators | Citations, h-index, SJR and quartile are shown with a DORA sentence and are never ranked |
| API | The batch endpoint from the shortlist branch, plus one query parameter and nine optional fields |
| Analytics | Automatic page views from the start, and a `compare` event in phase 2 |
| Rollout | Phase 0 waits for the shortlist branch, phase 1 ships the feature, phase 2 adds the extras |

## 1. The user problem

An author with a finished manuscript usually has two to four realistic candidate journals. Each candidate has its own long journal page, and the facts that decide between them sit in different places on that page. Deal coverage is a badge at the top, the list price is in the overview, the cap status is in the deal panel, and the policy for green OA is in another panel further down. To compare three candidates, the author opens three tabs and scrolls between them.

The guided finder narrows the choice, but it does not line the candidates up. Each result card explains one journal in about 700 px on a desktop and over 1,000 px on a phone, so three candidates fill several screens.

The compare page puts the candidates side by side and answers one question per row. The author reads across a row and sees where the candidates differ.

The page does not rank journals or name a winner. Prices, caps and policies change, and journal-level indicators say little about one article. The page lays out the facts and leaves the judgement to the author.

## 2. What exists today

The following facts were checked on 2026-11-25 against the code, the live API and read-only queries on the live database. Each one shapes the design.

| Fact | Consequence for the design |
|---|---|
| The shortlist branch adds `GET /api/v1/{inst}/journals/batch`, which returns browse rows for up to 100 ISSN-Ls. It also defines the share parameter `j` and its parser. The branch is not merged. | The compare page reuses both, so its first release waits for that merge. |
| One journal detail response is 108 KB, and 74 KB of it is the list of works that only OpenAlex reports for the institution. With `include_gaps=false` the response is 33 KB. | The compare page must not call the detail endpoint for every journal. |
| Of 177,738 journals, 17,791 have a list price (7,715 of them also have a mean of amounts paid), 3,590 have only a mean of amounts paid, and 155,486 have neither. | "No price" is a normal cell and never becomes a zero. |
| 27,734 journals have a record in the Jisc Open Policy Finder. The other 150,004 have none. | A missing record must not read as "no route allowed". |
| 5 of 553 current deals report cap usage, and 545 are for corresponding authors only. | Most cells for the cap say that no data exists, and the row about who may publish rarely differs. |
| 146,575 journals have no quartile, and 1,597 carry "-" as their quartile. | Both are shown as "Not in Scimago". |
| At Twente, 62,034 journals are on the browsable list, and 10,809 of them are covered by a deal. | Deal coverage differs often, so it is the first row. |

## 3. How many journals

The page compares 2 to 4 journals.

- Four fit on a desktop. The page uses the widest content container (`max-w-screen-2xl` with 16 px side padding), which is 1,333 px wide at a 1365 px viewport. A 200 px label column leaves about 280 px for each journal column, about 250 px of it for text (estimate). That is enough for a title in two lines and a value in one line. A fifth journal would make most values wrap.
- Four fit on a phone. Each attribute block shows one line per journal of about 40 px (estimate), so four journals take about 160 px and the next attribute stays close.
- The limit is cheap to change. The batch endpoint accepts 100 ISSN-Ls, so another limit needs no backend work.

| Journals in the link | What the page does |
|---|---|
| 0 | Shows the empty state with a search box and a link to the browse page. |
| 1 | Shows the single journal and an "Add a journal" column, because one journal cannot be compared. |
| 2 to 4 | Shows the comparison. |
| 5 or more | Compares the first 4 and shows a notice that names the others, each with a link to its journal page. |

## 4. Entry points

### 4.1 The compare tray

The tray holds the journals that a reader is comparing right now. It is stored in `sessionStorage` under `jb_compare_{inst}` as a list of `{issnL, title}` in the order in which they were added, with at most 4 entries. Closing the tab clears it. The shortlist remains the durable list in `localStorage`, and the tray never writes to it.

The compare page reads its journals from the URL, and opening the page sets the tray to the journals in the URL. Tray and URL are therefore always equal on that page. Adding or removing a journal on the page changes both, so a copied link always matches what is on screen.

### 4.2 Controls

| Surface | Control | Behaviour |
|---|---|---|
| Browse rows, desktop | A checkbox in a narrow first column headed "Compare" | Adds the journal to the tray or removes it. The click does not navigate to the journal page. |
| Browse rows, phone | A "Compare" chip at the end of the badges line | Same as the checkbox. It is pressed while the journal is in the tray (`aria-pressed`). |
| Shortlist page | A checkbox per row, with "Compare selected" and "Compare all" above the table | "Compare selected" opens the compare page for the checked journals when 2 to 4 are checked. "Compare all" appears when the list has 2 to 4 journals. |
| Journal page | A "Compare" button beside "Cite" | Adds the journal to the tray (the oldest entry is dropped when the tray is full) and opens the compare page. |
| Finder results | A "Compare" chip on each result card, and "Compare top 3" in the header of the results | The chip toggles the tray. The button sets the tray to the top three results and opens the compare page. |
| Shared link | `/{inst}/compare?j=...` | Opens the compare page for anyone who has the link. |

Three details decide whether these controls work:

- On desktop the browse table is already 1,201 px wide inside a 963 px scroll area, so a narrow first column costs little. The first column must stick to the left edge while the table scrolls sideways.
- On a phone the title link is stretched over the whole row, so the chip needs `relative z-10` to stay clickable, as the shortlist bookmark does.
- On a phone the journal page shows "Cite" alone on its row, so "Compare" fits beside it without a new row. The shortlist branch puts its bookmark button in the same place, so the three buttons can share one container after that branch merges.

### 4.3 The tray bar

Browse and finder pages show a bar fixed to the bottom edge while the tray holds at least one journal.

```
+----------------------------------------------------------------+
| Compare  (A) Remote Sensing of Environment  (B) ISPRS Journal  |
| 2 of 4               [ Compare now ]  [ Clear ]                |
+----------------------------------------------------------------+
```

"Compare now" is enabled from 2 journals and opens the compare page for the tray. "Clear" empties the tray. The bar shifts the feedback button up by the height of the bar, because that button floats over the bottom right corner. The bar is not shown on the compare page itself.

## 5. The page

The route is `/{inst}/compare`, for example `/ut/compare?j=0034-4257,0924-2716,1932-6203`.

| Aspect | Decision |
|---|---|
| The `j` parameter | The `j` parameter has the same format as in a shortlist share link. Both pages use `parseShareIssns` from `frontend/lib/shortlist.ts`, which splits on commas, normalises each part as an ISSN-L, drops parts that are not ISSN-Ls, removes duplicates and keeps the order. |
| "Copy link" | "Copy link" copies the page URL with the clipboard code of the shortlist page, including the fallback that shows the link in a read-only input when the clipboard is blocked. |
| The institution | The heading names the institution, for example "Compare journals at University of Twente". Deal coverage and the count of works by the institution depend on it. The institution menu links to the home page of the other institution, so the page must say which institution's data is on screen. |
| The funder | The selected funder applies. The existing funder picker stores it in `localStorage`, so a funder chosen on the browse page also applies here. |
| The years | The control for the year range, as on the browse page, applies to the row about works by the institution. A shared link carries neither the funder nor the years (open question 3). |
| Rendering | The page is a client component that renders its table after hydration, as the shortlist page does, because the tray is read from `sessionStorage`. |

The page is built in this order:

1. The heading, with "Copy link", "Print" and one line that names the institution.
2. A line with the number of journals and the selected funder, with a "Change" link that opens the funder picker.
3. The legend for the two markers.
4. A header block for each journal, and below them the seven groups.

## 6. What to compare

Seven groups, and each one is a question that an author asks. The order follows the decision. Publishing for free comes first, because deal coverage differs often and decides the price. Context about the journal comes last.

Conditions and policy texts come from openaccess.nl and the Jisc Open Policy Finder. The page shows them as the source wrote them. Nobody shortens them by hand or with a language model, because a shortened condition can change who may publish for free.

### 6.1 Can I publish open access for free?

| Row | What the cell shows | Marker | Data |
|---|---|---|---|
| Deal coverage | The publisher and duration of each deal that covers the journal. Without a deal, "No deal for {institution}". | Best when covered | `deal_covered`, `deals[]` |
| Cap | "Cap reached, {used} of {total} used in {year}" or "Cap not reached, {used} of {total} used in {year}". When the deal reports no usage, "No cap data". | "Can block" when reached | `deal_cap_reached`, new `deals[].cap_usage` |
| Who may publish for free | "Corresponding author must be at {institution}" or "Any author". | None | New `deals[].corresponding_authors_only` |
| Article types | The list of publication types in the deal, cut to one line, with "Show full text". | None | Deal endpoint, loaded when the reader expands the row |
| Conditions | The summary of the deal, with "Show full conditions". | None | Deal endpoint, loaded when the reader expands the row |

### 6.2 What will it cost?

| Row | What the cell shows | Marker | Data |
|---|---|---|---|
| Cost to publish open access | The label that the finder already produces, such as "€0 (Covered by {institution} deal)", "{price} APC (list price)" or "APC unknown". | Best for the lowest amount, only when every journal has an amount in euro | New `estimated_cost_label` and `estimated_cost_eur` |
| List price | "{price} {currency} from OpenAlex, harvested {year}". When the price was converted, the original amount follows in brackets. Without a list price, "No list price". | None | Existing `apc_source`, `apc_price`, `apc_currency`, `apc_original_price`, `apc_original_currency` and `apc_year` |
| Amounts paid | "€{mean} on average for {n} paid articles in {year}, reported to OpenAPC", with the lowest and highest amount, and "{n} articles cost €0 under a deal" when that count is above zero. Without records, "No payment records". | None | Existing `apc_stats[]` |

The first row is an estimate. The other two are the evidence behind it. Three rules keep the group honest:

1. A list price and a mean of amounts paid are different things, so they get separate rows and are never compared with each other. One journal can show a list price and a lower mean of amounts paid.
2. The mean covers only articles with an amount above €0. Articles that cost €0 under a deal are counted separately, and articles without an amount are not in the mean.
3. The amounts come from OpenAPC, a shared dataset. They show what all contributing institutions reported, not what {institution} paid.

The row for the list price names the year of the harvest and not the year of the price, because the sources do not date their prices. `apc_year` is the year in which the source was harvested.

### 6.3 Does my funder's policy allow it?

| Row | What the cell shows | Marker | Data |
|---|---|---|---|
| Funder fit | "Compliant", "Check" or "Not compliant", each with the reasons from the engine that evaluates the policy of the funder. When the funder's policy is text only, "Policy is text only. Check it yourself." | Best for compliant, "Can block" for not compliant | `funder_fit`, which needs the new `funder` parameter |

With no funder selected, the group shows one line, "Choose your funder to check its policy against each journal", with the existing funder picker.

The engine in `backend/src/journal_browser/services/funder_fit.py` returns four tiers. A deposit that the policy prohibits gives "Not compliant". Gold or diamond open access, and any deal, give "Compliant". Any green route gives "Check". A journal with no route gives "Not compliant". A policy that is text only gives no tier.

### 6.4 Is my manuscript in scope?

| Row | What the cell shows | Marker | Data |
|---|---|---|---|
| Topics | The top three OpenAlex topics with their work counts. | None. A topic that two or more journals share gets a light tint. | New `topics` |
| Publication type and language | "Journal", "Book series" or "Conference series", and the languages of the works. | None | Existing `pub_type`, `language` |

The browse list can contain book series and conference series, because `pub_type` allows them. The header block of each journal repeats the type, so nobody compares a book series with a journal by mistake.

### 6.5 Can I archive my own copy?

| Row | What the cell shows | Marker | Data |
|---|---|---|---|
| Best route for green OA | "Published version", "Accepted manuscript" or "Submitted manuscript". When the policy forbids a deposit, "Open access deposit prohibited". When the policy allows no route, "No route allowed". When the journal has no record, "Not in the Jisc Open Policy Finder". | Best for the most permissive route, "Can block" for prohibited or no route | Existing `green_oa`, new `oa_prohibited` |
| Embargo on that route | "{n} months", or "No embargo stated in the policy record". | None | New `green_oa_embargo_months` |

"Not in the Jisc Open Policy Finder" is missing data. It is never ranked and never marked, because 150,004 journals have no record there.

The embargo cell says what the record says. The Jisc record for Remote Sensing of Environment (ISSN-L 0034-4257) has no embargo months on any route, although its note mentions 24 months. The cell must therefore not claim that there is no embargo.

### 6.6 How is the journal regarded?

| Row | What the cell shows | Marker | Data |
|---|---|---|---|
| Citations per paper | The two-year mean citedness from OpenAlex. | Never | Existing `twoyr_mean_citedness` |
| h-index | The h-index of the journal. | Never | New `indicators.h_index` |
| Works per year | The mean number of works per year over the three latest years with data. | Never | New `indicators.works_per_year` |
| Scimago | "SJR {value} ({year}), best quartile {quartile}" or "Not in Scimago". | Never | New `indicators.sjr` and `indicators.sjr_year`, existing `quartile` |

The heading of this group carries one sentence, and no row in the group gets a marker or a sort control. Proposed wording: "DORA recommends judging research on its own merits instead of on the journal it appears in. Use these numbers as context."

A best quartile is the best quartile that a journal reaches in any of its Scimago categories. Categories differ, so Q1 in one category is not Q1 in another, and a quartile alone cannot rank two journals. Of the 177,738 journals, 146,575 have no quartile and 1,597 carry "-" instead of one. The compare page shows both as "Not in Scimago" and does not reuse `QuartileBadge`, which prints a badge for "-".

### 6.7 Has {institution} published here before?

| Row | What the cell shows | Marker | Data |
|---|---|---|---|
| Works by {institution} | The number of works by {institution} in the journal, for the selected year range. | None | Existing `works` |

A journal where colleagues have published is one that the library knows. A higher count is not better, so the row gets no marker. Phase 2 adds a small bar for each year.

## 7. Showing differences

Two markers show where the journals differ. Both carry a word, so the meaning never depends on colour.

| Marker | Appearance | Where it appears |
|---|---|---|
| Best | A check icon and the word "Best" in the deal emerald (`oa-deal`) | On every journal that has the best value in a row with a meaningful order |
| Can block | A warning icon and the words "Can block" in alert red | On every journal with a value that can stop open access publishing |

| Rule | Wording |
|---|---|
| 1 | Each row in section 6 declares whether an order is meaningful. Citations, h-index, works per year, SJR and quartile are never ordered. |
| 2 | A marker appears only when at least two journals have a known value and those values differ. When all known values are equal, the row has no marker. |
| 3 | Unknown values are left out of the order. They show their own wording, such as "APC unknown" or "No cap data", and never receive a marker. |
| 4 | "Best" marks every journal that shares the best value. On the cost row it appears only when every journal has an amount in euro, because an unknown price might be lower. |
| 5 | "Can block" is reserved for three cases: a reached cap, a policy that prohibits a deposit or allows no route, and a funder fit of "Not compliant". The highest price never gets it. |

A legend above the table explains both markers in words. In phase 2, a toggle "Only differences" hides the rows in which all known values are equal.

Two alternatives are ruled out. A total score or a rank order needs weights that the tool cannot defend, and one number would hide them. A colour scale per cell suggests an order in rows that has none, and it fails in dark mode and on paper.

## 8. Layout

### 8.1 Desktop, 1024 px and wider

The table has journals as columns and attributes as rows. The label column is 200 px wide and sticks to the left edge when the table scrolls sideways. Table text uses the size that DESIGN.md sets for tables (0.875rem).

From 1024 px to 1365 px the journal columns get narrower. At 1024 px four journals get about 198 px each (estimate), which wraps a long title to three lines and keeps every value readable.

The header block of each journal holds, from top to bottom:

1. The journal letter in a muted pill, the title as a link to the journal page, and a "Remove" button.
2. The publisher and the ISSN-L.
3. The access lockup and the deal badge from the browse table, reused without changes.
4. The publication type, such as "Journal" or "Book series".

With fewer than four journals, the first empty column is a dashed "Add a journal" column with a search box. Suggestions come from the existing search endpoint, `GET /{inst}/journals?q=...&limit=5&include_facets=false`.

Each group heading is a row that spans all columns. The reader can collapse a group, and all groups are open by default.

Wireframe at 1365 px with three journals:

```
+-----------------------------------------------------------------------------------------------------------+
| [site header: brand, institution menu, navigation, theme toggle]                                          |
| Compare journals at University of Twente                                              [Copy link] [Print] |
| 3 journals. Funder: European Commission [Change]                                                          |
| [v] Best value for this attribute                                    [!] Can block open access publishing |
|                                                                                                           |
+-----------------------------------------------------------------------------------------------------------+
|                    | A  Remote Sens. of Env. [x]  | B  ISPRS J. of Photo. [x]    | C  PLOS ONE [x]        |
|                    | Elsevier. ISSN-L 0034-4257   | Elsevier. ISSN-L 0924-2716   | PLOS. ISSN-L 1932-6203 |
|                    | HYBRID  DEAL  Q1             | HYBRID  DEAL  Q1             | GOLD  {quartile}       |
|                    | Journal                      | Journal                      | Journal                |
+--------------------+------------------------------+------------------------------+------------------------+
| v  1. Can I publish open access for free?                                                                 |
| Deal coverage      | [v Best] Elsevier, {years}   | [v Best] Elsevier, {years}   | No deal for {inst.}    |
| Cap                | No cap data                  | No cap data                  | No deal                |
| Who may publish    | Corresponding author must    | Corresponding author must    | Any author             |
| for free           | be at {inst.}                | be at {inst.}                |                        |
| Article types  [v] | Full Length Article, Review  | {article types}              | {article types}        |
|                    | Article, ...                 | [Show full text]             | [Show full text]       |
|                    | [Show full text]             |                              |                        |
| Conditions     [v] | {summary of the deal}        | {summary of the deal}        | Not under a deal       |
|                    | [Show full conditions]       | [Show full conditions]       |                        |
+--------------------+------------------------------+------------------------------+------------------------+
| v  2. What will it cost?                                                                                  |
| Cost to publish    | [v Best] EUR 0 (covered by   | [v Best] EUR 0 (covered by   | EUR {price} (list)     |
| open access        | the {inst.} deal)            | the {inst.} deal)            |                        |
| List price         | EUR {price} from OpenAlex,   | USD {price} from OpenAlex,   | No list price          |
|                    | harvested {year}             | harvested {year}, about      |                        |
|                    |                              | EUR {price})                 |                        |
| Amounts paid       | EUR {mean} on average for    | No payment records           | No payment records     |
|                    | {n} paid articles in {year}  |                              |                        |
+--------------------+------------------------------+------------------------------+------------------------+
| v  3. Does my funder's policy allow it?                                                                   |
| Funder fit         | [v Best] Compliant           | [v Best] Compliant           | [!] Not compliant      |
|                    |                              |                              | No route allowed       |
| (Groups 4 to 7 follow in the same grid.)                                                                  |
+-----------------------------------------------------------------------------------------------------------+
```

### 8.2 Phone, 390 px

Recommendation: one block per attribute.

Each block has the attribute label on top and one line per journal under it. Each line starts with the journal letter.

```
+------------------------------------------------+
| [site header]                                  |
| Compare journals at University of Twente       |
| [Copy link] [Print]                            |
| 3 journals. Funder: European Commission        |
| [Change funder]                                |
| [v] Best value for this attribute              |
| [!] Can block open access publishing           |
+------------------------------------------------+
| STICKY STRIP, stays on top while scrolling     |
| [1. Can I publish open access for free?  v]    |
| A  Remote Sens.   B  ISPRS J.   C  PLOS        |
+------------------------------------------------+
| A  Remote Sensing of Environment           [x] |
|    Elsevier. ISSN-L 0034-4257                  |
|    HYBRID  DEAL  Q1  Journal                   |
| B  ISPRS Journal of Photogrammetry and         |
|    Remote Sensing                          [x] |
|    Elsevier. ISSN-L 0924-2716  HYBRID  DEAL    |
| C  PLOS ONE                                [x] |
|    PLOS. ISSN-L 1932-6203  GOLD                |
| [+ Add a journal]                              |
+------------------------------------------------+
| v  1. Can I publish open access for free?      |
| Deal coverage                                  |
|    A  [v Best] Elsevier, {years}               |
|    B  [v Best] Elsevier, {years}               |
|    C  No deal for {inst.}                      |
| Cap                                            |
|    A  No cap data                              |
|    B  No cap data                              |
|    C  No deal                                  |
| Who may publish for free                       |
|    A  Corresponding author must be at {inst.}  |
|    B  Corresponding author must be at {inst.}  |
|    C  Any author                               |
| Article types                            [v]   |
|    A  Full Length Article, Review Article, ... |
|    B  {article types}                          |
|    C  {article types}                          |
+------------------------------------------------+
| v  2. What will it cost?                       |
| Cost to publish open access                    |
|    A  [v Best] EUR 0 (covered by the           |
|       {inst.} deal)                            |
|    B  [v Best] EUR 0 (covered by the           |
|       {inst.} deal)                            |
|    C  EUR {price} (list price)                 |
| List price                                     |
|    A  EUR {price} from OpenAlex,               |
|       harvested {year}                         |
|    B  USD {price} from OpenAlex,               |
|       harvested {year}, about EUR {price})     |
|    C  No list price                            |
| Amounts paid                                   |
|    A  EUR {mean} on average for {n} paid       |
|       articles in {year}                       |
|    B  No payment records                       |
| (Groups 3 to 7 follow in the same way.)        |
+------------------------------------------------+
```

In both wireframes "[v]" is the check icon, "[!]" is the warning icon and "[x]" is the "Remove" button. Text in braces stands for values from the API. The journal names are real, and the values are illustrative.

The reasons for this layout:

- Values that belong together stay together. The reader compares the values for one attribute inside one block and holds nothing in memory.
- Alignment is safe. A deal name runs over two lines and "No cap data" takes one. Cards that are swiped sideways do not share a baseline, so the reader loses track of which value belongs to which attribute.
- Nothing scrolls sideways at 390 px. Journal columns would need a sideways scroll, and the attribute label would scroll out of view.
- The look is already in the product. Below 768 px the shortlist page shows each value under a muted label. The blocks reuse that pairing of label and value, with another grouping.

The price is that the journal titles are not on screen while the reader is inside a block. A strip that sticks to the top of the screen compensates. It holds a select for the question, which jumps to the group, and the journal letters with short titles. Tapping a letter opens a menu with "Open journal page" and "Remove".

The layout is the same `<table>` in the DOM at every size. Below 1024 px, CSS lays each row out as a block, with the label above and the cells under it. Screen readers therefore get one structure on every device (section 11).

Swipe with one card per journal is ruled out for phase 1. It shows one journal at a time, so comparing three journals means that the reader memorises values while swiping. It hides the other journals from mouse and keyboard users, and it gets harder with every journal added. A variant that pins the first journal and swipes the rest compares one pair at a time and has the same keyboard problem. The swipe view can return in phase 2 as an option, if readers ask for a page that shows one journal in full.

## 9. Print

| Topic | Decision |
|---|---|
| Orientation | A4 landscape with four journals, and portrait with two or three. The global print rule in `frontend/app/globals.css` sets A4 portrait with 18 mm margins for every page. The compare page adds a page rule with a name for landscape (`@page compare { size: A4 landscape }`). This plan did not test named pages in a browser. The implementation must check Chrome, Firefox and Safari. Portrait is the fallback where a browser ignores the rule. |
| Hidden | The site header, the footer, the tray bar, the feedback button, "Copy link", "Print", "Remove", "Add a journal" and the "Change" link of the funder line. |
| Kept | The heading with the institution, the selected funder, the date of printing and the URL of the page. |
| Markers | Printed as the words "Best" and "Can block", so a printout in black and white keeps their meaning. |
| Page breaks | The row with the journal headers repeats on every page (`thead`). A row is never split over two pages, and a group heading stays with its first row. |
| Expanded text | Text that the reader expanded before printing is printed in full. A collapsed row prints its one line. |
| Colours | The print rules override the theme tokens to the paper palette, as the print stylesheet for docs does, so dark mode prints on white. |
| Start | The "Print" button calls `window.print()`. The print command of the browser gives the same result. |

## 10. Empty and error states

| State | When it happens | What the page shows |
|---|---|---|
| No journals | `j` is missing or empty | "Choose journals to compare", the search box, and a link "Browse journals" to `/{inst}`. |
| One journal | `j` holds one ISSN-L | The journal's header block and all its values in one column, plus the "Add a journal" column with the text "Add one more journal to compare". |
| Unknown ISSN-L | An ISSN-L in `j` is not in the browsable list | The endpoint returns it in `missing`. A notice says "One journal in the link is not in the list for {institution}", and the page compares the rest. |
| More than four | `j` holds five or more ISSN-Ls | The first four are compared, and a notice names the others with a link for each. |
| Invalid `j` | `j` holds text that is not an ISSN-L | The parser drops every part that is not an ISSN-L. If nothing is left, the empty state appears. |
| Loading | The batch request is running | A skeleton of the table with the journal letters, and the status text "Loading comparison". |
| Failed request | The endpoint returns an error or times out | "The comparison could not be loaded." with a "Try again" button. |
| Stale funder | The stored funder id returns 404 | The page loads the table without a funder. Group 3 says "Your saved funder could not be found. Choose another." with the funder picker. |
| Lazy text fails | A deal text or a policy does not load | The row keeps its summary and shows "Full text unavailable" in place of the expansion. |
| No JavaScript | The page cannot run its script | The HTML from the server holds the heading, the sentence "The comparison loads in your browser." and a link to the browse page. |

## 11. Accessibility

| Requirement | How the page meets it |
|---|---|
| Table structure | One real `<table>`. The header cells of the journals use `<th scope="col">` and every attribute label is `<th scope="row">`, so a screen reader announces the journal and the attribute for each cell. |
| One structure at every size | The phone layout is CSS only. The DOM stays the same table, so a screen reader gets the same structure on every device. |
| Colour and contrast | Every colour comes from the token block. Each marker has a visible word, so colour is never the only signal. |
| Icons | The check icon and the warning icon are `aria-hidden`. The words "Best" and "Can block" are read instead. |
| Focus | Every control has the 2 px orange focus ring of the token block. Focus moves through the header blocks of the journals from left to right, then through the rows from top to bottom. |
| Expand and collapse | The buttons for groups and for long texts carry `aria-expanded` and `aria-controls`. |
| Remove | After "Remove", focus moves to the heading of the page, and a status line announces "Removed {title}". |
| Messages | Loading and notice messages use `role="status"`. The error for a failed request uses `role="alert"`. |
| Touch targets | Controls keep the 40 px height of the design system's buttons, above the 24 px minimum of WCAG 2.2 (success criterion 2.5.8). |
| Motion | The page adds no animation. The access lockup already stops under `prefers-reduced-motion`. |
| Zoom | The layout holds at 200 % zoom, because the block layout takes over below 1024 px. |
| Language | Group 2 explains the abbreviation once, under its heading. "APC is the article processing charge that a journal asks for an open access article." |

## 12. API

### 12.1 The endpoint

The page reuses `GET /api/v1/{inst}/journals/batch` from the shortlist branch. It takes `issn_l` (at most 100 values, then 422), `year_from` and `year_to`, and it returns `{items, missing}`. Each item is a browse row (`JournalListItem`) with two additions. `deals[]` holds the id, the name of the publisher and the duration text of each deal. `green_oa` holds the best route, `none` or null.

### 12.2 New query parameter

| Parameter | Type | Meaning |
|---|---|---|
| `funder` | integer, optional | The id of a funder in the Jisc Open Policy Finder, with the same meaning as on the list and detail endpoints. When it is present, each item carries `funder_fit`. An unknown id returns 404, as on those endpoints. The route already has the helper `_funder_policy` for that check. |

### 12.3 New optional fields on `JournalBatchItem`

All nine are nullable, so the shortlist page can ignore them.

| Field | Type | Used for |
|---|---|---|
| `estimated_cost_label` | string | The row "Cost to publish open access" |
| `estimated_cost_eur` | number or null | The "Best" marker on that row |
| `indicators` | `{h_index, sjr, sjr_year, works_per_year}` or null | Group 6 |
| `topics` | list of `{display_name, count}`, the top three | Group 4 |
| `oa_prohibited` | boolean or null | Separates "deposit prohibited" from "no route" in group 5 |
| `green_oa_embargo_months` | number or null | The row "Embargo on that route" |
| `deals[].corresponding_authors_only` | boolean or null | The row "Who may publish for free" |
| `deals[].cap_usage` | list of usage entries or null | The row "Cap" |
| `deals[].summary` | string or null | The row "Conditions" |

The rows "List price" and "Amounts paid" use fields that the item already has (`apc_source`, `apc_price`, `apc_original_price`, `apc_original_currency`, `apc_year` and `apc_stats[]`). Nothing is added for them.

### 12.4 One function for the cost label

The finder builds its cost label in `_extract_apc_and_cost` in `backend/src/journal_browser/services/recommend.py`. The plan moves the label part into a new leaf module, `services/apc_cost.py`, and calls it from `recommend.py` and from `services/search/batch.py`. The reason is the import rule in `backend/pyproject.toml`. Sibling modules import each other in one direction only, and `recommend.py` already imports `services.search`. So `services/search/batch.py` must not import `recommend.py`.

A test pins that both callers return the same label for the same journal.

### 12.5 Long texts

Two rows load their full text only when the reader expands them.

| Text | Endpoint | Size |
|---|---|---|
| Article types and conditions of a deal | `GET /{inst}/deals/{deal_id}` | About 5 KB per deal |
| Full policy for green OA | `GET /{inst}/journals/{issn_l}?include_gaps=false` | 33 KB per journal |

### 12.6 Alternatives ruled out

- Four detail requests. They weigh 132 KB and run heavier queries, for data that the table mostly does not use.
- A new `compare` endpoint. It would repeat the batch projection and add a second convention for the same job.

### 12.7 Schema files

After the backend change, regenerate `openapi.json` with `uv run python scripts/dump_openapi.py` and `frontend/lib/api-types.ts` with `npm run generate`. Commit both with the backend change.

## 13. Performance

| Item | Plan |
|---|---|
| Requests | One batch request loads the page. Each expanded deal row adds one request of about 5 KB, and each expanded policy adds one of 33 KB. |
| Payload | About 10 KB for four journals (estimate), against 132 KB for four detail responses. |
| Switching data | TanStack Query with `keepPreviousData` keeps the old table on screen when a journal is removed or the funder changes, until the new response arrives. |
| Query key | `(inst, ordered ISSN-Ls, year_from, year_to, funder id)`. |
| First paint | The heading renders on the server. The table renders after hydration and the first response, as on the shortlist page. |
| Markers | Pure functions over at most four items. They need no memoisation. |
| Tray | A small store in `frontend/lib/compare-tray.ts`, with the same shape as the shortlist store in `frontend/lib/shortlist.ts`. It reads `sessionStorage` once per page. |

## 14. Internationalisation

- The frontend uses next-intl with one locale (`en`) and one message file per namespace. Each namespace is registered in `frontend/i18n/request.ts` and in `clientNamespaces` in `frontend/app/layout.tsx`.
- The compare page adds the namespace `compare` (`frontend/messages/en/compare.json`) for its headings, the labels of the rows, the markers and the states. It reuses keys from `common` for badges and buttons, and the number formatting of the journal page for prices and counts.
- Strings that the shortlist page also uses, such as "Copy link" and the feedback after copying, move to `common.json` when the shortlist branch merges. Neither page then owns them alone.
- The backend returns some text in English only: the funder reasons, the cost label and the deal texts from openaccess.nl. The page shows them as they arrive. Translating them is outside this plan.

## 15. Analytics events

Phase 1 adds no event. The tracker records a `page_view` for `/ut/compare`, and it stores the pathname without the query string (`frontend/lib/usage/tracker.ts`). The ISSN-Ls of a comparison therefore never reach the usage table, and the number of compare page views is visible from the first day.

Phase 2 adds a `compare` event. The check constraint `ck_usage_event_type` in `backend/src/journal_browser/models/app_data.py` allows only `page_view`, `search` and `error`, and the admin summary has one column per day for those three. The new event therefore needs a migration that extends the constraint and restores it on downgrade. The admin panel also needs a section for the event.

| Field | Value |
|---|---|
| `type` | `compare` |
| `action` | `view`, `add`, `remove`, `copy_link`, `print`, `toggle_differences`, `expand` |
| `journal_count` | 1 to 4 |
| `source` | `browse`, `shortlist`, `journal_page`, `finder`, `link` |
| `funder_selected` | `true` or `false` |
| Never recorded | ISSN-Ls, journal titles, funder ids |

## 16. Test plan

### 16.1 Backend

The batch tests from the shortlist branch (`test_journal_batch.py`) grow by four cases.

| Case | What it checks |
|---|---|
| `funder` parameter | Each item carries `funder_fit` for a valid funder. An unknown id returns 404. Without the parameter the field is absent, as on the list endpoint. |
| Cost fields | `estimated_cost_label` and `estimated_cost_eur` for four journals: one covered by a deal, one with a list price in dollars, one with only a mean of amounts paid, and one without any price. |
| Policy and indicator fields | `oa_prohibited`, `green_oa_embargo_months`, `indicators` and `topics` for a journal with a Scimago record and a Jisc record, and for one without either. |
| Missing | Unknown ISSN-Ls come back in `missing`, and known ones in `items` in request order. |

A separate test for the cost rule pins that `recommend.py` and `apc_cost.py` give the same label for one fixed set of journals.

### 16.2 Frontend

Vitest (`cd frontend && npm run test`):

| File | What it checks |
|---|---|
| `compare-tray` | Add and remove. The limit of four drops the oldest entry. Each institution has its own tray. A new tab starts empty. |
| `compare-url` | The parser and the link builder for duplicates, invalid parts and more than four journals. |
| `compare-model` | Every rule in section 7, as a table of input rows and expected markers. It includes unknown values, equal values, and the cost row with one unknown price. |
| `compare-view` | Each state in section 10, the legend text, the marker words, and `aria-expanded` on the group headings. |
| Entry points | The browse checkbox and chip change the tray without navigating. The button on the journal page opens the compare page with the ISSN-Ls of the tray. The button in the finder opens it with the top three. |

### 16.3 Manual, before release

- Check 1365 by 768 and 390 by 844, in light and in dark mode.
- Check the print preview in Chrome, Firefox and Safari, with two, three and four journals.
- Use the keyboard only. Add three journals on the browse page, open the compare page, expand a row, remove a journal and copy the link.
- With a screen reader (NVDA or VoiceOver), read one cell and confirm that it announces the journal and the attribute.

## 17. Phased rollout

| Phase | Content | Depends on |
|---|---|---|
| 0 | Merge the shortlist branch. It brings the batch endpoint, the `j` parameter, its parser and the clipboard code. | Shortlist slice |
| 1 | The first release has the route, the tray, the four entry points, the seven groups, the markers, both layouts, the link for sharing, print, the states, i18n and the tests. | Phase 0 |
| 2 | Extras, in this order: the "Only differences" toggle, a bar per year in group 7, the share of open access works by {institution} in group 7, the `compare` event with its migration and its section in the admin, a link that opens the same journals for the other institution, CSV export with the formula guard of the shortlist, and the topic match of the finder in group 4. | Usage figures from phase 1 |

Phase 1 needs no feature flag. The page is new, the added controls change no existing behaviour, and the frontend has no flag mechanism.

Comparisons saved across devices are not planned. The product has no accounts, and adding them is a different decision.

## 18. Assumptions made without an interview

The plan was written from a written brief, without an interview with the owner or with authors. It rests on three assumptions.

- Authors compare journals that they have already found. The page does not help to find candidates. That stays the job of the browse page and of the finder.
- Deal coverage and cost come first in the order of the groups, because they decide what an author pays. The order is a list in one component and is cheap to change.
- A reader compares journals of one institution in one tab. The tray is therefore per institution and per tab (open question 1).

If one of the first two is wrong, only the order and the scope of the page change. The third one is open question 1.

## 19. Open questions for the owner

| # | Question | Recommendation |
|---|---|---|
| 1 | Should the tray exist beside the shortlist, or should compare work only from the shortlist page? Two lists can confuse a reader about which one is in use. | Keep the tray. It is per tab, holds at most four journals and clears itself. |
| 2 | Is the maximum four journals, or three? Four fits at 1365 px. Three gives wider columns and shorter blocks on a phone. | Four. |
| 3 | Should a shared link carry the funder and the years? The link would show the sender's view exactly, but it gets longer and it carries a funder choice. | Not in phase 1. |
| 4 | May the `compare` event record ISSN-Ls? They would allow a list of the most compared journals in the admin. | No. Counts only, as in section 15. |
| 5 | Should the row "Cost to publish open access" reuse the label of the finder? A new label could also show the status of the cap. | Reuse it, so that the finder and the compare page say the same thing about one journal. |
| 6 | Should group 4 show the topic match of the finder? Only readers who arrive from the finder have a manuscript to match. | Phase 2. |
| 7 | Twente has `ut_authorship` (faculties and research groups). Does Groningen have an equivalent, and should the compare page show it? | Not until the data exists for both institutions. |
| 8 | Should a shared link show the journal titles in the preview of a chat app? That needs the titles in the HTML from the server. | Phase 2, if usage shows that links are shared often. |
| 9 | Is landscape print acceptable for four journals? | Yes. Portrait cannot hold four columns. |
| 10 | Should the section for usage in the admin arrive together with the `compare` event, or earlier? | Together, in phase 2. |
| 11 | Should the printout show a "data as of" date? The harvest runs have dates. This plan did not check whether an API exposes them. | Print the printing date in phase 1. Add the data date when an endpoint exposes it. |
| 12 | Which colour should "Can block" use? DESIGN.md reserves alert red for destructive actions. | Allow alert red for this marker, together with the words "Can block". A new warning token changes DESIGN.md and needs your approval. |
| 13 | Is the proposed DORA sentence in section 6.6 acceptable? The finder has its own sentence today. | Approve it, or supply the wording that the library prefers. |
| 14 | The browse table already scrolls sideways on desktop. Is a "Compare" column of about 48 px acceptable there, or should desktop rows use the chip as phones do? | A checkbox column. It sticks to the left edge together with the title. |
