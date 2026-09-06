"""The text of a provision as it stands on a date — or an honest refusal to say.

`amendamente.py` records *that* a provision changed, by which act and when, and now carries the
replacement text each change supplies. This applies those changes to a provision's original text,
in date order, and returns the wording in force as of a date. It is the layer that turns "here is
the 2016 original" into "here is the law today", which is the question a person drafting or citing
a provision actually has.

**The governing rule is refusal, not best effort.** Applying an amendment wrong does not produce a
hedged finding; it produces a confident, fluent, wrong statement of the law, which is the single
worst thing this package could emit and the exact failure everything else here is built to avoid. So
a provision is consolidated *only* when every change touching it up to the date applied cleanly — a
recognised operation, a locator, and, where the operation supplies text, a payload. If any change
could not be applied, the original text is returned untouched with a `blocking` limitation naming
the act whose change was not applied. Never splice partial: a provision four-of-five consolidated,
presented as consolidated, is a lie about the fifth.

**Scope** (see `docs/CONSOLIDARE.md`). This applies, per provision: `modifica` (replace the text
with the payload), `abroga` (mark it repealed as of the date), and `completeaza` (append the payload
to the text). `introduce` inserts a *new* provision after an anchor — it does not change the
anchor's own text, so it neither applies to it nor refuses it; `consolideaza_in` materialises the
provision as its own result. Still refused, visibly: an unrecognised verb, a text-supplying change
with no quoted text, an operation with no date, and — for `introduce` — renumbering of the
provisions that follow (the inserted article is shown, but the shift of later numbers is not
applied). A case not handled is a `blocking` refusal, never a silent pass.

Standard library only. The consolidated text is `derived` — it is the result of applying
operations, not a string that appears in any single source document; the payloads it splices are
`verbatim`, being literal quotations from the amending acts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from scripts.amendamente import amendamente
from scripts.text import cheie

if TYPE_CHECKING:
    from scripts.parsare import ActParsat, Provizie

# Operations that change a provision's own text or state, applied in date order below.
_TEXT = frozenset({"modifica", "abroga", "completeaza"})
# Operations that need a quoted payload to apply (abroga does not; it just marks the state).
_CU_PAYLOAD = frozenset({"modifica", "completeaza"})


@dataclass(frozen=True)
class Operatie:
    """One change to apply: what it does, where, when, by which act, and the text it supplies."""

    fel: str
    locator: str  # the provision it targets, e.g. 'art7' or 'art7.alin2'
    data: date | None  # when it took effect; None means the change cannot be placed in time
    act: str  # the amending act id, kept for provenance
    continut_nou: str | None = None  # the replacement/inserted text, for operations that supply one


@dataclass(frozen=True)
class Schimbare:
    """One change that was actually applied, for attribution in the result."""

    fel: str
    act: str
    data: date | None


@dataclass(frozen=True)
class Rezultat:
    """A provision's text as of a date, or its original text and why it was not consolidated."""

    locator: str
    text: str  # the consolidated text when `complet`; the untouched original when not
    abrogat: bool
    la_data: date
    schimbari: tuple[Schimbare, ...] = ()
    limitari: tuple[str, ...] = ()
    complet: bool = True

    @property
    def increderea(self) -> str:
        """The text-as-of-a-date claim is derived — the product of applying operations, not a
        string quoted from one document. Kept explicit so the result labels itself like the rest."""
        return "derived"


