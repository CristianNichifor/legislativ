# Stilul danez — ghid pentru rescrierea în limbaj clar

The plain-language rewrite (the right-hand side of the side-by-side view) restates a provision the
way a person can read it. It is **a reading aid, never the law** — it is always shown labelled as a
suggestion, next to the authoritative text, and it must not change meaning. This file is the style
it targets, and the prompt/few-shot examples the AI layer will be built on. It is deterministic in
spirit: the rules below are checkable, not a matter of taste.

## Where the style comes from

Denmark's law-drafting quality guide — Justitsministeriets **Vejledning om lovkvalitet**
(<https://lovkvalitet.dk/wp-content/uploads/sites/5/2023/11/Vejledning-om-lovkvalitet.pdf>) — states
the form should be *simple, short and precise* in word choice and style; sentences short and clear;
long and inserted clauses avoided; the main statement placed as early as possible. Provisions whose
breach carries a penalty must be phrased so citizens and businesses can understand their legal
position. Its own example: prefer `den ordning, der er nævnt i stk. 1` ("the arrangement referred to
in subsection 1") over the front-loaded `den i stk. 1 nævnte ordning`.

## The rules, applied to a Romanian rewrite

1. **One idea per sentence.** Split a long provision into several short sentences. If the original
   is a single 90-word sentence with three conditions, the rewrite is four sentences.
2. **Main statement first.** Say who does what, then the conditions and exceptions — not the other
   way round. "Autoritatea publică publică anunțul. Termenul este de 30 de zile." not "În termen de
   30 de zile de la…, în condițiile…, autoritatea publică publică anunțul."
3. **Active voice, named actor.** "Autoritatea contractantă decide", not "se decide". If the actor
   is unknown, keep the passive rather than invent one.
4. **Relative clause, not front-loaded participle.** "regimul care este prevăzut la alin. (2)", not
   "regimul prevăzut la alin. (2) menționat mai sus" — the Danish `der er nævnt` rule.
5. **Resolve short cross-references inline.** A bare "conform art. 5" becomes, where art. 5 is short,
   a one-clause statement of what it says. Long chains are named, not expanded, and flagged.
6. **Everyday words over jargon — but defined terms stay exact.** Simplify connective and procedural
   language; never paraphrase a term the act defines (`autoritate contractantă` stays verbatim).
7. **Concrete over abstract; digits for numbers.** "30 de zile", "3 ani".
8. **No double negatives.** "se aplică numai dacă" beats "nu se aplică decât dacă nu".
9. **Duties and penalties get extra clarity.** For an obligation or an offence, the rewrite states
   plainly *who* must do *what*, *by when*, and *what happens otherwise* — even at the cost of length.

## The honesty rail (non-negotiable)

- The rewrite **may not add, drop, or shift meaning.** When a faithful plain restatement is not
  possible, keep closer to the original wording rather than smooth it into something cleaner-but-wrong.
- It is **always** presented as *"limbaj clar — sugestie, nu textul legii"*, beside the authoritative
  consolidated text, never instead of it.
- It carries the provenance the rest of the package uses: the source text is `verbatim`, the rewrite
  is `assumed` (a machine's plain restatement), the strongest hedge in the vocabulary.

## Sources

- Justitsministeriet, *Vejledning om lovkvalitet* —
  <https://lovkvalitet.dk/wp-content/uploads/sites/5/2023/11/Vejledning-om-lovkvalitet.pdf>
- Overview / excerpt — <https://www.ft.dk/samling/20231/almdel/reu/bilag/59/2787337.pdf>
