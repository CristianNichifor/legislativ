"""Legislation as code: a provision written as a rule, checked and rendered like one.

`compunere.py` compiles *intents* (which article, which operation) into an amending act. This is the
other half — the *content* of a provision written as structured logic instead of prose:

    DACĂ valoare >= 5000000 lei ATUNCI se aplică procedura deschisă ALTFEL procedura simplificată

The Danish plain-language guide asks a provision to say plainly *who* does *what*, under *which*
condition, and *what happens otherwise* (STIL_DANEZ.md, rule 9). Written this way the "otherwise" is
not optional — it is a branch of the rule — and the shape is checkable: a condition can contradict
itself, be always true, or leave a case unspecified, and a machine can say so before a court does.

What this module does, all deterministic, standard library only, no model:

- **parse** the one-line rule into an AST (a boolean condition over comparisons, plus the two
  consequences);
- **render** it back to Romanian legistic prose in either norm (`nou` plain / `actual` current), so
  a drafter writes the logic and gets the wording;
- **check** it — the "as code" payoff: an unsatisfiable condition (`x >= 100 ȘI x < 50`), a vacuous
  one (always true / always false), a threshold with no ALTFEL branch, the variables it rests on;
- **enumerate** representative cases (values around each threshold) into a small table, so the two
  branches are concrete rather than asserted.

It is deliberately small and honest about its limits: comparisons over named quantities and simple
equalities, joined by ȘI / SAU / NU. Anything it cannot parse is reported, never guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from scripts.text import fara_diacritice

# --- tokens & keywords -----------------------------------------------------------------------
# Keywords are matched diacritic-insensitively (DACĂ == DACA) and case-insensitively, so a drafter
# typing quickly without diacritics is understood. Operators accept both symbols and words.
_KW = {"daca": "DACA", "atunci": "ATUNCI", "altfel": "ALTFEL", "si": "SI", "sau": "SAU", "nu": "NU"}
_OP_CUV = {"este": "=", "egal": "=", "cel putin": ">=", "cel mult": "<=", "peste": ">", "sub": "<"}

_UNITATI = {
    "lei",
    "zile",
    "luni",
    "ani",
    "ore",
    "%",
    "la suta",
    "euro",
    "persoane",
    "zile lucratoare",
}


@dataclass(frozen=True)
class Valoare:
    """The right-hand side of a comparison: a number (with unit), an identifier, or a string."""

    numar: float | None = None
    unitate: str | None = None
    ident: str | None = None
    text: str | None = None

    def __str__(self) -> str:
        if self.numar is not None:
            n = int(self.numar) if self.numar == int(self.numar) else self.numar
            grup = f"{n:,}".replace(",", ".") if isinstance(n, int) else str(n)
            return f"{grup} {self.unitate}".strip() if self.unitate else grup
        return self.ident or self.text or "?"


@dataclass(frozen=True)
class Comparatie:
    """`var OP valoare`, e.g. `valoare >= 5000000 lei`. The atom of a condition."""

    var: str
    op: str  # one of >= <= > < = !=
    val: Valoare


@dataclass(frozen=True)
class Si:
    parti: tuple  # of nodes


@dataclass(frozen=True)
class Sau:
    parti: tuple


@dataclass(frozen=True)
class Nu:
    parte: object


@dataclass(frozen=True)
class Regula:
    """A whole provision-as-rule: an optional condition, a consequence, an optional else-branch."""

    conditie: object | None
    atunci: str
    altfel: str | None = None
    probleme: tuple[str, ...] = field(default=())


class EroareRegula(ValueError):
    """The rule could not be parsed — reported to the drafter, never guessed around."""


def _fold(s: str) -> str:
    return fara_diacritice(s).lower()


# ---------------------------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------------------------

_NUMAR = re.compile(r"\d[\d.\s]*\d|\d")
_IDENT = re.compile(r"[A-Za-zĂÂÎȘȚăâîșț][\wĂÂÎȘȚăâîșț]*")


def _tokenizeaza(text: str) -> list[tuple[str, str]]:
    """Turn a condition string into (kind, value) tokens: KW, OP, NUM, UNIT, IDENT, LP, RP."""
    toks: list[tuple[str, str]] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == "(":
            toks.append(("LP", "("))
            i += 1
            continue
        if c == ")":
            toks.append(("RP", ")"))
            i += 1
            continue
        # two-char operators first
        if text[i : i + 2] in (">=", "<=", "!=", "<>"):
            toks.append(("OP", "!=" if text[i : i + 2] == "<>" else text[i : i + 2]))
            i += 2
            continue
        if c in "><=":
            toks.append(("OP", c))
            i += 1
            continue
        m = _NUMAR.match(text, i)
        if m and (not toks or toks[-1][0] in ("OP", "KW", "LP", "WORD")):
            brut = re.sub(r"[.\s]", "", m.group(0))
            toks.append(("NUM", brut))
            i = m.end()
            continue
        m = _IDENT.match(text, i)
        if m:
            cuv = m.group(0)
            fold = _fold(cuv)
            if fold in _KW:
                toks.append(("KW", _KW[fold]))
            elif fold in _UNITATI:
                toks.append(("UNIT", fold))
            elif fold == "este":
                toks.append(("OP", "="))
            elif fold in ("cel", "putin", "mult", "mai", "mare", "mic", "diferit", "de", "decat"):
                toks.append(("WORD", fold))  # word-operator fragments, resolved below
            else:
                toks.append(("IDENT", cuv))
            i = m.end()
            continue
        # anything else (stray punctuation) is skipped
        i += 1
    return _rezolva_operatori_cuvant(toks)


def _rezolva_operatori_cuvant(toks: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Fold word-operators (`cel puțin`, `cel mult`, `mai mare`, `diferit de`) into OP tokens."""
    _PERECHI = {
        ("cel", "putin"): ">=",
        ("cel", "mult"): "<=",
        ("mai", "mare"): ">",
        ("mai", "mic"): "<",
        ("diferit", "de"): "!=",
    }
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(toks):
        k, v = toks[i]
        pair = (v, toks[i + 1][1] if i + 1 < len(toks) else "")
        if k == "WORD" and pair in _PERECHI:
            out.append(("OP", _PERECHI[pair]))
            i += 2
            continue
        if k == "WORD":
            i += 1  # leftover connective ("decât", stray "de") — drop it
            continue
        out.append((k, v))
        i += 1
    return out


