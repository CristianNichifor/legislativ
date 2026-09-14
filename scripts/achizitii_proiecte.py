"""Local parliamentary source browser and explicit, recorded acquisition actions."""

import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from scripts import documente_proiecte as documente
from scripts.lifecycle import normalize_stage_label, watchlist_lifecycle

PAGE_SIZE = 25
MAX_RECORDS = 100
MAX_TRACKER_EVENTS = 200


def _fold(text):
    return "".join(
        c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)
    ).casefold()


def _readonly(path):
    con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    budget = 0

    def stop():
        nonlocal budget
        budget += 1
        return budget > 20_000

    con.set_progress_handler(stop, 10_000)
    return con


def _initiative(stare, plx):
    if not isinstance(plx, str) or not 1 <= len(plx) <= 120:
        raise ValueError("Selecteaza o initiativa.")
    with closing(_readonly(stare.initiative)) as con:
        row = con.execute(
            "SELECT plx_id, titlu, stadiu, citit_la, cam, idp FROM initiative WHERE plx_id=?",
            (plx,),
        ).fetchone()
    if not row:
        raise ValueError("Initiativa nu exista in baza locala.")
    return dict(row)


def _metadata(row):
    out = dict(row)
    addressable = out["cam"] in (1, 2) and bool(re.fullmatch(r"\d{1,10}", out["idp"] or ""))
    out["fisa_url"] = (
        f"{documente.BASE}.proiect?cam={out['cam']}&idp={out['idp']}" if addressable else None
    )
    out["limba"] = None  # Parliamentary imports do not record an independently verified language.
    out["actualitate"] = "necunoscuta"
    out["lifecycle"] = normalize_stage_label(out.get("stadiu"))
    out["watchlist"] = watchlist_lifecycle(out)
    return out


def _event_source_family(chamber):
    folded = _fold(chamber)
    if "senat" in folded:
        return "senat"
    if "camera" in folded or "deputat" in folded:
        return "camera"
    return "parlament"


def _event_source_url(meta, row=None):
    row = row or {}
    steno_ids = row.get("steno_ids")
    steno_idm = row.get("steno_idm")
    if steno_ids:
        url = f"https://www.cdep.ro/pls/steno/steno2015.stenograma?ids={steno_ids}"
        if steno_idm:
            url += f"&idm={steno_idm}"
        return url
    return meta.get("fisa_url") or meta.get("sursa_url")


def _committee_role(action):
    folded = _fold(action)
    if "raport" in folded:
        return "report"
    if "aviz" in folded:
        return "opinion"
    return "committee"


def _report_position(action):
    folded = _fold(action)
    if "resping" in folded or "negativ" in folded:
        return "respingere"
    if "adopt" in folded or "favorabil" in folded or "admit" in folded:
        return "adoptare"
    return None


def _is_report_filed(action):
    folded = _fold(action)
    return "raport" in folded and any(
        term in folded
        for term in (
            "depus",
            "depun",
            "primit",
            "primire",
            "prezentat",
            "inaintat",
        )
    )


def _is_plenary_agenda(action, row):
    folded = _fold(action)
    return bool(row.get("steno_ids")) or any(
        term in folded
        for term in (
            "ordine de zi",
            "ordinea de zi",
            "plen",
            "programul de lucru",
        )
    )


def _nominal_url(idv):
    return f"https://www.cdep.ro/ords/pls/steno/evot2015.Nominal?idv={idv}" if idv else None


def _document_matches(document, *needles):
    folded = _fold((document.get("label") or "") + " " + (document.get("url") or ""))
    return any(needle in folded for needle in needles)


def _document_category(document):
    folded = _fold((document.get("label") or "") + " " + (document.get("url") or ""))
    if "raport" in folded:
        return "report"
    if "aviz" in folded or "punct de vedere" in folded:
        return "opinion"
    if "vot" in folded or "voturi" in folded:
        return "vote"
    return "document"


