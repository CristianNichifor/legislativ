# V1 local release rehearsal

Preparation for M8, not release sign-off. No user database, network fetch,
inference API, secret inventory or paid service is accessed.

Current integrated evidence is in [v1_rehearsal_current.json](v1_rehearsal_current.json).
It exercises schema 7 -> 9 with populated reassessment, recovery, dossier metadata
and EU-link records. The dated runs below retain earlier intermediate results;
`v1_rehearsal_schema9.json` is provisional historical evidence, not the current run.

## Repeatable command

From a clean checkout with Python >=3.12 and SQLite FTS5:

```sh
python -m scripts.v1_rehearsal
python -m pytest tests/test_v1_rehearsal.py tests/test_dosare.py tests/test_propuneri.py tests/test_proposal_workflow.py tests/test_interventii_propuneri.py tests/test_analize_propuneri.py tests/test_etalon.py tests/test_etalon_real.py tests/test_consolidare_gold.py
```

The harness uses only the standard library and production modules, including its
schema-9 synthetic EU fixture. Development dependencies are needed only for pytest.
It creates a fresh `TemporaryDirectory` and deletes it even on failure. JSON goes
to stdout; assertion failures exit nonzero, including under `python -O`.
Network connection/DNS functions are blocked during the run. No model is invoked.
This is a service-layer workflow, not browser or listening-HTTP-server acceptance.

`RehearsalState` overrides only the precomputed-report loader to return explicitly
empty reports. This fixture set contains no prebuilt gap/CCR/Parliament reports.
The harness never reads ambient `web/data` or cwd report files; `date_dir` remains
unset so production local-write checks still apply. Production code is unchanged.

It builds the actual corpus through the production parser/store, generates and
reopens a real dossier report, then explicitly injects a synthetic finding to reach
structured proposal creation against authentic article text. Two immutable proposal
revisions and one revision-linked analysis are saved/reopened/exported. The newer
revision must not inherit the older analysis. Retry checks prevent duplicate saves.
The extended workflow then changes article 1 in the temporary corpus with explicit
synthetic text and saves a source reassessment against the first analysis. It checks
both exact analysis exports, including the original basis, before and after restore.
A source comparison may remain incomplete because the full-act capture is bounded;
the structured target change must still be detected. This mutation is a test control,
not authentic newly retrieved legislation.

The dossier is renamed and archived, with one editor draft, one run-linked proposal
recovery payload (including retry identity), and one deleted recovery tombstone.
All database rows must survive backup/restore. Recovery reads, archive metadata and
library listing must agree with the original database. After removing the restored
corpus, the saved reassessment must retry without recomputation, and the restored
dossier must unarchive without changing recovery records.
SQLite backup APIs preserve corpus and dossier data; fresh paths validate integrity,
foreign keys, all logical table rows and exact historical exports. Historical exports
are checked again after the restored corpus is removed. Production data is never used.
Initiative/graph databases are absent, so this is not a full deployment backup.
On schema 9 the synthetic EU database is included and compared through restore.

## Upgrade boundary

`tests/fixtures/v1_schema7.sql` freezes actual schema-7 DDL and synthetic populated
history generated using PR140 baseline `7392e5fb0c4adce022d43e54e53aa1422a84ef87`.
It has two historical proposal revisions and one retained analysis. Do not regenerate
it under a newer runtime or relabel a current database with `PRAGMA user_version=7`.

The harness restores that baseline, confirms reads do not migrate it, backs it up,
triggers the production migration with a write, and compares old named columns and
historical exports. It validates backups before and after the write. It reads
`dosare.SCHEMA_VERSION` dynamically and reports the actual version. At schema 7 this
is compatibility rehearsal only (`migration_exercised=false`). After schema 8 lands,
rerun unchanged to exercise 7-to-8 migration; failures belong to the migration owner.
This does not assert that older application binaries can read upgraded databases.

## Deployment and AI-cost inventory still required

Record status/owner/evidence, never credentials or their values. All entries below
are currently unverified for the intended deployment.

