# The modules

What each module in `scripts/` is for. The ordering is thematic, not alphabetical: text and
references first, then what an act does to another act, then the corpus, then the sources, then the
surfaces that render all of it.

## Text, references, extraction

| | |
| --- | --- |
| `text.py` | Cedilla folding, superscript article numbers, the stemmer. Everything downstream assumes it ran. |
| `referinte.py` | Which act, which provision. Nominative and genitive, dotted thousands, three-level locators. |
| `amendamente.py` | What one act does to another. Chapeau inheritance lives here; captures the quoted replacement text an amendment supplies. |
| `termene.py` | Obligations with a deadline and an anchor. |
| `vid.py` | Obligations the corpus cannot show were discharged. |
| `definitii.py` | An act's own definition articles, and drafts that talk around them. |
| `nomenclator.py` | The named acts: from what a citation calls them to what the corpus stored. |
| `ancore.py` | Where a citation sits in a passage, so a reader can follow it without leaving the sentence. |
| `publicare.py` | The Monitorul Oficial line from an act's own text: issue number, publication date, whether it is a republication. `--db` re-reads a whole corpus. |

## Consolidation, drafting, law as code

| | |
| --- | --- |
| `consolidare.py` | A provision's text as of a date, spliced from the parsed tree — or an honest refusal when a change would not apply cleanly. Reads operations off an amending page (`operatii_amendatoare`). Gold-tested against the portal's own consolidated view ([CONSOLIDARE.md](CONSOLIDARE.md)). |
| `consolidat.py` | The consolidation surface: an act's touched provisions with attribution, from locally synced pages. Pluggable source (fixtures now, a hosted consolidated DB later). |
| `sugestii.py` | While a draft is written: the legistic form of the line, plain restatement plus the Legea 24/2000 formula. Deterministic, no model. |
| `redactare.py` | Legistic drafting form (Legea 24/2000): flags intent said the wrong way, generates the right way. |
| `norma.py` | Which drafting norm a passage is written in, and whether a project mixes the two. |
| `compunere.py` | Legislation as code: a list of structured intents compiled into a whole amending act — and verified by reading it back through the extractor. |
| `lac.py` | Legislation as code: a provision written as a rule, checked and rendered like one. |
| `parsare_text.py` | The plain text of an act into the block tree the Redactează editor draws. |

## Constitutional layer

| | |
| --- | --- |
| `decizii.py` | What a Curtea Constituțională decision decided, read from its dispozitiv: solution per point, provisions struck, the referral's object, and whether the Court ranged beyond it. |
| `lovituri.py` | What each decision put out of force, extracted once and kept. |
| `neconstitutional.py` | Struck provisions the corpus cannot show were ever brought into line — the art. 147 (1) register. |
| `coliziune.py` | A draft against that register: does the article you are touching sit on a provision the Court struck and nobody repaired. Graded by reach; only a direct hit the corpus can vouch for is allowed to block. |
| `temeiuri.py` | On what constitutional ground a provision was struck, read from the Court's own reasoning. Separates a violation the Court stated from an article merely argued about, excludes the Court's own competence articles, and names articles under the numbering in force when the decision was given — the 2003 revision moved property from art. 41 to 44. |
| `reluare.py` | Does the draft *re-enact* struck wording — the art. 147 (4) question, which a citation check cannot see because a draft can repass a struck rule while citing nothing. Character 5-grams, containment plus a size guard, calibrated against the noise floor of legistic boilerplate. Never blocking. |
| `prevedere.py` | The text of a struck provision, recovered from the containing act — codes resolved to the version in force when they were struck. Falls back to the article, labelled, and never guesses an alineat the source flattened away. |
| `opinie.py` | The one pass that needs a model: does the draft have the defect the Court found. Retrieval is done by the deterministic layers, so the model reasons over a fixed dictionary and never searches; `validare.py` drops anything citing outside it. On-device or not at all, and a pass that did not run says so. |

## The corpus and its sources

