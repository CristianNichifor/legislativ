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
  "source_metadata": {
    "celex": "32014L0024",
    "celex_url": "http://publications.europa.eu/resource/celex/32014L0024",
    "item_url": "https://publications.europa.eu/resource/cellar/.../DOC_1",
    "work_uri": "http://publications.europa.eu/resource/cellar/...",
    "expression_uri": "http://publications.europa.eu/resource/cellar/...",
    "manifestation_uri": "http://publications.europa.eu/resource/cellar/...",
    "language": "RON",
    "format": "xhtml",
    "title": "...",
    "document_date": "2014-02-26",
    "legal_type_uri": "...",
    "in_force": true,
    "read_at": "2026-09-13T...",
    "text_sha256": "<sha256 of stored extracted text>"
  },
  "manifestari": {
    "total": 3,
    "languages": {"RON": 2, "ENG": 1},
    "readable": [
      {
        "language": "RON",
        "format": "xhtml",
        "item_url": "https://publications.europa.eu/resource/cellar/.../DOC_1",
        "title": "..."
      }
    ],
    "readable_truncated": false
  },
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
  "source_metadata": null,
  "manifestari": {
    "total": 1,
    "languages": {"RON": 1},
    "readable": [],
    "readable_truncated": false
  },
  "snapshot": null,
  "source_hash": ""
}
```

Unavailable response:

```json
{
  "contract": "celex-on-demand-source-v1",
  "celex": "32014L0024",
  "stare": "indisponibil",
  "language_state": "language_unavailable",
  "source_metadata": null,
  "manifestari": {
    "total": 0,
    "languages": {},
    "readable": [],
    "readable_truncated": false
  },
  "snapshot": null,
  "source_hash": ""
}
```

## Boundaries

- The endpoint is available only in the local app because it performs live network acquisition.
- GitHub Pages/static mode returns a local-only error for this route.
- The importer stores official source metadata and extracted text; it does not produce a legal
  compatibility verdict.
- The import response exposes enough provenance for the UI to show the CELEX reference URL, selected
  official stream URL, Cellar manifestation identity, language/fallback state, extracted-text hash,
  and article/provision boundaries immediately after one import.
- Failed imports keep the last good local text and record the attempt without exposing local paths or
  private transport errors to the client.

## EU issue workflow

The dossier EU note builder may call `/api/ue/import` before article selection. The user can paste a
CELEX id or an official URL, choose `RON,ENG` or `ENG,RON`, then select the retained snapshot and one
parsed article. The selected article is passed to `ro-eu-issue-note-v1` together with a Romanian
corpus provision or imported parliamentary project version.

This is an evidence workflow only: the saved dossier note records `possible_conflict`,
`possible_gap` or `possible_coverage`, source URLs, hashes, language/fallback metadata and explicit
uncertainty. It never records a compliance verdict.