| Inventory | Required evidence before release |
| --- | --- |
| Release build | Exact integrated commit/tag, Python and SQLite/FTS5 versions, clean install and update logs, static artifact hashes. |
| Data placement | Actual corpus/initiative/graph/EU/dossier paths, schema versions, provenance, storage permissions and capacity. |
| Backup/rollback | Consistent backup of every deployed database and imported document, WAL handling, retention, restore duration and recovery point; restore to a separate location. |
| Local mode | Bind address/port, local origin protections, launch/restart behavior and offline operation. |
| Static mode | Hosting target, artifact/config versions, CSP and network dependencies; dossier persistence/local-only features are unavailable there. |
| Browser/UX | Desktop/mobile, supported browser, retry/recovery, rename/archive, unsaved drafts, navigation and sharing limitations on integrated M6. |
| AI disabled | Verify deterministic workflow needs no configured provider or key; explicitly record disabled vs untested. |
| Local AI | Presence/configuration owner of LEGISLATIV_MODEL and LEGISLATIV_MODEL_URL; endpoint locality, model/version, memory/storage/compute cost, timeout. No environment values collected here. |
| Browser BYOK | Selected provider/model, destination, session key retention/clear behavior, consent and text sent; OpenAI/Anthropic/custom worker CSP allowances are not proof of deployment. |
| Hosted services | Worker/hosting account owner, route, authentication, quotas, billing owner and logs/retention; unknown until deployment evidence is supplied. |
| Cost control | Dated price reference, currency, input/output/cached token rates, request bounds, retries, daily/monthly limits, alerts and stop mechanism. No paid probe needed for this inventory. |

Estimate only after values are supplied: requests * (input tokens * input rate +
output tokens * output rate) / billing-unit tokens, plus retry and infrastructure
costs. Keep all unknowns explicit. This work inspected repository configuration
contracts only; it did not inspect live accounts, secrets, environment or billing.

Release remains blocked on integrated workstream checks, approved M7 measurements,
real deployment inventory, actual clean-install/update/restore evidence and a manual
versioned release decision. Fixture success cannot close those gates.

## Recorded local evidence (2026-09-10)

Base commit: PR140 `7392e5fb0c4adce022d43e54e53aa1422a84ef87`, plus the files in
this acceptance-preparation commit. Python 3.14.0; SQLite 3.50.4.

| Check | Observed result |
| --- | --- |
| Rehearsal | Passed in normal Python and `python -O`; repeatability and temp cleanup also tested. |
| Fresh runtime | Passed in a new `venv` created with `with_pip=False`, running from this checkout; not a packaged deployment or hosted install. |
| Focused persistence/etalon suite | 118 passed in 12.61s. |
| Authentic pilot import | 1,457 provisions from Legea 98; 178 from Legea 208. |
| Actual report | Zero findings for issuer PARLAMENTUL; synthetic finding used for proposal workflow. |
| Saved/restored history | One dossier, two reports, two proposal revisions, two intervention snapshots and one analysis; exact exports retained. |
| Analysis states | Citations and terminology partial; compatibility, gap, CCR and projects unsupported. No legal-clear verdict. |
| Schema rehearsal | Baseline 7, runtime 7, migration_exercised=false; two baseline historical exports preserved. Schema-8 migration remains untested. |
| Synthetic etalon | 42 TP / 0 FP / 0 FN across extractor outputs; synthetic cases only. |
| Authentic S_LGI proxy | Pilot Legea 98: 570/580 (98.3%); Legea 208: zero marks, unmeasured. Full committed marked set: 811/822 (98.7%), including out-of-pilot Legea 310/2021. |
| Formatting tooling at initial run | `git diff --check` and Python syntax checks passed. Ruff was unavailable through the system Python; subsequent uv checks are recorded below. |

The initial full-suite run had 1,257 passes and seven failures: two exposed the
new manifest's missing schema, now supplied; five were sandbox-denied Unix socket
binds in multiprocessing tests (`test_banda_titluri`, `test_graf`). These failures
were not silently excluded. The subsequent full-suite result is recorded below.

