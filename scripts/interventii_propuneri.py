"""Explicit local target snapshots and deterministic proposal composition."""

import hashlib
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from scripts import dosare
from scripts.compunere import Interventie, compune

FIELDS = {"act_id", "locator", "operatie", "text_nou", "articol_nou"}
LOCATOR = re.compile(
    r"art([1-9]\d{0,3}(?:\^[1-9]\d{0,3})?)(?:\.alin([1-9]\d{0,3}))?(?:\.lit([a-z]))?"
)
CITATIONS = {
    "lege": "Legea",
    "oug": "Ordonan\u021ba de urgen\u021b\u0103 a Guvernului",
    "og": "Ordonan\u021ba Guvernului",
    "hg": "Hot\u0103r\u00e2rea Guvernului",
    "ordin": "Ordinul",
    "decret": "Decretul",
}


def valideaza(request):
    if (
        not isinstance(request, dict)
        or not set(request) >= FIELDS
        or set(request) - FIELDS - {"sha256_tinta"}
    ):
        raise ValueError("Interventie invalida.")
    result = {k: dosare._text(request[k], 12000 if k == "text_nou" else 100) for k in FIELDS}
    if result["operatie"] not in ("modifica", "abroga", "introduce"):
        raise ValueError("Operatie nesuportata.")
    if not LOCATOR.fullmatch(result["locator"]):
        raise ValueError("Locator nesuportat sau ambiguu.")
    if result["operatie"] == "abroga":
        if result["text_nou"]:
            raise ValueError("Abrogarea nu poate contine text de inlocuire.")
    elif not result["text_nou"]:
        raise ValueError("Textul propus este obligatoriu.")
    if result["operatie"] == "introduce":
        if "." in result["locator"] or not re.fullmatch(
            r"[1-9]\d{0,3}(?:\^[1-9]\d{0,3})?", result["articol_nou"]
        ):
            raise ValueError(
                "Introducerea necesita un articol nou si o ancora la nivel de articol."
            )
    elif result["articol_nou"]:
        raise ValueError("Numar nou permis numai pentru introducere.")
    return result


def _snapshot(stare, intent):
    path = getattr(stare, "corpus", None)
    if path is None:
        raise ValueError("Corpus local indisponibil pentru tinta.")
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        con.execute("BEGIN")
        act = con.execute(
            "SELECT id,sursa_url,citit_la FROM acte WHERE id=?", (intent["act_id"],)
        ).fetchone()
        rows = con.execute(
            "SELECT locator,ord,text,vigoare_de_la,vigoare_pana_la FROM provizii "
            "WHERE act_id=? AND locator=? ORDER BY ord LIMIT 101",
            (intent["act_id"], intent["locator"]),
        ).fetchall()
        if not act or not rows or len(rows) > 100:
            raise ValueError("Tinta exacta lipseste sau depaseste limita.")
        if (
            intent["operatie"] == "introduce"
            and con.execute(
                "SELECT 1 FROM provizii WHERE act_id=? AND (locator=? OR locator LIKE ?) LIMIT 1",
                (
                    intent["act_id"],
                    "art" + intent["articol_nou"],
                    "art" + intent["articol_nou"] + ".%",
                ),
            ).fetchone()
        ):
            raise ValueError("Numarul articolului nou exista deja in corpusul local.")
        texts = [r["text"] or "" for r in rows]
        longest = max(texts, key=len)
        if not longest.strip() or any(t not in longest for t in texts):
            raise ValueError("Tinta are texte ambigue; nu poate fi previzualizata integral.")
        if sum(len(t.encode()) for t in texts) > 80000:
            raise ValueError("Textul tintei depaseste limita.")
        return {"act": dict(act), "prevederi": [dict(r) for r in rows], "text": longest}


def pregateste(stare, request, *, snapshot=None, require_hash=False):
    intent = valideaza(request)
    match = re.fullmatch(
        r"(lege|oug|og|hg|ordin|decret)-(\d{1,5})-((?:19|20)\d{2})", intent["act_id"]
    )
    if not match:
        raise ValueError("Identificatorul actului nu permite o citare exacta suportata.")
    source = snapshot if snapshot is not None else _snapshot(stare, intent)
    digest = hashlib.sha256(dosare._json(source).encode()).hexdigest()
    if require_hash and request.get("sha256_tinta") != digest:
        raise ValueError("Tinta s-a schimbat sau previzualizarea lipseste. Refa previzualizarea.")
    article, paragraph, letter = LOCATOR.fullmatch(intent["locator"]).groups()
    result = compune(
        [
            Interventie(
                operatie=intent["operatie"],
                act=f"{CITATIONS[match[1]]} nr. {match[2]}/{match[3]}",
                articol=article,
                alineat=paragraph,
                litera=letter,
                text_nou=intent["text_nou"],
                articol_nou="art. " + intent["articol_nou"] if intent["articol_nou"] else None,
            )
        ]
    )
    generated = result.titlu + "\n\n" + result.text
    dosare._text(generated, 12000, True)
    return {
        "schema_version": 1,
        "cerere": {**intent, "sha256_tinta": digest},
        "tinta": source,
        "text_compus": generated,
        "verificare": list(result.verificare),
        "inainte": source["text"],
        "dupa": "" if intent["operatie"] == "abroga" else intent["text_nou"],
        "limitari": [
            "Simulare a interventiei, nu consolidare sau efect juridic certificat.",
            "Tinta capturata din corpusul local, separat de dovada istorica a constatarii.",
            "Introducere: ancora ramane neschimbata; textul de dupa este articolul nou.",
            "Verificarea compunerii testeaza recitirea sintactica, nu compatibilitatea juridica.",
        ],
    }
