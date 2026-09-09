# V1 local release rehearsal

Preparation for M8, not release sign-off. No user database, network fetch,
inference API, secret inventory or paid service is accessed.

## Repeatable command

From a clean checkout with Python >=3.12 and SQLite FTS5:

```sh
python -m scripts.v1_rehearsal
python -m pytest tests/test_v1_rehearsal.py tests/test_dosare.py tests/test_propuneri.py tests/test_proposal_workflow.py tests/test_interventii_propuneri.py tests/test_analize_propuneri.py tests/test_etalon.py tests/test_etalon_real.py tests/test_consolidare_gold.py
```

The harness uses the standard library only; pytest is a development dependency.
It creates a fresh `TemporaryDirectory` and deletes it even on failure. JSON goes
to stdout; assertion failures exit nonzero, including under `python -O`.
Network connection/DNS functions are blocked during the run. No model is invoked.
This is a service-layer workflow, not browser or listening-HTTP-server acceptance.

It builds the actual corpus through the production parser/store, generates and
reopens a real dossier report, then explicitly injects a synthetic finding to reach
structured proposal creation against authentic article text. Two immutable proposal
revisions and one revision-linked analysis are saved/reopened/exported. The newer
revision must not inherit the older analysis. Retry checks prevent duplicate saves.
SQLite backup APIs preserve corpus and dossier data; fresh paths validate integrity,
foreign keys, all logical table rows and exact historical exports. Historical exports
are checked again after the restored corpus is removed. Production data is never used.
Optional initiative/graph/EU databases are absent, so this is not a full deployment backup.

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
The executable rehearsal passed again; its exact stdout is retained in
[`v1_rehearsal_current.json`](v1_rehearsal_current.json). This is the schema-7
fixture result from this follow-up, not a live or integrated schema-8 result.
The pilot remains proposed without a user approval response. Domain and release
acceptance remain pending; schema-8 validation awaits the integrated UX work.