# ---------------------------------------------------------------------------------------------
# Recursive-descent parser for the condition:  sau := si ("SAU" si)* ; si := nu ("SI" nu)* ;
# nu := "NU" nu | atom ; atom := "(" sau ")" | IDENT OP valoare
# ---------------------------------------------------------------------------------------------


class _Parser:
    def __init__(self, toks: list[tuple[str, str]]):
        self.toks = toks
        self.i = 0

    def _peek(self) -> tuple[str, str] | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def _next(self) -> tuple[str, str]:
        t = self.toks[self.i]
        self.i += 1
        return t

    def parse(self):
        nod = self._sau()
        if self.i != len(self.toks):
            raise EroareRegula("condiție incompletă sau simboluri neașteptate")
        return nod

    def _sau(self):
        parti = [self._si()]
        while self._peek() and self._peek() == ("KW", "SAU"):
            self._next()
            parti.append(self._si())
        return parti[0] if len(parti) == 1 else Sau(tuple(parti))

    def _si(self):
        parti = [self._nu()]
        while self._peek() and self._peek() == ("KW", "SI"):
            self._next()
            parti.append(self._nu())
        return parti[0] if len(parti) == 1 else Si(tuple(parti))

    def _nu(self):
        if self._peek() and self._peek() == ("KW", "NU"):
            self._next()
            return Nu(self._nu())
        return self._atom()

    def _atom(self):
        t = self._peek()
        if t and t[0] == "LP":
            self._next()
            nod = self._sau()
            if not (self._peek() and self._peek()[0] == "RP"):
                raise EroareRegula("paranteză nedeschisă/neînchisă")
            self._next()
            return nod
        if not (t and t[0] == "IDENT"):
            raise EroareRegula("așteptam o variabilă (ex.: «valoare»)")
        var = self._next()[1]
        t = self._peek()
        if not (t and t[0] == "OP"):
            raise EroareRegula(f"așteptam un operator după «{var}» (>=, <=, >, <, =)")
        op = self._next()[1]
        op = {"=": "=", "==": "="}.get(op, op)
        return Comparatie(var=var, op=op, val=self._valoare())

    def _valoare(self) -> Valoare:
        t = self._peek()
        if not t:
            raise EroareRegula("așteptam o valoare după operator")
        if t[0] == "NUM":
            self._next()
            numar = float(t[1])
            unit = None
            if self._peek() and self._peek()[0] == "UNIT":
                unit = self._next()[1]
            return Valoare(numar=numar, unitate=unit)
        if t[0] == "IDENT":
            self._next()
            return Valoare(ident=t[1])
        raise EroareRegula("așteptam o valoare (număr sau identificator) după operator")


# ---------------------------------------------------------------------------------------------
# Splitting the rule into condition / then / else, then parsing the condition
# ---------------------------------------------------------------------------------------------

_RE_DACA = re.compile(r"\bdac[aă]\b", re.IGNORECASE)
_RE_ATUNCI = re.compile(r"\batunci\b", re.IGNORECASE)
_RE_ALTFEL = re.compile(r"\baltfel\b", re.IGNORECASE)


