"""The honest number: extraction measured against the publisher's own marks.

`etalon.py` scores the extractors on thirty-six sentences written by the same hand that wrote the
patterns. That measures whether they do what they were designed to do; it cannot measure how much
of real law they catch, because there is no independent truth in it. This module supplies the
independent truth: the portal wraps every legislative reference it recognises in the running text
in an `S_LGI` span, so those spans are the Ministry's own answer key, and this checks the
extractor against it over real acts.

**Recall against `S_LGI`, on committed fixtures.** For every span the publisher marked, did
`referinte.py` find a reference overlapping it. The acts are the ones already saved in `sources/`
that carry marks — a citation-dense law cites hundreds of others, and two such acts hold over
eight hundred marks between them, which is a larger and more real sample than the hand-written
set. Fixtures rather than a live fetch, so the number is reproducible and CI can hold it.

**What this is not.** It measures recall, not precision: `S_LGI` says where a reference *is*, not
where one *is not*, so it cannot catch a reference the extractor invents. And a short act that
cites nothing carries no marks and contributes nothing — the sample is citation-heavy law, which
is exactly where the linter earns its keep. The synthetic set still guards precision and the
amendment and deadline extractors; this guards reference recall against the real world, and the
two together are the measurement, neither alone.

Run: `python -m scripts.etalon_real`.
"""

from __future__ import annotations

import gzip
import html
import re
from dataclasses import dataclass
from pathlib import Path

from scripts.referinte import referinte
from scripts.text import cheie, normalizeaza

SURSE = Path(__file__).resolve().parent.parent / "sources"
_LGI = re.compile(r'class="S_LGI"[^>]*>(.*?)</', re.S)


@dataclass(frozen=True)
class Masura:
    act: str
    marcaje: int
    gasite: int

    @property
    def recall(self) -> float:
        return self.gasite / self.marcaje if self.marcaje else 1.0


def _text_curat(fragment: str) -> str:
    return normalizeaza(html.unescape(re.sub(r"<[^>]+>", " ", fragment)))


def masoara_fisier(cale: Path) -> Masura:
    """Recall over one act: publisher marks found by the extractor."""
    s = gzip.decompress(cale.read_bytes()).decode("utf-8", errors="replace")
    marcaje = [m for m in (_text_curat(x) for x in _LGI.findall(s)) if len(m) > 3]
    body = _text_curat(s)
    chei_ref = [cheie(r.text) for r in referinte(body) if r.text]
    gasite = 0
    for mk in marcaje:
        k = cheie(mk)
        if k and any(k in rk or rk in k for rk in chei_ref):
            gasite += 1
    return Masura(cale.stem, len(marcaje), gasite)


def masoara(surse: Path = SURSE) -> list[Masura]:
    """Every fixture that carries publisher marks. Acts without marks contribute nothing."""
    masuri = [masoara_fisier(f) for f in sorted(surse.glob("*.html.gz"))]
    return [m for m in masuri if m.marcaje]


def recall_global(masuri: list[Masura]) -> float:
    total = sum(m.marcaje for m in masuri)
    gasit = sum(m.gasite for m in masuri)
    return gasit / total if total else 1.0


def raport(surse: Path = SURSE) -> str:
    masuri = masoara(surse)
    linii = ["recall referințe vs marcajele S_LGI ale portalului:", ""]
    for m in masuri:
        linii.append(f"  {m.act:22} {m.gasite:>4}/{m.marcaje:<4} {m.recall:.1%}")
    total = sum(m.marcaje for m in masuri)
    gasit = sum(m.gasite for m in masuri)
    linii += ["", f"  TOTAL {gasit}/{total} = {recall_global(masuri):.1%}"]
    return "\n".join(linii)


if __name__ == "__main__":
    print(raport())
