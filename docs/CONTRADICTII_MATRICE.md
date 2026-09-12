# Matrix contradiction candidates

`GET /api/matrice-contradictii?emitent=Parlamentul` compares definitions, deadlines and competences
from the selected matrix row. It accepts the matrix `tip`, `rang`, and `domeniu`
filters and a result `limita` (default 40, maximum 100).

`GET /api/matrice` also accepts `source_quality=current|attention|queued|missing|unknown`.
The source-quality axis reads the local source registry for Romanian legislative
portal sources. It does not fetch official portals. A row can therefore be used
as a work queue for missing source records, failed/changed sources, queued sources
or acts whose local source record is current. `GET /api/matrice-acte` and
`GET /api/matrice-dosar` preserve the same filter, so a missing-source matrix row
lists the exact acts still missing local source provenance.

The first detector groups the same normalized term in different acts with the
same known, heuristic domain. Different normalized definition wording produces an
unconfirmed candidate with both act IDs, provision locators, extracted text,
normative rank metadata and provision drilldown actions. Unknown domains,
same-act comparisons and equal normalized definitions are excluded.

The row action displays evidence pairs. The work dossier includes the candidates
and their limitations in the view and copied Markdown.

## Graph/matrix scaffold

`GET /api/matrice-graf?emitent=Parlamentul` exposes the same selected matrix row
as law-as-code candidate material. It reuses the matrix `tip`, `rang`, `domeniu`
and `source_quality` filters, then returns:

- `nodes`: selected acts with `act_id`, citation key, title, rank, heuristic
  domain, source URL and local source-quality state;
- `edges`: graph rows touching those acts, including source act/provision,
  target act/provision, relation kind, extraction confidence and drilldown actions;
- `graph_state`: `ok` or `indisponibil`, so a missing graph is visible instead
  of being mistaken for no relationships.

Every edge is marked `relatie_candidata_neconfirmata`. This endpoint is a
developer/user inspection scaffold for future provision graphs, domain matrices
and rule candidates. It does not decide contradiction, compatibility,
applicability, hierarchy or whether a provision is suitable for executable legal
rules. Source state comes from the local registry and no official portal is
refetched.

Coverage is bounded to the newest 100 matching acts, 1000 provisions per act and
5000 extracted definitions and 5000 comparable deadlines. `trunchiat` identifies partial results, including
result-limit overflow or unavailable corpus data. Counters describe the selected
acts and provisions actually visited; they are not a whole-corpus conflict count.
The existing extractor recognizes only supported definition patterns and may
shorten extracted definitions. Open the source provision to inspect full context.

Text differences can be lawful because scope, exceptions or effective dates
differ. This detector does not establish simultaneous applicability, resolve
hierarchy, or infer organic-law status. Human legal review is required. No result
does not establish compatibility. No model or paid API is called.

## Deadline candidates

`termen_divergent` candidates compare single-obligation provisions with an explicit
responsible party, supported action verb, object and event after `de la`.
The normalized wording must match after removing the duration and initial article
header. Different subjects, objects, actions or triggering events do not match.
Only different acts in the selected row and the same known domain are compared.

Numeric and supported spelled-out quantities are recognized using the existing
deadline numeral vocabulary. Units are preserved: one month is not converted to
30 days, nor one year to 365 days. Different explicit working/calendar day bases
produce a candidate even at equal quantities. An unspecified basis is retained;
it is never assumed to mean calendar days and alone does not produce a candidate.

The detector excludes missing/ambiguous anchors, references to an act's own
publication or entry into force, local article references, explicit exceptions,
conditional/permissive wording and provisions with multiple deadlines. Its narrow
grammar can miss real conflicts, including differently worded equivalent duties.
Matching trigger wording does not establish the same real-world event or scope.

Each pair includes full provision text, exact deadline wording, quantity, unit,
day basis, trigger and source actions. The UI and Markdown dossier include review
prompts for scope, exceptions, event identity and counting rules. Coverage counter
`termene_analizate` counts accepted comparable deadlines, not every deadline in
the corpus. Both detector types share the response limit.

## Authority overlap candidates

`competenta_suprapusa` compares different named authorities assigned the same
action and complete object wording in different acts of the same known domain
and selected matrix row. It accepts a narrow, single-sentence present-tense
grammar. Original provision text, authority names and source drilldowns appear
in the matrix and copied dossier, with status `candidat_neconfirmat`.

Joint actions, explicit consultation/approval/delegation clauses, exceptions and
conditional/permissive wording are excluded. Generic roles such as the competent
authority are excluded, as are local/regional/territorial names (including names
using `din`). Territorial qualifiers in the object remain part of the matching
key: different territories do not match. Same authority or same-act pairs are
excluded. Institutional aliases and historical renamings are not resolved.

Only explicit wording in the analyzed provision is checked. Scope, shared roles,
delegations or territorial divisions defined elsewhere can still make a candidate
legitimate. Review prompts cover those cases and effective versions. No inference
of exclusive jurisdiction or final contradiction is made. The detector can miss
equivalent duties expressed differently and named institutions outside its grammar.

`atributii_analizate` counts accepted comparable competences, capped at 5000.
All detector types share the result limit and `trunchiat` partial-coverage flag.

## Conflicts between pending drafts

The matrix row's `Compară proiecte` action lists initiatives from its target index
using `GET /api/matrice-proiecte`. Select two different initiatives and paste their
draft texts, then submit to `POST /api/conflicte-proiecte` with `emitent`, optional
matrix filters, `plx_a`, `plx_b`, `text_a`, and `text_b`.

