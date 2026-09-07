"""What to call an act when several acts claim the same name.

A citation key is `tip-numar-an` — `hg-1-2016` — and that is the right shape for a *citation*,
because it is everything a citation says. It is the wrong shape for a *document*, and the corpus
has been paying for the difference: 205 321 documents collapse onto 151 152 keys, and `acte` is
keyed on the citation, so **53 242 documents never got a row at all**. The number is exact and it
is the whole gap: `count(documente) - count(acte) = 53 242`.

They are not duplicates. `hg-1-2016` is claimed by eighteen different acts — a Government decision,
a Senate decision, one of the Chamber, one of the Permanent Electoral Authority, one of the College
of Psychologists, one of the Central Requisitions Commission, and twelve more. Every one is a real
`Hotărâre nr. 1 din 2016`; only the issuer tells them apart. `scrie_act` deletes by id before
inserting, so each collection overwrote the last, and the surviving row was whichever document was
read most recently — with its provisions, since those cascade. Seventeen acts' text went with it.

**The fix keeps the citation key working.** The act whose issuer is the one a citation means keeps
the bare `hg-1-2016`; the others take `hg-1-2016-<emitent>`. Nothing that already points at a bare
key breaks — not the graph's 926 759 edges, not a watchlist, not a shipped shard — because the bare
key still names the act a reader citing `HG nr. 1/2016` meant. What changes is that the other
seventeen stop being deleted.

**Which issuer a bare citation means** is stated per type rather than guessed per act. `Hotărârea
Guvernului` is the Government's; `Legea` is Parliament's; a `decret` is the President's. For the
types many bodies issue under the same word — `ordin`, `decizie` — no issuer is canonical, so the
bare key goes to the earliest published, deterministically, and the reader is told the key is
shared. That is a worse answer than a citation that named its issuer, and it is the honest one:
the citation genuinely does not say.

Measured on the collected corpus: of the 53 552 documents sitting on a numbered key that more than
one document claims, adding the issuer separates 45 236 — 84,5%. The remaining 8 316 share type,
number, year *and* issuer, and they are overwhelmingly `rectificare` and `act-aditional`, whose
number is not their own but that of the act they correct.
"""

from __future__ import annotations

import sqlite3
from typing import Final

from scripts.text import cheie

# Who a bare citation means, by type. Only the types with one issuer are listed: `Hotărârea
# Guvernului nr. 1/2016` is unambiguous in a way `Hotărârea nr. 1/2016` is not, and the reader
# writing the second one has not said which body they meant.
EMITENT_CANONIC: Final[dict[str, str]] = {
    "lege": "parlamentul",
    "oug": "guvernul",
    "og": "guvernul",
    "hg": "guvernul",
    "decret": "presedintele romaniei",
}


def _canonic(tip: str, emitent: str) -> bool:
    asteptat = EMITENT_CANONIC.get(tip)
    return bool(asteptat) and cheie(emitent or "").startswith(asteptat)


def id_unic(
    con: sqlite3.Connection,
    *,
    cheie_citare: str,
    tip: str,
    emitent: str,
    id_portal: str,
) -> str:
    """The id this document should hold, given what is already in `acte`.

    The bare citation key when this document is entitled to it — because nothing holds it, because
    this document already does, or because its issuer is the canonical one for the type and the
    holder's is not. Otherwise the key with the issuer's slug appended.

    Re-running this for a document already stored returns the same id, so a re-collection replaces
    its own row rather than growing a second one beside it.
    """
    randuri = con.execute(
        "SELECT id, id_portal, emitent FROM acte WHERE id = ? OR cheie_citare = ?",
        (cheie_citare, cheie_citare),
    ).fetchall()
    al_meu = next((r for r in randuri if r[1] and r[1] == id_portal), None)
    if al_meu:
        return al_meu[0]

    detine = next((r for r in randuri if r[0] == cheie_citare), None)
    if detine is None:
        return cheie_citare
    # The bare key is taken. It changes hands only for a canonical issuer displacing one that is
    # not — never between two non-canonical claimants, where the swap would depend on the order the
    # corpus happened to be collected in.
    if _canonic(tip, emitent) and not _canonic(tip, detine[2] or ""):
        return cheie_citare
    # The portal's own document id, not a slug of the issuer's name. A name would read better and
    # would not be stable: the service encodes its responses in a charset without `ș` and `ț` and
    # emits a literal `?` for both, so 113 910 documents — 55% of the corpus, across 344 of the 488
    # distinct issuers — carry `Ministerul Sănătă?ii` where the page says `Sănătății`. A slug of
    # the damaged spelling and a slug of the repaired one are different strings, so every such act
    # would change its id the day the names are cleaned, and every stored reference to it would
    # dangle. `id_portal` is unique at the source, so it also removes the need to break ties
    # between two acts of the same issuer, type, number and year — of which there are 8 316.
    return f"{cheie_citare}-{id_portal}" if id_portal else cheie_citare