Full suite rerun with local Unix socket support: **1,264 passed in 42.76s**.
No tests skipped to obtain this result. This is automated repository evidence,
not real-domain acceptance, browser acceptance or final release approval.

## Formatting follow-up (2026-09-10)

On top of `13d9925`, uv used cached dependencies and Python 3.12.12 (SQLite
3.50.4). Both requested commands completed successfully after formatting and
correcting one import-order finding:

```sh
uv run ruff format scripts/v1_rehearsal.py tests/test_v1_rehearsal.py
uv run ruff check scripts/v1_rehearsal.py tests/test_v1_rehearsal.py
uv run pytest -q tests/test_v1_rehearsal.py
uv run python -m scripts.v1_rehearsal
```

The focused rerun passed **4 tests in 6.26s**. The full 1,264-test result above
belongs to the preceding preparation run; it was not rerun for formatting changes.
The executable rehearsal passed again at schema 7. The current-result artifact
has since been replaced by the extended schema-8 run documented below.
The pilot remains proposed without a user approval response. Domain and release
acceptance remain pending; schema-8 validation awaits the integrated UX work.

## Extended history coverage (2026-09-10)

Base: `055ce49`, with `13d9925` and `b99ba6b` cherry-picked as `f3d37d9` and
`2abbd8c`, followed by this harness extension. No M5/schema-9 changes are included.
The runtime schema is still read dynamically; rerun after later integrations.
Exact current stdout: [`v1_rehearsal_current.json`](v1_rehearsal_current.json).

Observed on this exact base: schema **7 -> 8**, `migration_exercised=true`, with
both frozen baseline historical exports intact. The populated workflow retains
two analyses (original plus reassessment), one `dosare_stare` row and three `ciorne`
rows (two recoverable drafts plus one tombstone). The archived metadata revision
is 2; the restored active revision is 3. All logical rows and exact analysis exports
are compared through restore, including after the restored corpus is removed.

The reassessment reports `schimbat` and `comparatie_incompleta=true`; the synthetic
target change is detected without claiming full-act coverage. The captured isolated
run reports **0 findings**. Investigation below explains the parent's earlier count
of **1** without attributing the difference to a code change.
The pilot remains proposed; domain and release acceptance remain pending.

Validation for this extension: Ruff format/check passed; **78 tests passed in
12.27s** across `test_v1_rehearsal`, `test_surse_propuneri`,
`test_dossier_usability`, `test_analize_propuneri` and `test_dosare`.
This includes repeatability/cleanup and a negative check that dropping the recovery
table from a backup fails the rehearsal. The full-suite result earlier in this
document remains historical; it was not rerun for this extension.

## Isolation and retry correction (2026-09-10)

Reproduced on unchanged loaded service code and Python 3.12.12: running from this
worktree produced 0 findings, while changing only cwd to the integration worktree
produced 1. `Stare._incarca_raport` read the latter's `web/data/vid.json` (three
entries) and `parlament.json`. Excluding only `vid.json` restored the count to 0;
excluding only Parliament data left it at 1. Thus the extra finding came from an
ambient precomputed gap report, not the two imported corpus fixtures or Python version.

The harness-only empty report loader now produces the same captured count from
both directories. A regression test denies reads of ambient reports and passes;
before the fix it failed at `web/data/vid.json`. The JSON result explicitly records
the empty-report policy. Counts remain observations, not legal acceptance criteria.

The recovered proposal now includes all three form values and a retry fingerprint
equal to the browser's `JSON.stringify` request, preserving its request identity.
The restored SQLite payload passed the strict `restoreFindingDrafts` function read
from `96365a0:app/index.html` in Node. A retained regression test verifies the
fingerprint against Node's serialization after backup/restore; before the fix the
fingerprint was absent. This is a function-level check, not a browser UI rehearsal.