def consolideaza(
    locator: str,
    text_original: str,
    operatii: list[Operatie],
    la_data: date | None = None,
) -> Rezultat:
    """The provision's text as of `la_data`, or the original with a blocking reason it could not be.

    Only operations that target this `locator` and took effect on or before `la_data` are
    considered; an operation dated after `la_data` is future, and is neither applied nor a defect.
    An operation this slice cannot apply — an unrecognised verb, a `modifica` with no quoted text,
    or one with no date to place it in time — makes the whole provision refuse: `complet=False`,
    `text` is the original, and `limitari` names the act. Applicable operations are applied in date
    order; `abroga` marks the provision repealed and stops further text changes.
    """
    la_data = la_data or date.today()
    ale_mele = [op for op in operatii if op.locator == locator]

    # Future changes do not apply as of this date, and are not a problem — set them aside first so
    # they neither splice nor trip the rail.
    aplicabile = [op for op in ale_mele if op.data is not None and op.data <= la_data]
    nedatate = [op for op in ale_mele if op.data is None]

    limitari: list[str] = []
    for op in nedatate:
        if op.fel == "introduce":
            continue  # an insertion never changes this provision, so its date does not gate it
        limitari.append(
            f"amendamentul din {op.act} nu are dată și nu poate fi plasat în timp; "
            "textul nu a fost consolidat."
        )
    for op in aplicabile:
        if op.fel == "introduce":
            continue  # handled at the document level (consolideaza_in), not on this provision
        if op.fel not in _TEXT:
            limitari.append(
                f"operația «{op.fel}» din {op.act} nu este aplicată automat în această versiune; "
                "citește actul modificator."
            )
        elif op.fel in _CU_PAYLOAD and not op.continut_nou:
            limitari.append(
                f"{op.fel} din {op.act} nu citează textul nou; "
                "nu poate fi aplicată fără a inventa text."
            )

    if limitari:
        return Rezultat(
            locator=locator,
            text=text_original,
            abrogat=False,
            la_data=la_data,
            schimbari=(),
            limitari=tuple(limitari),
            complet=False,
        )

    text = text_original
    abrogat = False
    schimbari: list[Schimbare] = []
    for op in sorted((o for o in aplicabile if o.fel != "introduce"), key=lambda o: o.data):
        if op.fel == "abroga":
            abrogat = True
        elif op.fel == "modifica":
            text = op.continut_nou or text
        elif op.fel == "completeaza":
            text = f"{text.rstrip()}\n{op.continut_nou}"
        schimbari.append(Schimbare(op.fel, op.act, op.data))

    return Rezultat(
        locator=locator,
        text=text,
        abrogat=abrogat,
        la_data=la_data,
        schimbari=tuple(schimbari),
        limitari=(),
        complet=True,
    )


def consolideaza_in(
    act: ActParsat,
    operatii: list[Operatie],
    la_data: date | None = None,
) -> dict[str, Rezultat]:
    """Consolidate every provision an operation touches, taking its original text from the tree.

    This is the wiring the design pointed at: the provision's original wording is not passed in by
    hand, it is read from the parsed act (`parsare.ActParsat.provizii`), which is the only source
    in this package that has structure below the whole document. One `Rezultat` per distinct
    locator the operations name; a locator no provision in the act carries is itself a refusal —
    the operation targets text that is not there — returned `complet=False` with a limitation
    rather than silently dropped, because a change that cannot be located is exactly the kind of
    gap that must stay visible.
    """
    la = la_data or date.today()
    dupa_loc = {p.locator_id: p.text for p in act.provizii}
    rezultate: dict[str, Rezultat] = {}

    # existing provisions the operations change: modifica / abroga / completeaza target a locator
    # that must already be there. An `introduce`'s locator is an *anchor*, not a provision this
    # touches, so it does not drive a per-provision consolidation.
    for locator in dict.fromkeys(op.locator for op in operatii if op.fel != "introduce"):
        original = dupa_loc.get(locator)
        if original is None:
            rezultate[locator] = Rezultat(
                locator=locator,
                text="",
                abrogat=False,
                la_data=la,
                limitari=(
                    f"locatorul «{locator}» nu există în {act.act.id}; "
                    "amendamentul nu poate fi aplicat unui text care nu a fost găsit.",
                ),
                complet=False,
            )
            continue
        rezultate[locator] = consolideaza(locator, original, operatii, la_data)

    # inserted provisions: an `introduce` adds a new provision after its anchor. Its text is the
    # payload; the shift it implies for later article numbers is not applied — the result says so.
    for n, op in enumerate((o for o in operatii if o.fel == "introduce"), start=1):
        if op.data is not None and op.data > la:
            continue  # a future insertion is not in force as of this date
        cheie_noua = f"{op.locator}~nou{n}" if op.locator else f"nou{n}"
        if not op.continut_nou:
            rezultate[cheie_noua] = Rezultat(
                locator=cheie_noua,
                text="",
                abrogat=False,
                la_data=la,
                limitari=(f"introducerea din {op.act} nu citează textul noii prevederi.",),
                complet=False,
            )
            continue
        rezultate[cheie_noua] = Rezultat(
            locator=cheie_noua,
            text=op.continut_nou,
            abrogat=False,
            la_data=la,
            schimbari=(Schimbare("introduce", op.act, op.data),),
            limitari=(
                f"prevedere nouă introdusă după «{op.locator}» prin {op.act}; renumerotarea "
                "articolelor care urmează nu este aplicată.",
            ),
            complet=True,
        )
    return rezultate


