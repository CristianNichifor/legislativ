# On-demand CELEX source import

Contract: `celex-on-demand-source-v1`

This is the local-only foundation for importing one EU law source by CELEX or a CELEX-bearing URL.
It fetches official Cellar metadata, prefers Romanian (`RON`), falls back to English (`ENG`) when a
compatible Romanian text stream is unavailable, stores the selected text in `eu.db`, and exposes
snapshot/hash metadata for later review.

## Endpoint

`POST /api/ue/import`

The existing `POST /api/ue/surse` route remains supported for the current UI. New code should use
`/api/ue/import` when the action is an explicit source import.

Request:

```json
{
  "identifier": "32014L0024",
  "limbi": ["RON", "ENG"]
}
```

`identifier` may also be an EUR-Lex/Publications Office URL containing a CELEX id. `celex` is still
accepted as a compatibility alias. `limbi` is optional and defaults to `["RON", "ENG"]`.

Successful text response:

```json
{
  "contract": "celex-on-demand-source-v1",
  "source_identifier": "32014L0024",
  "celex": "32014L0024",
  "stare": "ok",
  "language_preference": ["RON", "ENG"],
  "selected_language": "RON",
  "selected_language_label": "romana oficiala",
  "language_fallback": false,
  "source_hash": "<sha256 of stored extracted text>",
  "snapshot": {
    "id": "<snapshot id>",
    "text_sha256": "<sha256 of stored extracted text>",
    "source_hash": "<sha256 of stored extracted text>"
  }
}
```

Metadata-only response:

```json
{
  "contract": "celex-on-demand-source-v1",
  "celex": "32014L0024",
  "stare": "metadate",
  "snapshot": null,
  "source_hash": ""
}
```

## Boundaries

- The endpoint is available only in the local app because it performs live network acquisition.
- GitHub Pages/static mode returns a local-only error for this route.
- The importer stores official source metadata and extracted text; it does not produce a legal
  compatibility verdict.
- Failed imports keep the last good local text and record the attempt without exposing local paths or
  private transport errors to the client.
