"""What each Curtea Constituțională decision put out of force, extracted once and kept.

The register used to read every decision on every run: 177 of its 178 seconds went on parsing
all 20 006 of them to find the ~530 that strike anything. The text does not change once it has
been collected, so neither does the answer — and a tool an MP waits three minutes for is a tool
nobody opens a second time.

**"Has no strikes" is the normal case, so it cannot mean "not yet examined".** 97% of the case
law strikes nothing. Resuming on the absence of rows would re-read the whole corpus every pass,
which is precisely the mistake `publicat IS NULL` made before it: a mark records that a document
was examined, whatever the answer was.

**Strikes belong to the document, not to the citation key.** `decizie-5-1996` names a Court
decision no better than an agency's, and attributing a strike to the wrong issuer is the failure
`documente` exists to prevent. Re-collecting a document therefore replaces its strikes wholesale
— including replacing them with none, when a re-read finds the decision struck nothing after all.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import date

from scripts import depozit
from scripts.decizii import Proviziune, citeste


def _data(brut: str | None) -> date | None:
    try:
        return date.fromisoformat(brut) if brut else None
    except ValueError:
        return None


def extrage(cale_db: str = "corpus.db", *, lot: int = 2000, log=print) -> dict[str, int]:
    """Read strikes out of the decisions not yet examined. Returns what it did."""
    examinate = scrise = 0
    with depozit.deschide(cale_db) as con:
        ids = [
            r[0]
            for r in con.execute(
                "SELECT id_portal FROM documente WHERE lovituri_extrase IS NULL"
                " AND emitent LIKE 'Curtea Constitu%' AND tip = 'decizie'"
            )
        ]
        log(f"{len(ids)} decizii de examinat")
        for start in range(0, len(ids), lot):
            felie = ids[start : start + lot]
            semne = ",".join("?" * len(felie))
            randuri = con.execute(
                f"SELECT id_portal, cheie_act, publicat, vigoare, text FROM documente"
                f" WHERE id_portal IN ({semne})",
                felie,
            ).fetchall()
            for r in randuri:
                dec = citeste(r["cheie_act"], r["text"])
                # Wholesale replacement: a re-read that finds nothing must clear what was there.
                con.execute("DELETE FROM lovituri WHERE id_portal = ?", (r["id_portal"],))
                for ord_, prov in enumerate(dec.neconstitutionale, start=1):
                    con.execute(
                        "INSERT INTO lovituri (id_portal, ord, cheie_act, publicat, definitiva,"
                        " act, locator, fel, text) VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            r["id_portal"],
                            ord_,
                            r["cheie_act"],
                            r["publicat"] or r["vigoare"],
                            None if dec.definitiva is None else int(dec.definitiva),
                            prov.act,
                            prov.locator,
                            prov.fel,
                            prov.text,
                        ),
                    )
                    scrise += 1
                con.execute(
                    "UPDATE documente SET lovituri_extrase = 1 WHERE id_portal = ?",
                    (r["id_portal"],),
                )
                examinate += 1
            con.commit()
            log(f"  {examinate}/{len(ids)} decizii · {scrise} lovituri")
    return {"examinate": examinate, "lovituri": scrise}


def incarca(cale_db: str = "corpus.db") -> list:
    """Every recorded strike, as the register consumes them. Reads only; never parses."""
    from scripts.neconstitutional import Lovitura

    cx = sqlite3.connect(f"file:{cale_db}?mode=ro", uri=True)
    try:
        return [
            Lovitura(
                decizie=r[0],
                publicat=_data(r[1]),
                proviziune=Proviziune(r[3], r[4], r[6], r[5]),
                definitiva=None if r[2] is None else bool(r[2]),
            )
            for r in cx.execute(
                "SELECT cheie_act, publicat, definitiva, act, locator, fel, text"
                " FROM lovituri ORDER BY cheie_act, ord"
            )
        ]
    finally:
        cx.close()


def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="corpus.db")
    a = ap.parse_args()
    r = extrage(a.db)
    print(f"\ngata: {r['examinate']} decizii examinate, {r['lovituri']} lovituri înregistrate")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