def _event_documents(key, documents):
    if key == "report_filed":
        needles = ("raport",)
    elif key in {"opinion_received", "opinion_requested"}:
        needles = ("aviz", "punct de vedere")
    elif key == "vote_recorded":
        needles = ("vot", "voturi")
    elif key == "plenary_agenda":
        needles = ("ordine de zi", "ordinea de zi", "plen")
    else:
        needles = ()
    if not needles:
        return []
    return [doc for doc in documents if _document_matches(doc, *needles)][:20]


def parliamentary_evidence_summary(*, documents=(), events=()):
    """Summarize parliamentary evidence without treating missing rows as legal absence."""
    documents = [doc for doc in documents if isinstance(doc, dict)]
    events = [event for event in events if isinstance(event, dict)]
    counts = {
        "documents": len(documents),
        "committees": sum(1 for event in events if event.get("key") == "committee_assignment"),
        "reports": sum(1 for event in events if event.get("key") == "report_filed"),
        "opinions": sum(
            1 for event in events if event.get("key") in {"opinion_received", "opinion_requested"}
        ),
        "votes": sum(1 for event in events if event.get("key") == "vote_recorded"),
        "plenary": sum(1 for event in events if event.get("key") == "plenary_agenda"),
    }
    available_links = sum(1 for doc in documents if doc.get("url"))
    unavailable_links = sum(1 for doc in documents if doc.get("status") == "unavailable")
    document_counts = {"reports": 0, "opinions": 0, "votes": 0}
    for doc in documents:
        category = _document_category(doc)
        if category == "report":
            document_counts["reports"] += 1
        elif category == "opinion":
            document_counts["opinions"] += 1
        elif category == "vote":
            document_counts["votes"] += 1
    for key, value in document_counts.items():
        counts[key] = max(counts[key], value)
    missing = [key for key, value in counts.items() if key != "documents" and not value]
    return {
        "contract": "parliamentary-project-evidence-summary-v1",
        "counts": counts,
        "available_document_links": available_links,
        "unavailable_document_links": unavailable_links,
        "missing": missing,
        "complete": not missing,
        "next_action": (
            "Verifică fișa parlamentară pentru: " + ", ".join(missing[:4]) + "."
            if missing
            else "Dovezile parlamentare principale există în trackerul local."
        ),
        "limitari": [
            "Rezumatul folosește numai date locale deja extrase.",
            "Lipsa unui rând local înseamnă dovadă neîncărcată, nu absență juridică.",
        ],
    }


def with_event_documents(events, documents):
    """Attach matching document links to already-normalized parliamentary events."""
    documents = [doc for doc in documents if isinstance(doc, dict)]
    enriched = []
    for event in events:
        if not isinstance(event, dict):
            continue
        linked = event.get("documents") or _event_documents(event.get("key"), documents)
        enriched.append({**event, "documents": linked})
    return enriched


