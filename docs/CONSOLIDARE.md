# Consolidation — the text of the law as it stands today

## The gap

Every layer of this package reasons over acts **as published**. The parser reads the 2016 text of
Legea 98/2016; the graph records that a 2023 act modified its article 7; `vigoare.py` knows article
15 was repealed. What nothing knows is **what article 7 says now**. The graph has the edge and the
date; it does not have the resulting text.

That is the difference between "here is the original" and "here is the law today", and it is the
one question a person drafting or citing a provision actually has. Consolidation is the layer that
answers it: given a provision and a date, return the text in force on that date, with every change
attributed to the act that made it.

It is also the keystone the rest of the design already leans toward. With it, the linter checks a
draft against live text rather than the original; search returns the current wording of a
provision, not a superseded one; `redactare` cites the current `cuprins`. Without it, each of those
silently reasons over text that may be years out of date.

## Why this is done carefully, not quickly

Applying an amendment wrong does not produce a hedged finding — it produces a **confident, fluent,
wrong statement of the law**, which is the exact failure this whole repository is built to avoid. A
consolidated article that looks authoritative and is subtly incorrect is worse than no consolidated
article at all, because a reader cannot tell by looking. So the governing rule is the same one that
governs `vid.py` and the gold set:

> **Consolidate a provision only when every amendment touching it applied cleanly. Otherwise return
> the original text and a `blocking` limitation naming the amendments that could not be applied.**

Never splice partial. A provision touched by five amendments where four parsed and one did not is
returned *un*-consolidated, with "4 of 5 changes applied automatically; read
`{act}` for the fifth." Silence about the fifth is how the tool starts lying.

## The contract

```
consolideaza(provizie, operatii, la_data) -> Rezultat
```

- `provizie` — the original text of one provision (an article, an alineat) with its locator.
- `operatii` — the amendments whose target is this provision, each with an operation
  (`modifica` / `abroga` / `completeaza` / `introduce`), a date it took effect, the amending act,
  and — for the operations that supply new text — the **replacement payload**, verbatim.
- `la_data` — the date to consolidate as of; operations after it are not applied.

`Rezultat` carries the resulting text, the provenance of each change (which act, which date), and a
tuple of limitations. `complet` is true only when every operation up to `la_data` applied; when it
is false the text field is the *original*, untouched, and the limitations say why.

Provenance is the repository's existing vocabulary. The replacement payload is `verbatim` (it is a
literal quotation from the amending act). The claim "this is the text as of {date}" is `derived` —
it is the result of applying operations, not a string that appears anywhere in a source document.

## The layers, and where each stands

| Layer | State |
| --- | --- |
| Target + operation + effective **date** of each amendment | exists — `graf.py` edges carry `de_la`, `amendamente.py` the target and verb |
| The **replacement payload** (the quoted new text) | **the first gap** — `amendamente.Amendament` records the operation but not the text it substitutes |
| A **provision tree** to splice into | only the HTML parse has it (`parsare.py`: `S_ART`/`S_ALN`/`S_LIT`); the flat SOAP text the collector stores has no structure below the whole document |
| The **splice engine** — apply operations in date order → text as of a date | new (`consolidare.py`) |
| The **honesty rail** — refuse to splice when any operation did not parse | part of the engine, non-negotiable |

## Data implication: on demand, per act — never the corpus

The splice needs a provision tree, and only the HTML parse produces one. The collector stores the
API's flat text, which has no article structure. So consolidation does **not** run over the stored
corpus; it fetches and parses the HTML of the **one act a user is looking at** (`parsare.din_fisier`
over the fetched page), consolidates the provision in view, and discards the tree. Consolidating
251 000 acts eagerly would be a different project with a different risk profile; consolidating the
one article on screen is bounded and is what a drafter needs.

## Scope — the honest first slice

Deliberately small, because correctness compounds and each operation type has its own failure modes:

**In the first slice**
- One act, article and alineat level.
- `modifica` (replace the provision's text with the payload) and `abroga` (mark the provision
  repealed, keep the shell with its repeal date).
- Operations applied in date order; `la_data` cutoff.
- The honesty rail: any operation missing a clean (locator, op, payload) leaves the provision
  original and `blocking`.

**Deferred, and named as deferred so the silence is not mistaken for coverage**
- `introduce` with renumbering (inserting art. 7^1 shifts nothing, but inserting between and
  renumbering does — and renumbering is where consolidation engines go wrong).
- `completeaza` that appends rather than replaces.
- Global substitutions (`se înlocuiește sintagma X cu Y` across the whole act).
- Amendments to tables, annexes, and structural units above the article.

Each deferred case must produce a `blocking` limitation when encountered, never a silent pass.

## Measurement

The portal publishes its **own** consolidated view of each act (the "formă consolidată"). That is
the answer key, exactly as `S_LGI` was for reference recall: consolidate a provision the tool
believes it can, diff the result against the portal's consolidated text of the same provision, and
report agreement. A committed before/after fixture (an article of a real act plus the later act that
amended it, and the portal's consolidated result) makes the number reproducible and lets CI hold it.

## Phases

1. **Payload extraction** — `amendamente.py` captures the quoted replacement/inserted text. Small,
   self-contained, `verbatim`, and independently useful (a finding can quote the new wording).
2. **The engine** — `consolidare.py`: apply operations to a provision in date order with the rail,
   over plain provision/operation structures. Unit-tested without any HTML.
3. **The tree + the gold test** — wire `parsare`'s article tree in as the provision source, add the
   before/after fixture, diff against the portal's consolidated view, hold it in CI.
4. **Surface it** — the product shows the consolidated provision with each change attributed, and
   the linter checks drafts against consolidated rather than original text.

This document is the plan; phases 1 and 2 land with it.
