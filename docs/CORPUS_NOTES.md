# The corpus: field notes

Why the source is what it is, what a full walk cost, and the three defects that only appeared at
scale. Kept because each one looked like something else first.

## One source, checked rather than assumed

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

## What collecting all 25 156 pages cost, and what it taught

The first full walk took two hours and produced 205 321 documents. Three defects surfaced only at
that scale, and each was silent — the collector stayed up, the log stayed quiet, and the corpus
stopped being correct.

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

## What one page yields

Verified on Legea nr. 98/2016 (`sources/lege-98-2016.html.gz`):

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
documents, which is the one thing a hand-written gold set cannot buy.

**Neither portal number identifies the act.** Requesting document `178667` returns a page whose own
`id_act` reads `290673`. The first is a search handle, the second a consolidated form; the act is
`lege-98-2016`, which is what the law calls itself and what every citation in every other act uses.
Both portal numbers are stored — one to refetch by, one to audit by — and neither is a key.

**Stored in SQLite**, because `sqlite3` is standard library and the corpus therefore costs no
dependency. FTS5 gives diacritic-insensitive search, so `hotarare` finds `hotărâre` — which matters
when half the corpus was typed before the comma-below letters were reliably available. A graph
database was the obvious alternative and loses on this corpus: the deepest question anyone asks is
*what points at this act and what does it point at*, which is two indexed selects.

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

## How the extractors are measured

`data/etalon.json` is 36 hand-annotated cases; `uv run python -m scripts.etalon` scores the
deterministic extractors against it and names every case that fails.

**A second number, measured against truth this project did not write.** `python -m
scripts.etalon_real` checks reference extraction against the portal's own `S_LGI` marks. Over two
citation-dense real laws (822 marks): **97,2% recall**. The synthetic set guards precision and the
amendment and deadline extractors; this guards reference recall against real law. Neither alone is
the measurement.

**Read the synthetic number with the discount it deserves.** The cases are written in the register of
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

```bash
uv run python -m scripts.neindeplinite --lista lista_oficiala.csv --corpus corpus.db --graf graf.db
```

It reports coverage — of the authority's outstanding norms whose host act the corpus actually
holds, the fraction the tool independently flags — and names both the misses and the acts it
cannot judge because they are not yet collected. That last set is kept out of the fraction on
purpose: an act the scrape has not reached is not a disagreement with the authority, and scoring it
as one would be the same confident-but-wrong output the whole package is built to avoid. The format
is documented in `data/neindeplinite_exemplu.csv`; the committed rows there are illustrative, not
the authority's list.

## The fixture that is not a corpus

`data/exemplu.json` is a four-provision fixture written in the register of Romanian legislation to
put the pipeline in motion. Prose in that register is quotable as though it were the law, so the
warning that it is not travels as a `blocking` limitation in the shared vocabulary rather than as a
field of its own, and both the schema and a test require it to stay there. It gets thrown away the
moment the parser reads real pages.

Both data files declare a `$schema` under `schema/` and are validated by `tests/test_date.py`.
Their provenance confidence is `assumed`, which is the accurate label: neither came from a source
document, and `assumed` is defined as *not in any source document yet*.