The database currently holds initiative metadata and target references, not full
draft texts. Supplied texts are transient and their association with an official
draft version is a user assertion. No document is fetched or saved, and no model
is called. Status and source links come from stored metadata and may be stale.
Rejected, withdrawn, promulgated, closed and unknown/empty-status initiatives are
excluded according to the existing terminal-status markers (empty status is also
excluded). The server rechecks eligibility on every comparison.

The existing amendment extractor supplies explicit or inherited act targets,
locators, operation spans and quoted payloads. Only selected-row acts are eligible.
The comparison detects repeal versus modification (including repeal of an ancestor
provision), different quoted replacements at the same locator, and duplicate new
article/paragraph numbering. An insertion is matched on its new locator, not the
preceding provision. Unknown targets, missing replacement payloads and ambiguous
multi-article insertions cannot establish those candidate types. Letter/point
insertions are outside this first slice. No effective-date ordering is inferred.

Limits: newest 100 matching acts; 500 indexed initiatives; 60,000 characters per
supplied text; first 200 extracted operations per text; 40 result pairs. Partial
coverage is labelled. The result includes both operation texts, target provision
drilldown, parliamentary status and collection timestamps, alongside the existing
matrix dossier. Copy/print includes the transient findings and their limitations.
An empty result does not establish compatibility.

## Official document imports (local application)

Each comparison input has a `Documente oficiale` action. It discovers PDF/DOCX
links on the stored initiative's Chamber page, including official Senate links
present there. Source labels and adjacent row descriptions are preserved: users
must select the appropriate draft/version, as pages also contain opinions and
reports. Legacy `.doc` and indirect download links are outside this slice.

`GET /api/documente-proiect?plx=...` lists discovered documents and up to 100 local
snapshots. `POST /api/importa-proiect` accepts `plx` plus a discovered `url`, or
`plx` plus an existing `versiune` ID to reopen a snapshot. Every fresh import
rechecks that the link belongs to the initiative page. Only exact official CDEP
and Senate HTTPS hosts are fetched; redirects are checked, proxies are disabled,
downloads are bounded (2 MB pages, 10 MB files) and socket timeouts apply.

Snapshots live in a separate database beside the initiative database, using the
suffix `.documente.db`. They retain original bytes, extracted text, source URL,
label, SHA-256 and first retrieval time. Identical bytes at the same initiative/URL
reuse the snapshot; changed bytes create a new version without replacing history.
Local versions remain available if the remote page is temporarily unavailable.

PDF extraction uses installed Poppler `pdftotext`; on Debian/Ubuntu install
`poppler-utils`. DOCX uses the existing bounded reader. Extraction runs in a fresh
POSIX child with CPU, address-space and output-file limits and a parent timeout.
Pages with fewer than 20 word characters are conservatively marked as needing
OCR/manual inspection; that can also include intentionally blank pages. OCR is
not performed. Images, existing OCR mistakes and complex layout can still require
manual verification. Such flagged snapshots cannot feed comparison directly.

Successful imports fill the textarea and display provenance. Editing the text
clears the selected snapshot. Comparison with `versiune_a`/`versiune_b` reloads
stored text and validates initiative ownership, rather than trusting client text
or a client-supplied hash. The dossier preserves the source, timestamp and hash.
The existing 60,000-character comparison ceiling still applies without truncation.

The static Pyodide build keeps pasted-text comparison but reports official import
as a local-app feature. No background refresh, automatic document selection,
Senate-page crawling or version alerts are implemented in this slice.
# Comparația versiunilor importate

În aplicația locală, „Documente oficiale” permite alegerea a două importuri ale
aceleiași inițiative, în ordinea explicită „Înainte” / „După”. Comparația arată
unitățile adăugate, eliminate și modificate, aliniate numai după numărul scris al
articolului; preambulul este păstrat. Spațiile sunt ignorate la egalitate, dar nu
literele mari, diacriticele sau numerele. Textul nu este o concluzie juridică.

Articolele lipsă ori duplicate declanșează comparația documentelor integrale.
Textele identice la numere diferite sunt semnalate drept posibilă renumerotare,
nu realiniate automat. Erorile de extragere PDF rămân de verificat; importurile
care necesită OCR nu pot fi comparate. Sursele diferite pot fi documente de tipuri
diferite, iar momentul importului nu stabilește ordinea parlamentară.

Raportul include schimbările în mulțimile de ținte de amendare, termene explicite
și autorități recunoscute de gramaticile existente, nu o inventariere exhaustivă.
Mențiunile repetate nu sunt numărate. Exportul Markdown include ambele URL-uri,
momentele importului și hash-urile SHA-256. Limite: 60000 caractere pe document,
100 de unități schimbate afișate (cu total și avertisment), 2000 de tokenuri pe
unitate pentru evidențiere; peste această limită textul integral rămâne vizibil.

„Verifică actualizări” revalidează prezența URL-ului ales pe fișa oficială și
compară hash-ul octeților descărcați cu importul „După”. Octeții neschimbați
reutilizează importul; octeții diferiți păstrează o versiune separată. O schimbare
de fișier nu implică neapărat o schimbare de text. Istoricul și textul din editor
nu sunt suprascrise. Nu există monitorizare automată sau urmărirea automată a
unui link înlocuit. Aceste operații nu sunt disponibile în versiunea statică.
