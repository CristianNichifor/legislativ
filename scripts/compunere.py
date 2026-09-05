"""Legislation as code: a list of intended changes compiled into a whole amending act.

`redactare.py` phrases one operation. This assembles many into the document Legea nr. 24/2000
requires: a title, then one article per act touched, each opening with the mandated chapeau and
listing the changes as arabic-numbered points. The input is structured — an operation, a target, a
new text — so the output is deterministic: the same intents always compile to the same act. That is
the "as code" of it — the intents are the source, this is the compiler, and the emitted text is the
build.

**The extractor is the compiler's own test.** After composing the text, this reads it back with
`amendamente.py` and checks that every intent reappears as the operation it was — same verb, same
target, same locator. A point that does not round-trip is reported, not hidden: it means the
composed wording came out ambiguous to the very parser the rest of the package trusts, and a
drafter should look at it. So the tool does not just emit legistic text, it emits text it has
verified it can itself read back — the honesty rail applied to generation.

Standard library only; no model. The phrasing is the guide's, filled by a template.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from scripts.amendamente import amendamente
from scripts.referinte import Locator, acte

# operation -> the category the chapeau names it under. Abrogation is a modification; an insertion
# is a completion — Legea 24/2000's chapeau verb reflects the mix.
_MODIFICARE = {"modifica", "abroga"}
_COMPLETARE = {"completeaza", "introduce"}

# Leading article word -> its genitive, for the title ("Lege pentru modificarea Legii nr. …").
_GENITIV = {
    "Legea": "Legii",
    "Ordonanța": "Ordonanței",
    "Ordonanţa": "Ordonanței",
    "Hotărârea": "Hotărârii",
    "Ordinul": "Ordinului",
    "Decretul": "Decretului",
    "Codul": "Codului",
}

_ROMANE = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]


@dataclass(frozen=True)
class Interventie:
    """One intended change, structured — the source the act is compiled from."""

    operatie: str  # modifica | completeaza | abroga | introduce
    act: str  # the target act as it must be cited, e.g. "Legea nr. 98/2016 privind achizițiile…"
    articol: str | None = None
    alineat: str | None = None
    litera: str | None = None
    text_nou: str = "…"
    articol_nou: str | None = None


@dataclass(frozen=True)
class ActCompus:
    """A composed amending act, with the round-trip check's verdict."""

    titlu: str
    text: str
    verificare: tuple[str, ...] = field(default=())

    @property
    def curat(self) -> bool:
        """True when every point read back as the intent it was — nothing to look at by hand."""
        return not self.verificare


def _genitiv(act: str) -> str:
    prim, _, rest = act.partition(" ")
    return f"{_GENITIV.get(prim, prim)} {rest}".strip() if rest else act


def _subunitate(intv: Interventie) -> str:
    parti = []
    if intv.alineat:
        parti.append(f"alineatul ({intv.alineat})")
    if intv.litera:
        parti.append(f"litera {intv.litera})")
    return ", ".join(parti)


def _tinta_punct(intv: Interventie) -> str:
    """The target of a point, without the act — the chapeau above it names the act already."""
    sub = _subunitate(intv)
    if intv.articol and sub:
        return f"La articolul {intv.articol}, {sub}"
    if intv.articol:
        return f"Articolul {intv.articol}"
    if sub:
        return f"{sub[0].upper()}{sub[1:]}"
    return "Prezentul act"


def _punct(intv: Interventie) -> str:
    tinta = _tinta_punct(intv)
    if intv.operatie == "modifica":
        return f"{tinta} se modifică și va avea următorul cuprins:\n«{intv.text_nou}»"
    if intv.operatie == "abroga":
        return f"{tinta} se abrogă."
    if intv.operatie == "completeaza":
        return f"{tinta} se completează cu următorul cuprins:\n«{intv.text_nou}»"
    if intv.operatie == "introduce":
        dupa = f"articolul {intv.articol}" if intv.articol else "articolul …"
        return (
            f"După {dupa} se introduce un nou articol, "
            f"{intv.articol_nou or 'art. …'}, cu următorul cuprins:\n«{intv.text_nou}»"
        )
    raise ValueError(f"operație necunoscută: {intv.operatie}")


def _chapeau_verb(operatii: set[str]) -> str:
    are_mod = bool(operatii & _MODIFICARE)
    are_compl = bool(operatii & _COMPLETARE)
    if are_mod and are_compl:
        return "se modifică și se completează"
    return "se completează" if are_compl else "se modifică"


def _titlu_verb(operatii: set[str]) -> str:
    are_mod = bool(operatii & _MODIFICARE)
    are_compl = bool(operatii & _COMPLETARE)
    if are_mod and are_compl:
        return "modificarea și completarea"
    return "completarea" if are_compl else "modificarea"


def _locator_asteptat(intv: Interventie) -> Locator:
    # For an insertion the locator that matters downstream is the anchor article, as the extractor
    # reads it; the new article number rides along separately.
    return Locator(articol=intv.articol, alineat=intv.alineat, litera=intv.litera)


def compune(interventii: list[Interventie]) -> ActCompus:
    """Compile the intents into a complete amending act, then verify it reads back.

    Points are grouped by target act, in first-seen order; each group becomes one article with its
    chapeau and numbered points. The title names every act touched, in the genitive. The composed
    text is then parsed by `amendamente`, and any intent that does not reappear as its own operation
    is reported in `verificare`.
    """
    if not interventii:
        return ActCompus(titlu="", text="", verificare=("nicio intervenție — nimic de compus.",))

    # group, preserving order
    grupuri: dict[str, list[Interventie]] = {}
    for intv in interventii:
        grupuri.setdefault(intv.act, []).append(intv)

    toate_ops = {i.operatie for i in interventii}
    acte_gen = ", ".join(_genitiv(a) for a in grupuri)
    titlu = f"Lege pentru {_titlu_verb(toate_ops)} {acte_gen}"

    corpuri: list[str] = []
    for idx, (act, grup) in enumerate(grupuri.items()):
        verb = _chapeau_verb({i.operatie for i in grup})
        roman = _ROMANE[idx] if idx < len(_ROMANE) else str(idx + 1)
        puncte = "\n".join(f"{n}. {_punct(i)}" for n, i in enumerate(grup, start=1))
        corpuri.append(f"Articolul {roman}. - {act} {verb} după cum urmează:\n{puncte}")
    text = "\n\n".join(corpuri)

    return ActCompus(titlu=titlu, text=text, verificare=_verifica(interventii, text))


def _verifica(interventii: list[Interventie], text: str) -> tuple[str, ...]:
    """Read the composed text back and flag any intent the extractor did not recover as its own."""
    citite = {
        (a.fel, a.act_tinta.id if a.act_tinta else None, a.locator.id if a.locator else "")
        for a in amendamente(text)
    }
    probleme: list[str] = []
    for n, intv in enumerate(interventii, start=1):
        refs = acte(intv.act)
        act_id = refs[0].act.id if refs else None
        asteptat = (intv.operatie, act_id, _locator_asteptat(intv).id)
        if asteptat not in citite:
            probleme.append(
                f"punctul {n} ({intv.operatie} {asteptat[2] or 'act întreg'} din {act_id}) "
                "nu s-a recitit identic — verifică formularea manual."
            )
    return tuple(probleme)