| | |
| --- | --- |
| `api.py` | The official SOAP web service: `GetToken`, paged `Search`, full text and in-force date. |
| `parsare.py` | One portal page into an act: designation, issuer, publication, the article tree, and the `S_CIT` replacement blocks an amending act carries. |
| `depozit.py` | The corpus: SQLite, full-text search, and a fetch-once cache. |
| `colector.py` | Walks the whole corpus through the API — polite, resumable, keep-all; `--actualizeaza` re-walks the tail to stay current. |
| `surse.py` | The portal's own document pages, fetched once and kept, so the article tree is read from `S_ART`/`S_ALN`/`S_LIT` instead of from flattened text. Asked-for-once, like every other pass. |
| `graf.py` | The amendment graph, derived from the corpus text — who amends and references each act. |
| `vigoare.py` | In force or not: repeals from the graph, and drafts that cite a repealed article. |
| `impact.py` | Raza de impact: the true downstream reach of an amendment, so a small change with a large blast radius is visible before it is made. |
| `domenii.py` | The corpus grouped by the body that issued it. By issuer and not by subject: the portal publishes no classification of any kind, and inventing one would present a guess as something read. |
| `omonime.py` | What to call an act when several claim the same name. `hg-1-2016` is eighteen different acts by eighteen different bodies; keying `acte` on the citation deleted seventeen of them. The one a bare citation means keeps the bare id, the rest take the portal's own document id. |
| `curatare.py` | One-off repairs to text already collected: the service's block markers, the byte-order mark in titles, and the `ș`/`ț` the API cannot spell — it encodes in a charset without them and emits a literal `?`, in 55% of the corpus. |
| `ritm.py` | A ceiling on requests per second, shared by every worker. Concurrency and politeness are separate dials: connections sharing one clock multiply throughput, connections that each sleep multiply load. |
| `supraveghere.sh` | Keeps a collection moving: restarts the collector if it stops committing pages, at a measured concurrency that does not draw 503s. |

## Parliament

| | |
| --- | --- |
| `cdep.py` | Pending initiatives from the Chamber of Deputies, with their Senate id. |
| `parcurs.py` | How a bill actually moved: who proposed it, which committees were asked and what they said, and how the room voted. Read off the Chamber's Fișa; nothing inferred that the page does not say. |
| `stenograme.py` | The debate itself, at the item it was held under. Each speaker carries the same (legislature, chamber, id) their profile is keyed on, so a speech joins to the person through the Chamber's id and never through the name. |
| `deputati.py` | What a member has put their name to. Identity is (legislature, chamber, id) — `idm` alone covered 1 044 people with 349 values. A signature is not authorship and a bill without a recorded vote is not a defeat. |
| `dublura.py` | Does a new draft duplicate a bill already moving — shared amendment target first. |
| `imbogateste.py` | Index of which acts each pending initiative touches — "who is already on this law". |

## Measurement and gates

| | |
| --- | --- |
| `validare.py` | The gate between a model's output and a reader. |
| `etalon.py` | Precision and recall, with the failures named. |
| `etalon_real.py` | Reference recall vs the portal's own `S_LGI` marks — the number measured against real law. |
| `neindeplinite.py` | The authority's list of unfulfilled norms, imported from a file, compared to the derived gap report. |
| `vid_corpus.py` | The gap report over real law: obligations × graph, blocking until the corpus vouches. |
| `analiza.py` | The extractors over the live corpus: a deadline inventory and a term dictionary. |
| `linter.py` | The three reports, in the order they should be trusted. |
| `inventar_surse.py` | Read-only inventory of the databases actually present locally. |
| `app_completeness.py` | The final product acceptance gate ([APP_COMPLETENESS.md](APP_COMPLETENESS.md)). |

## Surfaces and distribution

| | |
| --- | --- |
| `servicii.py` | The engine-facing services (one per question the UI asks), with no transport attached — so localhost and the browser build call the same functions. |
| `server.py` | The localhost transport: `http.server` over `servicii.py`, plus the UI. Verify a draft, redactează a new one, search, consolidate, a zoomable connections graph, who made the law, and a watchlist that opens each bill's passage — its sponsors, its votes, and the debate at the sitting item the step points at. Read-only, so it runs while the corpus fills. |
| `construieste_web.py` | Builds the browser build — the same app under Pyodide, no server, draft never leaves the tab (`web/README.md`). |
| `shard.py` | Turns a corpus into fetch-on-demand search shards: a compact act index, a prefix-sharded inverted index, one provisions file per act. |
| `cauta_web.py` | The browser's search: fold-identical to the shard builder, it fetches only the shards a query's tokens need — coverage of the corpus, download of the query. |
| `delta.py` | The increment an offline copy needs: acts written since its stated position, with their provisions, relations, strikes and graph edges. A day's law is a couple of megabytes against a 742 MB release. Replaces act by act, never deletes, and applying twice changes nothing. |
| `distributie.py` | A corpus to hand someone, cut from the corpus of record. |
| `impacheteaza.py` | Package the built corpus for the research team. |
| `actualizare.py` | Bring a collected corpus up to today, in the time a daily job can afford. |
| `fonturi.py` | Vendor the three typefaces into `app/fonts/`, subset to the alphabet this app actually sets. |

This table covers the modules worth knowing by name. `scripts/` holds more — registry, lifecycle,
dossier, EU-link and acceptance modules that belong to the v1 workflow surfaces and are documented
where those workflows are: [DOSARE.md](DOSARE.md), [SOURCE_SYNC.md](SOURCE_SYNC.md),
[LIFECYCLE_WATCHLIST.md](LIFECYCLE_WATCHLIST.md), [LEGATURI_UE.md](LEGATURI_UE.md).
