# MCP boundary

MCP is treated as an external execution surface. The app may prepare an MCP call, but it must not
send legal text to a connected tool until the user sees and approves the exact payload.

The first contract is `mcp-boundary-v1`:

- `GET /api/mcp/capabilities` lists supported intent classes.
- `POST /api/mcp/preview` validates one intended call and returns an approval payload plus an audit
  event.
- `POST /api/dosare/ai-draft/mcp-preview` builds the existing evidence-grounded AI draft prompt,
  wraps it in the MCP approval contract, and returns a copyable handoff packet.
- The preview includes server, tool, purpose, capability, visible data preview, truncation state, and
  SHA-256 of the full text.
- The preview includes cost ownership and token estimate metadata. Server cost is `none`; a real
  executor must disclose provider-side pricing/retention before approval.
- The audit event is always `approved: false`; a later executor must persist a user-approved event
  before calling any MCP server.

This PR does not add an MCP executor and does not connect to Claude, ChatGPT, GitHub, calendar, or
document tools. GitHub Pages can show the capability list, but rejects MCP previews because the
public static worker has no approved local executor.

The first user workflow is an explicit AI-draft handoff from a manual note. The
browser prepares the source-backed prompt, shows the MCP approval packet, lets the
user copy it to a user-owned MCP tool, and accepts pasted output back into the note
with the MCP audit timestamp and payload hash. The pasted result remains ordinary
unreviewed note text until the user saves the note.

Allowed v1 capability classes:

- `ai_draft`: send selected evidence to a user-owned AI subscription for a draft or summary.
- `document_export`: create a document in the user connected workspace.
- `consultation_reminder`: create a reminder for a consultation deadline.
- `source_ingest`: inspect local or connected folders for source candidates.
- `github_issue`: draft an issue from a reviewed finding.

Executor rules for a later PR:

- No background calls.
- No hidden legal-text export.
- No app-paid AI usage through MCP.
- Show the same payload the executor will send.
- Keep the app usable when MCP is unavailable.

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
