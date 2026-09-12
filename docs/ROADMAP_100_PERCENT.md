# Roadmap to full legislation tracking, AI and MCP

This roadmap describes the path from the current local-first v1 app to a complete
legislation tracking and assisted-analysis product. It is not a promise that legal
answers are automatically correct. The finish line is: complete source provenance,
clear workflow states, user-owned data and keys, source-grounded analysis, and
repeatable measurements.

## Product principle

Ship usable workflows first, then expand coverage. Large public releases, complete
EU imports and model integrations must not block small improvements that help a
person write, review and track legislative gaps today.

The app should always distinguish:

- what is in the local dataset;
- what is missing but known by identifier;
- what changed upstream;
- what was inferred by deterministic code;
- what was drafted or summarized by AI;
- what was accepted by a human reviewer.

## Current baseline

The current v1 foundation already has local-first dossiers, structured proposals,
revision-linked checks, source-change comparison, applicability context, bounded EU
linking, browser workspace persistence, release rehearsal and real-data acceptance
runner support.

The known hard gaps are:

- public source coverage is intentionally tiny;
- consultation/project lifecycle tracking is not complete;
- EU text availability is measured but missing in the pilot data;
- external reference recall and precision are not independently adjudicated;
- AI is an assistive drafting layer, not a measured reliable legal analyzer;
- MCP integration is not a finished user-facing product surface.

## Finish phases

### Phase 1: usable manual gap workspace

Goal: make the app useful even with partial data.

Deliverables:

- Manual creation of a gap, loophole, contradiction or EU-risk note.
- Stable shared note vocabulary in code, starting with `scripts.constatari_manuale`,
  so storage, UI, exports and future AI/MCP flows use the same keys.
- Required fields: title, problem type, affected act, locator, evidence quote,
  source URL or source hash, user reasoning, status and owner.
- Optional fields: domain, legal hierarchy, affected institutions, applicability
  date, territory, recipients, exceptions and related projects.
- Dossier view that separates manual notes from generated findings.
- Export of a dossier with manual notes, sources and unresolved limitations.

Acceptance:

- A user can write and preserve a complete legislative-gap note without AI.
- The note survives reload, export, backup and restore.
- Missing source data is shown as missing, not guessed.

### Phase 2: source registry and acquisition queue

Goal: track public sources without forcing huge rebuilds.

The shared state vocabulary and the first one-source sync boundary are defined in
`docs/SOURCE_SYNC.md`. That contract is the implementation target before any
portal-wide scheduler or release pipeline work.

Deliverables:

- Source registry table for every source family:
  - Romanian legislative portal acts;
  - Parliament bills/projects;
  - Chamber/Senate procedure pages;
  - Government consultation pages;
  - ministry consultation pages;
  - Monitorul Oficial references where available;
  - CCR decisions;
  - EU Cellar/EUR-Lex CELEX records.
- Per-source state: discovered, queued, fetched, unchanged, changed, failed,
  unavailable, rate-limited and needs manual review.
- Incremental fetch queue by identifier or URL.
- Small “sync selected sources” UI action instead of whole-dataset rebuilds.
- Stored fetch logs with URL, timestamp, status code, content hash and parser
  version.

Acceptance:

- A user can add one public URL or identifier and sync only that source.
- The UI explains whether source content was fetched, unchanged, changed or failed.
- No full release rebuild is needed for a normal source refresh.

### Phase 3: project and consultation lifecycle tracking

Goal: show where a draft/project is in the public process.

Deliverables:

- Unified lifecycle model:
  - public consultation announced;
  - consultation open;
  - consultation closed;
  - ministry/government drafting;
  - government adopted;
  - sent to Parliament;
  - Chamber/Senate registered;
  - committee stage;
  - report issued;
  - plenary scheduled;
  - adopted/rejected;
  - promulgated;
  - published;
  - archived/withdrawn.
- Timeline per project with source links and timestamps.
- Watchlist by act, domain, CELEX, keyword, issuer and committee.
- Diff between project text versions when text is available.
- “Needs attention” feed for changed watched items.

Acceptance:

- A user can follow a project from consultation to parliamentary stage.
- The app shows the latest known stage, source, date and uncertainty.
- Stage changes are backed by source snapshots, not overwritten in place.

### Phase 4: law/domain matrix

Goal: give users the matrix view they asked for: gaps, overlaps and contradictions
inside legally meaningful areas.

Deliverables:

- Matrix dimensions:
  - domain;
  - legal hierarchy/rank: Constitution, organic law, ordinary law, government
    ordinance, emergency ordinance, government decision, ministerial order, local
    act, EU regulation/directive/decision;
  - issuer;
  - applicability date;
  - affected subject/person/institution;
  - obligation/prohibition/permission/procedure/sanction;
  - source quality: loaded, partial, missing, stale, unknown.
- Matrix rows for detected and manual issues.
- Filters for “only missing source”, “only real text loaded”, “only reviewable”.
- Drilldown from issue to exact supporting provisions and source snapshots.

Acceptance:

- A user can see one domain’s legislative map without reading every act.
- Contradictions and gaps are shown as candidates with evidence, not legal verdicts.
- Missing data is visible in the same matrix, not hidden.

### Phase 5: EU law coverage and conflict workflow

Goal: make EU checks source-backed without requiring all EU law upfront.

Deliverables:

- CELEX import by demand from official source metadata.
- Prefer official Romanian text; fallback to English with explicit label.
- Store EU source snapshots, language, date, hash and article boundaries.
- Link Romanian provisions/projects to exact EU articles.
- EU matrix states:
  - CELEX referenced but text missing;
  - CELEX text loaded;
  - article selected;
  - possible coverage;
  - possible conflict;
  - possible transposition gap;
  - reviewed.
