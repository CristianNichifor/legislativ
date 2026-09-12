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