def _tracker_events_from_rows(meta, stages, opinions, votes, documents=()):
    documents = [doc for doc in documents if isinstance(doc, dict)]
    events = []
    project_id = meta.get("plx_id") or ""
    for row in stages:
        action = row.get("actiune") or ""
        folded = _fold(action)
        committees = [c for c in (row.get("comisii") or "").split("\n") if c]
        base = {
            "project_id": project_id,
            "date": row.get("data"),
            "chamber": row.get("camera"),
            "source_family": _event_source_family(row.get("camera")),
            "source_url": _event_source_url(meta, row),
            "raw_action": action,
        }
        if committees and (
            "trimis" in folded
            or "trimisa" in folded
            or "sesiz" in folded
            or "repartiz" in folded
            or "raport" in folded
            or "aviz" in folded
        ):
            events.append(
                {
                    **base,
                    "key": "committee_assignment",
                    "committees": committees,
                    "role": _committee_role(action),
                    "deadline": None,
                }
            )
        if _is_report_filed(action):
            event_docs = _event_documents("report_filed", documents)
            events.append(
                {
                    **base,
                    "key": "report_filed",
                    "committee": committees[0] if committees else None,
                    "committees": committees,
                    "position": _report_position(action),
                    "document_hash": None,
                    "documents": event_docs,
                    "filed_at": row.get("data"),
                }
            )
        if _is_plenary_agenda(action, row):
            event_docs = _event_documents("plenary_agenda", documents)
            events.append(
                {
                    **base,
                    "key": "plenary_agenda",
                    "agenda_date": row.get("data"),
                    "documents": event_docs,
                }
            )
    for row in opinions:
        key = "opinion_received" if row.get("primit") else "opinion_requested"
        event_docs = _event_documents(key, documents)
        events.append(
            {
                "key": key,
                "project_id": project_id,
                "date": row.get("data"),
                "source_family": "avize",
                "source_url": meta.get("fisa_url") or meta.get("sursa_url"),
                "issuer": row.get("de_la"),
                "position": row.get("sens"),
                "number": row.get("numar"),
                "received": bool(row.get("primit")),
                "documents": event_docs,
            }
        )
    for row in votes:
        event_docs = _event_documents("vote_recorded", documents)
        events.append(
            {
                "key": "vote_recorded",
                "project_id": project_id,
                "date": row.get("data"),
                "chamber": row.get("camera"),
                "source_family": _event_source_family(row.get("camera")),
                "source_url": meta.get("fisa_url") or meta.get("sursa_url"),
                "vote_date": row.get("data"),
                "result": row.get("rezultat"),
                "question": row.get("intrebare"),
                "for": row.get("pentru"),
                "against": row.get("contra"),
                "abstain": row.get("abtineri"),
                "absent": row.get("absenti"),
                "nominal_url": _nominal_url(row.get("idv")),
                "documents": event_docs,
            }
        )
    return sorted(
        events,
        key=lambda item: (
            item.get("date") or "",
            {
                "committee_assignment": 10,
                "opinion_requested": 20,
                "opinion_received": 30,
                "report_filed": 40,
                "plenary_agenda": 50,
                "vote_recorded": 60,
            }.get(item["key"], 99),
            item.get("raw_action") or item.get("question") or "",
        ),
    )


def tracker_events(stare, plx, *, limit=MAX_TRACKER_EVENTS):
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= MAX_TRACKER_EVENTS
    ):
        raise ValueError("Limită invalidă.")
    meta = _metadata(_initiative(stare, plx))
    with closing(_readonly(stare.initiative)) as con:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"initiativa_etapa", "initiativa_aviz", "initiativa_vot"} & tables:
            return []
        stages = []
        if "initiativa_etapa" in tables:
            stages = [
                dict(r)
                for r in con.execute(
                    "SELECT data,camera,actiune,comisii,steno_ids,steno_idm "
                    "FROM initiativa_etapa WHERE plx_id=? ORDER BY ord LIMIT ?",
                    (plx, limit),
                )
            ]
        opinions = []
        if "initiativa_aviz" in tables:
            opinions = [
                dict(r)
                for r in con.execute(
                    "SELECT de_la,data,sens,numar,primit FROM initiativa_aviz "
                    "WHERE plx_id=? ORDER BY COALESCE(data,''), de_la LIMIT ?",
                    (plx, limit),
                )
            ]
        votes = []
        if "initiativa_vot" in tables:
            votes = [
                dict(r)
                for r in con.execute(
                    "SELECT data,camera,intrebare,pentru,contra,abtineri,rezultat,absenti,idv "
                    "FROM initiativa_vot WHERE plx_id=? ORDER BY COALESCE(data,''), camera LIMIT ?",
                    (plx, limit),
                )
            ]
    documents = documente.versiuni(stare, plx)
    return _tracker_events_from_rows(meta, stages, opinions, votes, documents)[:limit]


