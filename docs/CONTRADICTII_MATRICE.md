# Matrix contradiction candidates

`GET /api/matrice-contradictii?emitent=Parlamentul` compares extracted definitions
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
5000 extracted definitions. `trunchiat` identifies partial results, including
result-limit overflow or unavailable corpus data. Counters describe the selected
acts and provisions actually visited; they are not a whole-corpus conflict count.
The existing extractor recognizes only supported definition patterns and may
shorten extracted definitions. Open the source provision to inspect full context.

Text differences can be lawful because scope, exceptions or effective dates
differ. This detector does not establish simultaneous applicability, resolve
hierarchy, or infer organic-law status. Human legal review is required. No result
does not establish compatibility. No model or paid API is called.

Further detectors for deadlines, authority competence and amendment conflicts
remain separate work.