def operatii_amendatoare(
    amendator: ActParsat,
    citate: list[Provizie],
    data_operatie: date | None = None,
) -> dict[str, list[Operatie]]:
    """Every operation an amending page performs, grouped by the act each one targets.

    This is the bridge that lets consolidation run *from* an amending page rather than only be
    measured against one. `amendamente.py` resolves, for each numbered point, what it does
    (`fel`), to which act (`act_tinta`) and which provision (`locator`) — the whole
    chapeau-inheritance apparatus — but not the replacement text, because the portal marks that in
    an `S_CIT` block, not in the guillemets a person types. `parsare.citate` reads those blocks.
    Here the two are joined: the points that say `... va avea următorul cuprins:` are exactly the
    ones that carry a block, and they and the blocks appear in the same document order, so the
    n-th such point takes the n-th block.

    The alignment is checked, not trusted: if the count of replacement-announcing points and the
    count of blocks disagree, the page parsed skew and this raises rather than pairing a payload
    to the wrong provision — the one outcome consolidation must never reach. The operation date is
    the amending act's own entry into force (`amendator.vigoare`); a law that staggers its articles
    across several dates is not handled here, and an operation with no date will make the engine
    refuse downstream, which is the correct visible failure.
    """
    plain = "\n".join(p.text for p in amendator.provizii)
    ams = amendamente(plain, act_gazda=amendator.act)
    data = data_operatie or amendator.vigoare
    act_id = amendator.act.id

    anunta = [a for a in ams if "urmatorul cuprins" in cheie(a.text)]
    if len(anunta) != len(citate):
        raise ValueError(
            f"{act_id}: {len(anunta)} puncte anunță un cuprins nou dar pagina are "
            f"{len(citate)} blocuri S_CIT — pagina s-a parsat strâmb, nu împerechez la orbeală."
        )
    bloc = {id(a): c.text for a, c in zip(anunta, citate, strict=True)}

    grupat: dict[str, list[Operatie]] = {}
    for a in ams:
        if a.act_tinta is None or not a.locator:
            continue
        grupat.setdefault(a.act_tinta.id, []).append(
            Operatie(
                fel=a.fel,
                locator=a.locator.id,
                data=data,
                act=act_id,
                continut_nou=bloc.get(id(a)),
            )
        )
    return grupat


def raport(r: Rezultat) -> str:
    """The consolidated provision as it goes in front of a reader, with each change attributed."""
    if not r.complet:
        linii = [f"{r.locator}: text neconsolidat (original păstrat) — motive:"]
        linii += [f"  ⚠ {lim}" for lim in r.limitari]
        return "\n".join(linii)
    cap = f"{r.locator} — text la {r.la_data:%d.%m.%Y}"
    if r.abrogat:
        cap += " [ABROGAT]"
    linii = [cap, r.text]
    if r.schimbari:
        linii.append("modificat prin: " + ", ".join(f"{s.act} ({s.fel})" for s in r.schimbari))
    return "\n".join(linii)
