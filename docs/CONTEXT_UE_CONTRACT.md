# Proposed Romanian/EU evidence-linking contract v1

Status: implementation handoff for milestone 5, **not an implemented endpoint or
completed assessment workflow**. M4 introduces no persistence changes. Integrate
this interface after agreement with the proposal/source and dossier owners;
do not add schema 8 writes from the context branch.

## Existing inputs

| Input | Existing API | Boundary |
| --- | --- | --- |
| Saved finding and cited contexts | `GET /api/dosare/revizuiri?id=...&rulare_id=...` | Saved report and per-target events; labels are unauthenticated |
| Context history | `GET /api/dosare/context?id=...&rulare_id=...&constatare_id=...&tinta=...&offset=...` | Revisions of a single owned target |
| National provision | `GET /api/prevedere?act=...&loc=...` | Current local text, not an immutable historical source |
| Saved proposal | `GET /api/dosare/propuneri?id=...&rulare_id=...&constatare_id=...&revizie=...` | Use an explicit saved revision, never unsaved editor contents |
| Revision-linked analysis | `GET /api/dosare/propuneri/analize?id=...&rulare_id=...&constatare_id=...&revizie=...` | Existing bounded checks and captured basis; not EU substantive assessment |
| EU discovery | `POST /api/ue` | Search candidates are contextual leads, not obligations automatically linked to a proposal |
| EU source history | `GET /api/ue/surse?celex=...&offset=...` | Current observation and archived observation summaries |
| EU retained text | `GET /api/ue/surse?celex=...&instantanee=...` | Validates CELEX ownership, snapshot identity and text hash |

EU acquisition remains a separate explicit action through `POST /api/ue/surse`.
Linking must not implicitly acquire sources or invoke inference. Source URLs,
timestamps and language come from resolved server evidence, not client assertions.

## Proposed interface

Define a pure service `prepare_eu_link(selection, resolved_evidence)` first; route
and durable storage are integration decisions. A future POST preview accepts
only selectors and a research hypothesis, never client-supplied source text or
trusted hashes. Suggested wire shape (illustrative IDs):

```json
{
  "contract": "ro-eu-link-v1",
  "dosar_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "rulare_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "constatare_id": "cccccccccccccccccccccccccccccccc",
  "national": {"kind": "saved_proposal", "revizie": 2},
  "eu": {
    "celex": "32014L0024",
    "instantanee": "explicit-existing-snapshot-id",
    "locator": "explicit-obligation-locator",
    "start": 0,
    "end": 120
  },
  "context_events": [],
  "hypothesis": "potential_gap",
  "reason": "User-declared research question"
}
```

Alternative national selector: `{"kind":"corpus_provision","act_id":"...",
"locator":"..."}`. The service must capture the exact current text and its
provenance as a new basis, explicitly labeled current local capture. Reusing an
old finding's act ID is not proof of historical text. For a proposal, resolve
the requested revision under the dossier/run/finding ownership tuple and retain
its revision hash and structured target snapshot when available. Repeal intents
can have empty replacement text: resolve their saved operation and original
target text instead of treating emptiness as a legal gap. Free-text proposals
without a resolved national target remain contextual.

`start`/`end` are half-open Unicode code-point offsets into the exact retained EU
snapshot text, bounded to a nonempty excerpt (suggested maximum 12,000 code
points). A UI using JavaScript UTF-16 offsets must convert before submission.
The locator is an explicit user-selected citation; the resolver must validate it
against available provision structure, or label it unverified and block
substantive use. Never guess article boundaries from a search snippet. Select
the obligation passage and relevant qualifications/exceptions explicitly.

Allowed hypotheses: `potential_coverage`, `potential_conflict`, `potential_gap`.
They are user-declared research hypotheses, never automatic legal conclusions.
Reason is required for a substantive candidate, at most 4,000 characters.
Unknown keys, invalid IDs/revisions, unsupported contracts, foreign ownership,
invalid offsets and mismatched snapshots are validation errors, not empty hits.

## Resolution and missing-text gate

The preview returns `contract`, the exact `selection`, `scope`, `state`,
`blockers`, `national_evidence`, `eu_obligation`, `context`, and
`substantive_candidate`. Evidence records include identity/locator, retained
text, source URL, language, observation time, hash and hash algorithm, plus
origin (`saved_proposal_revision`, `current_corpus_capture`, `eu_snapshot`).
Hash contracts must remain distinct; byte and extracted-text hashes are not
interchangeable. Captured source content must be bounded without silent truncation.

Parent M3 integration (under development in the sources branch): use its
`scripts/surse_propuneri.py` capture/comparison service and
`GET /api/dosare/propuneri/surse` for proposal dependency observations. Its optional
`analiza_baza_id` and `reevaluare` analysis JSON link reassessment to the original
basis without a migration. Preserve that link in a future EU assessment; a source
comparison is still contextual and cannot satisfy the explicit EU obligation gate.
These additions are not present in this branch's PR140 base. Reconcile the exact
parameters against the integrated M3 implementation before wiring M5 routes.

```json
{
  "contract": "ro-eu-link-v1",
  "scope": "contextual",
  "state": "blocked_missing_text",
  "blockers": [{"side": "eu", "code": "missing_text"}],
  "national_evidence": {"state": "resolved"},
  "eu_obligation": {"state": "missing_text"},
  "context": {"applicability": "unknown"},
  "substantive_candidate": null
}
```

This abbreviated response illustrates blocking, not a complete resolved record.
Required blocker codes include `missing_text`, `metadata_only`, `unverified_hash`,
`ambiguous_locator`, `unresolved_national_target`, `unsupported_source`,
`capture_limit`, and `missing_obligation`. Any blocker forces contextual scope
and a null substantive candidate. Missing text on either side specifically
returns `blocked_missing_text`; other unresolved evidence returns
`blocked_evidence`. A CELEX citation, title, domain hint, metadata-only import,
search rank or source-check success can never satisfy this gate.

After all evidence gates pass, `state=ready_for_explicit_link` still has
`scope=contextual` and a null candidate. An explicit user confirmation with
the same resolved basis may produce `scope=substantive_candidate` and
`state=linked_hypothesis`. This is an evidence-linked possible coverage/conflict/
gap with rationale, not confirmed compliance. Do not require an authenticated
reviewer or repurpose existing review decisions to supply confirmation.
Context fields keep known-declared/unknown/heuristic states independently;
unresolved applicability is displayed even when source text is available.

## Acceptance before M5 completion

Implement selection UI, exact-revision resolver, obligation excerpt selection,
server-side gates, explicit link confirmation, durable retry-safe basis/history
and export under the agreed storage contract. Preserve contextual references
separately from substantive candidates and finding/source-change queues.
Changed sources require an explicit new assessment basis; original evidence and
proposal text remain unchanged. Same ownership, local Host/Origin checks and
no-store responses as the existing dossier APIs apply to future routes.

Tests must cover missing text on each side, metadata-only EU data, hash mismatch,
foreign snapshots/revisions, ambiguous locator, out-of-range and astral-character
offsets, unsupported sources, capture limits, English fallback labeling, repeal
operations, unknown context, retries and stale basis confirmation. Browser
checks must show blocked substantive actions and explicit context-only results.
Real-source acceptance remains M7; fixtures and this contract cannot establish
legal accuracy or complete national/EU coverage.