def _local(stare, plx, detail=False):
    out = {
        "versiuni_total": 0,
        "documente_total": 0,
        "documente_indisponibile_total": 0,
        "documente_descoperite": [],
        "versiuni": [],
        "incercari": [],
        "stare": "metadate",
    }
    path = documente.cale_store(stare)
    if not path.exists():
        return out
    with closing(_readonly(path)) as con:
        con.execute("BEGIN")
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not tables.intersection({"documente", "achizitii"}):
            raise sqlite3.DatabaseError("Unrecognized import store")
        if "documente" in tables:
            out["versiuni_total"] = con.execute(
                "SELECT count(*) FROM documente WHERE plx_id=?", (plx,)
            ).fetchone()[0]
            if out["versiuni_total"]:
                out["stare"] = "importat"
            if detail:
                out["versiuni"] = [
                    dict(r)
                    for r in con.execute(
                        "SELECT id, url, label, sha256, preluat_la, status FROM documente "
                        "WHERE plx_id=? ORDER BY preluat_la DESC, id DESC LIMIT ?",
                        (plx, MAX_RECORDS),
                    )
                ]
        if "document_links" in tables:
            out["documente_total"] = con.execute(
                "SELECT count(*) FROM document_links WHERE plx_id=?", (plx,)
            ).fetchone()[0]
            out["documente_indisponibile_total"] = con.execute(
                "SELECT count(*) FROM document_links WHERE plx_id=? AND status='unavailable'",
                (plx,),
            ).fetchone()[0]
            if out["documente_total"] and out["stare"] == "metadate":
                out["stare"] = "descoperit"
            if detail:
                out["documente_descoperite"] = [
                    dict(r)
                    for r in con.execute(
                        "SELECT id, url, label, source_url, status, discovered_at "
                        "FROM document_links WHERE plx_id=? "
                        "ORDER BY status, discovered_at DESC, id LIMIT ?",
                        (plx, MAX_RECORDS),
                    )
                ]
        if "achizitii" in tables:
            rows = [
                dict(r)
                for r in con.execute(
                    "SELECT operatie, url, versiune, incercat_la, reusit_la, stare, eroare "
                    "FROM achizitii WHERE plx_id=? "
                    "ORDER BY incercat_la DESC, operatie, url LIMIT ?",
                    (plx, MAX_RECORDS + 1 if detail else 1),
                )
            ]
            out["ultima_incercare"] = rows[0] if rows else None
            if detail:
                out["incercari"] = rows[:MAX_RECORDS]
                out["incercari_trunchiate"] = len(rows) > MAX_RECORDS
        out["versiuni_trunchiate"] = out["versiuni_total"] > len(out["versiuni"])
        out["documente_trunchiate"] = out["documente_total"] > len(out["documente_descoperite"])
    return out


def lista(stare, query="", offset=0):
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError("Cautare prea lunga.")
    if not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset <= 100_000:
        raise ValueError("Pagina invalida.")
    # Escape LIKE metacharacters: searches are literal, not caller-controlled wildcard scans.
    needle = "%" + query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    with closing(_readonly(stare.initiative)) as con:
        rows = con.execute(
            "SELECT plx_id, titlu, stadiu, citit_la, cam, idp FROM initiative "
            "WHERE plx_id LIKE ? ESCAPE '\\' OR titlu LIKE ? ESCAPE '\\' "
            "ORDER BY plx_id LIMIT ? OFFSET ?",
            (needle, needle, PAGE_SIZE + 1, offset),
        ).fetchall()
    results = []
    for row in rows[:PAGE_SIZE]:
        item = _metadata(row)
        try:
            item.update(_local(stare, row["plx_id"]))
        except (OSError, sqlite3.Error):
            item.update(stare="indisponibil", versiuni_total=None)
        results.append(item)
    return {
        "mod": "local",
        "initiative": results,
        "offset": offset,
        "mai_multe": len(rows) > PAGE_SIZE,
    }


