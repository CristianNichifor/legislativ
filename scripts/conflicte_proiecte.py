"""Compare explicit amendment operations from two user-supplied draft texts."""

from scripts.amendamente import amendamente
from scripts.referinte import Locator
from scripts.text import cheie

MAX_TEXT = 60_000
MAX_OPERATII = 200


def operatii(text: str, tinte: set[str]) -> tuple[list[dict], bool]:
    extrase = amendamente(text)
    out = []
    for am in extrase[:MAX_OPERATII]:
        if not am.act_tinta or am.act_tinta.id not in tinte:
            continue
        loc = am.locator
        if am.fel == "introduce":
            nou = am.locator_nou
            if not nou or nou.litera or nou.punct or len(am.articole_noi) > 1:
                continue
            loc = Locator(
                articol=nou.articol or loc.articol,
                alineat=nou.alineat,
                litera=nou.litera,
                punct=nou.punct,
            )
        if am.fel != "abroga" and not loc.articol:
            continue
        if am.fel not in {"abroga", "modifica", "introduce"}:
            continue
        out.append(
            {
                "act_tinta": am.act_tinta.id,
                "locator": loc.id,
                "fel": am.fel,
                "text": am.text,
                "continut_nou": am.continut_nou,
                "incredere": am.increderea,
            }
        )
    return out, len(extrase) > MAX_OPERATII


def compara(a: list[dict], b: list[dict], limita: int = 40) -> tuple[list[dict], bool]:
    out = []
    for x in a:
        for y in b:
            if x["act_tinta"] != y["act_tinta"]:
                continue
            tip = None
            if {x["fel"], y["fel"]} == {"abroga", "modifica"}:
                repeal, change = (x, y) if x["fel"] == "abroga" else (y, x)
                loc = repeal["locator"]
                if not loc or change["locator"] == loc or change["locator"].startswith(loc + "."):
                    tip = "abrogare_modificare"
            elif x["locator"] == y["locator"]:
                if x["fel"] == y["fel"] == "introduce":
                    tip = "numerotare_dublata"
                elif x["fel"] == y["fel"] == "modifica" and (
                    x["continut_nou"]
                    and y["continut_nou"]
                    and cheie(x["continut_nou"]) != cheie(y["continut_nou"])
                ):
                    tip = "inlocuiri_diferite"
            if tip:
                if len(out) == limita:
                    return out, True
                out.append({"tip": tip, "a": x, "b": y})
    return out, False
