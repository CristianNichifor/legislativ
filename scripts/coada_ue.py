"""Paginated contextual EU queue derived only from saved dossiers and checks."""

from pathlib import Path

from scripts import dosare


def lista(path, offset=0, status="toate"):
    if type(offset) is not int or not 0 <= offset <= 1_000_000:
        raise ValueError("Offset invalid.")
    filters = {
        "toate": "1",
        "text": "texte>0",
        "limba": "limbi>0",
        "metadate": "metadate>0",
        "schimbat": "texte>0 OR limbi>0",
        "indisponibil": "verificat=1 AND incomplet=1",
        "neverificat": "verificat=0",
        "neschimbat": "verificat=1 AND incomplet=0 AND texte=0 AND limbi=0 AND metadate=0",
    }
    if status not in filters:
        raise ValueError("Filtru invalid.")
    out = {"rulari": [], "total": 0, "offset": offset, "limita": 50}
    if not Path(path).exists():
        return out
    with dosare._open(path) as con:
        checks = (
            "LEFT JOIN verificari_dovezi c ON c.seq=(SELECT seq FROM verificari_dovezi "
            "WHERE rulare_id=r.id ORDER BY seq DESC LIMIT 1) "
            if con.execute("PRAGMA user_version").fetchone()[0] >= 3
            else "LEFT JOIN (SELECT NULL id,NULL verificat_la,NULL rezultat_json) c ON 0 "
        )
        # Count source signals, not findings. The latest stored check wins even without EU data.
        query = (
            """
        WITH base AS (
            SELECT r.id rulare_id,r.dosar_id,d.titlu,r.creat_la,
                c.id verificare_id,c.verificat_la,
                json_array_length(r.dovezi_json,'$.referinte_ue') referinte,
                json_extract(c.rezultat_json,'$.surse_ue') eu
            FROM rulari r JOIN dosare d ON d.id=r.dosar_id
        """
            + checks
            + """
            WHERE json_array_length(r.dovezi_json,'$.referinte_ue')>0
        ), summary AS (
            SELECT b.rulare_id,b.dosar_id,b.titlu,b.creat_la,b.verificare_id,b.verificat_la,
                b.referinte,
                b.eu IS NOT NULL verificat,
                CASE WHEN json_extract(b.eu,'$.schema_version') IS NOT 1
                    OR json_extract(b.eu,'$.comparatie_incompleta') IS NOT 0
                    OR count(j.key)<b.referinte THEN 1 ELSE 0 END incomplet,
                sum(CASE WHEN json_extract(j.value,'$.text_schimbat')=1
                    THEN 1 ELSE 0 END) texte,
                sum(CASE WHEN json_extract(j.value,'$.limba_schimbata')=1
                    THEN 1 ELSE 0 END) limbi,
                sum(CASE WHEN json_extract(j.value,'$.metadate_schimbate')=1
                    AND json_extract(j.value,'$.text_schimbat')=0
                    AND json_extract(j.value,'$.limba_schimbata')=0
                    THEN 1 ELSE 0 END) metadate
            FROM base b LEFT JOIN json_each(CASE
                WHEN json_extract(b.eu,'$.schema_version')=1
                THEN json_extract(b.eu,'$.surse') ELSE '[]' END) j
            GROUP BY b.rulare_id
        )
        """
        )
        where = " FROM summary WHERE " + filters[status]
        out["total"] = con.execute(query + "SELECT count(*)" + where).fetchone()[0]
        out["rulari"] = [
            dict(row)
            for row in con.execute(
                query
                + "SELECT *"
                + where
                + " ORDER BY COALESCE(verificat_la,creat_la) DESC,rulare_id LIMIT 50 OFFSET ?",
                (offset,),
            )
        ]
    return out
