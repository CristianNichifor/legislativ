"""The consolidation surface: a provision's current wording, with each change attributed.

`consolidare.py` is the engine — it applies operations to a provision and refuses when it cannot.
This is the layer the product sits on: it gathers the operations an act has undergone, runs the
engine over the act's provision tree, and returns each touched provision as text-in-force plus the
acts that changed it, or an honest note where consolidation was refused.

**The provision source is a seam, on purpose.** Today it reads committed local pages — the target
act and the amending acts that touch it, from `sources/`. That is offline and bounded, a demo of
the surface rather than general coverage. The intended evolution (recorded with the product
decisions) is a hosted database of consolidated law that a local install re-syncs; when that
arrives it fills the same `CATALOG` shape and the surface above does not change. What must never
happen here is a live per-request fetch from the portal on the product path — the tool stays
local, and consolidation reads what has been synced, not what a page returns right now.

Standard library only, like the rest.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from scripts.consolidare import Operatie, Rezultat, consolideaza_in, operatii_amendatoare
from scripts.parsare import ActParsat, citate_din_fisier, din_fisier

_SURSE = Path(__file__).resolve().parent.parent / "sources"

# act id → the local pages that consolidate it. The seam a hosted, re-syncable source will later
# fill; the keys are act ids because that is what the rest of the package keys on.
CATALOG: dict[str, dict[str, object]] = {
    "lege-98-2016": {
        "tinta": "lege-98-2016.html.gz",
        "amendatoare": ["lege-208-2022.html.gz"],
    },
}


def acte_disponibile() -> list[dict]:
    """The acts this install can consolidate right now — those whose pages are actually present."""
    out: list[dict] = []
    for act_id, spec in CATALOG.items():
        tinta = _SURSE / str(spec["tinta"])
        amendatoare = [a for a in spec["amendatoare"] if (_SURSE / a).is_file()]  # type: ignore[union-attr]
        if tinta.is_file() and amendatoare:
            out.append({"act_id": act_id, "amendatoare": len(amendatoare)})
    return out


def consolideaza_local(
    act_id: str,
    la_data: date | None = None,
) -> tuple[ActParsat, dict[str, Rezultat]]:
    """Consolidate every provision of `act_id` that a locally available amending act touches.

    Returns the parsed target act (so the surface can show a provision's current text even where it
    was not changed) and one `Rezultat` per touched provision — consolidated text with attribution
    where the engine could apply the change, the original with a reason where it refused.
    """
    spec = CATALOG.get(act_id)
    if spec is None:
        raise KeyError(act_id)
    tinta = din_fisier(_SURSE / str(spec["tinta"]))
    operatii: list[Operatie] = []
    for nume in spec["amendatoare"]:  # type: ignore[union-attr]
        cale = _SURSE / nume
        if not cale.is_file():
            continue
        amendator = din_fisier(cale)
        citate = citate_din_fisier(cale)
        # No date override: each operation is dated by its own amending act's entry into force.
        # `la_data` is the as-of cutoff, and belongs to the engine below, not to the operations.
        operatii += operatii_amendatoare(amendator, citate).get(act_id, [])
    rezultate = consolideaza_in(tinta, operatii, la_data)
    return tinta, rezultate


@lru_cache(maxsize=64)
def _consolidat_cache(act_id: str, la_data: date | None) -> dict[str, Rezultat]:
    """Parsing the fixtures on every lint would be wasteful — the corpus does not change between
    requests — so the touched-provision map is memoised per (act, date)."""
    _, rez = consolideaza_local(act_id, la_data=la_data)
    return rez


def modificari_pentru(act_id: str, la_data: date | None = None) -> dict[str, Rezultat]:
    """The provisions of `act_id` a locally available amending act touched, keyed by locator.

    Empty when the act cannot be consolidated locally — the honest answer a caller can act on
    without special-casing. This is what the linter reads to tell a draft it may be citing a
    provision that has since moved.
    """
    if act_id not in CATALOG:
        return {}
    try:
        return _consolidat_cache(act_id, la_data)
    except Exception:
        return {}
