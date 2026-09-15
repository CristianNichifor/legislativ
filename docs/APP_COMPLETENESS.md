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

## Sync capability classes

"Unsynced" covered three different situations, which made the blocker list read
as one reachable task. Each required family is now classified from the registry's
own constants, and the class says what local proof is possible at all:

| Class | Families | What a green row means |
| --- | --- | --- |
| `automated` | `parlament`, `camera`, `senat`, `consultare_econsultare`, `ue_cellar` | fetched and parsed locally, with per-source state and freshness |
| `manual_metadata` | `consultare_guvern`, `consultare_minister`, `avize`, `monitorul_oficial_pi` | an operator entered metadata rows; there is no automatic freshness |
| `anchor_only` | `legislatie_ro`, `monitorul_oficial`, `ccr` | the official entrypoint answered. Nothing more — these families are carried by `scripts.colector`, `scripts.monitor_tracker` and `scripts.decizii`, outside the registry |

Only `automated` families can be moved by syncing from the UI. `anchor_only`
families are reported under the `source_anchor_only` blocker kind rather than
`source_unsynced`, so the blocker list names work that someone can actually do.
`sync_capability_counts` in the report carries the per-class totals.

A verified anchor proves the entrypoint responds. It does not prove a single
document was ingested, and the gate now states that among its limitations.

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
