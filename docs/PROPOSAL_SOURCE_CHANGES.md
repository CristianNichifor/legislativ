# Proposal source changes (v1 milestone 3)

The proposal analysis panel now separates three explicit actions:

- **Compare local sources** reads the selected saved revision and selected analysis
  against the local corpus. It does not save, download sources, run analysis, or
  modify the draft. Opening history never runs this comparison automatically.
- **Reassess from selected analysis** runs the existing bounded checks on that same
  saved revision, retaining a source comparison and the original analysis ID in a
  new append-only result. This does not approve the proposal or update its target.
- **Check this revision** remains an independent new analysis; an interrupted retry
  retains its original request ID and reassessment basis across finding navigation.

## States and scope

`schimbat` means complete captured provision rows differ. `neschimbat` means their
content, dates and ordering match, not that the law is current or applicable.
Collection timestamp/source URL differences are reported separately as metadata
changes and do not masquerade as changed statutory text. Missing, blank, ambiguous
or partial source rows are `indisponibil`, never unchanged or presumed repealed.
Unsupported contracts, broken retained hashes and uncaptured dependencies are
explicit. A changed dependency combined with missing coverage remains changed with
`comparatie_incompleta=true`.

The baseline is the selected analysis's retained local act snapshots, not a live
reconstruction of the original saved finding. A structured proposal's separately
retained exact target is also compared, including before its first analysis. A free
text proposal without an analysis has no captured dependencies and is unsupported.
Internal citations and legal applicability remain outside this source comparison.
An insertion whose new article number is occupied fails exact target reacquisition;
its target comparison is unavailable with the reason retained, not unchanged.

Capture reuses the analysis engine's read-only transaction, 20-act, 500-row/act and
400 KB provision limits. The structured target retains its existing 100-row/80 KB
limit. Act snapshots and structured targets are separate reads; this is not an
atomic lock on the complete corpus. The comparison retains content fingerprints,
source metadata, up to 8,000 characters of each before/after excerpt and 200 diff
lines per dependency. Truncated text/diffs are flagged. Original snapshots remain
unchanged in historical records. The overall saved analysis ceiling remains 4 MB.

## API and persistence

`GET /api/dosare/propuneri/surse?id=<dossier>&rulare_id=<run>&constatare_id=<finding>&revizie=<n>`
compares the exact revision using its latest saved analysis, if any. Optional
`analiza_id` selects an exact baseline belonging to that revision. It returns
`salvata: false`, the baseline ID/hash, proposal ID/revision/hash, capture time,
dependency results, aggregate state, incomplete flag and limitations. Ownership,
revision and baseline selection are validated before source reads. The route uses
local Host/Origin controls, `no-store`, and explicit static refusal.

`POST /api/dosare/propuneri/analize` additionally accepts optional `analiza_baza_id`.
This must belong to the exact requested proposal revision. The server computes the
new analysis and saves `reevaluare` alongside its existing fields, with `salvata:
true`. Source comparisons use the act snapshots actually retained by the new
analysis; they do not certify that a previous transient comparison remains current.
An exact committed retry returns the original result without source reads or
recomputation. Reusing an ID with a different revision or reassessment basis fails.
The existing 16 KB request ceiling still applies.

No new table or migration is needed beyond schema 7. New reassessments use existing
analysis history. Selecting one displays its saved source warnings and previous
analysis ID. Proposal JSON/Markdown exports and SQLite backups retain that same
comparison and its limitations without needing the current corpus. Selecting a
newer proposal revision cannot borrow an older revision's analysis or source basis.

## Verification

Tests cover metadata/text/date changes, lost sources, ambiguous/partial coverage,
unsupported hashes/contracts, bounded excerpts, exact baseline ownership, structured
targets, mixed changed/unavailable states, reassessment retry, immutable history,
backup/export, new-revision isolation, local Host/Origin restrictions and static
refusal. Desktop/mobile browser checks exercise read-only comparison, before/after
text, missing sources, saved reassessment, a lost response after commit, retry after
finding navigation, retained unsaved text and historical export.
