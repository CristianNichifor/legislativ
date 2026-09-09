# Matrix contradiction candidates

`GET /api/matrice-contradictii?emitent=Parlamentul` compares definitions, deadlines and competences
from the selected matrix row. It accepts the matrix `tip`, `rang`, and `domeniu`
filters and a result `limita` (default 40, maximum 100).

The first detector groups the same normalized term in different acts with the
same known, heuristic domain. Different normalized definition wording produces an
unconfirmed candidate with both act IDs, provision locators, extracted text,
normative rank metadata and provision drilldown actions. Unknown domains,
same-act comparisons and equal normalized definitions are excluded.

The row action displays evidence pairs. The work dossier includes the candidates
and their limitations in the view and copied Markdown.

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

Amendment and repeal conflicts remain separate work.
