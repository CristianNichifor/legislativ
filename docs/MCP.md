# MCP boundary

MCP is treated as an external execution surface. The app may prepare an MCP call, but it must not
send legal text to a connected tool until the user sees and approves the exact payload.

The first contract is `mcp-boundary-v1`:

- `GET /api/mcp/capabilities` lists supported intent classes.
- `POST /api/mcp/preview` validates one intended call and returns an approval payload plus an audit
  event.
- `POST /api/dosare/ai-draft/mcp-preview` builds the existing evidence-grounded AI draft prompt,
  wraps it in the MCP approval contract, and returns a copyable handoff packet.
- `POST /api/dosare/ai-workflow` completes the bounded local/BYOK assistant run, checks returned
  draft claims against the selected evidence manifest, blocks out-of-manifest citations, labels
  uncited legal-looking claims, and stores the result with audit hashes.
- `POST /api/dosare/ai-draft/mcp-execute` accepts only an explicitly approved payload hash and
  runs the v1 local mock executor for the AI draft workflow.
- The preview includes server, tool, purpose, capability, visible data preview, truncation state, and
  SHA-256 of the full text.
- The preview includes cost ownership and token estimate metadata. Server cost is `none`; a real
  executor must disclose provider-side pricing/retention before approval.
- Preview audit events are `approved: false`. Executor audit events are persisted only after the
  request supplies `approved: true` plus the exact preview `data_sha256`.

The v1 executor does not connect to Claude, ChatGPT, GitHub, calendar or document tools. It supports
only `local-mock/ai.draft`, which is a deterministic local adapter used to prove configure, test,
approve, run and audit behavior without network access or credential storage. GitHub Pages can show
the capability list, but rejects MCP previews/execution because the public static worker has no
approved local executor.

The first user workflow is an explicit AI-draft handoff from a manual note. The
browser prepares the source-backed prompt, shows cost/privacy/approval metadata,
then lets the user choose local deterministic drafting, online BYOK or MCP handoff.
Local and BYOK results are stored through `ai-draft-storage-audit-v1`; MCP executor
results are stored through `mcp-executor-boundary-v1`. A draft remains ordinary
unreviewed note text until the user saves the note, and insertion is blocked when
the draft cites evidence outside the selected manifest.

Both `ai_draft_audit_events` and `mcp_audit_events` are part of the private dossier
schema and are append-only. Browser backup/import validation therefore preserves
AI/MCP audit history instead of treating it as an ad hoc extra table.

Allowed v1 capability classes:

- `ai_draft`: send selected evidence to a user-owned AI subscription for a draft or summary.
- `document_export`: create a document in the user connected workspace.
- `consultation_reminder`: create a reminder for a consultation deadline.
- `source_ingest`: inspect local or connected folders for source candidates.
- `github_issue`: draft an issue from a reviewed finding.

Executor rules:

- No background calls.
- No hidden legal-text export.
- No app-paid AI usage through MCP.
- Show the same payload the executor will send.
- Keep the app usable when MCP is unavailable.
- Reject credentials and unknown server/tool pairs.
- Store an append-only dossier audit event with request, data and result hashes.

## Executor boundary v1

`scripts.mcp_executor` implements `mcp-executor-boundary-v1`:

- `test_config({"server":"local-mock","tool":"ai.draft"})` reports whether the selected executor is
  available.
- `execute(path, request)` recomputes the MCP preview from selected evidence, compares the approved
  payload hash, runs the deterministic local mock adapter and stores an audit event in the private
  dossier database.

The execute request must include only:

- `id` — caller-generated audit id;
- `dosar_id` — private dossier id;
- `server` — currently `local-mock`;
- `tool` — currently `ai.draft`;
- `draft` — the same selected-evidence AI draft request used for preview;
- `approved` — must be `true`;
- `approved_data_sha256` — must match the preview payload hash.

The returned draft is labeled `draft_unreviewed`, includes a non-verdict notice and may be inserted
into a note through the ordinary note workflow. The executor never accepts API keys, never stores
credentials and never sends legal text to an external MCP server in v1.

## Bounded local tools v1

`scripts.mcp_tools` defines the minimal local tool surface an external AI client
may wrap as MCP tools. It is a local command/module adapter, not a server and
not an executor:

```sh
uv run python -m scripts.mcp_tools list
uv run python -m scripts.mcp_tools call search_laws '{"q":"achizitii","limit":5}'
```

Allowed tools:

- `search_laws` — full-text search in the local law corpus, with optional
  act-type/year filters.
- `search_projects` — search local parliamentary projects and return bounded
  lifecycle status.
- `get_source_status` — report which local data stores are present; no sync,
  download or freshness verdict.
- `get_project_timeline` — return local tracker events for one project.
- `get_evidence_bundle` — assemble selected local tracker/dossier evidence for
  one project via `project-evidence-pack-v1`.
- `draft_from_evidence` — build the existing source-grounded AI drafting prompt
  from selected evidence; no model is called.

Explicitly absent / rejected tool classes:

- legal verdicts;
- compliance verdicts;
- constitutionality decisions;
- automated legal-effect conclusions;
- any app-paid model call or credential-storing tool.

The adapter preserves the same local-first/BYOK boundary as the browser flow:
it performs no external calls, stores no credentials, and emits draft prompts
only as unreviewed work product grounded in selected evidence.
