"""Index which acts each pending initiative sets out to change.

`dublura.py` already reads an initiative's targets from its title and obiect at query time; this
precomputes them into `initiative_tinta` so the reverse question — *which pending bills touch this
law* — is a single indexed lookup rather than a scan of every initiative's text. That is the
question a drafter amending a law most wants answered before filing: not "does my exact wording
duplicate something" but "is anyone already working on this law at all".

The targets come from the same `amendamente` + `referinte` extraction the whole package runs on,
so the index is only ever as good as those — which is the point of measuring them. Read-only on
the initiative store, writing the index beside it; re-runnable, replacing each initiative's rows.
"""

from __future__ import annotations

from scripts import depozit
from scripts.dublura import tinte


def imbogateste(cale_db: str = "initiative.db", *, log=print) -> int:
    """Fill `initiative_tinta` from every initiative's title and obiect. Returns rows written."""
    with depozit.deschide(cale_db, readonly=True) as con:
        randuri = con.execute("SELECT plx_id, titlu, obiect FROM initiative").fetchall()

    scrise = 0
    with depozit.deschide(cale_db) as con:
        for i, r in enumerate(randuri, start=1):
            text = f"{r['titlu']} {r['obiect'] or ''}"
            con.execute("DELETE FROM initiative_tinta WHERE plx_id = ?", (r["plx_id"],))
            for t in tinte(text):
                act_id, _, locator = t.partition(" ")
                con.execute(
                    "INSERT OR REPLACE INTO initiative_tinta (plx_id, act_id, locator)"
                    " VALUES (?,?,?)",
                    (r["plx_id"], act_id, locator),
                )
                scrise += 1
            if i % 500 == 0:
                con.commit()
                log(f"  {i}/{len(randuri)} inițiative · {scrise} ținte")
    return scrise


def initiative_pe_act(con, act_id: str, *, doar_vii: bool = True) -> list[dict]:
    """Pending initiatives that touch a given act, newest first — the reverse lookup the index is for."""  # noqa: E501
    from scripts.dublura import STADII_MOARTE
    from scripts.text import cheie

    randuri = con.execute(
        "SELECT DISTINCT i.plx_id, i.senat_id, i.titlu, i.stadiu FROM initiative_tinta t"
        " JOIN initiative i ON i.plx_id = t.plx_id WHERE t.act_id = ? ORDER BY i.data_inreg DESC",
        (act_id,),
    ).fetchall()
    out = []
    for r in randuri:
        viu = not any(m in cheie(r["stadiu"] or "") for m in STADII_MOARTE)
        if doar_vii and not viu:
            continue
        out.append(
            {
                "plx_id": r["plx_id"],
                "senat_id": r["senat_id"],
                "titlu": r["titlu"],
                "stadiu": r["stadiu"] or "",
                "in_viata": viu,
            }
        )
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="initiative.db")
    a = ap.parse_args()
    n = imbogateste(a.db)
    with depozit.deschide(a.db, readonly=True) as con:
        acte = con.execute("SELECT count(DISTINCT act_id) FROM initiative_tinta").fetchone()[0]
        top = con.execute(
            "SELECT act_id, count(DISTINCT plx_id) c FROM initiative_tinta"
            " GROUP BY act_id ORDER BY c DESC LIMIT 8"
        ).fetchall()
    print(f"\n{n} ținte, {acte} acte atinse de inițiative în lucru")
    print("cele mai vizate acte:")
    for r in top:
        print(f"  {r['act_id']}: {r['c']} inițiative")
