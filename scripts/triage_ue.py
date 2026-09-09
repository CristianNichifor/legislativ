"""Rule-based triage hints for EU-law retrieval.

The labels here do not decide compatibility. They only name why a row is shown and which
manual checks are still blocked by missing local CELEX data.
"""

from __future__ import annotations

from scripts.text import cheie

DEROGARE_EXPRESII = (
    ("prin derogare", "prin derogare"),
    ("se deroga", "se derogă"),
    ("nu se aplica", "nu se aplică"),
    ("nu sunt aplicabile", "nu sunt aplicabile"),
    ("exceptie de la", "excepție de la"),
    ("exceptia de la", "excepția de la"),
    ("se suspenda aplicarea", "se suspendă aplicarea"),
)


def triere_rezultat(rand: dict) -> dict:
    """Label a returned EU provision by the deterministic reason it was retrieved."""
    if rand.get("potrivire") == "referinta":
        return {
            "nivel": "referinta",
            "eticheta": "referință UE citată",
            "explicatie": (
                "Proiectul citează explicit acest act CELEX; verifică prevederile afișate."
            ),
        }
    return {
        "nivel": "materie",
        "eticheta": "aceeași materie",
        "explicatie": (
            "Prevederea folosește termeni apropiați de proiect; nu implică o contradicție."
        ),
    }


def triere_referinta_lipsa(ref: dict) -> dict:
    """Label an explicit EU citation that cannot yet be inspected locally."""
    celex = ref.get("celex") or "CELEX"
    return {
        "nivel": "neimportat",
        "eticheta": "act UE neimportat",
        "explicatie": f"{celex} este citat explicit, dar lipsește din eu.db.",
    }


def semnale_draft(text: str, referinte: list[dict]) -> list[dict]:
    """Draft-level EU triage signals that are visible before any AI/legal judgement."""
    text_cheie = cheie(text or "")
    expresii = [afisaj for cautare, afisaj in DEROGARE_EXPRESII if cautare in text_cheie]
    if not expresii:
        return []

    return [
        {
            "nivel": "posibila_derogare",
            "eticheta": "posibilă derogare de la drept UE",
            "explicatie": (
                "Textul folosește formulări de derogare sau excepție; verifică manual actele UE "
                "citate ori candidate."
            ),
            "expresii": expresii,
            "referinte": sorted({r["celex"] for r in referinte if r.get("celex")}),
        }
    ]


def _celexuri(randuri: list[dict]) -> list[str]:
    return sorted({r["celex"] for r in randuri if r.get("celex")})


def _rand_matrice(
    cheie: str,
    dimensiune: str,
    stare: str,
    nivel: str,
    numar: int,
    actiune: str,
    *,
    celexuri: list[str] | None = None,
    detalii: str = "",
) -> dict:
    return {
        "cheie": cheie,
        "dimensiune": dimensiune,
        "stare": stare,
        "nivel": nivel,
        "numar": numar,
        "actiune": actiune,
        "celexuri": celexuri or [],
        "detalii": detalii,
    }


def matrice_analiza(
    rezultate: list[dict],
    referinte_neimportate: list[dict],
    semnale: list[dict],
    *,
    referinte: list[dict] | None = None,
) -> dict:
    """A deterministic EU-analysis checklist, not a compatibility verdict."""
    exacte = [r for r in rezultate if r.get("potrivire") == "referinta"]
    textuale = [r for r in rezultate if r.get("potrivire") != "referinta"]
    celex_citate = _celexuri((referinte or []) + exacte + referinte_neimportate)
    celex_lipsa = _celexuri(referinte_neimportate)
    derogari = [s for s in semnale if s.get("nivel") == "posibila_derogare"]

    randuri = [
        _rand_matrice(
            "acte_citate",
            "acte UE incidente citate",
            "detectate" if celex_citate else "fără citare explicită",
            "material" if celex_citate else "note",
            len(celex_citate),
            "Verifică actele importate și tratează actele lipsă ca blocaj de acoperire.",
            celexuri=celex_citate,
            detalii=f"{len(exacte)} prevederi afișate din citări explicite.",
        ),
        _rand_matrice(
            "acoperire_locala",
            "acoperire eu.db",
            "incompletă" if celex_lipsa else "completă pentru citările detectate",
            "blocking" if celex_lipsa else "note",
            len(celex_lipsa),
            "Importă CELEX-urile lipsă înainte de analiza pe prevederi.",
            celexuri=celex_lipsa,
        ),
        _rand_matrice(
            "aceeasi_materie",
            "aceeași materie",
            "candidate textuale" if textuale else "fără potriviri textuale",
            "material" if textuale else "note",
            len(textuale),
            "Folosește potrivirile textuale ca piste de verificare, nu ca verdict.",
            celexuri=_celexuri(textuale),
        ),
        _rand_matrice(
            "derogare_posibila",
            "derogare posibilă",
            "formulare detectată" if derogari else "nedetectată",
            "material" if derogari else "note",
            len(derogari),
            "Dacă există derogare, compară expres prevederea UE cu textul național.",
            celexuri=sorted({c for s in derogari for c in s.get("referinte", [])}),
        ),
        _rand_matrice(
            "lacuna_ue",
            "lacună sau obligație UE",
            "necalculată",
            "note",
            0,
            "Necesită identificarea obligației UE și a transpunerii naționale relevante.",
        ),
        _rand_matrice(
            "contradictie_ue",
            "contradicție posibilă",
            "necalculată",
            "note",
            0,
            "Necesită comparare juridică punctuală; retrieverul nu emite verdict.",
        ),
    ]
    return {
        "rezumat": {
            "acte_citate": len(celex_citate),
            "neimportate": len(celex_lipsa),
            "potriviri_textuale": len(textuale),
            "semnale": len(semnale),
        },
        "randuri": randuri,
        "limitari": [
            "Matricea UE este o listă de verificare deterministă; nu este verdict juridic."
        ],
    }


def aplica_triere(rezultate: list[dict]) -> list[dict]:
    """Attach row-level triage labels in place and return the same list."""
    for rand in rezultate:
        rand["triere"] = triere_rezultat(rand)
    return rezultate


def aplica_triere_lipsa(referinte: list[dict]) -> list[dict]:
    """Attach missing-import labels in place and return the same list."""
    for ref in referinte:
        ref["triere"] = triere_referinta_lipsa(ref)
    return referinte
