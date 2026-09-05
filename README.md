# legislativ

A linter for draft Romanian legislation: what a bill contradicts, what it re-names, and what the
law already required that nobody ever issued.

> **Nu e un simulator.** Everything else under `simulators/` takes a published proposal and lets a
> reader argue with it. This reads law and reports on it, which is a different genus. It lives here
> because this is where the repository keeps self-contained applications with their own pyproject,
> tests and data, and inventing a second top-level home for a single occupant is how a directory
> tree starts to rot. If a second tool of this kind appears, the two of them can move together.

It runs on the same rule as the rest of the repository: **every finding carries the document and
the article it came from, and where the data does not reach, the report says so instead of filling
the gap with a plausible guess.**

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

`data/etalon.json` is 36 hand-annotated cases; `python -m scripts.etalon` scores the deterministic
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

## What is not here

**The parser.** `scripts/parsare.py` is a stub that raises. `legislatie.just.ro` was not reachable
from the environment this was written in, so nothing here has seen the portal's markup, and a parser
written against imagined markup is the most expensive thing a project like this can carry: it looks
finished, its invented fixtures pass, and it fails on the first real page. `ActParsat` is the
contract the rest of the package consumes — fill it from real HTML and everything downstream runs
unchanged. Two things worth settling in the same ten minutes, because both change the design rather
than the code: whether a document id addresses an act or a *version* of one (if it is versions,
walking an id range returns the same law at six dates with nothing marking which is in force), and
what `robots.txt` says. This is a tool for a political party; a prototype assembled by hammering a
Ministry of Justice server is a story that gets told about the party rather than about the tool.

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
law, so the warning that it is not travels as a `blocking` limitation in
`packages/provenance`'s vocabulary rather than as a field of its own — it means the same thing here
as in every dataset in the repository, and both the schema and a test require it to stay there. It
gets thrown away the moment the parser reads real pages.

Both data files declare a `$schema` under `schema/`, and both are validated by the repository-wide
gate in `scripts/validate_data.py` along with the other 322 documents. Their provenance confidence
is `assumed`, which is the accurate label: neither came from a source document, and `assumed` is
defined in this repository as *not in any source document yet*.

## Running it

```bash
cd simulators/legislativ
uv run --no-project --with pytest python -m pytest tests -q   # 75 tests
uv run --no-project python -m scripts.etalon                  # precision / recall
uv run --no-project python -m scripts.linter                  # the worked example
```

No dependencies. Every extractor is `re`, `difflib` and `datetime` — the layer that decides what a
law says should not be the layer that needs a wheel to build. A model client, when there is one,
brings its own and does not belong in this package: `analizeaza(..., model=...)` takes any callable
from prompt to string, so Ollama, a free-tier endpoint and a recorded fixture are the same shape.

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
| `parsare.py` | The contract for the stage that is not written. |

Data files live under `data/` with their schemas in `schema/`, the same shape as every other
simulator here, so the repository-wide validation gate covers them.
