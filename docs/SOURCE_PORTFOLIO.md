# Source portfolio for MP law-writing workflows

This file defines which public-source families matter for writing, checking and
tracking Romanian legislative work. It is a portfolio and sizing contract, not a
bulk crawler plan.

The checked-in machine contract is `scripts/source_portfolio.py`.

## Priority order

| Priority | Source family | Why it matters | First usable slice |
| --- | --- | --- | --- |
| 1 | Portal Legislativ | Published and consolidated Romanian law text. | Act text, Monitorul Oficial reference and consolidation metadata. |
| 2 | Camera Deputaților | PL-x lifecycle, committees, reports, agendas and votes. | Project ficha, committee/report links, agenda and vote events. |
| 3 | Senat | L/B/BP lifecycle, consultation list, committees and opinions. | Project list/detail, consultation deadline and status events. |
| 4 | E-Consultare | Draft normative acts before or outside Parliament. | Consultation id, authority, deadline, attachments and state. |
| 5 | Ministry consultation pages | Draft acts that are not reliably mirrored elsewhere. | One ministry adapter at a time, with public-deadline parsing. |
| 6 | EU Cellar / EUR-Lex | Official EU text and metadata for compatibility and transposition checks. | CELEX referenced by dossiers or Romanian acts; Romanian first, English fallback. |
| 7 | CCR | Constitutional risk and invalidated provisions. | Decision metadata, operative part, affected provisions. |
| 8 | Institutional opinions / avize | Required opinions and objections. | Issuer, positive/negative/observations, document hash. |
| 9 | Monitorul Oficial Partea I | Official publication proof for normative acts. | Part I index, text extraction, law-publication links. |
| 10 | Monitorul Oficial Parts II-VII | Announcements and non-core material. | Metadata and user-requested/domain-triggered documents only. |
| 11 | Monitorul Oficial Local | Local acts, HCL, dispositions, local regulations and urbanism. | MDLPA/UAT registry, per-UAT source state, opt-in local packs. |

## Monitorul Oficial policy

Do not ingest all Monitorul Oficial parts as the default path.

Part I should be indexed and text-extracted because it is the publication proof
for laws, ordinances, decisions and other normative acts.

Part II should start as metadata/selective ingestion. It matters sometimes, but
it is not the core law-writing corpus.

Parts III-VII should not be full-ingested by default. Treat them as metadata,
short-retention/source-status entries or user-triggered retrieval targets until
there is a concrete workflow that needs a specific part.

Monitorul Oficial Local should start registry-first: identify UAT sources,
coverage, freshness and document links, then allow opt-in local packs by UAT or
domain. A full national local mirror is storage-heavy, parser-heavy and less
useful than targeted local coverage.

## Storage estimates

These are rough R2 Standard storage bands from `scripts.source_portfolio`. They
include the 10 GB/month free storage allowance and use 0.015 USD/GB-month for
stored bytes. Operation costs are separate and depend on object count and read
patterns.

| Profile | Included sources | Rough storage | R2 storage/month |
| --- | --- | ---: | ---: |
| `v1` | Portal Legislativ, Camera, Senat, E-Consultare, EU Cellar, CCR | 55-310 GB | 0.68-4.50 USD |
| `serious` | `v1` plus ministry consultations, avize and Monitorul Oficial Part I | 120-630 GB | 1.65-9.30 USD |
| `everything` | All listed sources, including MO Parts II-VII and MO Local | 320-3630 GB | 4.65-54.30 USD |

The practical cost risk is not only GB stored. The expensive parts are object
counts, PDF parsing, OCR fallback, retries, change detection and UI latency when
the corpus becomes too broad.

## Tracker events

The tracker should normalize public-source movement into these events:

| Event | Main source | Minimum fields |
| --- | --- | --- |
| `public_consultation_opened` | E-Consultare/ministry pages | authority, deadline, project URL, attachment hashes |
| `public_consultation_closed` | E-Consultare/ministry pages | authority, closed date, project URL |
| `committee_assignment` | Camera/Senat | committee, role, deadline, project id, source URL |
| `opinion_received` | Avize | issuer, position, observations, document hash, source URL |
| `report_filed` | Camera/Senat | committee, position, document hash, filed date, source URL |
| `plenary_agenda` | Camera/Senat | chamber, agenda date, project id, source URL |
| `vote_recorded` | Camera/Senat | chamber, vote date, result, counts, nominal-vote URL |
| `published_in_monitor` | Monitorul Oficial Part I | part, number, date, act id, source hash |

The local append-only storage/API contract for these normalized observations is
`scripts/tracker_events.py`. It is intentionally separate from source sync:
`GET /api/tracker-evenimente` reads local normalized events and
`POST /api/tracker-evenimente` records one event. Neither endpoint fetches public
sources or mutates saved legal conclusions.

`scripts/monitor_tracker.py` is the bounded Monitorul Oficial Part I replay
slice. It converts publication references already present in local `acte`,
`documente`, `initiative` or `initiativa_etapa` rows into
`published_in_monitor` event-shaped dictionaries, then can store them through the
same tracker contract. It does not crawl Monitorul Oficial and it does not bulk
ingest PDFs; missing issue numbers or dates remain missing.

## Execution order

1. Keep one-source sync as the operational boundary.
2. Add E-Consultare as the next real adapter because it captures drafts before
   Parliament.
3. Expand Camera/Senat tracking from project metadata to committee, report,
   agenda, vote and opinion events.
4. Add Monitorul Oficial Part I publication events and connect them to published
   acts.
5. Add avize as metadata-first, document-on-demand sources.
6. Add local Monitorul Oficial as opt-in packs after the registry/freshness UI is
   useful.

## UI coverage rule

The app should show source coverage before it offers conclusions. The coverage
panel groups sources as:

- necessary now: sources needed for useful V1 legislative drafting and tracking;
- planned: useful source families that should be integrated adapter by adapter;
- deferred or opt-in: broad Monitorul Oficial/local mirrors that should not be
  full-ingested by default.

Missing, stale, changed, failed, rate-limited and unavailable sources remain
visible. They are user actions, not empty results. A changed source means “review
affected dossiers and proposals”; it does not automatically update saved legal
findings.
