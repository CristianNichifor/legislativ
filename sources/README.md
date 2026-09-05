# sources

Empty on purpose, and this file records what belongs here so the first person with network access
does not have to guess.

Save the raw pages here, one file per document, named by the id they were fetched under. Three are
enough to write `scripts/parsare.py` against, and they should not be three of the same kind:

- a plain law that amends nothing,
- an amending act, so the chapeau and its numbered points are real rather than reconstructed,
- a republished act, because republication renumbers articles and that is the case nothing in the
  package can currently see.

They are fixtures as much as sources: once the parser exists, its tests read these files, and a
parser tested only against markup invented alongside it is a parser that has never been tested.

Keep whatever the fetch returned, unedited — the cedilla spellings and the superscript article
numbers that `scripts/text.py` folds are exactly the details a tidied-up copy loses.

One thing to know before saving them: `.gitignore` drops `sources/*.html`, because scraped pages
are normally re-fetchable and large. Fixtures are the exception that rule was not written for — a
parser test against a page nobody else can fetch is not a test. Un-ignore the ones you keep,
explicitly and by name, and say in the exception why that page had to be kept.

## What is actually here

- `lege-98-2016.html.gz` — a large substantive law, and the portal's *consolidated* form of it.
- `decizie-815-2015.html.gz` — a Curtea Constituțională decision, `S_PAR` all the way down, no
  article tree; the case that proves the parser does not return empty for a document without one.
- `lege-310-2021.html.gz` — another substantive law (anti-doping), a second plain page.
- `lege-208-2022.html.gz` — **the amending act.** It amends Legea 98/2016 and wraps each
  replacement in an `S_CIT` block, so the chapeau, the numbered points and the replacement payloads
  are real. It is the answer key for consolidation: `tests/test_consolidare_gold.py` checks that a
  replacement it supplies equals the portal's consolidated text of the provision it rewrote. The
  first three did not include an amending act — this is the one the list above asked for.

Still missing from the list: a **republished** act, for the renumbering case nothing in the package
can yet see.
