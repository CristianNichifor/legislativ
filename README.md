# legislativ

A linter for draft Romanian legislation: what a bill contradicts, what it re-names, and what the
law already required that nobody ever issued.

> **Split out of [romania-reforms](https://github.com/CristianNichifor/romania-reforms).** It began
> as a directory there and carries that history. It left because it is a different genus — those
> are simulators that take a published proposal and let a reader argue with it, published for the
> public; this reads law and reports on it, for a research team — and because a legislative corpus
> and its HTTP cache do not belong in a repository with a size gate.

It keeps that repository's rule, which is the reason the split is a move rather than a fork:
**every finding carries the document and the article it came from, and where the data does not
reach, the report says so instead of filling the gap with a plausible guess.** The vocabulary that
enforces it — `schema/provenance.schema.json`, with its three confidence levels and three
limitation severities — is vendored from there. It is a copy, copies drift, and
`tests/test_date.py` at least makes the drift loud.

## Pentru echipa de cercetare (cum se folosește)

Un singur pas, local, fără să trimită nimic în afara mașinii — proiectul lipit rămâne pe calculatorul
tău, iar verificarea nu face nicio cerere externă:

```bash
./ruleaza.sh
```

Se deschide în browser la `http://127.0.0.1:8000`. Lipești textul unui proiect de act normativ și
vezi patru lucruri, fiecare cu sursa lui: **ce atinge** (ce legi modifică și de câte ori au fost deja
amendate), **termenele** de implementare pe care le impune, **terminologia** față de termenii definiți
în lege, și **inițiativele în lucru** care s-ar putea suprapune — ca să amendezi una existentă în loc
să depui un duplicat.

Ai nevoie o singură dată de corpus (baza de legislație). Fie îl descarci, dacă a fost publicat:

```bash
scripts/ia_corpus.sh https://github.com/CristianNichifor/legislativ/releases/download/<versiune>
```

fie îl construiești local (câteva ore, o singură dată, reia de unde a rămas dacă se oprește):

```bash
uv run python -m scripts.colector --db corpus.db      # legislația
uv run python -m scripts.cdep     --db initiative.db   # inițiativele din Parlament
```

Odată colectat, îl ții la zi re-parcurgând coada — enumerarea serviciului e cronologică, așa că
legile noi apar pe pagini noi la sfârșit, iar o lege modificată sosește ca act modificator nou.
Serviciul nu are filtru „modificat după", deci actualizarea re-descoperă sfârșitul și re-colectează
coada (ultima pagină, adesea parțială, plus paginile noi), apoi reconstruiește graful:

```bash
uv run python -m scripts.colector --db corpus.db --actualizeaza --graf graf.db
```

Serviciul SOAP întoarce textul deja aplatizat — fără titluri de articol în care să te încrezi și
fără alineate — așa că pagina HTML a documentului se aduce separat, **o singură dată per document**,
și se păstrează în corpus. De acolo `parsare.py` citește arborele real de articole:

```bash
uv run python -m scripts.surse --db corpus.db                 # aduce ce lipsește
uv run python -m scripts.surse --db corpus.db --imbogateste   # structurează ce s-a adus
```

`scripts.actualizare` face ambele ca parte din rularea zilnică, plafonat, ca durata jobului să nu
depindă de cât a trecut de la ultima rulare.

Verificarea de constituționalitate rulează **fără model** și offline. Pasul care cere un model —
„are proiectul meu același viciu pentru care Curtea a lovit textul?" — rulează **doar pe mașina ta**,
fiindcă proiectul e un text nepublicat și nu pleacă nicăieri:

```bash
LEGISLATIV_MODEL=llama3.1 ./ruleaza.sh     # cu Ollama pornit local
```

Fără variabilă, pasul raportează că nu a rulat — nu că nu a găsit nimic.

Cine e offline nu re-descarcă releaseul ca să afle ce s-a publicat ieri. Copia își știe poziția,
iar pachetul e doar ce s-a scris de atunci încoace (386 de acte ≈ 2,8 MB comprimat, față de 742 MB):

```bash
uv run python -m scripts.delta versiune --db copie.db                    # unde e copia
uv run python -m scripts.delta construieste --de-la <poziție> --tinta delta.db
uv run python -m scripts.delta aplica --db copie.db --pachet delta.db --graf graf.db
```

Graful de amendamente se construiește singur din corpus la prima pornire. Cine întreține proiectul
împachetează corpusul pentru echipă cu `python -m scripts.impacheteaza` și îl atașează la un release.

---

## The ordering is the argument

A tool like this is usually built in pipeline order — scrape, parse, graph, ask a model — which
puts the least reliable output in front of the reader first. Ranked by value over risk it inverts,
and that inversion is most of what this package is:

| | pass | needs a model | what it costs to be wrong |
| --- | --- | --- | --- |
| 1 | **Unfulfilled obligations** | no | nothing: every row is a date and a failed search, checkable on the spot |
| 2 | **Terminology** | no | ten seconds of a drafter's attention |
| 3 | **Contradictions** | yes | a researcher repeating an invented article in committee |

**The first pass is the one to lead a demo with.** Romanian primary legislation habitually
delegates its own operation — *în termen de 30 de zile de la data intrării în vigoare, Guvernul
aprobă normele metodologice* — and whether those norms were ever issued is a fact about the corpus
rather than a judgement about it. It needs no model, it cannot hallucinate, and an implementing act
that was legally due in 2016 and does not exist is a finding that survives being checked in public.

**The third pass is the one that needs a fence around it.** A small local model working in legal
Romanian will produce fluent, well-formatted, correctly-typed findings about articles that do not
exist. `scripts/validare.py` is the gate: a finding is dropped unless the provision it cites was in
the prompt, the quote appears verbatim in that provision, and the quote is long enough to check.
Rejections are reported, not swallowed — the rejection rate is the only honest measurement of
whether a given model can be trusted on this corpus, and a validator that hid it would make a bad
model look like a quiet one.

## What is measured

`data/etalon.json` is 36 hand-annotated cases; `uv run python -m scripts.etalon` scores the deterministic
extractors against it and names every case that fails.

```
extractor       precizie  acoperire      F1   tp/fp/fn
--------------------------------------------------------------
acte             100.0%     100.0%    1.00   10/0/0
amendamente      100.0%     100.0%    1.00   15/0/0
articole_noi     100.0%     100.0%    1.00   1/0/0
obligatii        100.0%     100.0%    1.00   10/0/0
referinte        100.0%      83.3%    0.91   5/0/1
--------------------------------------------------------------
TOTAL            100.0%      97.6%    0.99   41/0/1
```

**And a second number, measured against truth this project did not write.** `python -m
scripts.etalon_real` checks reference extraction against the portal's own `S_LGI` marks — the
Ministry wraps every citation it recognises in the running text, so those spans are an independent
answer key. Over two citation-dense real laws (822 marks): **97,2% recall**. The synthetic set
guards precision and the amendment and deadline extractors; this guards reference recall against
real law. Neither alone is the measurement.

**Read that number with the discount it deserves.** The cases are written in the register of
Romanian legislative drafting, but they were written by the same hand as the patterns and none of
them came off the portal. It measures whether the extractors do what they were designed to do; it
does not measure how much of the real corpus they cover, and the real figure will be lower. The
first honest number arrives with the first hundred sentences sampled from actual acts, and
replacing this set with those is the highest-value hour anyone can spend on this package.

**The set keeps its failures — and keeps the cases once they pass.** `ref-10` — article
enumerations, *la articolele 7 și 8* — was the standing known miss. The locators now expand an
enumeration, so it passes and stays in the set as a green case; `cunoscut_ratat` remains for the
next real miss. The set therefore currently reads 100%, which is the number to distrust most: it
says the extractors do not fail on 36 sentences written to exercise them, not that they cover the
corpus. What stops that number being bought by deletion is that cases are never removed — the
tests put a floor on the count — and the caveat above stands unchanged.

**A third number, for the report that matters most.** The gap report — obligations the corpus
cannot show were discharged — is derived from corpus text, so it is honest but unvalidated. The
Consiliul Legislativ / SGG publish the answer key: *Situația normelor neîndeplinite*, the official
list of implementing norms that were mandated and never issued. `scripts.neindeplinite` imports
that list from a file (the tool stays offline) and compares it to the derived report, at the level
of the host act:

```
uv run python -m scripts.neindeplinite --lista lista_oficiala.csv --corpus corpus.db --graf graf.db
```

It reports coverage — of the authority's outstanding norms whose host act the corpus actually
holds, the fraction the tool independently flags — and names both the misses and the acts it
cannot judge because they are not yet collected. That last set is kept out of the fraction on
purpose: an act the scrape has not reached is not a disagreement with the authority, and scoring it
as one would be the same confident-but-wrong output the whole package is built to avoid. The format
is documented in `data/neindeplinite_exemplu.csv`; the committed rows there are illustrative, not
the authority's list.

## What the gold set caught

Every one of these looked right on the page and none was found by reading the pattern:

- **`articolului` did not match a pattern written for `articolul`.** Romanian declines, and
  `alineatul (3) al articolului 8` came out as a paragraph belonging to no article — so an
  abrogation of one paragraph read as the repeal of the whole of article 8.
- **`se înlocuiește` did not match its own pattern.** The singular was spelled `înlocuiesc?`, which
  matches `înlocuiesc` and `înlocuies` and not the form actually used — so every global substitution
  of a phrase, which silently rewrites dozens of articles at once, went unrecorded.
- **Derogations lost the article they derogate from**, becoming derogations from an entire law.
- **The terminology check did the opposite of its job.** It flagged `o autoritate contractantă` and
  `autorități contractante` — an article and a plural — and stayed silent on `achiziții de stat`,
  the drafting error it exists for. Romanian inflection is not drift, so comparison now runs on
  stems (`scripts/text.py: radacina`).
- **One label in the gold set was wrong, and was corrected rather than the extractor.** `se emite
  hotărârea Guvernului` was annotated as naming no institution; a Government decision is issued by
  the Government. Correcting the annotation is legitimate; correcting the annotation *because the
  extractor disagreed with it* would not have been, and the case note records which happened.

## The corpus

`legislatie.just.ro` is the only source, and it offers **an official free web service** — the right
way in. That was checked rather than assumed: **N-Lex** proxies its Romanian search straight back to
the same portal, neither **data.europa.eu** nor **data.gov.ro** carries Romanian legislation as text,
and Romania publishes no `data.europa.eu` ELI for it. The two existing clients — the government's own
`govro/legislatie-just-python-soap-client` (2015, MIT) and the newer `ro-eli-mcp` — both wrap this
same service; both were read for the contract and neither is a dependency this package takes.

**The API is the spine.** `scripts/api.py` speaks its SOAP directly — `GetToken`, then paged
`Search` — with the standard library and no SOAP stack, because the service speaks one fixed dialect
and two envelopes are less to reason about than `suds`. It needs no registration, returns records
with the full text inline, and carries `DataVigoare`, **the in-force date the HTML search will not
filter by**. Getting it working meant learning three things by calling it: the endpoint is
`.svc/SOAP`, a named binding (posting to `.svc` or `?wsdl` is a 404); it has **no act-type filter**,
so a search for number 98 returns the DECRET, the HG and the ORDIN that share it, and scoping to the
six normative types is done client-side; and results come **ten to a page**, so a year is hundreds of
pages.

**The HTML is enrichment, not spine.** The API's `Text` is flattened — no `S_ART`, no `S_LGI`. So
article-level locators and the publisher's own reference marks still come from the `DetaliiDocument`
HTML that `parsare.py` reads, for the acts that need parsing to that depth. Two sources, each for
what it is best at: the API to know the corpus and stay current, the HTML to read one act deeply.

The HTML path also carries a constraint worth keeping: the portal answers an honest identifying
`User-Agent` and refuses a bare one, and it does not answer GitHub Actions runners — so the corpus is
built locally and committed, never fetched in CI.

### What collecting all 25 156 pages cost, and what it taught

The first full walk took two hours and produced 205 321 documents. Three defects surfaced only at
that scale, and each was silent — the collector stayed up, the log stayed quiet, and the corpus
stopped being correct. They are recorded here because each looked like something else first.

**The token dies at ~114 requests and says so with `HTTP 500`.** Not a SOAP fault, so
`TokenExpired` — which is parsed out of a fault body — never fires, and a caller that treats 500 as
a transient server error retries a token the service has already discarded, forever. Two runs sat at
zero throughput looking healthy: 0.02 s of CPU in two minutes, hundreds of sockets in `CLOSE-WAIT`,
no traceback. Measured directly: 114 searches at ~0.5 s, then 500 on every call with that token,
then 0.6 s on a fresh one. `Client` now rotates the token at 100 requests and still treats a 500 as
refresh-once-and-retry.

**A citation key is not a document identity.** `acte.id` is `tip-numar-an`, which is what a drafter
writes — and ministries number their ordine from 1 each year, so it collides constantly. Writing
every record into `acte` meant the second erased the first: 19 975 records written, 15 014
surviving, a quarter of the collection deleted by namesakes. `documente` now keeps every record
under its portal id; `acte` stays the citation view. `rezumat()` reports the collision count so it
can never be invisible again.

**`DELETE FROM provizii_fts WHERE act_id = ?` is a full scan.** `act_id` is `UNINDEXED` inside the
fts5 table, correctly — nobody full-text-searches an id — but that leaves the delete no index, and
it runs once per record written. Measured mid-collection: 65 ms per scan at 18 000 rows, ten records
to a page, so two thirds of every page was this one statement, and the cost grows with the corpus
being built. Projected at the full 251 460 documents: 9.1 s per page, or roughly 32 hours of
collection that gets slower the whole way. A rowid map (`provizii_fts_rand`) made the delete an
indexed lookup; collection went from 53 to 173 pages a minute on the spot.

**The rate is measured, not assumed.** With those fixed: 2 workers → 173 pages/min, 0 × 503;
3 workers → 230, 0 × 503; 4 workers → 280, but **51 × 503 in four minutes**. `colector.py` already
says a run that provokes 503s is collecting slower than one that stays under the limit — the backoff
eats the gain — quite apart from being rude to a ministry's server. Three workers and a 0.2 s pause
is the fastest point that does not.

What one page yields, verified on Legea nr. 98/2016 (`sources/lege-98-2016.html.gz`):

| | |
| --- | --- |
| designation, issuer, publication date | `S_DEN`, `S_EMT_BDY`, `S_PUB_BDY` |
| **246 articles**, 724 alineate, 465 litere | `S_ART` / `S_ALN` / `S_LIT`, nested |
| 1 435 addressable provisions | one row per level, so a finding can quote any of them |
| 512 publisher-marked citations | `S_LGI` spans |
| four relation flags | `ActiuniInduse`, `Actiunisuferite`, `Referape`, `Referitde` |

**246 is the portal's own count, and the parser is checked against it** rather than against a number
written down here — the same discipline the court importer next door uses.

**`S_LGI` is the find worth naming.** The portal wraps every citation it recognises in the running
text in a span. It does not resolve them, so `referinte.py` still decides *which* act is meant — but
it means reference *positions* arrive marked by the publisher. That is recall ground truth over real
documents, which is the one thing the gold set below cannot buy.

**Neither portal number identifies the act.** Requesting document `178667` returns a page whose own
`id_act` reads `290673`. The first is a search handle, the second a consolidated form; the act is
`lege-98-2016`, which is what the law calls itself and what every citation in every other act uses.
Both portal numbers are stored — one to refetch by, one to audit by — and neither is a key.

**Stored in SQLite**, because `sqlite3` is standard library and the corpus therefore costs no
dependency. FTS5 gives diacritic-insensitive search, so `hotarare` finds `hotărâre` — which matters
when half the corpus was typed before the comma-below letters were reliably available. A graph
database was the obvious alternative and loses on this corpus: the deepest question anyone asks is
*what points at this act and what does it point at*, which is two indexed selects.

## What is not here

**A collector.** `scripts/api.py` talks to the portal's official web service and
`scripts/depozit.py` stores what it returns, but nothing yet loops over the whole corpus. That
loop is the next piece, and the constraint it must respect is already in the schema: the `cache`
table exists so a document is fetched **once, ever**. This reads a ministry's server on behalf of a
political party, and the number of times it asks for the same act should be one.

**The Court's case law after 2004.** `decizii.py` and `neconstitutional.py` read what the
Constituțională struck and report what nobody repaired, but they read the corpus that exists: 231
decisions, all of them between 1992 and 2004, because the chronological collector has not been run
past 2008. The Court has issued tens of thousands since. **The register is therefore a working
mechanism over a fifth of a percent of the material, not an answer to "what is still
unconstitutional in Romanian law".** Every row it emits says `blocking` for that reason, and it
will keep saying so until `--complet-pentru` can honestly name a type the collector finished.

**Whether a 1990s strike survived recourse.** Until the 2003 revision a decision could be appealed
to the plenum within ten days, and 24 decisions in this corpus admit such an appeal. `decizii.py`
records whether a decision says it became final; it does not resolve *which earlier decision* a
recourse overturned, because the corpus keys decisions by year of publication while the text cites
them by year of pronouncement, and the two differ. Until that is resolved, an unfinalised strike is
`blocking` rather than quietly counted.

**Consolidation.** The package records that article 7(2) changed on a date and by which act. It does
not apply the amendment and compute what the article now says. That is a separate problem with its
own failure modes, and warning an MP that they are citing a provision which has moved is already the
job.

**Republication renumbering, remapped.** Republication renumbers an act's articles, so a reference
to `art. 15` means different provisions before and after. `consolidare.py` refuses to apply a
pre-republication operation across that boundary and `vigoare.py` qualifies rather than asserts a
repeal that crosses it — but neither *remaps* a locator, because nothing in the corpus carries the
old-to-new correspondence. Until something does, the boundary is a place where the tool says "this
may not be the same provision", not one it can see through.

(Article enumerations were the other entry here. `la articolele 7 și 8` now reads as both
articles; `ref-10` in the gold set is green.)

**A corpus.** `data/exemplu.json` is a four-provision fixture written in the register of Romanian
legislation to put the pipeline in motion. Prose in that register is quotable as though it were the
law, so the warning that it is not travels as a `blocking` limitation in the shared vocabulary
rather than as a field of its own, and both the schema and a test require it to stay there. It gets
thrown away the moment the parser reads real pages.

Both data files declare a `$schema` under `schema/` and are validated by `tests/test_date.py`.
Their provenance confidence is `assumed`, which is the accurate label: neither came from a source
document, and `assumed` is defined as *not in any source document yet*.

## Running it

```bash
uv sync --all-groups
uv run pytest -q                  # 372 tests
uv run python -m scripts.etalon   # precision / recall, with the failures named
uv run python -m scripts.linter   # the worked example

# What the Constituțională struck and nobody repaired, over the collected corpus:
uv run python -m scripts.neconstitutional --db corpus.db --graf graf.db
```

**No runtime dependencies.** Every extractor is `re`, `difflib` and `datetime`; the parser is
`html.parser` and the corpus is `sqlite3` — all standard library. The layer that decides what a law
says should not be the layer that needs a wheel to build, and a legal corpus is not the place to
discover that two HTML libraries disagree about where a tag ends. `jsonschema` is a dev dependency
only: a document is validated when it is written, not every time it is read.

A model client, when there is one, brings its own and does not belong in this package:
`analizeaza(..., model=...)` takes any callable from prompt to string, so Ollama, a free-tier
endpoint and a recorded fixture are the same shape.

## The modules

| | |
| --- | --- |
| `text.py` | Cedilla folding, superscript article numbers, the stemmer. Everything downstream assumes it ran. |
| `referinte.py` | Which act, which provision. Nominative and genitive, dotted thousands, three-level locators. |
| `amendamente.py` | What one act does to another. Chapeau inheritance lives here; captures the quoted replacement text an amendment supplies. |
| `termene.py` | Obligations with a deadline and an anchor. |
| `vid.py` | Obligations the corpus cannot show were discharged. |
| `consolidare.py` | A provision's text as of a date, spliced from the parsed tree — or an honest refusal when a change would not apply cleanly. Reads operations off an amending page (`operatii_amendatoare`). Gold-tested against the portal's own consolidated view (`docs/CONSOLIDARE.md`). |
| `consolidat.py` | The consolidation surface: an act's touched provisions with attribution, from locally synced pages. Pluggable source (fixtures now, a hosted consolidated DB later). |
| `sugestii.py` | While a draft is written: the legistic form of the line, plain restatement plus the Legea 24/2000 formula. Deterministic, no model. |
| `compunere.py` | Legislation as code: a list of structured intents compiled into a whole amending act — and verified by reading it back through the extractor. |
| `definitii.py` | An act's own definition articles, and drafts that talk around them. |
| `validare.py` | The gate between a model's output and a reader. |
| `etalon.py` | Precision and recall, with the failures named. |
| `linter.py` | The three reports, in the order they should be trusted. |
| `api.py` | The official SOAP web service: `GetToken`, paged `Search`, full text and in-force date. |
| `parsare.py` | One portal page into an act: designation, issuer, publication, the article tree, and the `S_CIT` replacement blocks an amending act carries. |
| `depozit.py` | The corpus: SQLite, full-text search, and a fetch-once cache. |
| `api.py` | The official SOAP web service: `GetToken`, paged `Search`, full text and in-force date. |
| `colector.py` | Walks the whole corpus through the API — polite, resumable, keep-all; `--actualizeaza` re-walks the tail to stay current. |
| `cdep.py` | Pending initiatives from the Chamber of Deputies, with their Senate id. |
| `dublura.py` | Does a new draft duplicate a bill already moving — shared amendment target first. |
| `analiza.py` | The extractors over the live corpus: a deadline inventory and a term dictionary. |
| `graf.py` | The amendment graph, derived from the corpus text — who amends and references each act. |
| `etalon_real.py` | Reference recall vs the portal's own S_LGI marks — the number measured against real law. |
| `vigoare.py` | In force or not: repeals from the graph, and drafts that cite a repealed article. |
| `imbogateste.py` | Index of which acts each pending initiative touches — "who is already on this law". |
| `redactare.py` | Legistic drafting form (Legea 24/2000): flags intent said the wrong way, generates the right way. |
| `neindeplinite.py` | The authority's list of unfulfilled norms, imported from a file, compared to the derived gap report. |
| `vid_corpus.py` | The gap report over real law: obligations × graph, blocking until the corpus vouches. |
| `publicare.py` | The Monitorul Oficial line from an act's own text: issue number, publication date, whether it is a republication. `--db` re-reads a whole corpus. |
| `supraveghere.sh` | Keeps a collection moving: restarts the collector if it stops committing pages, at a measured concurrency that does not draw 503s. |
| `decizii.py` | What a Curtea Constituțională decision decided, read from its dispozitiv: solution per point, provisions struck, the referral's object, and whether the Court ranged beyond it. |
| `neconstitutional.py` | Struck provisions the corpus cannot show were ever brought into line — the art. 147 (1) register. |
| `coliziune.py` | A draft against that register: does the article you are touching sit on a provision the Court struck and nobody repaired. Graded by reach; only a direct hit the corpus can vouch for is allowed to block. |
| `opinie.py` | The one pass that needs a model: does the draft have the defect the Court found. Retrieval is done by the deterministic layers, so the model reasons over a fixed dictionary and never searches; `validare.py` drops anything citing outside it. On-device or not at all, and a pass that did not run says so. |
| `temeiuri.py` | On what constitutional ground a provision was struck, read from the Court's own reasoning. Separates a violation the Court stated from an article merely argued about, excludes the Court's own competence articles, and names articles under the numbering in force when the decision was given — the 2003 revision moved property from art. 41 to 44. |
| `reluare.py` | Does the draft *re-enact* struck wording — the art. 147 (4) question, which a citation check cannot see because a draft can repass a struck rule while citing nothing. Character 5-grams, containment plus a size guard, calibrated against the noise floor of legistic boilerplate. Never blocking. |
| `prevedere.py` | The text of a struck provision, recovered from the containing act — codes resolved to the version in force when they were struck. Falls back to the article, labelled, and never guesses an alineat the source flattened away. |
| `delta.py` | The increment an offline copy needs: acts written since its stated position, with their provisions, relations, strikes and graph edges. A day's law is a couple of megabytes against a 742 MB release. Replaces act by act, never deletes, and applying twice changes nothing. |
| `surse.py` | The portal's own document pages, fetched once and kept, so the article tree is read from `S_ART`/`S_ALN`/`S_LIT` instead of from flattened text. Asked-for-once, like every other pass. |
| `servicii.py` | The engine-facing services (one per question the UI asks), with no transport attached — so localhost and the browser build call the same functions. |
| `server.py` | The localhost transport: `http.server` over `servicii.py`, plus the UI. Verify a draft, redactează a new one, search, consolidate, and a zoomable connections graph. |
| `construieste_web.py` | Builds the browser build — the same app under Pyodide, no server, draft never leaves the tab (`web/README.md`). |
| `shard.py` | Turns a corpus into fetch-on-demand search shards: a compact act index, a prefix-sharded inverted index, one provisions file per act. |
| `cauta_web.py` | The browser's search: fold-identical to the shard builder, it fetches only the shards a query's tokens need — coverage of the corpus, download of the query. |

## The documents

| | |
| --- | --- |
| [`docs/DESIGN.md`](docs/DESIGN.md) | The design system: USR's palette and typeface, where each token came from, and the two brand values that are deliberately not used as published because they fail WCAG AA as text. Read this before changing a colour. |
| [`docs/STIL_DANEZ.md`](docs/STIL_DANEZ.md) | The style the plain-language rewrite targets, taken from Denmark's law-drafting quality guide — and the honesty rail: a rewrite may not add, drop or shift meaning, and is never shown as the law. |
| [`docs/CONSOLIDARE.md`](docs/CONSOLIDARE.md) | How a provision's text as of a date is spliced, and what makes `consolidare.py` refuse rather than guess. |
| [`docs/DISCLOSURE.md`](docs/DISCLOSURE.md) | A responsible-disclosure draft for defects found incidentally in `legislatie.just.ro` while reading public law through it. **Unsent** — it is addressed to the portal's technical contact and is for the maintainer to send, from an address they control. |
