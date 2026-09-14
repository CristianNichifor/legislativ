# UX acceptance gate

Contract: `ux-acceptance-gate-v1`

The Civic UX bible has a deterministic static gate:

```bash
uv run python -m scripts.ux_acceptance
uv run python -m scripts.ux_acceptance --require-complete
```

The gate reads only:

- `app/index.html`
- `app/civic-ui-adapter.css`

It does not build the browser app, fetch sources, call AI/MCP, inspect private data or infer legal
quality. It reports whether the checked-in shell preserves the required civic UX copy and anchors.

## Blockers

The gate blocks when it finds:

- user-visible internal wording: `rebuild`, `index`, `reload`, `cache`, `manifest`, `shard`;
- missing `civic-ui-adapter.css`, missing Civic UI stylesheet link or missing `civic-legislativ`
  body scope;
- missing source-status explanations for missing, partial, reviewable and unknown source states;
- missing AI/MCP approval copy, including BYOK/session-key boundaries and explicit handoff/action;
- missing no-verdict, candidate and human-review wording;
- missing basic daily workflow anchors from source to note, evidence, draft and export.

## Warnings

Warnings do not weaken blockers. They keep the checked-in UI status honest if the shell is usable
but exposes technical legal provenance terms in primary copy.

Policy: prefer Romanian labels in normal user-facing surfaces. Machine/provenance terms such as
`Source hash` and `stale` are allowed only inside disclosure details, raw contract payloads or debug
areas (`<details>`, `data-raw-contract`, `data-debug` or `.debug`). If they appear in primary copy,
the gate reports `technical_wording_visible`.

Current checked-in status: the UI should stay `ready` with no warnings. If `Source hash` or `stale`
returns to primary copy, the gate should report `technical_wording_visible` until the wording is
localized or moved into accepted detail/raw areas.

`--require-complete` exits with code `2` only for blockers. Warnings remain visible in the JSON so
the report stays honest when copy is usable but still contains technical wording worth cleaning up.