def detaliu(stare, plx):
    meta = _metadata(_initiative(stare, plx))
    local = _local(stare, plx, detail=True)
    events = tracker_events(stare, plx)
    documents = [*local.get("documente_descoperite", []), *local.get("versiuni", [])]
    return {
        **meta,
        **local,
        "tracker_events": events,
        "parliamentary_evidence": parliamentary_evidence_summary(
            documents=documents, events=events
        ),
    }


def _record(stare, plx, operation, url, version, error=None):
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(documente.cale_store(stare), timeout=5) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS achizitii (plx_id TEXT NOT NULL, operatie TEXT NOT NULL, "
            "url TEXT NOT NULL, versiune TEXT, incercat_la TEXT NOT NULL, reusit_la TEXT, "
            "stare TEXT NOT NULL, eroare TEXT, PRIMARY KEY(plx_id, operatie, url))"
        )
        con.execute(
            "INSERT INTO achizitii VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(plx_id,operatie,url) DO UPDATE SET versiune=excluded.versiune, "
            "incercat_la=excluded.incercat_la, "
            "reusit_la=coalesce(excluded.reusit_la,achizitii.reusit_la), "
            "stare=excluded.stare, eroare=excluded.eroare",
            (
                plx,
                operation,
                url,
                version,
                now,
                None if error else now,
                "eroare" if error else "ok",
                error,
            ),
        )


def _record_unavailable_documents(stare, plx, result):
    for doc in result.get("documente_indisponibile") or []:
        url = doc.get("url") or doc.get("label") or result.get("fisa_url") or ""
        if not url:
            continue
        _record(
            stare,
            plx,
            "document_indisponibil",
            url,
            None,
            "Fișa proiectului referă un document care nu este disponibil pentru import automat.",
        )


def executa(stare, request):
    if (
        not isinstance(request, dict)
        or not isinstance(request.get("operatie"), str)
        or request["operatie"]
        not in {
            "descopera",
            "importa",
            "actualizeaza",
        }
    ):
        raise ValueError("Operatie invalida.")
    plx, operation = request.get("plx"), request["operatie"]
    meta = _metadata(_initiative(stare, plx))
    if not meta["fisa_url"]:
        raise ValueError("Initiativa nu are o fisa parlamentara adresabila.")
    version = None
    if operation == "descopera":
        url = meta["fisa_url"]
    elif operation == "importa":
        url = documente.url_oficial(request.get("url"))
    else:
        version = request.get("versiune")
        if not isinstance(version, str) or len(version) != 64:
            raise ValueError("Selecteaza o versiune importata.")
        url = documente.citeste(stare, plx, version)["url"]
    try:
        if operation == "descopera":
            result = documente.lista(stare, plx)
            _record_unavailable_documents(stare, plx, result)
            if result.get("avertisment"):
                raise OSError("Official source unavailable")
        elif operation == "importa":
            result = documente.importa(stare, plx, url)
        else:
            result = documente.verifica_actualizari(stare, plx, version)
    except (OSError, ValueError, sqlite3.Error) as exc:
        # Do not persist raw transport/database exceptions, which may contain local paths.
        if isinstance(exc, sqlite3.Error):
            error = "Depozitul local de importuri nu este disponibil."
        elif isinstance(exc, OSError):
            error = "Sursa oficiala nu este disponibila."
        else:
            error = "Documentul nu apare pe fisa sau formatul/extragerea nu este acceptat(a)."
        try:
            _record(stare, plx, operation, url, version, error)
        except (OSError, sqlite3.Error):
            raise ValueError(error + " Incercarea nu a putut fi inregistrata.") from exc
        raise ValueError(error) from exc
    try:
        _record(stare, plx, operation, url, version)
    except (OSError, sqlite3.Error):
        result["avertisment_achizitie"] = (
            "Rezultatul este disponibil, dar incercarea nu a fost inregistrata."
        )
    return result
