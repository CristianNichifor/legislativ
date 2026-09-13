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

The report is also exposed in the UI through **Gate produs** and over HTTP at:

```text
/api/app-completeness
```

The older acceptance dashboard remains a supporting read-only status view. The
completeness gate is stricter and is the one to use before claiming final
product acceptance.
