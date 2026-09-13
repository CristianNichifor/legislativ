# AI evaluation harness

This is the offline comparison layer for local, BYOK and future MCP-assisted AI
outputs. It does not call any provider. A run stores model outputs produced
elsewhere, then `scripts.evaluari_ai` scores them deterministically against the
same source snippets.

The first supported tasks are:

- source summarization;
- legislative gap-note drafting;
- Romanian/EU article comparison;
- amendment wording.

The harness scores six criteria: source faithfulness, citation correctness,
hallucinated legal claims, useful structure, Romanian drafting quality and
uncertainty. The scores are review signals, not legal conclusions.

## Input contract

Cases contain the task, bounded source snippets, required citations and known
forbidden claims. Runs contain saved candidate outputs with `provider` and
`model` labels. Tests use fixtures under `tests/fixtures/ai_eval/`.

```sh
uv run python -m scripts.evaluari_ai \
  --cases tests/fixtures/ai_eval/cases.json \
  --run tests/fixtures/ai_eval/run_good.json \
  --pretty
```

The output includes per-case scores and a provider/model comparison summary.
Future provider adapters should only write run JSON files into this contract.
Paid calls and keys stay outside this deterministic evaluator: the app first
creates an `ai-external-send-approval-v1` payload with evidence hashes, prompt
hash, token estimate and server cost `none`; the user then sends the prompt
through local AI, BYOK or MCP explicitly.

The selected-evidence draft flow also exposes
`ai-byok-execution-boundary-v1`. Execution happens in the browser through local
WebGPU or the user's configured BYOK provider. The localhost/Python server still
does not call OpenAI, Anthropic or compatible endpoints, and API keys are not
part of saved app data or approval payloads. Provider calls are tested with
mocks only; live calls remain a user action in the browser.

BYOK execution failures use the `ai-byok-provider-failure-v1` contract. The
browser maps mocked/direct provider failures to these states: `timeout`,
`bad_key`, `quota`, `refusal`, `malformed_response` and
`provider_unavailable`. A failed run returns an `ai-byok-execution-result-v1`
with `status: failed`, `output_status: no_draft_created`, a safe user message
and an audit event. Raw provider error text is not saved because it may contain
secrets, request IDs or account details.

## Limits

- Lexical source overlap is a conservative proxy for support.
- Citation checks verify declared source IDs, not the truth of a legal argument.
- Hallucination checks rely on unsupported claims, hard verdict phrases and
  fixture-specific forbidden terms.
- Romanian quality is a drafting heuristic based on length, language markers,
  diacritics and obvious English leakage.
- Uncertainty rewards explicit limitation language because the app must not
  present AI text as a legal verdict.
