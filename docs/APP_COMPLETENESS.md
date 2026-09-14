# App completeness gate

`scripts/app_completeness.py` is the final product acceptance/status gate. It
does not mark the app complete unless every required user-visible capability is
`ready`.

Run the report:

```bash
python -m scripts.app_completeness
```

Run it as a release-blocking gate:

```bash
python -m scripts.app_completeness --require-complete
```

`--require-complete` exits non-zero while any required capability is `partial`
or `missing`. That is intentional: partial workflows may be useful, but they
must not be converted into a product-complete claim.

## Required capabilities

The gate checks one report contract, `app-completeness-gate-v1`, covering:

- local data separation;
- public source data availability;
- dossier workflow;
- matrix-to-dossier flow;
- lifecycle tracking;
- EU issue note;
- AI/MCP bounded draft;
- export, backup and restore;
- no hidden legal verdicts.

## Current truth

The gate is expected to report `blocked` until public source coverage and
lifecycle freshness are proven against the actual local runtime data. Bounded
vertical workflows can pass before that happens.

Use **Adaugă sursele oficiale de bază** in the source registry, or call
`POST /api/source-registry` with `{"action":"bootstrap"}`, to register the
required official source-family entrypoints. That removes the “missing family”
class of blocker, but the gate still reports `blocked` while those families are
only `unsynced`. A registered source family is not the same as current legal
data.

The report is also exposed in the UI through **Gate produs** and over HTTP at:

```text
/api/app-completeness
```

The older acceptance dashboard remains a supporting read-only status view. The
completeness gate is stricter and is the one to use before claiming final
product acceptance.

## Local runtime acceptance

Use the same persistent data directory as the local app when checking a real
install:

```bash
python -m scripts.app_completeness --data-home ~/.local/share/legislativ
```

To close the official-source anchor gate for that install, run the bounded
availability verifier before the report:

```bash
python -m scripts.app_completeness --data-home ~/.local/share/legislativ --sync-source-anchors --require-complete
```

This verifies each official family entrypoint and stores only the bounded
availability snapshot in the local source registry. It does not crawl large
datasets, upload private dossiers, call AI or mark legal coverage as complete
without the visible limitations in the report.
