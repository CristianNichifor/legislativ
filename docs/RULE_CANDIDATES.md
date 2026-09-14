# Rule candidate contract

`rule-candidate-v1` is the reviewable bridge between source-backed legal text
and future executable law-as-code rules.

It does not decide legal correctness and does not run a rule engine. It only
validates that a proposed structured extraction is bounded, source-linked and
explicit about review state.

## Required fields

- `provision_id`
- `act_id`
- `locator`
- `source_hash`
- `text`
- `modality`
- `review_state`

Supported modalities:

- `obligation`
- `prohibition`
- `permission`
- `procedure`
- `deadline`
- `competence`
- `sanction`
- `definition`
- `exception`
- `vague_standard`
- `not_codeable`

Supported review states:

- `machine_detected`
- `human_reviewed`
- `legally_validated`
- `disputed`
- `obsolete`

## Optional structure

- `actor`
- `condition`
- `action`
- `deadline`
- `exceptions`
- `effect`
- `reviewer`

## Preview workflow

`POST /api/dosare/rule-candidates/preview` validates the same payload and
returns the `rule-candidate-v1` packet. The endpoint is read-only: it does not
save a candidate, call AI or promote the output to an executable rule.

The browser exposes this as **Propune regulă** from a provision preview and from
manual notes. A reviewer can fill the structured fields, preview the normalized
candidate, then decide later whether it belongs in a review queue. Until a
persistence store exists, the result is explicitly unsaved.

## Output states

- `reviewable`: enough structure for later human review or deterministic checks.
- `needs_more_structure`: the source is present, but actor/action are missing.
- `needs_legal_review`: vague standard; should not become executable without
  interpretation.
- `not_codeable`: provision is intentionally marked as unsuitable for executable
  rules.

Every output includes:

- stable `candidate_id`;
- `text_sha256`;
- original `source_hash`;
- limitations explaining that the candidate is not a legal conclusion.

## Role in law as code

Executable legal checks should only consume candidates that remain tied to exact
source text and a provision identity. AI and MCP tools may draft candidate
structure, but they must not silently promote a candidate to a legally validated
rule.

## Local review queue

Validated candidates can be saved into a dossier-scoped local queue:

- `POST /api/dosare/reguli`
- `GET /api/dosare/reguli?id=<dosar_id>&stare=<bucket>`

The POST body is:

```json
{
  "action": "save",
  "id": "caller supplied 32-char retry id",
  "dosar_id": "dossier id",
  "candidate": {
    "contract fields": "same payload accepted by scripts.rule_candidates.validate"
  }
}
```

The server validates the candidate before storage and groups queue items into:

- `needs_more_structure`
- `needs_legal_review`
- `not_codeable`
- `reviewable`
- `human_reviewed`

`stare=all` returns the paginated queue plus the first 20 rows per group.
Saving is local-only, dossier-scoped and idempotent for the same caller retry id
and stable `candidate_id`. A duplicate candidate with a different retry id is
rejected so the review queue does not silently fork one extraction into multiple
review tasks.

The queue is an operational review surface. It does not certify that a candidate
is legally correct, executable or accepted into the future rule engine.

## Promotion to draft rules

Reviewed candidates can be promoted into immutable dossier-scoped draft rules via
`POST /api/dosare/rule-drafts`:

```json
{
  "action": "promote",
  "id": "cccccccccccccccccccccccccccccccc",
  "dosar_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "queue_id": "11111111111111111111111111111111",
  "accepted_by": "autor",
  "acceptance_note": "Structura exprimă obligația din textul citat."
}
```

The response contract is `law-rule-draft-v1`. It copies the exact validated
candidate, source provision identity, source hash, text hash and reviewer note.
Draft rules are append-only and deduplicated by `dosar_id,candidate_id`.

Promotion is allowed only for candidates in the `reviewable` or `human_reviewed`
buckets. Candidates needing more structure, legal review or marked as not
codeable must stay in the queue.

`GET /api/dosare/rule-drafts?id=...` lists promoted draft rules, with optional
`act=...` and `provision_id=...` filters. These records are the first persistent
law-as-code bridge, but they are still explicitly labelled
`draft_rule_not_legal_verdict`; deterministic checks may consume them only as
reviewable source-backed inputs.

## Deterministic draft/proposal checks

`POST /api/dosare/rule-drafts/execute-draft` runs promoted draft rules against a
single draft/proposal text supplied by the user:

```json
{
  "id": "dosar id",
  "act": "optional act filter",
  "text": "draft or amendment text",
  "limit": 50
}
```

The response contract is `law-rule-draft-text-execution-v1`. It never calls AI,
never consults external services and never returns a legal verdict. Every finding
is a `law-rule-deterministic-issue-v1` candidate for human review.

The v1 deterministic slice checks:

- obligation/action found without the reviewed actor;
- procedure/deadline/body fields missing from the supplied text;
- locator references such as `art. 5` where no act is cited in the same fragment;
- citations to provisions the local graph marks as repealed;
- citations to provisions the local graph marks as suspended, derogated from or
  prorogated;
- delegated norms already reported as missing by the local gap checker;
- saved EU links whose author-declared hypothesis is `potential_conflict`, when
  the draft text overlaps the retained CELEX/article evidence.

Each issue cites its source:

- for draft-rule checks: `rule_draft_id`, `candidate_id`, `provision_id`,
  `act_id`, `locator`, `source_hash` and `text_sha256`;
- for draft-text/reference checks: the supplied text hash and exact matched
  quote/span where available;
- for graph checks: the quoted citation plus act/locator and graph-derived
  repeal or qualification evidence;
- for EU checks: saved CELEX, article locator and the retained obligation quote.

Uncertainty is part of the contract. Missing graph data, missing EU links, absent
source text or synonym-heavy drafting is reported as a limitation, not treated as
proof that the draft is clean.