def parseaza(text: str) -> Regula:
    """Parse one provision-as-rule. No `DACĂ` → the whole text is an unconditional consequence."""
    brut = " ".join((text or "").split())
    if not brut:
        raise EroareRegula("regulă goală")

    m_daca = _RE_DACA.search(brut)
    if not m_daca:
        return Regula(conditie=None, atunci=brut.rstrip(". ") + ".", altfel=None)

    m_atunci = _RE_ATUNCI.search(brut, m_daca.end())
    if not m_atunci:
        raise EroareRegula("lipsește «ATUNCI» — o regulă este DACĂ … ATUNCI … [ALTFEL …]")
    cond_txt = brut[m_daca.end() : m_atunci.start()].strip()

    rest = brut[m_atunci.end() :]
    m_altfel = _RE_ALTFEL.search(rest)
    if m_altfel:
        atunci = rest[: m_altfel.start()].strip()
        altfel = rest[m_altfel.end() :].strip() or None
    else:
        atunci, altfel = rest.strip(), None
    if not atunci:
        raise EroareRegula("lipsește consecința după «ATUNCI»")

    conditie = _Parser(_tokenizeaza(cond_txt)).parse()
    return Regula(
        conditie=conditie,
        atunci=atunci.rstrip(". ") + ".",
        altfel=(altfel.rstrip(". ") + "." if altfel else None),
    )


# ---------------------------------------------------------------------------------------------
# Rendering to prose, in either norm
# ---------------------------------------------------------------------------------------------

_OP_NOU = {
    ">=": "este cel puțin",
    "<=": "este cel mult",
    ">": "depășește",
    "<": "este sub",
    "=": "este",
    "!=": "nu este",
}
_OP_ACTUAL = {
    ">=": "este mai mare sau egal cu",
    "<=": "este mai mic sau egal cu",
    ">": "este mai mare decât",
    "<": "este mai mic decât",
    "=": "este egal cu",
    "!=": "este diferit de",
}


def _randeaza_cond(nod, actual: bool) -> str:
    ops = _OP_ACTUAL if actual else _OP_NOU
    if isinstance(nod, Comparatie):
        return f"{nod.var} {ops[nod.op]} {nod.val}"
    if isinstance(nod, Si):
        return " și ".join(_randeaza_cond(p, actual) for p in nod.parti)
    if isinstance(nod, Sau):
        return " sau ".join(_randeaza_cond(p, actual) for p in nod.parti)
    if isinstance(nod, Nu):
        return f"nu ({_randeaza_cond(nod.parte, actual)})"
    return "?"


def randeaza(regula: Regula, norma: str = "nou") -> str:
    """The rule as one legistic sentence, in the chosen norm."""
    actual = norma == "actual"
    if regula.conditie is None:
        return regula.atunci
    cond = _randeaza_cond(regula.conditie, actual)
    prima = "În cazul în care" if actual else "Dacă"
    text = f"{prima} {cond}, {regula.atunci[0].lower()}{regula.atunci[1:]}"
    if regula.altfel:
        leg = "În caz contrar" if actual else "Altfel"
        text = f"{text.rstrip('.')}. {leg}, {regula.altfel[0].lower()}{regula.altfel[1:]}"
    return text


# ---------------------------------------------------------------------------------------------
# Static checks — the "as code" payoff
# ---------------------------------------------------------------------------------------------


def _comparatii(nod, acc: list[Comparatie]) -> None:
    if isinstance(nod, Comparatie):
        acc.append(nod)
    elif isinstance(nod, (Si, Sau)):
        for p in nod.parti:
            _comparatii(p, acc)
    elif isinstance(nod, Nu):
        _comparatii(nod.parte, acc)


def variabile(regula: Regula) -> list[str]:
    """The distinct quantities the rule rests on, in first-seen order."""
    acc: list[Comparatie] = []
    if regula.conditie is not None:
        _comparatii(regula.conditie, acc)
    vazute: list[str] = []
    for c in acc:
        if c.var not in vazute:
            vazute.append(c.var)
    return vazute


def _interval_contradictoriu(comps: list[Comparatie]) -> bool:
    """True if a conjunction of numeric comparisons on one variable cannot be satisfied."""
    lo, hi = float("-inf"), float("inf")  # inclusive bounds
    egal: set[float] = set()
    interzis: set[float] = set()
    for c in comps:
        if c.val.numar is None:
            continue
        v = c.val.numar
        if c.op == ">=":
            lo = max(lo, v)
        elif c.op == ">":
            lo = max(lo, v + 1e-9)
        elif c.op == "<=":
            hi = min(hi, v)
        elif c.op == "<":
            hi = min(hi, v - 1e-9)
        elif c.op == "=":
            egal.add(v)
        elif c.op == "!=":
            interzis.add(v)
    if lo > hi:
        return True
    if len(egal) > 1:
        return True
    return bool(egal and (min(egal) < lo or max(egal) > hi or (egal & interzis)))