- Report that quotes both Romanian and EU source text.

Acceptance:

- A user can import one CELEX and use it in one dossier without rebuilding the
  entire dataset.
- The app can produce a source-backed EU issue note with exact quotes.
- The app never claims compliance/non-compliance without human review.

### Phase 6: AI as drafting assistant, not legal oracle

Goal: use AI where it helps writing and summarization, while keeping legal evidence
verifiable.

Deliverables:

- AI tasks:
  - plain-language explanation;
  - summarize source changes;
  - draft issue note from selected evidence;
  - draft legislative amendment text;
  - produce reviewer checklist;
  - compare two quoted provisions for possible tension.
- Hard boundaries:
  - AI cannot invent sources;
  - AI output must reference selected source snippets;
  - AI output is labeled draft/unreviewed;
  - AI cannot mark a legal issue as accepted.
- Local AI mode for privacy-sensitive drafting where WebGPU is available.
- BYOK online mode for quality models, with keys kept client/session-side where
  possible and never committed into app data.
- Provider controls: OpenAI, Anthropic and compatible endpoints where feasible.
- Cost preview, token estimate and per-request confirmation for online AI.
- `rule-candidate-v1` from [RULE_CANDIDATES.md](RULE_CANDIDATES.md), so AI/MCP
  can propose structured obligations, prohibitions, deadlines and exceptions
  without turning them into unreviewed executable legal rules.

Acceptance:

- A user can complete a dossier using no AI.
- A user can use AI to draft better text from already selected evidence.
- AI output is traceable to evidence or clearly marked unsupported.

### Phase 7: AI quality evaluation

Goal: stop asking whether AI is reliable in the abstract; measure it.

Deliverables:

- Golden set of legislative tasks:
  - source summarization;
  - contradiction candidate explanation;
  - gap note drafting;
  - EU article comparison;
  - amendment wording draft.
- Scoring categories:
  - source faithfulness;
  - citation correctness;
  - hallucinated legal claims;
  - useful structure;
  - Romanian legal drafting quality;
  - refusal/uncertainty when evidence is missing.
- Provider/model comparison table.
- Regression test harness that can run against user-provided keys.
- “Recommended models” document based on measured results, not preference.

Acceptance:

- The app can say which AI mode is best for which task, with measurements.
- Reliability claims are scoped to tested tasks.
- Cheap models are allowed only where quality is good enough for the task.

### Phase 8: MCP integration

Goal: let users connect external tools and subscriptions without making the app pay
for all inference or storage.

Deliverables:

- MCP client boundary in the app/runtime:
  - list configured servers;
  - test connection;
  - request tool capability;
  - run a bounded tool call;
  - store audit log of the user-approved call.
- Supported MCP use cases:
  - user’s AI subscription or API provider through an MCP server;
  - file/document export to user storage;
  - calendar/task reminders for consultation deadlines;
  - source ingestion from user-provided folders;
  - optional GitHub issue/PR creation for reviewed findings.
- Permission UX:
  - show tool name, server, input data and expected output;
  - require explicit user action before sending legal text to an external MCP;
  - record what was sent.
- Local-first fallback when MCP is unavailable.

Acceptance:

- A user can connect an MCP server and run one bounded AI/document workflow.
- The app remains usable without MCP.
- No hidden data exfiltration path exists.

### Phase 9: public data distribution without huge mandatory releases

Goal: keep public deployment useful while avoiding multi-GB release churn.

Deliverables:

- Small base dataset for GitHub Pages.
- Optional source packs by domain or source family.
- Incremental update manifests.
- UI update button that can fetch only changed packs.
- Local-only user data remains separate from public source data.
- Release channels: stable, pilot, experimental.
- Checksums for every pack.

Acceptance:

- First load is small enough to be practical.
- Users can opt into larger packs only when needed.
- Updating public source data never overwrites private dossiers.

### Phase 10: operations, monitoring and trust

Goal: make the system maintainable and honest after launch.

Deliverables:

- Source freshness dashboard.
- Parser failure dashboard.
- Coverage dashboard by domain/source family.
- Security checklist for local runtime and browser mode.
- Backup/restore drill.
- Public documentation for limitations and data provenance.
- Issue templates for wrong extraction, stale source, missing source, bad AI draft
  and UX bug.

Acceptance:

- Anyone can see what data is current and what is stale.
- Failures are actionable, not buried in logs.
- Security and privacy claims are documented and test-backed.

## Definition of 100%

The app is “100%” for the intended product when all of these are true:

- A non-technical user can search, save a dossier, write a gap, attach evidence,
  draft a proposal and export it.
- Public source tracking covers the agreed source families and lifecycle stages.
- Incremental sync works for individual sources and watchlists.
- EU checks work for imported CELEX texts with official language labels.
- AI helps draft and summarize but cannot silently make legal claims.
- BYOK is available for online AI; local AI is available where hardware supports it.
- MCP is available as an optional integration surface.
- Large datasets are split into optional packs.
- Every finding has source provenance, uncertainty state and review state.
- Acceptance metrics exist for extraction, precision/recall, source freshness,
  AI faithfulness and UX-critical workflows.

## Recommended execution order

1. Manual gap workspace.
2. Incremental source registry and single-source sync.
3. Project/consultation lifecycle model.
4. Watchlists and changed-source feed.
5. Law/domain matrix.
6. On-demand EU CELEX imports.
7. Source-backed EU issue notes.
8. AI drafting from selected evidence.
9. AI evaluation harness and model comparison.
10. MCP connector boundary and first MCP workflow.
11. Optional source packs and incremental public updates.
12. Operations dashboards and final acceptance.

This order keeps the app usable at every step and avoids blocking progress on a
large all-or-nothing data release.
