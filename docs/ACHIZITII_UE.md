# EU source acquisition

The Drept UE tab connects each CELEX import-queue row to a source panel. A CELEX
can also be entered directly, including one already imported. Opening the panel
reads local state only. Import/update and retry are explicit commands; they do
not run an AI model, modify the editor, or recalculate or change saved dossiers.

## Language and state

The importer uses existing Cellar metadata and text extraction, preferring a
readable official Romanian manifestation and then English. The fallback is labeled
explicitly and is not machine translation. Romanian PDF-only metadata can coexist
with an English text import. A failed Romanian download is an error, not proof
that Romanian is unavailable and not permission to silently fall back to English.

The panel separates no import, metadata without readable text, usable local text,
and an unverifiable local observation. Latest-attempt errors can coexist with a
usable previous text. Discovery metadata is retained even if text acquisition
fails. No compatible manifestation produces a metadata-only result, not a new
empty act. PDF parsing/OCR is not added in this batch.

Current and historical text show CELEX, official stream/reference links, language,
retrieval time and extracted-text SHA-256. Historical observations are not certified
legal versions, and retrieval dates do not establish freshness or applicability.

## API and persistence

- `GET /api/ue/surse?celex=...`: local metadata, last attempt, current observation
  summary and 20 archived observations per page (`offset`, maximum 100000).
- `GET /api/ue/surse?celex=...&instantanee=...`: bounded retained text; validates
  CELEX ownership, snapshot identity and text hash. Older databases with current
  text but no archive remain readable without backfilling on GET.
- `POST /api/ue/surse`: accepts exactly `{"celex":"32014L0024"}`. Identifiers are
  canonical uppercase CELEX tokens, not arbitrary URLs, paths or language options.

The endpoints require localhost Host and matching Origin when present; requests
are bounded at 16 KB and responses are no-store. Static builds return an explicit
unavailable response. Readers use escaped read-only SQLite URIs, no DDL, and a
bounded inventory-query budget. An absent file is not created by reading it.

Explicit writes use `eu.db`, adding `eu_achizitii` lazily for the latest attempt
per CELEX and the previous successful text-retrieval date. This is not a full job
log, nor a retrospective log of CLI imports. Metadata discovery, including a
metadata-only outcome, does not overwrite the previous text-success timestamp.
Interrupted processes can leave refreshed metadata without a final attempt record.

Existing append-only `eu_instantanee` archives preserve text, language, provenance
and hashes before/after updates. Current text, provision/FTS replacement, archive
and success status commit together; failures preserve the previous text. Identical
text and provenance do not create another observation or advance its original
retrieval time; the attempt-success time advances instead. There is one interactive
import at a time per server process. Separate CLI/server processes still use SQLite
transactions; this is not a distributed acquisition scheduler.

## Download bounds

The HTTP acquisition adapter permits only publications.europa.eu, op.europa.eu and
eur-lex.europa.eu, upgrades official HTTP links to HTTPS, disables proxies and
validates every redirect before following it. URLs with credentials, alternate
ports, controls or backslashes are rejected. Callers cannot configure the opener.

Limits are 20 requests including redirects, 10 document parts, 2 MiB metadata,
8 MiB per text response, 16 MiB total and a 90-second deadline checked between
reads; individual blocking socket operations have at most a 15-second timeout.
Non-identity Content-Encoding is rejected. Retained snapshots have the existing
8 MB bound. Every selected part must download and parse successfully. No partial
multipart result replaces the previous text. Unsupported encodings, malformed
metadata and download/extraction failures produce bounded, non-sensitive errors.

The CLI retains its existing transport/partial-document policy; these additional
transport and all-parts requirements apply to the new HTTP acquisition path.
No automated legal-compatibility claims or production-source availability claims
are introduced. Tests use deterministic official-shaped metadata/text fixtures.