def verifica(regula: Regula) -> list[str]:
    """Everything a machine can say about the rule before a court does."""
    probleme: list[str] = []
    cond = regula.conditie
    if cond is None:
        return probleme

    comps: list[Comparatie] = []
    _comparatii(cond, comps)

    # 1) contradiction inside a top-level conjunction, per variable
    if isinstance(cond, (Si, Comparatie)):
        directe = list(cond.parti) if isinstance(cond, Si) else [cond]
        pe_var: dict[str, list[Comparatie]] = {}
        for p in directe:
            if isinstance(p, Comparatie):
                pe_var.setdefault(p.var, []).append(p)
        for var, cs in pe_var.items():
            if _interval_contradictoriu(cs):
                probleme.append(
                    f"condiție imposibilă pe «{var}»: nicio valoare nu o poate satisface — "
                    "regula nu s-ar aplica niciodată."
                )

    # 2) a bare threshold on a single variable with no ALTFEL leaves the other case unspecified
    if regula.altfel is None and isinstance(cond, Comparatie) and cond.op in (">=", ">", "<=", "<"):
        probleme.append(
            f"prag fără «ALTFEL»: regula spune ce se întâmplă când {cond.var} trece pragul, dar "
            "nu și altfel — adaugă o ramură ALTFEL (regula de claritate: spune și «altfel»)."
        )

    # 3) same consequence on both branches makes the condition inert
    if regula.altfel is not None and _fold(regula.atunci) == _fold(regula.altfel):
        probleme.append(
            "ambele ramuri au aceeași consecință — condiția nu schimbă nimic, poate fi eliminată."
        )

    return probleme


# ---------------------------------------------------------------------------------------------
# Case enumeration — make the two branches concrete
# ---------------------------------------------------------------------------------------------


def _evalueaza(nod, mediu: dict[str, float]) -> bool | None:
    if isinstance(nod, Comparatie):
        if nod.val.numar is None or nod.var not in mediu:
            return None
        x, v = mediu[nod.var], nod.val.numar
        return {
            ">=": x >= v,
            ">": x > v,
            "<=": x <= v,
            "<": x < v,
            "=": x == v,
            "!=": x != v,
        }[nod.op]
    if isinstance(nod, Si):
        vals = [_evalueaza(p, mediu) for p in nod.parti]
        return None if None in vals else all(vals)
    if isinstance(nod, Sau):
        vals = [_evalueaza(p, mediu) for p in nod.parti]
        return None if None in vals else any(vals)
    if isinstance(nod, Nu):
        v = _evalueaza(nod.parte, mediu)
        return None if v is None else not v
    return None


def _praguri(comps: list[Comparatie]) -> dict[str, list[float]]:
    """Per numeric variable, sample points that straddle every threshold it is compared against."""
    puncte: dict[str, set[float]] = {}
    for c in comps:
        if c.val.numar is None:
            continue
        v = c.val.numar
        puncte.setdefault(c.var, set()).update({v - 1, v, v + 1})
    return {k: sorted(s) for k, s in puncte.items()}


def cazuri(regula: Regula, limita: int = 12) -> list[dict]:
    """A small table: representative values → which branch fires. Bounded, so it never explodes."""
    cond = regula.conditie
    if cond is None:
        return []
    comps: list[Comparatie] = []
    _comparatii(cond, comps)
    grile = _praguri(comps)
    if not grile or any(c.val.numar is None for c in comps):
        return []

    variabile_ord = [v for v in variabile(regula) if v in grile]
    if not variabile_ord:
        return []

    import itertools

    combinatii = list(itertools.product(*(grile[v] for v in variabile_ord)))
    if len(combinatii) > limita:
        combinatii = combinatii[:limita]

    randuri: list[dict] = []
    for combo in combinatii:
        mediu = dict(zip(variabile_ord, combo, strict=True))
        rez = _evalueaza(cond, mediu)
        randuri.append(
            {
                "valori": {k: (int(v) if v == int(v) else v) for k, v in mediu.items()},
                "adevarat": bool(rez),
                "consecinta": regula.atunci if rez else (regula.altfel or "— nespecificat —"),
            }
        )
    return randuri


def analizeaza(text: str) -> dict:
    """One call for the UI: parse, render both norms, check, enumerate cases. Errors are data."""
    try:
        regula = parseaza(text)
    except EroareRegula as e:
        return {"ok": False, "eroare": str(e)}
    return {
        "ok": True,
        "conditionala": regula.conditie is not None,
        "variabile": variabile(regula),
        "proza_nou": randeaza(regula, "nou"),
        "proza_actual": randeaza(regula, "actual"),
        "probleme": verifica(regula),
        "cazuri": cazuri(regula),
    }
