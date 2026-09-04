"""The one stage that is not written, and the reason it is not.

Everything else in this package works on text. This module is where text is supposed to come
from: `legislatie.just.ro`, whose act pages carry the structure the rest of the pipeline needs.
It is a stub, and the honest version of the stub is one that refuses rather than one that
guesses.

**Why there is no parser here.** The portal was not reachable from the environment this package
was written in, so nothing in it has ever seen the markup. A parser written against imagined
markup — `soup.find("div", class_="S_DEN")` and its neighbours — is the single most expensive
artefact a project like this can carry: it looks finished, it imports, it has tests that pass
against fixtures invented alongside it, and it fails on contact with the first real page. The
half-day that goes into writing it is small next to the half-day that goes into discovering it
was never right.

**What to do instead, and it takes ten minutes.** Fetch three acts and save them: one plain law,
one amending act, one republished act. Then write the parser against those files, and keep them
as fixtures. Ten minutes of reconnaissance is worth more here than any amount of anticipating.

Two things worth establishing in the same ten minutes, because both change the design rather
than the code:

- **Whether a document id addresses an act or a version of one.** If ids enumerate consolidated
  forms, walking a range returns the same law at six dates with nothing marking which is in
  force, and the seed-and-follow-references approach is the one that works.
- **What `robots.txt` says, and at what rate the server is content to be read.** This tool is
  built for a political party. A prototype assembled by hammering a Ministry of Justice server
  is a story that writes itself, and it would be told about the party rather than about the
  tool.

`ActParsat` below is the contract the rest of the package consumes. Fill it from real markup and
everything downstream runs unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from scripts.referinte import Act


@dataclass(frozen=True)
class Provizie:
    """One addressable provision, with the text a finding will quote."""

    locator_id: str
    text: str
    in_vigoare_de_la: date | None = None
    in_vigoare_pana_la: date | None = None


@dataclass(frozen=True)
class ActParsat:
    """What a document page has to yield for the rest of the pipeline to work.

    `publicat` and `vigoare` are separate fields and both are needed: a deadline anchored to
    publication and one anchored to entry into force are different dates, and the gap report
    refuses to compute an overdue figure rather than pick whichever it has.

    `republicat_din` matters more than it looks. Republication renumbers an act's articles, so a
    reference to `art. 15` means different provisions before and after — without this field the
    linter cannot tell which article an older citation was pointing at.
    """

    act: Act
    titlu: str
    publicat: date | None = None
    vigoare: date | None = None
    republicat_din: date | None = None
    provizii: tuple[Provizie, ...] = field(default=())
    sursa_url: str = ""


def parseaza(html: str, url: str = "") -> ActParsat:  # pragma: no cover - stub
    raise NotImplementedError(
        "Parserul nu e scris: portalul nu a fost accesibil din mediul în care s-a scris pachetul, "
        "iar un parser scris pe presupuneri despre markup e mai scump decât unul care lipsește. "
        "Vezi docstring-ul modulului pentru cei zece minute de recunoaștere care îl deblochează."
    )
