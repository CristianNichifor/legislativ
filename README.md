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

**Read that number with the discount it deserves.** The cases are written in the register of
Romanian legislative drafting, but they were written by the same hand as the patterns and none of
them came off the portal. It measures whether the extractors do what they were designed to do; it
does not measure how much of the real corpus they cover, and the real figure will be lower. The
first honest number arrives with the first hundred sentences sampled from actual acts, and
replacing this set with those is the highest-value hour anyone can spend on this package.

**The set keeps its failures.** `ref-10` — article enumerations, *la articolele 7 și 8* — is not
expanded, is marked `cunoscut_ratat`, and is left in. A gold set curated until it reports 100%
reports nothing.

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

**Consolidation.** The package records that article 7(2) changed on a date and by which act. It does
not apply the amendment and compute what the article now says. That is a separate problem with its
own failure modes, and warning an MP that they are citing a provision which has moved is already the
job.

**Article enumerations, and republication renumbering.** The first is a known miss in the gold set.
The second is a hole with no marker yet: republication renumbers an act's articles, so a reference
to `art. 15` means different provisions before and after, and `ActParsat.republicat_din` exists to
carry the date but nothing consumes it.

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
uv run pytest -q                  # 108 tests
uv run python -m scripts.etalon   # precision / recall, with the failures named
uv run python -m scripts.linter   # the worked example
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
| `amendamente.py` | What one act does to another. Chapeau inheritance lives here. |
| `termene.py` | Obligations with a deadline and an anchor. |
| `vid.py` | Obligations the corpus cannot show were discharged. |
| `definitii.py` | An act's own definition articles, and drafts that talk around them. |
| `validare.py` | The gate between a model's output and a reader. |
| `etalon.py` | Precision and recall, with the failures named. |
| `linter.py` | The three reports, in the order they should be trusted. |
| `api.py` | The official SOAP web service: `GetToken`, paged `Search`, full text and in-force date. |
| `parsare.py` | One portal page into an act: designation, issuer, publication, and the article tree. |
| `depozit.py` | The corpus: SQLite, full-text search, and a fetch-once cache. |
| `api.py` | The official SOAP web service: `GetToken`, paged `Search`, full text and in-force date. |
| `colector.py` | Walks the whole corpus through the API — polite, resumable, keep-all. |
| `cdep.py` | Pending initiatives from the Chamber of Deputies, with their Senate id. |
| `dublura.py` | Does a new draft duplicate a bill already moving — shared amendment target first. |
| `analiza.py` | The extractors over the live corpus: a deadline inventory and a term dictionary. |
| `graf.py` | The amendment graph, derived from the corpus text — who amends and references each act. |
| `server.py` | A stdlib backend and a paste-a-draft UI over all three deterministic passes. |
