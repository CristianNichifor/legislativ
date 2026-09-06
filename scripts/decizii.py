"""What a Curtea Constituțională decision actually decided, read from its operative part.

The corpus already holds these decisions as prose. Prose is where the interesting facts are
locked up: which provision was struck down, whether the Court struck more than it was asked to,
and — once `neconstitutional.py` joins this to the amendment graph — whether Parliament ever
repaired the text afterwards. None of that is available from the reference graph, because every
citation in a decision currently arrives as `refera`, and `refera` cannot tell the law under
review from the Court's own organic law.

**The verb is the fact; the noun is everywhere.** The word `neconstituționalitate` appears in
every decision the Court has ever *rejected* — it is the name of the procedure, not the outcome.
A parser keyed on the word rather than on the operative verb reports the entire case law of
Romania as struck down, and it does so fluently. So nothing is read outside the dispozitiv, and
inside it a provision is struck only when a declaration verb says so: `constată că ... este
neconstituțional`, `declară neconstituțional ...`, `constată neconstituționalitatea ...`. Points
that begin `Respinge` are never mined for declarations, whatever words they contain.

**The legal basis is not the object of review.** Every decision closes its reasoning with `în
temeiul art. 144 din Constituție ... și al art. 25 din Legea nr. 47/1992` — the Court's authority
to rule at all. Slicing from `DECIDE` drops it, which is the whole reason the slice starts there
and not at the last paragraph. The Constitution is dropped again by name wherever it appears: it
is the standard the provision is measured against and is never the thing measured.

**Older decisions have no diacritics, and the operative part is letter-spaced.** `D E C I D E:`
and `constata ca art. 34 ... este neconstitutional` are both real and both common in the 1990s
material. Matching therefore runs on a diacritic-folded copy — `fara_diacritice` is a
character-for-character translation, so offsets into the folded copy are offsets into the
original, and every quoted span still comes out of the text as the Court wrote it.

**Ultra petita is a comparison, and a comparison needs both sides.** When the referral's object
cannot be read, `ultra_petita` is `None`, not `()`. An empty tuple reads as *the Court stayed
within what it was asked*, which is a finding; `None` reads as *nobody checked*, which is the
truth. The same rule governs a struck provision whose act carries no number and no year — it is
reported, it is counted, and it is excluded from the comparison rather than attached to a
plausible law.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from scripts.referinte import Referinta, referinte
from scripts.text import fara_diacritice, normalizeaza

# The operative part is announced in capitals, and the portal's older records letter-space them:
# `C U R T E A În numele legii D E C I D E:`. Matched case-sensitively, because `decide` in
# lowercase is an ordinary verb of the reasoning and appears in it constantly.
_MARCA_DISPOZITIV: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Z])(?:D\s?E\s?C\s?I\s?D\s?E|H\s?O\s?T\s?A\s?R\s?A\s?S\s?T\s?E)\s*:?(?![A-Z])"
)

# Where the Court stops deciding and the record starts describing itself. A dissent is the one
# that matters: it is written in the same voice, it says `este neconstituțional`, and it is not
# the decision. Reading one as operative attributes a minority view to the Court.
_SFARSIT_DISPOZITIV: Final[re.Pattern[str]] = re.compile(
    r"Pronuntat|Deliberarea\s+a\s+avut\s+loc|PRESEDINTE|Presedinte,|Magistrat-asistent"
    r"|OPINIE\s+SEPARAT|Opinie\s+separat|-{4,}",
)

# `1. Admite ... 2. Respinge ...`. Required to be followed by a capital so that `nr. 1.767/1995`
# and `art. 13 alin. (1) lit. A.c)` are not read as point numbers; required to run 1, 2, 3 so a
# stray `2.` mid-sentence cannot split a single-point dispozitiv into two.
_PUNCT_NUMEROTAT: Final[re.Pattern[str]] = re.compile(
    r"(?:(?<=^)|(?<=[\s.;]))(\d{1,2})\.\s+(?=[A-ZȘȚĂÂÎ])"
)

_VERBE: Final[tuple[tuple[str, str], ...]] = (
    ("admite", r"Admite\b"),
    ("respinge", r"Respinge\b"),
    ("constata", r"(?:Constata|Declara)\b"),
    ("conexare", r"Conexeaza\b|Conexarea\b"),
)
_VERB = re.compile("|".join(rf"(?P<{nume}>{sablon})" for nume, sablon in _VERBE), re.IGNORECASE)

_NECONST = r"neconstitutional[aeiă]*"

# Three ways the Court writes the same operation. Each yields the span that holds the provisions
# actually struck, so that `invocată de X în Dosarul nr. Y` — which follows in most decisions —
# stays outside it.
_DECLARA: Final[re.Pattern[str]] = re.compile(rf"declar[aă]\s+{_NECONST}\b", re.IGNORECASE)
_CONSTATA_CA: Final[re.Pattern[str]] = re.compile(
    rf"(?:constat|declar)[aă]\s+(?:ca\s+)?(?P<obiect>.{{0,400}}?)\b(?:este|sunt|erau?)\s+{_NECONST}\b",
    re.IGNORECASE | re.DOTALL,
)
_CONSTATA_TAREA: Final[re.Pattern[str]] = re.compile(
    r"constat[aă]\s+neconstitutionalitatea\b", re.IGNORECASE
)

# Article 150 (1) of the 1991 Constitution abrogated, by its own force, every pre-constitutional
# provision that contradicted it. A quarter of the Court's early docket says so rather than
# `neconstituțional`: `art. 224 din Codul penal este abrogat parțial, conform art. 150 alin. (1)
# din Constituție`. The legal route differs — the text falls away instead of being struck — but
# for anyone asking which provisions the Court has put out of force, leaving these out drops a
# quarter of the answer. They are collected under their own `fel` so the two are never
# silently merged.
_ABROGAT_150: Final[re.Pattern[str]] = re.compile(
    r"\b(?:este|sunt|a\s+fost|au\s+fost)\s+abrogat[aeiăt]*[\s,]*(?:partial)?[\s,]*"
    r"(?:potrivit|conform|(?:î|i)n\s+temeiul)[\s,]*art\.?\s*150",
    re.IGNORECASE,
)
# How much of the sentence before `este abrogat` can hold the provision it is about.
_FEREASTRA_ABROGARE: Final[int] = 300

# In the 1990s a decision was open to recourse to the plenum for ten days, and 24 of the ones in
# this corpus admit one. A strike that a later panel reversed is not a strike, and this parser
# reads one decision at a time — so finality is carried as a fact of the text and the register
# above refuses to call an unfinalised strike settled.
_DEFINITIVA_NERECURATA: Final[re.Pattern[str]] = re.compile(
    r"Definitiv[aă]\s+prin\s+nerecurare", re.IGNORECASE
)
# How 84% of the case law states finality — 16 999 of 20 006 decisions. Matching only the 1990s
# `prin nerecurare` form (1%) left the rest marked "finality unknown", and the register then
# warned on every one of them that a recourse might have reversed the strike. There is no
# recourse to search: article 147 (4) makes a decision generally binding from publication, and
# the appeal to the plenum went with the 2003 revision. Matched against the diacritic-folded
# copy, where `și` is already `si`.
_DEFINITIVA_GENERALA: Final[re.Pattern[str]] = re.compile(
    r"Definitiv[aă]\s+(?:si|și)\s+general\s+obligatorie", re.IGNORECASE
)
_CU_RECURS: Final[re.Pattern[str]] = re.compile(r"Cu\s+recurs\s+(?:î|i)n\s+termen", re.IGNORECASE)
_ESTE_RECURS: Final[re.Pattern[str]] = re.compile(r"\brecursu(?:l|lui)\b", re.IGNORECASE)

# How the referral names what it is attacking, in both the `Pe rol` line and the older
# `examinând excepția ...` opening. `sesizarea de neconstituționalitate` is the a-priori form,
# where Parliament's own bill is the object.
_OBIECT: Final[re.Pattern[str]] = re.compile(
    r"(?:exceptii?le?|exceptiei?|exceptiilor|sesizar(?:ea|ii)|obiecti(?:a|ei))\s+de\s+"
    rf"{_NECONST}itate\s+(?:a|ale|al|asupra|privind|cu\s+privire\s+la)?\s*",
    re.IGNORECASE,
)
# The referral's object ends where the record starts saying who raised it and in which file.
# The sentence-boundary alternative is scoped case-sensitive: under a blanket IGNORECASE the
# uppercase class also matches `. b)` and the object is cut off in the middle of `lit. b)`,
# which silently truncates the referral and then reports the decision as ultra petita.
_SFARSIT_OBIECT: Final[re.Pattern[str]] = re.compile(
    r",?\s*(?:invocat|ridicat|formulat|sesizare|Presedintele|La\s+apelul)"
    r"|(?-i:\.\s+[A-ZȘȚĂÂÎ])",
    re.IGNORECASE,
)

# `prevederile art. 3 lit. b) din Legea nr. 61/1991, astfel cum au fost modificate prin
# Ordonanța Guvernului nr. 55/1994, aprobată prin Legea nr. 129/1994, sunt neconstituționale`
# strikes two letters of one law. The two acts named after the connector are how that text came
# to read as it does — its amendment history — and counting them as struck repeals an entire
# ordinance and its approving law on the strength of a subordinate clause.
# Two shapes, not one. `... modificate prin OG nr. 55/1994` is an amendment history trailing the
# struck provision. `Legea nr. 249/2006 **pentru modificarea și completarea** Legii nr. 393/2004`
# is different and commoner: the second act is inside the *title* of the first — what the amending
# law is called — and counting it repeals a statute on the strength of a name. Both end the span.
_LANT_MODIFICARE: Final[re.Pattern[str]] = re.compile(
    r",?\s*(?:astfel\s+cum"
    r"|(?:a(?:probat|stfel)|modificat|completat|republicat)[aăeiț]*\s+prin"
    r"|(?:pentru|privind|de)\s+(?:modificarea|completarea|aprobarea|modificare|completare)"
    r")\b",
    re.IGNORECASE,
)

# The Constitution is what a provision is measured against. It is cited in the operative part of
# a-priori decisions as the procedure to be opened (`art. 145 alin. (1)`), and reading it as
# struck would have the Court repealing the Constitution.
_ETALON: Final[frozenset[str]] = frozenset({"constitutie"})

# What may stand between two members of a list of provisions that share one act: `art. 34 și
# art. 35 din Legea nr. 15/1994`. `referinte.py` binds only the last of those to the act,
# correctly — adjacency across a full stop is not a binding. Inside one declaration span the
# enumeration is unambiguous, so the act is inherited leftwards here rather than there.
_ENUMERARE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:,|si|și|,\s*si|,\s*și|-|precum\s+si)\s*$", re.IGNORECASE
)


@dataclass(frozen=True)
class Proviziune:
    """A provision named in an operative part: the act if it could be keyed, the position, the
    span it was read from, and by which route the Court put it out of force."""

    act: str | None
    locator: str
    text: str
    fel: str = "obiect"

    @property
    def id(self) -> str:
        return f"{self.act or '?'} {self.locator}".strip()


# The two routes out of force, kept apart. `neconstitutional` is the Court striking a provision
# under its review powers; `abrogat_constitutional` is art. 150 (1) of the 1991 Constitution
# having already abrogated a pre-constitutional text, which the Court only records.
FELURI_LOVITE: Final[frozenset[str]] = frozenset({"neconstitutional", "abrogat_constitutional"})


@dataclass(frozen=True)
class Punct:
    """One point of the operative part. A dispozitiv with no numbering has exactly one."""

    numar: int
    solutie: str
    text: str
    neconstitutionale: tuple[Proviziune, ...]


@dataclass(frozen=True)
class Decizie:
    """A decision as the operative part states it, with what could not be read declared."""

    id: str
    puncte: tuple[Punct, ...]
    obiect: tuple[Proviziune, ...]
    limitari: tuple[str, ...]
    definitiva: bool | None = None
    este_recurs: bool = False

    @property
    def solutii(self) -> tuple[str, ...]:
        """The operative solutions, in order, once each. Procedural points do not count."""
        vazute: list[str] = []
        for p in self.puncte:
            if p.solutie != "altele" and p.solutie not in vazute:
                vazute.append(p.solutie)
        return tuple(vazute)

    @property
    def neconstitutionale(self) -> tuple[Proviziune, ...]:
        """Every provision this decision struck down, across all its points."""
        gasite: list[Proviziune] = []
        for p in self.puncte:
            for pr in p.neconstitutionale:
                if pr.fel in FELURI_LOVITE and pr not in gasite:
                    gasite.append(pr)
        return tuple(gasite)

    @property
    def ultra_petita(self) -> tuple[Proviziune, ...] | None:
        """Struck provisions the referral did not put in front of the Court.

        `None` when the object of the referral could not be read: the comparison was not made,
        and an empty tuple would say it was made and came out clean. Provisions whose act could
        not be keyed are excluded from the comparison and carried in `limitari` instead — they
        cannot be matched against the object without guessing which law they belong to.
        """
        if not self.obiect:
            return None
        return tuple(
            p
            for p in self.neconstitutionale
            if p.act is not None
            and not any(_acopera(o, p) for o in self.obiect)
            and not any(_acopera_pe_pozitie(o, p) for o in self.obiect if o.act is None)
        )


def _acopera(obiect: Proviziune, strica: Proviziune) -> bool:
    """Whether what was referred contains what was struck.

    An act referred whole (`empty locator`) contains everything in it. Otherwise the struck
    position must sit at or below the referred one: a referral against `art. 34 alin. (2)` does
    not cover a decision striking `art. 34` entire, which is the ordinary shape of ultra petita
    in Romanian constitutional practice.
    """
    if obiect.act != strica.act:
        return False
    if not obiect.locator:
        return True
    return _la_sau_sub(obiect.locator, strica.locator)


def _la_sau_sub(deasupra: str, dedesubt: str) -> bool:
    return dedesubt == deasupra or dedesubt.startswith(deasupra + ".")


def _acopera_pe_pozitie(obiect: Proviziune, strica: Proviziune) -> bool:
    """A referral whose act could not be keyed still blocks an ultra petita claim on position.

    `art. 175 alin. (1) lit. b)` referred against an unnamed act and `art. 175 alin. (1) lit. b)`
    struck down are, on any reading, the same provision. Asserting that the Court ranged beyond
    its referral because *this parser* could not key the referral's act would be a finding about
    the parser dressed up as a finding about the Court.
    """
    return bool(obiect.locator) and _la_sau_sub(obiect.locator, strica.locator)


def dispozitiv(text: str) -> str | None:
    """The operative part alone: from the last `DECIDE` to the record that follows it."""
    t = normalizeaza(text)
    return _dispozitiv(t, fara_diacritice(t))


def _dispozitiv(text: str, pliat: str) -> str | None:
    """As above, for a caller that already holds the normalised and folded text.

    `normalizeaza` and `fara_diacritice` are idempotent but not free — each is a pass over the
    whole document — and `citeste` needed the same two results three and two times over. Measured
    on 20 006 decisions that repetition was the entire cost of building the register.
    """
    marci = list(_MARCA_DISPOZITIV.finditer(pliat))
    if not marci:
        return None
    inceput = marci[-1].end()
    sfarsit = _SFARSIT_DISPOZITIV.search(pliat, inceput)
    return text[inceput : sfarsit.start() if sfarsit else len(text)].strip()


def _puncte_brute(disp: str) -> list[tuple[int, str]]:
    """Split a numbered operative part; a dispozitiv without numbering is one point."""
    marci = [m for m in _PUNCT_NUMEROTAT.finditer(disp)]
    asteptat = 1
    taieturi: list[tuple[int, int]] = []
    for m in marci:
        if int(m.group(1)) == asteptat:
            taieturi.append((asteptat, m.start()))
            asteptat += 1
    if len(taieturi) < 2:
        return [(1, disp)]
    bucati: list[tuple[int, str]] = []
    for i, (numar, poz) in enumerate(taieturi):
        capat = taieturi[i + 1][1] if i + 1 < len(taieturi) else len(disp)
        bucati.append((numar, disp[poz:capat].strip()))
    return bucati


def _solutie(punct: str) -> str:
    """The operative verb this point opens with. Anything else is procedure, not a solution."""
    m = _VERB.match(fara_diacritice(punct).lstrip("0123456789. "))
    if m is None:
        return "altele"
    return next(nume for nume, _ in _VERBE if m.group(nume) is not None)


def _spanuri_declaratie(punct: str) -> list[tuple[int, int, str]]:
    """Where inside a point the Court puts a provision out of force, and by which route."""
    pliat = fara_diacritice(punct)
    spanuri: list[tuple[int, int, str]] = []
    for m in _DECLARA.finditer(pliat):
        spanuri.append((m.end(), len(punct), "neconstitutional"))
    for m in _CONSTATA_CA.finditer(pliat):
        spanuri.append((m.start("obiect"), m.end("obiect"), "neconstitutional"))
    for m in _CONSTATA_TAREA.finditer(pliat):
        spanuri.append((m.end(), len(punct), "neconstitutional"))
    # The art. 150 form names the provision *before* the verb, so the window looks backwards.
    for m in _ABROGAT_150.finditer(pliat):
        spanuri.append(
            (max(0, m.start() - _FEREASTRA_ABROGARE), m.start(), "abrogat_constitutional")
        )
    return spanuri


def _mosteneste_actul(refs: list[Referinta], text: str) -> list[Referinta]:
    """`art. 34 și art. 35 din Legea nr. 15/1994` — both articles belong to the law.

    Applied only inside one declaration span, where an enumeration cannot be anything else. The
    inheritance runs right to left, because Romanian names the act once, at the end.
    """
    iesire = list(refs)
    for i in range(len(iesire) - 2, -1, -1):
        curent, urmator = iesire[i], iesire[i + 1]
        if curent.act is not None or urmator.act is None or not curent.locator:
            continue
        if _ENUMERARE.match(text[curent.end : urmator.start]):
            iesire[i] = Referinta(
                urmator.act, curent.locator, curent.text, curent.start, curent.end
            )
    return iesire


def _provizii(segment: str, fel: str = "obiect") -> list[Proviziune]:
    """Provisions named in a span, with the Constitution dropped and duplicates collapsed.

    The span stops at the first amendment-chain connector: what follows it is where the text
    came from, not another thing put out of force.
    """
    lant = _LANT_MODIFICARE.search(fara_diacritice(segment))
    if lant is not None:
        segment = segment[: lant.start()]
    refs = _mosteneste_actul(referinte(segment), segment)
    gasite: list[Proviziune] = []
    for r in refs:
        if r.act is not None and r.act.id in _ETALON:
            continue
        if r.act is None and not r.locator:
            continue
        pr = Proviziune(r.act.id if r.act else None, r.locator.id, r.text, fel)
        if pr not in gasite:
            gasite.append(pr)
    return gasite


def obiect(text: str, pana_la: int) -> list[Proviziune]:
    """What the referral put in front of the Court, read from the part before the dispozitiv."""
    t = normalizeaza(text)
    return _obiect(t, fara_diacritice(t), pana_la)


def _obiect(text: str, pliat: str, pana_la: int) -> list[Proviziune]:
    """As above, for a caller that already holds both forms."""
    text = text[:pana_la]
    pliat = pliat[:pana_la]
    gasite: list[Proviziune] = []
    for m in _OBIECT.finditer(pliat):
        capat = _SFARSIT_OBIECT.search(pliat, m.end())
        segment = text[m.end() : capat.start() if capat else min(m.end() + 300, len(text))]
        for pr in _provizii(segment):
            if pr not in gasite:
                gasite.append(pr)
    return gasite


def citeste(id_act: str, text: str) -> Decizie:
    """Read one decision. Everything the text does not support comes back as a limitation."""
    text = normalizeaza(text)
    pliat = fara_diacritice(text)
    disp = _dispozitiv(text, pliat)
    limitari: list[str] = []

    if disp is None:
        return Decizie(
            id=id_act,
            puncte=(),
            obiect=(),
            limitari=(
                "Actul nu are un dispozitiv recognoscibil («DECIDE» / «HOTĂRĂȘTE»), așa că nu i "
                "s-a citit nicio soluție. Hotărârile electorale ale Curții au această formă.",
            ),
        )

    puncte: list[Punct] = []
    declaratii_goale = 0
    for numar, brut in _puncte_brute(disp):
        solutie = _solutie(brut)
        provizii: list[Proviziune] = []
        # A point that rejects declares nothing, whatever it repeats of the referral's wording.
        if solutie != "respinge":
            for inceput, sfarsit, fel in _spanuri_declaratie(brut):
                gasite = _provizii(brut[inceput:sfarsit], fel)
                if not gasite:
                    declaratii_goale += 1
                for pr in gasite:
                    if pr not in provizii:
                        provizii.append(pr)
        puncte.append(Punct(numar, solutie, brut, tuple(provizii)))

    tinta = tuple(p for pct in puncte for p in pct.neconstitutionale)
    obiecte = _obiect(text, pliat, text.find(disp) if disp in text else len(text))

    neidentificate = [p for p in tinta if p.act is None]
    if neidentificate:
        limitari.append(
            "Dispozitivul lovește prevederi cu act neidentificat "
            f"({', '.join(p.text[:60] for p in neidentificate)}): actul e citat pe titlu, fără "
            "număr și an. Prevederile sunt raportate, dar nu intră în comparația cu obiectul "
            "sesizării, pentru că a le lega de o lege anume ar fi o presupunere."
        )
    if tinta and not obiecte:
        limitari.append(
            "Obiectul sesizării nu a putut fi citit din partea introductivă, deci nu se poate "
            "spune dacă instanța a mers dincolo de ce i s-a cerut. Verificarea nu s-a făcut."
        )
    if declaratii_goale:
        limitari.append(
            f"Dispozitivul conține {declaratii_goale} declarație(i) de scoatere din vigoare din "
            "care nu s-a putut citi nicio prevedere — actul e numit descriptiv («Legea pentru "
            "aprobarea Ordonanței ...») sau datat în litere. Decizia lovește ceva ce acest "
            "parser nu localizează."
        )
    if any(p.solutie == "altele" for p in puncte) and not tinta:
        limitari.append(
            "Niciun punct al dispozitivului nu deschide cu un verb de soluție cunoscut; "
            "soluția a fost marcată «altele» și nu s-a extras nimic din el."
        )

    finala = bool(_DEFINITIVA_NERECURATA.search(pliat) or _DEFINITIVA_GENERALA.search(pliat))
    definitiva = True if finala else (False if _CU_RECURS.search(pliat) else None)
    este_recurs = bool(_ESTE_RECURS.search(fara_diacritice(disp)))

    if definitiva is False and tinta:
        limitari.append(
            "Decizia era supusă recursului la data pronunțării («Cu recurs în termen de 10 "
            "zile») și textul nu spune că a rămas definitivă. Un recurs admis ulterior ar "
            "răsturna ce s-a lovit aici; corpusul nu a fost interogat pentru asta."
        )

    return Decizie(id_act, tuple(puncte), tuple(obiecte), tuple(limitari), definitiva, este_recurs)
