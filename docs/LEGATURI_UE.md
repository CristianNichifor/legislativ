# Bounded saved-proposal / EU obligation links

The saved proposal panel now has an EU-link workflow for an explicit saved
proposal revision and retained EU snapshot/article. The author identifies the
obligation, chooses a potential coverage/conflict/gap hypothesis, and supplies a
reason and unauthenticated author label. This is an evidence-linked research
hypothesis, never a compliance verdict or an authenticated review.

## Evidence and blockers

National evidence is the immutable saved structured proposal and its original
target snapshot. The resolver verifies the target hash, exact act/locator, saved
operation and composed proposal text. It never substitutes current national
corpus text. Free-text proposals without structured targets remain contextual;
missing text blocks linking. Repeal proposals retain the original target text
and explicit repeal operation, despite having empty replacement text.

EU selection is explicit: CELEX, snapshot ID, and article locator. Source history
uses the existing `/api/ue/surse` API. Articles are parsed from that exact snapshot
using the existing `cellar.provizii_din_text` parser, not the current provision
index or a search snippet. Only supported article blocks are selectable; duplicate
article headings, parser suffixes, missing article text, unsupported languages,
missing snapshots and invalid hashes block substantive linking. Full original
snapshot text is retained alongside the parsed article, so surrounding exceptions
and qualifications remain inspectable. The author must state the obligation;
an article heading alone does not identify it automatically. A heading plus
parser-identified title with no remaining body is blocked as missing text. The
obligation field must be an exact contiguous quote from that body, excluding
the heading/title. A quote match proves only retained-text provenance, not that
the passage legally imposes an obligation. The conservative parser may treat a
short sole body line as a title; such ambiguous extracts remain blocked.

Bounds: snapshot extracted text 1 MB; selected article 12,000 characters; at most
1,000 parsed blocks; source/article/history pages 20/50/20; saved basis plus result
4 MB. No silent excerpt truncation. Source acquisition, paid inference and legal
reasoning are not invoked. Romanian and English source language remain explicit.
Document/collection dates do not establish applicability or freshness.

Preview scope is always `contextual`, with `substantive_candidate=null` and state
`ready_for_explicit_link`, `blocked_missing_text`, or `blocked_evidence`. Blockers
identify the national/EU side and a machine-readable code. Invalid selectors and
foreign proposal identities fail with 400. Unavailable or invalid EU snapshots
never fall back to another observation. Unknown legal context remains unknown;
cited context events retain their author, citation, revision and time without
automatic legal verification. M3 source comparisons remain a separate workflow.

## APIs

All routes use the existing local Host/Origin checks, `no-store`, static-mode
rejection and 16 KB POST bound. No client-supplied source text is accepted.

- `GET /api/dosare/propuneri/legaturi-ue/obligatii?celex=...&instantanee=...&offset=0`
  returns bounded article selectors, provenance summary and blockers.
- `POST /api/dosare/propuneri/legaturi-ue/previzualizare` resolves selectors and
  returns the complete captured `baza`, `baza_sha256`, blockers and limitations.
- `POST /api/dosare/propuneri/legaturi-ue` confirms and appends a link.
- `GET /api/dosare/propuneri/legaturi-ue?id=...&rulare_id=...&constatare_id=...&revizie=1&offset=0`
  returns exact-revision history and the latest full link. `legatura_id=...`
  selects one link, validated against that revision and owning dossier/run/finding.
  `markdown` exports only the selected link; the UI JSON export likewise includes
  only the selected immutable record, not an unsaved form or moving source.

Preview body:

```json
{
  "dosar_id": "32-lowercase-hex-id",
  "rulare_id": "32-lowercase-hex-id",
  "constatare_id": "32-lowercase-hex-id",
  "revizie": 1,
  "celex": "32018R1805",
  "instantanee": "64-lowercase-hex-snapshot-id",
  "locator": "art1"
}
```

Save adds exactly `id` (32 lowercase hex retry ID), `baza_sha256` (preview hash),
`autor` (required, 120 characters), `ipoteza` (`potential_coverage`,
`potential_conflict`, `potential_gap`), `obligatie` (required, 2,000 characters)
and `motiv` (required, 4,000 characters). The server resolves again and rejects
changed bases before writing. Context is also rechecked inside the write
transaction. Identical committed retries return their original record even if
EU sources later disappear; changed requests under the same ID are rejected.
Concurrent identical retries create one row. Later proposal revisions never
inherit links. No existing review decision, source queue or proposal is changed.

## Storage and UI

Schema 9 adds only `legaturi_ue`, keyed to the immutable proposal ID, with
insertion sequence, unique retry ID, timestamp, normalized request JSON and full
resolved result JSON. Index and no-update/no-delete triggers are created by
`legaturi_ue_schema.migreaza` inside the dossier migration transaction. Reads do
not migrate older stores; failed writes roll back DDL and version markers.
SQLite backups preserve all links and retained text. Back up before upgrading:
older application versions reject schema 9. A database owner can bypass triggers;
hashes and local labels are not signatures or authenticated identities.

The migration module has no imports. `dosare` imports only that DDL helper;
`propuneri` does not import the EU engine/store, avoiding an import cycle.
Persisted history/export composition stays in `legaturi_ue_store`.

Opening the panel loads saved history only. Local source reads, previews and
confirmation are separate commands. Pending operations disable the EU controls;
session state retains inputs/retry identity across remounts and finding navigation.
EU drafts are session-only, excluded from M6 recovery/export, and trigger a
separate unload warning until saved or explicitly discarded. Source-selector
changes invalidate the preview. Both selected revision and latest available
revision are labeled. History selection/export never uses unsaved form text.

## Verification and preview rerun

```bash
uv run pytest -q
uv run python -m tests.eu_link_fixture
uv run python -m scripts.server --port 8043 --fara-browser \
  --corpus .eu-link-fixture/corpus.db \
  --initiative .eu-link-fixture/initiative.db \
  --eu .eu-link-fixture/eu.db --graf .eu-link-fixture/graf.db
```

In another terminal, from the integrated schema-9 checkout:

```bash
EU_LINK_BASE_URL=http://127.0.0.1:8043 \
PLAYWRIGHT_MODULE=/absolute/path/to/playwright \
node tests/eu_link_browser.cjs
```

The runner seeds each width independently and uses no downloads. An existing
integrated preview can set `EU_LINK_INITIATIVE_DB` to its absolute `--initiative`
path, using a disposable valid initiative DB copy. Its `--eu` must point to this
checkout's `.eu-link-fixture/eu.db` so it sees the synthetic retained snapshots.
The preview may use an actual corpus: national targets are historical fixture
captures, and the seeder writes source fixtures only in this checkout. Do not
point the fixture at working research dossiers. Artifacts under
`.eu-link-fixture/` are ignored and never committed.

Verification on the integrated schema-8 base plus this unit: 1,316 pytest tests
pass, repository-wide Ruff check/format pass, and 1280px/390px browser checks
cover blocking, exact selectors, lost-response retry, historical export,
duplicate-panel prevention across remount/reload/proposal saves, stale-selector
clearing, dirty-draft unload warning, revision isolation and no horizontal overflow.

This is a bounded whole-article hypothesis workflow. Annex/recital obligations,
arbitrary clause offsets, unstructured national targets, automated normative
coverage/conflict reasoning and real-data acceptance remain outside this unit.
The earlier M5 contract is a design handoff; this document describes the actual
implemented subset. Central milestone acceptance remains with the integrator.