Validation: Ruff format/check passed; **80 focused tests passed in 24.55s**.
The same-code two-cwd rerun passed at schema 8 with identical finding counts.
[`v1_rehearsal_current.json`](v1_rehearsal_current.json) contains the updated result.
M5/schema-9 backup coverage is not included. Pilot and release acceptance remain pending.

## Bounded synthetic EU-link extension (2026-09-10)

The harness now imports `legaturi_ue` and `legaturi_ue_store` locally when the
runtime schema is at least 9. Earlier runtimes explicitly report
`not_exercised_requires_schema9`; missing schema-9 modules fail instead of silently
skipping. Production/M5 worktree files are not modified.

`tests.test_instantanee_ue.write` supplies a synthetic retained snapshot using the
fixture CELEX identifier `32018R1805`. Its document title, article title and distinct
body are explicitly present, satisfying the missing-body gate. The quoted obligation,
provenance, author and potential-gap hypothesis are synthetic test controls, not
authentic EU legislation or a finding about public procurement. This does not expand
the approved domain (still pending) or the authentic-source manifest.

One explicit link is saved against proposal revision 1 from a hash-bound preview.
Its complete selected history and Markdown export must survive backup; revision 2
must have no inherited link and must reject the revision-1 link ID. All dossier rows,
including exactly one `legaturi_ue` row, and all EU database rows are compared.
The restored national and EU source databases are then deleted; exact history/export
and idempotent link retry must still return the original retained result.

Validation dynamically imported this harness by absolute file path from the M5
worktree, leaving `ROOT` on these fixture files while using M5's schema-9 modules.
[`v1_rehearsal_schema9.json`](v1_rehearsal_schema9.json) retains the successful result,
runtime base commit and hashes of the six M5 source/fixture files inspected. Those
hashes were unchanged before/after capture; the M5 tree was still uncommitted, so
this is provisional runtime evidence to rerun after its final commit.

Results: **8 harness tests passed in 20.07s** under schema 9, including a negative
check that omitting the EU-link table makes restore fail. Schema-8 compatibility:
**7 passed, 1 skipped in 17.07s** (only the schema-9-specific negative test skipped).
Ruff format/check passed. Migration 7 -> 9 was exercised with both frozen historical
exports preserved, one link restored and offline retry successful. Isolated actual
report count remained 0. No network calls, inference, or legal acceptance claims.

For a dynamic rerun from the integrated runtime directory:

```sh
uv run python - <<'PY'
import importlib.util, json
spec = importlib.util.spec_from_file_location(
    "acceptance_rehearsal",
    "/tmp/legislativ-v1-rehearsal-history/scripts/v1_rehearsal.py",
)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)
print(json.dumps(harness.rehearse(), indent=2))
PY
```

## Final integrated rehearsal (2026-09-10)

The combined runtime includes M3/M4, M6 recovery-race fixes, M5 schema 9 and the
expanded rehearsal. `python -m scripts.v1_rehearsal` passed in a fresh Python
3.12.12 venv created without pip or development packages (SQLite 3.50.4).
The final EU fixture is constructed directly through `cellar.ManifestareUE` and
`cellar.scrie_celex`, with explicitly synthetic `.invalid` provenance, rather than
importing pytest helpers. A subprocess regression disables all site packages.

The current JSON records two retained analysis exports, three recovery rows
(two recoverable copies and one tombstone), archived/restored metadata and one
EU link. Exact retries and exports remain valid after source removal. Frozen
schema-7 history survives migration to 9 and pre/post-upgrade backups. Ambient
reports are excluded, all network connections are blocked and temporary data is
removed. This is a clean-runtime fixture rehearsal, not a packaged deployment,
authentic EU-law evaluation or completed M7/M8 sign-off.

Final verification: **1,333 tests passed in 64.87s**; repository-wide Ruff lint
and formatting passed. The fresh-runtime rehearsal also passed under `python -O`.
Desktop/mobile source, context, recovery and EU-link workflows passed on the
integrated app; the EU test uses a matching synthetic national corpus so the
subsequent structured proposal save does not bypass stale-target protection.
