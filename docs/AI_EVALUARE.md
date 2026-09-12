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
Future provider adapters should only write run JSON files into this contract;
paid calls, keys and MCP approvals stay outside this deterministic evaluator.

## Limits

- Lexical source overlap is a conservative proxy for support.
- Citation checks verify declared source IDs, not the truth of a legal argument.
- Hallucination checks rely on unsupported claims, hard verdict phrases and
  fixture-specific forbidden terms.
- Romanian quality is a drafting heuristic based on length, language markers,
  diacritics and obvious English leakage.
- Uncertainty rewards explicit limitation language because the app must not
  present AI text as a legal verdict.
