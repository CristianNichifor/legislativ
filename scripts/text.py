"""Getting Romanian legal text into one shape before anything tries to read it.

Every extractor downstream is a regular expression, and a regular expression over Romanian
legal text fails for three reasons that have nothing to do with law. This module removes all
three once, so that no pattern in this package has to carry them.

**The cedilla problem is the one that silently halves a corpus.** Romanian ș and ț are
comma-below letters, U+0219 and U+021B. For most of the time Romanian was being typed into
computers they were written with the Turkish cedilla letters ş and ţ, U+015F and U+0163,
because those were in Latin-2 and the correct ones were not. Both spellings are still in
circulation, often inside the same document, and they are *different characters*: a pattern
written with the comma-below `se modifică` matches nothing at all in a paragraph that was
typed with cedillas. Nothing in the failure looks like an encoding bug — the extractor simply
returns an empty list, and an empty list from a legislative linter reads as "no amendments
here", which is the most dangerous wrong answer this package can give. So the fold happens
before any matching, and `test_text.py` guards it in both directions.

**Superscript article numbers are load-bearing, not decoration.** When a law inserts an
article between 12 and 13 it is numbered 12^1 — never 12 bis, and never renumbering what
follows. Portals render that as `12¹`, as `12^1`, and occasionally as `12 ind. 1`. All three
mean the same provision, and a linter that reads `12¹` as the number 121 will report against
an article that in most acts does not exist. They are folded to the caret form, which is what
the rest of the package matches and what Monitorul Oficial prints.

**Diacritics are sometimes simply absent.** Older scans and hand-typed drafts write `hotarare`
for `hotărâre`. `fara_diacritice` exists for tolerant comparison — never for storage. Text is
kept as written and folded only at the moment of comparison, because a linter that quotes the
law back to an MP with the diacritics stripped looks broken in exactly the way that makes
people stop trusting the rest of it.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

# The correct Romanian letters are comma-below; the cedilla forms are a legacy of Latin-2 and
# appear throughout older material on the legislative portal. Folded towards the correct form,
# never away from it.
CEDILA: Final[dict[str, str]] = {
    "ş": "ș",  # ş -> ș
    "Ş": "Ș",  # Ş -> Ș
    "ţ": "ț",  # ţ -> ț
    "Ţ": "Ț",  # Ţ -> Ț
}

# ¹²³ are in Latin-1; ⁴ upwards live in the superscripts block. Both appear in article numbers.
EXPONENT: Final[dict[str, str]] = {
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
}

_EXPONENT_DUPA_CIFRA = re.compile(r"(?<=\d)([¹²³⁴-⁹]+)")
_INDICE_SCRIS = re.compile(r"(?<=\d)\s*(?:ind\.|indice)\s*(\d+)", re.IGNORECASE)
_SPATII = re.compile(r"[ \t   ]+")
_LINII_GOALE = re.compile(r"\n{3,}")

_FARA_DIACRITICE: Final[dict[int, str]] = {
    ord("ă"): "a",
    ord("Ă"): "A",
    ord("â"): "a",
    ord("Â"): "A",
    ord("î"): "i",
    ord("Î"): "I",
    ord("ș"): "s",
    ord("Ș"): "S",
    ord("ț"): "t",
    ord("Ț"): "T",
}


# The SOAP service marks a block boundary with a lone `+` on its own line — after the header,
# before `Articolul UNIC`, after the enacting formula. 125 669 of the 151 947 documents carry at
# least one, and it is the only single-character line the service emits. The HTML the portal serves
# has none, which is what identified it as a transport artifact rather than part of the text.
_SEPARATOR_SOAP = re.compile(r"\n[ \t]*\+[ \t]*(?=\n|\Z)")


def fara_separatoare(text: str) -> str:
    """Drop the service's block markers, keeping the break they stand for.

    Applied to the *derived* copy in `provizii` — the one that gets quoted to a reader, searched,
    and put in front of a model — and never to `documente.text`, which stays exactly as the service
    returned it. That split is the archive's whole point: a marker removed from the archive could
    not be recovered, and a `+` shown inside a quotation from the Monitorul Oficial reads as an
    error in the law rather than an error in the pipe it came down.
    """
    return _SEPARATOR_SOAP.sub("", text)


def normalizeaza(text: str) -> str:
    """One canonical spelling of a passage, safe to run twice.

    Idempotence matters more than it looks: text arrives here from a parser, gets stored, and
    is normalised again on the way into a matcher. If the function were not stable under a
    second application, `12^1` would drift on every pass and stored text would stop matching
    freshly-read text.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.translate(str.maketrans(CEDILA))
    text = _INDICE_SCRIS.sub(lambda m: f"^{m.group(1)}", text)
    text = _EXPONENT_DUPA_CIFRA.sub(lambda m: "^" + "".join(EXPONENT[c] for c in m.group(1)), text)
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("„", '"').replace("”", '"').replace("«", '"')
    text = text.replace("»", '"').replace("’", "'")
    text = _SPATII.sub(" ", text)
    text = "\n".join(linie.strip() for linie in text.split("\n"))
    return _LINII_GOALE.sub("\n\n", text).strip()


def fara_diacritice(text: str) -> str:
    """For comparison only. Storage and quotation keep the text as the law wrote it."""
    return unicodedata.normalize("NFC", text).translate(_FARA_DIACRITICE)


def cheie(text: str) -> str:
    """The form two strings are compared in: no diacritics, no case, single spaces.

    Used for matching a term against a legal definition and a quote against its source. It
    deliberately does not strip punctuation — `alin. (2)` and `alin (2)` are different enough
    that collapsing them would hide a parse error rather than tolerate a typo.
    """
    return _SPATII.sub(" ", fara_diacritice(normalizeaza(text)).lower()).strip()


# Romanian inflects nouns and adjectives heavily and hangs the definite article on the end of
# the word: `autoritate contractantă`, `autorității contractante`, `autoritățile contractante`
# are one term in three forms. A character-similarity check cannot tell that apart from a
# drafter drifting off the defined term, and the first version of the terminology check proved
# it — it flagged the plural of a term as a deviation from the term. Comparison therefore runs
# on stems. Longest suffix first, and never below four characters, which is short enough to
# keep `lege` and long enough that `ordin` does not become `ord`.
SUFIXE: Final[tuple[str, ...]] = (
    "urilor",
    "elor",
    "ilor",
    "urile",
    "ului",
    "iile",
    "ele",
    "ile",
    "uri",
    "lor",
    "iei",
    "ii",
    "ie",
    "ul",
    "ea",
    "ei",
    "le",
    "a",
    "ă",
    "e",
    "i",
)
_LUNGIME_MINIMA: Final[int] = 4


def radacina(cuvant: str) -> str:
    """A crude stem, for comparing a term against an inflection of itself.

    Crude on purpose: a real Romanian stemmer is a dependency and a source of its own errors,
    and everything downstream of this treats a stem match as evidence of correct usage rather
    than as a fact. Over-stemming makes the terminology check quieter, which is the safe
    direction for a check whose false positives land on a drafter.
    """
    cuvant = cheie(cuvant)
    for sufix in SUFIXE:
        if cuvant.endswith(sufix) and len(cuvant) - len(sufix) >= _LUNGIME_MINIMA:
            return cuvant[: -len(sufix)]
    return cuvant


def radacini(expresie: str) -> str:
    """The stem form of a whole term, which is what two terms are compared in."""
    return " ".join(radacina(c) for c in cheie(expresie).split())