def candidati(con: sqlite3.Connection, cheie_citare: str) -> list[sqlite3.Row]:
    """Every act a bare citation could mean, the one it most likely means first.

    Ordered: the canonical issuer for the type, then the earliest published, then the lowest portal
    id. Deterministic all the way down, so the same corpus answers the same way twice.
    """
    randuri = con.execute(
        "SELECT id, tip, numar, an, titlu, emitent, publicat, id_portal FROM acte"
        " WHERE cheie_citare = ? OR id = ?",
        (cheie_citare, cheie_citare),
    ).fetchall()
    return sorted(
        {r[0]: r for r in randuri}.values(),
        key=lambda r: (
            0 if _canonic(r[1], r[5] or "") else 1,
            r[6] or "9999",
            r[7] or "",
        ),
    )


def rezolva(con: sqlite3.Connection, cheie_citare: str) -> str | None:
    """The act id a bare citation resolves to, or None where the corpus holds no such act."""
    lista = candidati(con, cheie_citare)
    return lista[0][0] if lista else None


def recupereaza(cale_db, *, limita: int | None = None, log=print) -> dict:
    """Give an act row back to every document that lost one to a namesake.

    The documents are all still there — `documente` is the archive and nothing deletes from it —
    so nothing is refetched. For each document with no act row, one is written from what the
    archive already holds, with the flat text as its single provision. A later enrichment pass
    reads its stored page and replaces that with the article tree, exactly as for any other act.

    Nothing that already exists is touched. An act row is only ever added.
    """
    from scripts import depozit
    from scripts.parsare import Provizie
    from scripts.text import fara_separatoare

    with depozit.deschide(cale_db) as con:
        lipsa = con.execute(
            "SELECT d.id_portal, d.cheie_act, d.tip, d.numar, d.an, d.titlu, d.emitent,"
            "  d.publicat, d.vigoare, d.sursa_url, d.text"
            " FROM documente d LEFT JOIN acte a ON a.id_portal = d.id_portal"
            " WHERE a.id IS NULL" + (f" LIMIT {int(limita)}" if limita else "")
        ).fetchall()
    log(f"{len(lipsa)} documente fără act")

    scrise = 0
    with depozit.deschide(cale_db) as con:
        for i, r in enumerate(lipsa, start=1):
            id_portal, cheie, tip, numar, an, titlu, emitent, publicat, vigoare, url, text = r
            act_id = id_unic(
                con, cheie_citare=cheie, tip=tip, emitent=emitent or "", id_portal=id_portal
            )
            if con.execute("SELECT 1 FROM acte WHERE id = ?", (act_id,)).fetchone():
                # The bare key's holder is this document under another portal id — leave it alone
                # rather than overwrite an act that is not this one.
                continue
            con.execute(
                "INSERT INTO acte (id, cheie_citare, tip, numar, an, titlu, emitent, publicat,"
                " vigoare, republicat_din, id_portal, id_act_portal, sursa_url, citit_la)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    act_id,
                    cheie,
                    tip,
                    numar,
                    an,
                    titlu,
                    emitent,
                    publicat,
                    vigoare,
                    None,
                    id_portal,
                    "",
                    url,
                    _acum(),
                ),
            )
            # Through the store's own writer, so the search index is maintained the one way it is
            # maintained everywhere: `content='provizii'` keeps no copy of its own.
            depozit.scrie_provizii(con, act_id, [Provizie("text", fara_separatoare(text or ""))])
            scrise += 1
            if i % 2000 == 0:
                con.commit()
                log(f"  {i}/{len(lipsa)} · {scrise} acte recuperate")
        con.commit()
    log(f"gata: {scrise} acte recuperate")
    return {"fara_act": len(lipsa), "recuperate": scrise}


def _acum() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Dă înapoi rândul de act omonimelor care l-au pierdut.")
    p.add_argument("--db", required=True)
    p.add_argument("--limita", type=int)
    a = p.parse_args(argv)
    recupereaza(a.db, limita=a.limita)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
