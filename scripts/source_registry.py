"""Local source registry for incremental, one-source acquisition work."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from scripts import cellar
from scripts.source_change_detection import detect_changes
from scripts.source_sync import STATE_LABELS, SYNC_STATES, can_transition, normalize_state

FAMILIES = {
    "legislatie_ro": "Legislație română",
    "parlament": "Proiecte parlamentare",
    "camera": "Camera Deputaților",
    "senat": "Senat",
    "consultare_guvern": "Consultări Guvern",
    "consultare_econsultare": "Consultări publice · e-consultare",
    "consultare_minister": "Consultări ministere",
    "monitorul_oficial": "Monitorul Oficial",
    "monitorul_oficial_pi": "Monitorul Oficial · Partea I",
    "monitorul_oficial_other_parts": "Monitorul Oficial · Părțile II-VII",
    "monitorul_oficial_local": "Monitorul Oficial Local",
    "ccr": "Decizii CCR",
    "avize": "Avize și opinii instituționale",
    "ue_cellar": "Drept UE · Cellar/EUR-Lex",
}
SCHEMA_VERSION = 1
PROJECT_PARSER_VERSION = "achizitii_proiecte.v1"
MANUAL_METADATA_PARSER_VERSION = "manual-source-metadata.v1"
MAX_TEXT = 1000
MAX_PAGE = 50
HEX64 = re.compile(r"^[a-f0-9]{64}$")
TOKEN = re.compile(r"^[a-z0-9_.:-]{1,120}$", re.I)
PROJECT_FAMILIES = frozenset({"parlament", "camera", "senat"})
ATTENTION_STATES = frozenset({"changed", "failed", "needs_review", "rate_limited"})
MANUAL_METADATA_FAMILIES = frozenset({"consultare_guvern", "consultare_minister", "avize"})
SYNC_FAMILIES = (
    PROJECT_FAMILIES | MANUAL_METADATA_FAMILIES | frozenset({"consultare_econsultare", "ue_cellar"})
)
BOOTSTRAP_ANCHOR_PREFIX = "family:"
BOOTSTRAP_SOURCES = (
    {
        "family": "legislatie_ro",
        "identifier": "family:legislatie_ro",
        "url": "https://legislatie.just.ro/",
        "label": "Portal Legislativ - legislatie consolidata",
    },
    {
        "family": "parlament",
        "identifier": "family:parlament",
        "url": "https://www.parlament.ro/",
        "label": "Parlamentul Romaniei - punct de intrare bicameral",
    },
    {
        "family": "camera",
        "identifier": "family:camera",
        "url": "https://www.cdep.ro/pls/proiecte/upl_pck2015.proiect",
        "label": "Camera Deputatilor - proiecte legislative PL-x",
    },
    {
        "family": "senat",
        "identifier": "family:senat",
        "url": "https://www.senat.ro/legis/lista.aspx",
        "label": "Senat - proiecte legislative",
    },
    {
        "family": "consultare_guvern",
        "identifier": "family:consultare_guvern",
        "url": "https://sgg.gov.ro/1/transparenta-decizionala/",
        "label": "Guvern - transparenta decizionala",
    },
    {
        "family": "consultare_econsultare",
        "identifier": "family:consultare_econsultare",
        "url": "https://e-consultare.gov.ro/Consultare-public%C4%83",
        "label": "e-consultare - consultari publice",
    },
    {
        "family": "consultare_minister",
        "identifier": "family:consultare_minister",
        "url": "https://www.gov.ro/ro/transparenta-decizionala",
        "label": "Ministere - transparenta decizionala",
    },
    {
        "family": "monitorul_oficial",
        "identifier": "family:monitorul_oficial",
        "url": "https://monitoruloficial.ro/",
        "label": "Monitorul Oficial - portal principal",
    },
    {
        "family": "monitorul_oficial_pi",
        "identifier": "family:monitorul_oficial_pi",
        "url": "https://monitoruloficial.ro/",
        "label": "Monitorul Oficial Partea I",
    },
    {
        "family": "ccr",
        "identifier": "family:ccr",
        "url": "https://www.ccr.ro/",
        "label": "Curtea Constitutionala - decizii",
    },
    {
        "family": "avize",
        "identifier": "family:avize",
        "url": "https://www.clr.ro/",
        "label": "Consiliul Legislativ si avize institutionale",
    },
    {
        "family": "ue_cellar",
        "identifier": "family:ue_cellar",
        "url": "https://op.europa.eu/en/web/cellar/cellar-data/metadata/knowledge-graph",
        "label": "EU Cellar knowledge graph / EUR-Lex",
    },
)


def cale(stare) -> Path:
    return Path(stare.initiative).with_suffix(".sources.db")


def now() -> str:
    return datetime.now(UTC).isoformat()


def _text(value, *, limit=MAX_TEXT, required=False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError("Câmp text invalid.")
    value = value.strip()
    if required and not value:
        raise ValueError("Câmp obligatoriu lipsă.")
    if len(value) > limit:
        raise ValueError("Câmp text prea lung.")
    return value


def _family(value: str) -> str:
    value = _text(value, limit=80, required=True)
    if value not in FAMILIES:
        raise ValueError("Familie de surse necunoscută.")
    return value


def _url(value) -> str:
    value = _text(value, limit=MAX_TEXT)
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL sursă invalid.")
    return value


def _hash(value) -> str:
    value = _text(value, limit=64)
    if value and not HEX64.fullmatch(value):
        raise ValueError("Hash sursă invalid.")
    return value


def _token(value, *, required=False) -> str:
    value = _text(value, limit=120, required=required)
    if value and not TOKEN.fullmatch(value):
        raise ValueError("Identificator sursă invalid.")
    return value


def _identifier(value) -> str:
    value = _text(value, limit=300)
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("Identificator public invalid.")
    return value


def _id(family: str, identifier: str, url: str) -> str:
    key = identifier or url
    if not key:
        raise ValueError("Sursa are nevoie de identificator sau URL.")
    digest = hashlib.sha256(f"{family}\0{key}".encode()).hexdigest()[:32]
    return f"src_{digest}"


def _open(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def init(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS source_registry (
          id TEXT PRIMARY KEY,
          family TEXT NOT NULL,
          identifier TEXT NOT NULL,
          url TEXT NOT NULL,
          label TEXT NOT NULL,
          state TEXT NOT NULL,
          last_hash TEXT NOT NULL DEFAULT '',
          parser_version TEXT NOT NULL DEFAULT '',
          last_attempt_at TEXT,
          last_http_status INTEGER,
          last_error TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_source_registry_family_state
          ON source_registry(family,state,updated_at);
        CREATE TABLE IF NOT EXISTS source_attempts (
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          source_id TEXT NOT NULL REFERENCES source_registry(id),
          attempted_at TEXT NOT NULL,
          state TEXT NOT NULL,
          http_status INTEGER,
          error_category TEXT NOT NULL DEFAULT '',
          content_hash TEXT NOT NULL DEFAULT '',
          parser_version TEXT NOT NULL DEFAULT '',
          note TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS source_snapshots (
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          source_id TEXT NOT NULL REFERENCES source_registry(id),
          captured_at TEXT NOT NULL,
          content_hash TEXT NOT NULL,
          parser_version TEXT NOT NULL DEFAULT '',
          snapshot_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_source_snapshots_source
          ON source_snapshots(source_id,captured_at DESC,seq DESC);
        PRAGMA user_version = 1;
        """
    )


def _sync_status(row: dict) -> dict:
    state = normalize_state(row["state"])
    is_anchor = str(row.get("identifier", "")).startswith(BOOTSTRAP_ANCHOR_PREFIX)
    can_sync = row["family"] in SYNC_FAMILIES and not is_anchor
    can_queue = state != "queued" and can_sync and can_transition(state, "queued")
    can_review = state in {"changed", "needs_review"}
    severity = {
        "unchanged": "ok",
        "changed": "attention",
        "failed": "attention",
        "needs_review": "attention",
        "rate_limited": "attention",
        "unavailable": "blocked",
        "queued": "ready",
        "discovered": "ready",
        "fetched": "ready",
    }[state]
    next_actions = {
        "discovered": "Pune sursa în coadă sau sincronizeaz-o explicit.",
        "queued": "Rulează sincronizarea pentru această singură sursă.",
        "fetched": "Verifică rezultatul ultimei preluări și clasificarea hash-ului.",
        "unchanged": "Nu este necesară nicio acțiune imediată.",
        "changed": "Revizuiește dosarele și propunerile dependente înainte de a închide alerta.",
        "failed": "Reîncearcă sincronizarea după ce verifici identificatorul sau URL-ul.",
        "unavailable": (
            "Păstrează sursa vizibilă și corectează identificatorul sau înlocuiește sursa."
        ),
        "rate_limited": "Reîncearcă mai târziu; nu porni sync-uri repetate automat.",
        "needs_review": (
            "Revizie manuală: sursa a fost citită, dar nu poate actualiza automat date juridice."
        ),
    }
    freshness = "current"
    freshness_label = "Sincronizată local."
    if is_anchor:
        freshness = "family_anchor"
        freshness_label = "Ancoră de familie; adaugă surse punctuale înainte de sync."
        next_actions["discovered"] = (
            "Adaugă o sursă punctuală din această familie; ancora nu se sincronizează direct."
        )
    elif not row.get("last_attempt_at"):
        freshness = "never_synced"
        freshness_label = "Nesincronizată; nu există încă o citire locală."
    elif state in {"failed", "rate_limited", "unavailable"}:
        freshness = state
        freshness_label = next_actions[state]
    elif state in {"changed", "needs_review"}:
        freshness = "needs_human_review"
        freshness_label = "Citită local, dar așteaptă revizie umană."
    return {
        "state": state,
        "label": STATE_LABELS[state],
        "severity": severity,
        "freshness": freshness,
        "freshness_label": freshness_label,
        "can_queue": can_queue,
        "can_sync": can_sync,
        "can_review": can_review,
        "next_action": next_actions[state],
    }


def _row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["sync_status"] = _sync_status(data)
    return data


def _plain_row(row: sqlite3.Row) -> dict:
    return dict(row)


def _latest_change(payloads: list[dict]) -> dict | None:
    if not payloads:
        return None
    previous = payloads[1] if len(payloads) > 1 else None
    return detect_changes(previous, payloads[0])


def _tables(con: sqlite3.Connection) -> set[str]:
    return {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _impact_empty(row: dict, *, available: bool = True) -> dict:
    state = normalize_state(row["state"])
    actionable = state in ATTENTION_STATES
    return {
        "contract": "changed-source-impact-v1",
        "available": available,
        "source_id": row["id"],
        "state": state,
        "actionable": actionable,
        "summary": {
            "affected_dossiers": 0,
            "affected_runs": 0,
            "affected_notes": 0,
            "affected_rule_drafts": 0,
            "affected_proposals": 0,
            "affected_watchlist_items": 0,
        },
        "samples": {
            "dossiers": [],
            "runs": [],
            "notes": [],
            "rule_drafts": [],
            "proposals": [],
            "watchlist": [],
        },
        "actions": {
            "inspect_source": True,
            "open_evidence": row["family"] in SYNC_FAMILIES,
            "open_affected_runs": row["family"] in PROJECT_FAMILIES,
            "create_review_note": actionable,
            "mark_reviewed": state in {"changed", "needs_review"},
            "retry_sync": row["family"] in SYNC_FAMILIES and state in {"failed", "rate_limited"},
        },
        "limitari": [
            "Impactul este local și conservator; nu reconsultă sursa oficială.",
            (
                "Propunerile sunt numărate numai când sunt legate de rulări "
                "sau referințe locale găsite."
            ),
        ],
    }


def _count_like(con: sqlite3.Connection, table: str, columns: list[str], needle: str) -> int:
    if not needle:
        return 0
    where = " OR ".join(f"{column} LIKE ? ESCAPE '\\'" for column in columns)
    escaped = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    return con.execute(
        f"SELECT count(*) FROM {table} WHERE {where}",
        [escaped] * len(columns),
    ).fetchone()[0]


def _sample_rows(
    con: sqlite3.Connection,
    sql: str,
    params: tuple[object, ...],
    *,
    limit: int = 5,
) -> list[dict]:
    return [dict(row) for row in con.execute(sql + " LIMIT ?", (*params, limit))]


def _project_impact(stare, row: dict, impact: dict, path: Path) -> None:
    from scripts import dosare

    affected = dosare.rulari_afectate_proiect(path, row["identifier"], 0)
    impact["summary"]["affected_runs"] = affected["total"]
    impact["samples"]["runs"] = affected["rulari"][:5]
    dossier_ids = {item["dosar_id"] for item in affected["rulari"]}
    impact["summary"]["affected_dossiers"] = len(dossier_ids)
    impact["samples"]["dossiers"] = [
        {"dosar_id": item["dosar_id"], "titlu": item.get("dosar_titlu", "")}
        for item in affected["rulari"][:5]
    ]
    if affected["total"] > len(affected["rulari"]):
        impact["limitari"].append(
            "Lista de rulări afectate este paginată; numărul de dosare "
            "este calculat pe pagina afișată."
        )
    with dosare._open(path) as con:
        tables = _tables(con)
        if "watchlist_dosare" in tables:
            watch = _sample_rows(
                con,
                "SELECT w.id,w.dosar_id,d.titlu,w.tip,w.valoare,w.eticheta,w.revizuit_la "
                "FROM watchlist_dosare w JOIN dosare d ON d.id=w.dosar_id "
                "WHERE w.tip='project' AND w.valoare=? ORDER BY w.creat_la DESC,w.id",
                (row["identifier"],),
            )
            impact["samples"]["watchlist"] = watch
            impact["summary"]["affected_watchlist_items"] = con.execute(
                "SELECT count(*) FROM watchlist_dosare WHERE tip='project' AND valoare=?",
                (row["identifier"],),
            ).fetchone()[0]
        if "propuneri" in tables and affected["rulari"]:
            run_ids = [item["rulare_id"] for item in affected["rulari"]]
            placeholders = ",".join("?" for _ in run_ids)
            impact["summary"]["affected_proposals"] = con.execute(
                "SELECT count(*) FROM propuneri WHERE rulare_id IN (" + placeholders + ")",
                run_ids,
            ).fetchone()[0]
            impact["samples"]["proposals"] = [
                dict(item)
                for item in con.execute(
                    "SELECT p.id,p.rulare_id,p.constatare_id,p.titlu,p.revizie,p.creat_la "
                    "FROM propuneri p WHERE p.rulare_id IN ("
                    + placeholders
                    + ") ORDER BY p.creat_la DESC,p.id LIMIT 5",
                    run_ids,
                )
            ]


def _direct_reference_impact(row: dict, impact: dict, path: Path) -> None:
    from scripts import dosare

    identifier = row.get("identifier") or ""
    hash_value = row.get("last_hash") or ""
    with dosare._open(path) as con:
        tables = _tables(con)
        if "note_manuale" in tables:
            params: list[object] = [identifier]
            checks = ["n.act_id=?"]
            if hash_value:
                checks.append("n.sursa_sha256=?")
                params.append(hash_value)
            if row.get("url"):
                checks.append("n.sursa_url=?")
                params.append(row["url"])
            where = " OR ".join(checks)
            impact["summary"]["affected_notes"] = con.execute(
                f"SELECT count(*) FROM note_manuale n WHERE {where}", params
            ).fetchone()[0]
            impact["samples"]["notes"] = [
                dict(item)
                for item in con.execute(
                    "SELECT n.id,n.dosar_id,d.titlu AS dosar_titlu,n.titlu,n.tip,n.stare,"
                    "n.act_id,n.locator,n.modificat_la FROM note_manuale n "
                    "JOIN dosare d ON d.id=n.dosar_id WHERE "
                    + where
                    + " ORDER BY n.modificat_la DESC,n.id LIMIT 5",
                    params,
                )
            ]
        if "law_rule_drafts" in tables:
            params = [identifier, f"%{identifier}%"]
            impact["summary"]["affected_rule_drafts"] = con.execute(
                "SELECT count(*) FROM law_rule_drafts WHERE act_id=? OR payload_json LIKE ?",
                params,
            ).fetchone()[0]
            impact["samples"]["rule_drafts"] = [
                dict(item)
                for item in con.execute(
                    "SELECT r.id,r.dosar_id,d.titlu AS dosar_titlu,r.act_id,r.locator,"
                    "r.provision_id,r.creat_la FROM law_rule_drafts r "
                    "JOIN dosare d ON d.id=r.dosar_id "
                    "WHERE r.act_id=? OR r.payload_json LIKE ? "
                    "ORDER BY r.creat_la DESC,r.id LIMIT 5",
                    params,
                )
            ]
        if "propuneri" in tables:
            impact["summary"]["affected_proposals"] += _count_like(
                con, "propuneri", ["titlu", "text", "motiv"], identifier
            )
            impact["samples"]["proposals"].extend(
                _sample_rows(
                    con,
                    "SELECT p.id,r.dosar_id,d.titlu AS dosar_titlu,p.rulare_id,"
                    "p.constatare_id,p.titlu,p.revizie,p.creat_la FROM propuneri p "
                    "JOIN rulari r ON r.id=p.rulare_id JOIN dosare d ON d.id=r.dosar_id "
                    "WHERE p.titlu LIKE ? ESCAPE '\\' OR p.text LIKE ? ESCAPE '\\' "
                    "OR p.motiv LIKE ? ESCAPE '\\' ORDER BY p.creat_la DESC,p.id",
                    tuple(
                        "%"
                        + identifier.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                        + "%"
                        for _ in range(3)
                    ),
                )
            )
        if "watchlist_dosare" in tables:
            watch_kind = "celex" if row["family"] == "ue_cellar" else "act"
            watch = _sample_rows(
                con,
                "SELECT w.id,w.dosar_id,d.titlu,w.tip,w.valoare,w.eticheta,w.revizuit_la "
                "FROM watchlist_dosare w JOIN dosare d ON d.id=w.dosar_id "
                "WHERE w.tip=? AND w.valoare=? ORDER BY w.creat_la DESC,w.id",
                (watch_kind, identifier),
            )
            impact["samples"]["watchlist"] = watch
            impact["summary"]["affected_watchlist_items"] = con.execute(
                "SELECT count(*) FROM watchlist_dosare WHERE tip=? AND valoare=?",
                (watch_kind, identifier),
            ).fetchone()[0]


def _impact(stare, row: dict) -> dict:
    impact = _impact_empty(row)
    path = Path(stare.dosare_db) if getattr(stare, "dosare_db", None) else None
    if path is None:
        try:
            from scripts import dosare

            path = dosare.cale(stare)
        except (OSError, ValueError):
            return _impact_empty(row, available=False)
    if not path.exists():
        return _impact_empty(row, available=False)
    try:
        if row["family"] in PROJECT_FAMILIES and row.get("identifier"):
            _project_impact(stare, row, impact, path)
        if row["family"] in {"ue_cellar", "legislatie_ro", "consultare_minister", "avize"} and (
            row.get("identifier") or row.get("url")
        ):
            _direct_reference_impact(row, impact, path)
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError):
        return _impact_empty(row, available=False)
    return impact


def _with_impact(stare, row: dict) -> dict:
    return {**row, "impact": _impact(stare, row)}


def families() -> dict[str, str]:
    return dict(FAMILIES)


def lista(stare, qs: dict | None = None) -> dict:
    qs = qs or {}
    offset = max(0, int((qs.get("offset") or ["0"])[0]))
    family = (qs.get("family") or [""])[0]
    state = (qs.get("state") or [""])[0]
    source_id = (qs.get("id") or [""])[0]
    attention = (qs.get("attention") or [""])[0] in {"1", "true", "da"}
    query = _text((qs.get("q") or [""])[0], limit=200).lower()
    params: list[object] = []
    where = []
    if source_id:
        where.append("id=?")
        params.append(_token(source_id, required=True))
    if family:
        where.append("family=?")
        params.append(_family(family))
    if state:
        where.append("state=?")
        params.append(normalize_state(state))
    elif attention:
        where.append("state IN (" + ",".join("?" for _ in ATTENTION_STATES) + ")")
        params.extend(sorted(ATTENTION_STATES))
    if query:
        where.append("(lower(identifier) LIKE ? OR lower(url) LIKE ? OR lower(label) LIKE ?)")
        needle = f"%{query}%"
        params.extend([needle, needle, needle])
    clause = " WHERE " + " AND ".join(where) if where else ""
    path = cale(stare)
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "families": families(),
            "states": list(SYNC_STATES),
            "attention_states": sorted(ATTENTION_STATES),
            "sources": [],
            "total": 0,
            "offset": offset,
            "more": False,
            "counts": {},
        }
    with closing(_open(path)) as con:
        init(con)
        total = con.execute("SELECT count(*) FROM source_registry" + clause, params).fetchone()[0]
        rows = con.execute(
            "SELECT * FROM source_registry"
            + clause
            + " ORDER BY updated_at DESC, id LIMIT ? OFFSET ?",
            [*params, MAX_PAGE, offset],
        ).fetchall()
        attempts: dict[str, list[dict]] = {row["id"]: [] for row in rows}
        snapshots: dict[str, list[dict]] = {row["id"]: [] for row in rows}
        snapshot_payloads: dict[str, list[dict]] = {row["id"]: [] for row in rows}
        if attempts:
            placeholders = ",".join("?" for _ in attempts)
            for attempt in con.execute(
                "SELECT source_id,attempted_at,state,http_status,error_category,content_hash,"
                "parser_version,note FROM source_attempts WHERE source_id IN ("
                + placeholders
                + ") ORDER BY attempted_at DESC, seq DESC",
                list(attempts),
            ):
                bucket = attempts[attempt["source_id"]]
                if len(bucket) < 3:
                    bucket.append(_plain_row(attempt))
            for snapshot in con.execute(
                "SELECT source_id,captured_at,content_hash,parser_version,snapshot_json "
                "FROM source_snapshots WHERE source_id IN ("
                + placeholders
                + ") ORDER BY captured_at DESC, seq DESC",
                list(snapshots),
            ):
                bucket = snapshots[snapshot["source_id"]]
                payload = json.loads(snapshot["snapshot_json"])
                payload = {
                    **payload,
                    "content_hash": snapshot["content_hash"],
                    "parser_version": snapshot["parser_version"],
                    "captured_at": snapshot["captured_at"],
                }
                if len(snapshot_payloads[snapshot["source_id"]]) < 2:
                    snapshot_payloads[snapshot["source_id"]].append(payload)
                if len(bucket) < 3:
                    bucket.append(
                        {
                            "captured_at": snapshot["captured_at"],
                            "content_hash": snapshot["content_hash"],
                            "parser_version": snapshot["parser_version"],
                            "summary": payload.get("summary", {}),
                        }
                    )
        counts = {
            f"{r['family']}:{r['state']}": r["c"]
            for r in con.execute(
                "SELECT family,state,count(*) c FROM source_registry GROUP BY family,state"
            )
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "families": families(),
        "states": list(SYNC_STATES),
        "attention_states": sorted(ATTENTION_STATES),
        "sources": [
            _with_impact(
                stare,
                dict(
                    _row(row),
                    attempts=attempts.get(row["id"], []),
                    snapshots=snapshots.get(row["id"], []),
                    latest_change=_latest_change(snapshot_payloads.get(row["id"], [])),
                ),
            )
            for row in rows
        ],
        "total": total,
        "offset": offset,
        "more": offset + len(rows) < total,
        "counts": counts,
    }


def descopera(stare, data: dict) -> dict:
    family = _family(data.get("family", ""))
    identifier = _identifier(data.get("identifier", ""))
    url = _url(data.get("url", ""))
    label = _text(data.get("label", ""), limit=300) or identifier or url
    ident = _id(family, identifier, url)
    stamp = now()
    with closing(_open(cale(stare))) as con:
        init(con)
        con.execute(
            """
            INSERT INTO source_registry
              (id,family,identifier,url,label,state,created_at,updated_at)
            VALUES (?,?,?,?,?,'discovered',?,?)
            ON CONFLICT(id) DO UPDATE SET
              url=COALESCE(NULLIF(excluded.url,''),url),
              label=excluded.label,
              updated_at=excluded.updated_at
            """,
            (ident, family, identifier, url, label, stamp, stamp),
        )
        con.commit()
        return _row(con.execute("SELECT * FROM source_registry WHERE id=?", (ident,)).fetchone())


def bootstrap(stare) -> dict:
    """Register the required official source-family anchors without fetching network data."""
    before = {row["id"] for row in lista(stare)["sources"]}
    sources = [descopera(stare, item) for item in BOOTSTRAP_SOURCES]
    created = sum(1 for row in sources if row["id"] not in before)
    return {
        "contract": "source-bootstrap-v1",
        "created": created,
        "updated": len(sources) - created,
        "total": len(sources),
        "sources": sources,
        "next_action": "Sincronizeaza sursele punctuale; ancorele doar declara familiile oficiale.",
    }


def descopera_econsultare(stare, data: dict | None = None) -> dict:
    """Fetch the official e-consultare listing and register bounded row snapshots."""
    data = data or {}
    try:
        limit = int(data.get("limit", 50))
    except (TypeError, ValueError) as exc:
        raise ValueError("Limită e-consultare invalidă.") from exc
    from scripts import achizitii_econsultare

    listing = achizitii_econsultare.descopera_actiongrid(limit=limit)
    created = 0
    updated = 0
    stored_snapshots = 0
    tracker_events = 0
    sources = []
    for snapshot in listing["snapshots"]:
        summary = snapshot.get("summary") or {}
        source = descopera(
            stare,
            {
                "family": "consultare_econsultare",
                "identifier": snapshot.get("url", ""),
                "url": snapshot.get("url", ""),
                "label": summary.get("title") or snapshot.get("url", ""),
            },
        )
        was_created = source["state"] == "discovered" and not source.get("last_hash")
        content_hash = achizitii_econsultare.snapshot_hash(snapshot)
        _store_snapshot(
            stare, source["id"], content_hash, snapshot, achizitii_econsultare.PARSER_VERSION
        )
        stored_snapshots += 1
        events = _persist_econsultare_tracker_event(stare, source["id"], snapshot, content_hash)
        tracker_events += len(events)
        final_state = (
            "needs_review"
            if not summary.get("title")
            else _sync_state(source.get("last_hash", ""), content_hash)
        )
        if source["state"] == "discovered" and final_state != "needs_review":
            source = pune_in_coada(stare, source["id"])
        if source["state"] == "queued" and final_state in {"changed", "unchanged"}:
            source = inregistreaza(
                stare,
                {
                    "id": source["id"],
                    "state": "fetched",
                    "http_status": listing.get("http_status", 200),
                    "content_hash": content_hash,
                    "parser_version": achizitii_econsultare.PARSER_VERSION,
                    "note": "Rând e-consultare descoperit din lista oficială.",
                },
            )
        source = inregistreaza(
            stare,
            {
                "id": source["id"],
                "state": final_state,
                "http_status": listing.get("http_status", 200),
                "content_hash": content_hash,
                "parser_version": achizitii_econsultare.PARSER_VERSION,
                "note": "Rând e-consultare actualizat din lista oficială.",
            },
        )
        created += int(was_created)
        updated += int(not was_created)
        sources.append(_with_tracker_sync(source, events))
    return {
        "contract": "source-registry-econsultare-discovery-v1",
        "listing_url": listing["listing_url"],
        "endpoint_url": listing["endpoint_url"],
        "http_status": listing["http_status"],
        "created": created,
        "updated": updated,
        "stored_snapshots": stored_snapshots,
        "tracker_events": tracker_events,
        "sources": sources,
        "limit": listing["limit"],
        "limitations": listing["limitations"],
    }


def pune_in_coada(stare, source_id: str) -> dict:
    source_id = _token(source_id, required=True)
    stamp = now()
    with closing(_open(cale(stare))) as con:
        init(con)
        row = con.execute("SELECT * FROM source_registry WHERE id=?", (source_id,)).fetchone()
        if row is None:
            raise ValueError("Sursa nu există în registru.")
        if not can_transition(row["state"], "queued"):
            raise ValueError("Tranziție de stare invalidă.")
        con.execute(
            "UPDATE source_registry SET state='queued',updated_at=? WHERE id=?",
            (stamp, source_id),
        )
        con.commit()
        updated = con.execute("SELECT * FROM source_registry WHERE id=?", (source_id,)).fetchone()
        return _row(updated)


def inregistreaza(stare, data: dict) -> dict:
    source_id = _token(data.get("id", ""), required=True)
    state = normalize_state(_text(data.get("state", ""), limit=40, required=True))
    content_hash = _hash(data.get("content_hash", ""))
    parser_version = _token(data.get("parser_version", ""))
    error = _token(data.get("error_category", ""))
    note = _text(data.get("note", ""), limit=500)
    http_status = data.get("http_status")
    if http_status is not None and (
        not isinstance(http_status, int) or not 100 <= http_status <= 599
    ):
        raise ValueError("Status HTTP invalid.")
    stamp = now()
    with closing(_open(cale(stare))) as con:
        init(con)
        row = con.execute("SELECT * FROM source_registry WHERE id=?", (source_id,)).fetchone()
        if row is None:
            raise ValueError("Sursa nu există în registru.")
        if not can_transition(row["state"], state):
            raise ValueError("Tranziție de stare invalidă.")
        con.execute(
            """
            INSERT INTO source_attempts
              (source_id,attempted_at,state,http_status,error_category,content_hash,parser_version,note)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (source_id, stamp, state, http_status, error, content_hash, parser_version, note),
        )
        con.execute(
            """
            UPDATE source_registry SET state=?,last_attempt_at=?,last_http_status=?,
              last_error=?,last_hash=COALESCE(NULLIF(?,''),last_hash),
              parser_version=COALESCE(NULLIF(?,''),parser_version),updated_at=?
            WHERE id=?
            """,
            (state, stamp, http_status, error, content_hash, parser_version, stamp, source_id),
        )
        con.commit()
        updated = con.execute("SELECT * FROM source_registry WHERE id=?", (source_id,)).fetchone()
        return _row(updated)


def marcheaza_revizuit(stare, source_id: str, note: str = "") -> dict:
    row = _source(stare, source_id)
    if row["state"] not in {"changed", "needs_review"}:
        raise ValueError("Doar sursele schimbate sau cu revizie necesară pot fi marcate revizuite.")
    return inregistreaza(
        stare,
        {
            "id": row["id"],
            "state": "unchanged",
            "content_hash": row.get("last_hash", ""),
            "parser_version": row.get("parser_version", ""),
            "note": _text(note, limit=500) or "Sursă marcată revizuită manual.",
        },
    )


def _source(stare, source_id: str) -> dict:
    source_id = _token(source_id, required=True)
    with closing(_open(cale(stare))) as con:
        init(con)
        row = con.execute("SELECT * FROM source_registry WHERE id=?", (source_id,)).fetchone()
    if row is None:
        raise ValueError("Sursa nu există în registru.")
    return _row(row)


def _celex_from_source(row: dict) -> str:
    value = row.get("identifier") or row.get("url") or ""
    try:
        return cellar.normalizeaza_celex(value)
    except ValueError:
        pass
    if row.get("url"):
        try:
            return cellar.normalizeaza_celex(row["url"])
        except ValueError:
            pass
    raise ValueError("Sursa UE nu are identificator CELEX valid.") from None


def _eu_hash(stare, celex: str) -> str:
    path = Path(stare.eu)
    if not path.exists():
        return ""
    with cellar.deschide(path, readonly=True) as con:
        row = con.execute("SELECT text_sha256 FROM eu_acte WHERE celex=?", (celex,)).fetchone()
    return row["text_sha256"] if row else ""


def _project_identifier(row: dict) -> str:
    identifier = _text(row.get("identifier", ""), limit=120, required=True)
    return identifier


def _stable_hash(data: object) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _sync_state(previous_hash: str, content_hash: str) -> str:
    return "unchanged" if previous_hash and previous_hash == content_hash else "changed"


def _list_of_text(value, *, limit: int = 20, item_limit: int = 300) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Listă metadata invalidă.")
    out = []
    for item in value[:limit]:
        text = _text(item, limit=item_limit)
        if text:
            out.append(text)
    return out


def _manual_documents(value) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Documente metadata invalide.")
    documents = []
    for item in value[:100]:
        if not isinstance(item, dict):
            raise ValueError("Document metadata invalid.")
        documents.append(
            {
                "url": _url(item.get("url")),
                "label": _text(item.get("label", ""), limit=300),
                "content_hash": _hash(item.get("content_hash", "")),
            }
        )
    return [item for item in documents if item["url"] or item["label"] or item["content_hash"]]


def _manual_metadata_snapshot(row: dict, metadata: dict) -> dict:
    if not isinstance(metadata, dict):
        raise ValueError("Metadata sursă invalidă.")
    family = row["family"]
    title = _text(metadata.get("title") or row.get("label") or row.get("identifier"), limit=300)
    authority = _text(metadata.get("authority", ""), limit=300)
    status = _token(metadata.get("status", ""))
    deadline = _text(metadata.get("deadline", ""), limit=80)
    project_id = _text(
        metadata.get("project_id") or row.get("identifier") or row.get("url"), limit=200
    )
    occurred_at = _text(metadata.get("occurred_at", ""), limit=80)
    documents = _manual_documents(metadata.get("documents"))
    if family in {"consultare_guvern", "consultare_minister"}:
        summary = {
            "title": title,
            "authority": authority,
            "status": status or "unknown",
            "deadline": deadline,
            "documents": len(documents),
            "truncated": bool(
                isinstance(metadata.get("documents"), list) and len(metadata["documents"]) > 100
            ),
        }
    else:
        issuer = _text(metadata.get("issuer") or authority, limit=300)
        position = _text(metadata.get("position", ""), limit=120)
        observations = _text(metadata.get("observations", ""), limit=500)
        document_hash = _hash(metadata.get("document_hash", ""))
        summary = {
            "issuer": issuer,
            "position": position,
            "observations": bool(observations),
            "document_hash": document_hash,
            "documents": len(documents),
            "truncated": bool(
                isinstance(metadata.get("documents"), list) and len(metadata["documents"]) > 100
            ),
        }
    return {
        "contract": "manual-source-metadata-snapshot-v1",
        "family": family,
        "identifier": row.get("identifier", ""),
        "url": row.get("url", ""),
        "label": row.get("label", ""),
        "summary": summary,
        "title": title,
        "authority": authority,
        "issuer": summary.get("issuer", ""),
        "position": summary.get("position", ""),
        "observations": _text(metadata.get("observations", ""), limit=500),
        "status": status or ("received" if family == "avize" else "unknown"),
        "deadline": deadline,
        "project_id": project_id,
        "occurred_at": occurred_at,
        "documents": documents,
        "tags": _list_of_text(metadata.get("tags")),
        "truncated": summary["truncated"],
        "metadata_only": True,
        "limitations": [
            "Sursă sincronizată metadata-first; nu s-a făcut parsing live al paginii oficiale.",
            "Documentele sunt păstrate ca linkuri/hash-uri declarate, nu ca bytes extrase.",
        ],
    }


def _manual_metadata_hash(snapshot: dict) -> str:
    return _stable_hash(
        {
            "contract": snapshot["contract"],
            "family": snapshot["family"],
            "identifier": snapshot["identifier"],
            "url": snapshot["url"],
            "summary": snapshot["summary"],
            "title": snapshot["title"],
            "authority": snapshot["authority"],
            "issuer": snapshot["issuer"],
            "position": snapshot["position"],
            "observations": snapshot["observations"],
            "status": snapshot["status"],
            "deadline": snapshot["deadline"],
            "project_id": snapshot["project_id"],
            "occurred_at": snapshot["occurred_at"],
            "documents": snapshot["documents"],
            "tags": snapshot["tags"],
        }
    )


def _project_local_meta(stare, plx: str) -> dict:
    from scripts import achizitii_proiecte

    try:
        detail = achizitii_proiecte.detaliu(stare, plx)
    except (OSError, ValueError, sqlite3.Error):
        return {}
    return {
        "plx_id": detail.get("plx_id"),
        "titlu": detail.get("titlu"),
        "stadiu": detail.get("stadiu"),
        "cam": detail.get("cam"),
        "idp": detail.get("idp"),
        "fisa_url": detail.get("fisa_url"),
        "lifecycle": (detail.get("lifecycle") or {}).get("key"),
    }


def _project_snapshot(row: dict, plx: str, operation: str, result: dict, local_meta: dict) -> dict:
    documents = [
        {"url": _url(doc.get("url")), "label": _text(doc.get("label", ""), limit=300)}
        for doc in result.get("documente", [])[:100]
        if isinstance(doc, dict)
    ]
    versions = [
        {
            "id": _token(version.get("id", "")),
            "url": _url(version.get("url")),
            "sha256": _hash(version.get("sha256", "")),
            "status": _token(version.get("status", "")),
        }
        for version in result.get("versiuni", [])[:100]
        if isinstance(version, dict)
    ]
    imported = {}
    if result.get("id") or result.get("sha256"):
        imported = {
            "id": _token(result.get("id", "")),
            "url": _url(result.get("url")),
            "sha256": _hash(result.get("sha256", "")),
            "status": _token(result.get("status", "")),
            "label": _text(result.get("label", ""), limit=300),
        }
    return {
        "contract": "parliament-project-source-snapshot-v1",
        "family": row["family"],
        "identifier": row["identifier"],
        "registry_url": row["url"],
        "plx": plx,
        "operation": operation,
        "summary": {
            "plx": plx,
            "operation": operation,
            "fisa_url": result.get("fisa_url") or local_meta.get("fisa_url") or "",
            "documents": len(documents),
            "versions": len(versions),
            "imported_status": imported.get("status", ""),
            "truncated": bool(result.get("trunchiat")),
        },
        "initiative": local_meta,
        "fisa_url": result.get("fisa_url") or local_meta.get("fisa_url") or "",
        "documents": documents,
        "versions": versions,
        "imported": imported,
        "truncated": bool(result.get("trunchiat")),
    }


def _project_content_hash(snapshot: dict) -> str:
    imported = snapshot.get("imported") or {}
    if imported.get("sha256"):
        return imported["sha256"]
    return _stable_hash(
        {
            "contract": snapshot["contract"],
            "family": snapshot["family"],
            "identifier": snapshot["identifier"],
            "registry_url": snapshot["registry_url"],
            "plx": snapshot["plx"],
            "operation": snapshot["operation"],
            "fisa_url": snapshot["fisa_url"],
            "documents": snapshot["documents"],
            "truncated": snapshot["truncated"],
        }
    )


def _store_snapshot(
    stare, source_id: str, content_hash: str, snapshot: dict, parser_version: str
) -> None:
    stamp = now()
    with closing(_open(cale(stare))) as con:
        init(con)
        con.execute(
            """
            INSERT INTO source_snapshots
              (source_id,captured_at,content_hash,parser_version,snapshot_json)
            VALUES (?,?,?,?,?)
            """,
            (
                source_id,
                stamp,
                content_hash,
                parser_version,
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            ),
        )
        con.commit()


def _tracker_date(value: str | None) -> str:
    value = (value or "").strip()
    if not value:
        return now()
    if re.fullmatch(r"\d{1,2}[./-]\d{1,2}[./-]\d{4}", value):
        day, month, year = re.split(r"[./-]", value)
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}T00:00:00+00:00"
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        return value + "T00:00:00+00:00"
    return value


def _tracker_sync_empty() -> dict:
    return {"contract": "source-sync-tracker-events-v1", "stored": 0, "event_types": {}}


def _tracker_sync_summary(events: list[dict]) -> dict:
    summary = _tracker_sync_empty()
    summary["stored"] = len(events)
    for event in events:
        event_type = event.get("event_type") or "unknown"
        summary["event_types"][event_type] = summary["event_types"].get(event_type, 0) + 1
    return summary


def _with_tracker_sync(row: dict, events: list[dict]) -> dict:
    return {**row, "tracker_sync": _tracker_sync_summary(events)}


def _persist_tracker_event(stare, data: dict) -> dict | None:
    from scripts import tracker_events

    try:
        return tracker_events.adauga(stare, data)["event"]
    except (ValueError, OSError, sqlite3.Error):
        return None


def _persist_project_tracker_events(stare, source_id: str, row: dict, plx: str) -> list[dict]:
    from scripts import achizitii_proiecte

    try:
        events = achizitii_proiecte.tracker_events(stare, plx)
    except (ValueError, OSError, sqlite3.Error):
        return []
    stored = []
    for event in events:
        key = event.get("key")
        if key == "opinion_requested":
            continue
        payload = {
            item: value
            for item, value in event.items()
            if item not in {"key", "date", "project_id", "source_family", "source_url"}
            and value not in (None, "")
        }
        saved = _persist_tracker_event(
            stare,
            {
                "event_type": key,
                "project_id": event.get("project_id") or plx,
                "source_family": event.get("source_family") or row["family"],
                "source_id": source_id,
                "source_url": event.get("source_url") or row.get("url", ""),
                "occurred_at": _tracker_date(event.get("date")),
                "title": event.get("raw_action") or event.get("question") or key,
                "payload": payload,
            },
        )
        if saved:
            stored.append(saved)
    return stored


def _persist_econsultare_tracker_event(
    stare, source_id: str, snapshot: dict, content_hash: str
) -> list[dict]:
    from scripts import achizitii_econsultare

    saved = _persist_tracker_event(
        stare,
        achizitii_econsultare.tracker_event_candidate(
            snapshot,
            source_id=source_id,
            content_hash=content_hash,
            observed_at=now(),
        ),
    )
    return [saved] if saved else []


def _persist_manual_metadata_tracker_event(
    stare, source_id: str, snapshot: dict, content_hash: str
) -> list[dict]:
    family = snapshot.get("family")
    observed_at = now()
    if family in {"consultare_guvern", "consultare_minister"}:
        status = (snapshot.get("status") or "unknown").strip().lower()
        event_type = (
            "public_consultation_closed"
            if status in {"closed", "inchisa", "închisă"}
            else "public_consultation_opened"
        )
        deadline = snapshot.get("deadline") or snapshot.get("occurred_at")
        payload = {
            "authority": snapshot.get("authority", ""),
            "project_url": snapshot.get("url", ""),
            "status": status,
        }
        if event_type == "public_consultation_closed":
            payload["closed_at"] = _tracker_date(deadline)
        else:
            if deadline:
                payload["deadline"] = _tracker_date(deadline)
            payload["attachment_hashes"] = [
                item["content_hash"]
                for item in snapshot.get("documents", [])
                if item.get("content_hash")
            ][:100]
            payload["documents"] = snapshot.get("documents", [])[:100]
        saved = _persist_tracker_event(
            stare,
            {
                "event_type": event_type,
                "project_id": snapshot.get("project_id") or snapshot.get("url") or source_id,
                "source_family": family,
                "source_id": source_id,
                "source_url": snapshot.get("url", ""),
                "occurred_at": _tracker_date(deadline),
                "observed_at": observed_at,
                "title": snapshot.get("title") or "Consultare publică",
                "payload": {key: value for key, value in payload.items() if value not in ("", [])},
                "content_hash": content_hash,
            },
        )
        return [saved] if saved else []
    if family == "avize" and snapshot.get("issuer") and snapshot.get("project_id"):
        payload = {
            "issuer": snapshot.get("issuer", ""),
            "position": snapshot.get("position", ""),
            "observations": snapshot.get("observations", ""),
            "document_hash": (snapshot.get("summary") or {}).get("document_hash", ""),
            "source_url": snapshot.get("url", ""),
            "documents": snapshot.get("documents", [])[:100],
        }
        saved = _persist_tracker_event(
            stare,
            {
                "event_type": "opinion_received",
                "project_id": snapshot["project_id"],
                "source_family": family,
                "source_id": source_id,
                "source_url": snapshot.get("url", ""),
                "occurred_at": _tracker_date(snapshot.get("occurred_at")),
                "observed_at": observed_at,
                "title": snapshot.get("title") or f"Aviz primit: {snapshot['issuer']}",
                "payload": {key: value for key, value in payload.items() if value not in ("", [])},
                "content_hash": content_hash,
            },
        )
        return [saved] if saved else []
    return []


def sincronizeaza_proiect(stare, source_id: str) -> dict:
    """Run one bounded sync for a registered parliamentary project source."""
    row = _source(stare, source_id)
    if row["family"] not in PROJECT_FAMILIES:
        raise ValueError("Doar sursele parlamentare pot fi sincronizate aici.")
    if row["state"] != "queued":
        row = pune_in_coada(stare, source_id)
    plx = _project_identifier(row)
    from scripts import achizitii_proiecte

    try:
        if row.get("url"):
            operation = "importa"
            result = achizitii_proiecte.executa(
                stare, {"plx": plx, "operatie": "importa", "url": row["url"]}
            )
            note = f"Document parlamentar importat pentru {plx}."
            needs_review = result.get("status") != "extras"
        else:
            operation = "descopera"
            result = achizitii_proiecte.executa(stare, {"plx": plx, "operatie": "descopera"})
            note = f"Fișa parlamentară {plx} consultată."
            needs_review = not result.get("documente")
    except ValueError as exc:
        return inregistreaza(
            stare,
            {
                "id": source_id,
                "state": "failed",
                "error_category": "fetch_failed",
                "note": str(exc)[:500],
            },
        )
    snapshot = _project_snapshot(row, plx, operation, result, _project_local_meta(stare, plx))
    content_hash = _project_content_hash(snapshot)
    _store_snapshot(stare, source_id, content_hash, snapshot, PROJECT_PARSER_VERSION)
    tracker_sync = _persist_project_tracker_events(stare, source_id, row, plx)
    inregistreaza(
        stare,
        {
            "id": source_id,
            "state": "fetched",
            "http_status": 200,
            "content_hash": content_hash,
            "parser_version": PROJECT_PARSER_VERSION,
            "note": note,
        },
    )
    if needs_review:
        return _with_tracker_sync(
            inregistreaza(
                stare,
                {
                    "id": source_id,
                    "state": "needs_review",
                    "http_status": 200,
                    "content_hash": content_hash,
                    "parser_version": PROJECT_PARSER_VERSION,
                    "note": "Sursa a fost citită, dar rezultatul necesită verificare manuală.",
                },
            ),
            tracker_sync,
        )
    return _with_tracker_sync(
        inregistreaza(
            stare,
            {
                "id": source_id,
                "state": _sync_state(row.get("last_hash", ""), content_hash),
                "http_status": 200,
                "content_hash": content_hash,
                "parser_version": PROJECT_PARSER_VERSION,
            },
        ),
        tracker_sync,
    )


def sincronizeaza_ue(stare, source_id: str) -> dict:
    """Run one bounded CELEX sync for one registry row, using the existing EU importer."""
    row = _source(stare, source_id)
    if row["family"] != "ue_cellar":
        raise ValueError("Doar sursele UE Cellar/EUR-Lex pot fi sincronizate aici.")
    if row["state"] != "queued":
        row = pune_in_coada(stare, source_id)
    celex = _celex_from_source(row)
    from scripts import achizitii_ue

    try:
        result = achizitii_ue.importa(stare, {"celex": celex})
    except ValueError as exc:
        return inregistreaza(
            stare,
            {
                "id": source_id,
                "state": "failed",
                "error_category": "fetch_failed",
                "note": str(exc)[:500],
            },
        )
    if result.get("stare") == "metadate":
        return inregistreaza(
            stare,
            {
                "id": source_id,
                "state": "needs_review",
                "error_category": result.get("language_state") or "text_unavailable",
                "parser_version": "achizitii_ue.v1",
                "note": result.get("language_note")
                or "Metadate UE disponibile, dar fără text RON/ENG compatibil.",
            },
        )
    if result.get("stare") == "indisponibil":
        return inregistreaza(
            stare,
            {
                "id": source_id,
                "state": "unavailable",
                "error_category": result.get("language_state") or "language_unavailable",
                "parser_version": "achizitii_ue.v1",
                "note": result.get("nota") or "Sursa CELEX nu este disponibila in limbile cerute.",
            },
        )
    content_hash = _eu_hash(stare, celex)
    language_note = result.get("language_note") or result.get("nota") or ""
    inregistreaza(
        stare,
        {
            "id": source_id,
            "state": "fetched",
            "http_status": 200,
            "content_hash": content_hash,
            "parser_version": "achizitii_ue.v1",
            "note": (
                f"CELEX {celex} importat în limba {result.get('limba', 'necunoscută')}. "
                f"{language_note}"
            ).strip(),
        },
    )
    return inregistreaza(
        stare,
        {
            "id": source_id,
            "state": "changed" if result.get("schimbat") else "unchanged",
            "http_status": 200,
            "content_hash": content_hash,
            "parser_version": "achizitii_ue.v1",
        },
    )


def _econsultare_url(row: dict) -> str:
    from scripts import achizitii_econsultare

    value = row.get("url") or row.get("identifier") or ""
    return achizitii_econsultare.url_oficial(value)


def sincronizeaza_econsultare(stare, source_id: str) -> dict:
    """Run one bounded sync for one official e-consultare source."""
    row = _source(stare, source_id)
    if row["family"] != "consultare_econsultare":
        raise ValueError("Doar sursele e-consultare pot fi sincronizate aici.")
    if row["state"] != "queued":
        row = pune_in_coada(stare, source_id)
    from scripts import achizitii_econsultare

    try:
        result = achizitii_econsultare.sincronizeaza(_econsultare_url(row))
    except ValueError as exc:
        return inregistreaza(
            stare,
            {
                "id": source_id,
                "state": "failed",
                "error_category": "fetch_failed",
                "note": str(exc)[:500],
            },
        )
    snapshot = result["snapshot"]
    content_hash = result["content_hash"]
    _store_snapshot(
        stare,
        source_id,
        content_hash,
        snapshot,
        achizitii_econsultare.PARSER_VERSION,
    )
    tracker_sync = _persist_econsultare_tracker_event(stare, source_id, snapshot, content_hash)
    title = snapshot["summary"].get("title") or snapshot["url"]
    inregistreaza(
        stare,
        {
            "id": source_id,
            "state": "fetched",
            "http_status": result.get("http_status", 200),
            "content_hash": content_hash,
            "parser_version": achizitii_econsultare.PARSER_VERSION,
            "note": f"Pagina e-consultare citită: {title}.",
        },
    )
    if result.get("needs_review"):
        return _with_tracker_sync(
            inregistreaza(
                stare,
                {
                    "id": source_id,
                    "state": "needs_review",
                    "http_status": result.get("http_status", 200),
                    "content_hash": content_hash,
                    "parser_version": achizitii_econsultare.PARSER_VERSION,
                    "note": "Pagina a fost citită, dar necesită verificare manuală.",
                },
            ),
            tracker_sync,
        )
    return _with_tracker_sync(
        inregistreaza(
            stare,
            {
                "id": source_id,
                "state": _sync_state(row.get("last_hash", ""), content_hash),
                "http_status": result.get("http_status", 200),
                "content_hash": content_hash,
                "parser_version": achizitii_econsultare.PARSER_VERSION,
            },
        ),
        tracker_sync,
    )


def sincronizeaza_manual_metadata(stare, source_id: str, metadata: dict | None = None) -> dict:
    """Retain one metadata-only ministry consultation or avize source snapshot."""
    row = _source(stare, source_id)
    if row["family"] not in MANUAL_METADATA_FAMILIES:
        raise ValueError("Doar sursele metadata-first pot fi sincronizate aici.")
    if row["state"] != "queued":
        row = pune_in_coada(stare, source_id)
    snapshot = _manual_metadata_snapshot(row, metadata or {})
    content_hash = _manual_metadata_hash(snapshot)
    _store_snapshot(stare, source_id, content_hash, snapshot, MANUAL_METADATA_PARSER_VERSION)
    tracker_sync = _persist_manual_metadata_tracker_event(stare, source_id, snapshot, content_hash)
    inregistreaza(
        stare,
        {
            "id": source_id,
            "state": "fetched",
            "content_hash": content_hash,
            "parser_version": MANUAL_METADATA_PARSER_VERSION,
            "note": "Metadata sursă reținută fără parsing live al paginii oficiale.",
        },
    )
    needs_review = not snapshot.get("project_id") or (
        row["family"] == "avize" and not snapshot.get("issuer")
    )
    final_state = (
        "needs_review" if needs_review else _sync_state(row.get("last_hash", ""), content_hash)
    )
    note = ""
    if needs_review:
        note = "Metadata reținută, dar lipsesc câmpuri pentru eveniment tracker complet."
    return _with_tracker_sync(
        inregistreaza(
            stare,
            {
                "id": source_id,
                "state": final_state,
                "content_hash": content_hash,
                "parser_version": MANUAL_METADATA_PARSER_VERSION,
                "note": note,
            },
        ),
        tracker_sync,
    )


def executa(stare, data: dict) -> dict:
    action = _text(data.get("action", "discover"), limit=40) or "discover"
    if action == "discover":
        return _with_impact(stare, descopera(stare, data))
    if action == "queue":
        return _with_impact(stare, pune_in_coada(stare, data.get("id", "")))
    if action == "record":
        return _with_impact(stare, inregistreaza(stare, data))
    if action == "review":
        return _with_impact(
            stare, marcheaza_revizuit(stare, data.get("id", ""), data.get("note", ""))
        )
    if action == "sync":
        row = _source(stare, data.get("id", ""))
        if str(row.get("identifier", "")).startswith(BOOTSTRAP_ANCHOR_PREFIX):
            raise ValueError(
                "Ancora de familie nu se sincronizeaza direct; adauga o sursa punctuala."
            )
        if row["family"] == "consultare_econsultare":
            return _with_impact(stare, sincronizeaza_econsultare(stare, row["id"]))
        if row["family"] == "ue_cellar":
            return _with_impact(stare, sincronizeaza_ue(stare, row["id"]))
        if row["family"] in PROJECT_FAMILIES:
            return _with_impact(stare, sincronizeaza_proiect(stare, row["id"]))
        if row["family"] in MANUAL_METADATA_FAMILIES:
            return _with_impact(
                stare, sincronizeaza_manual_metadata(stare, row["id"], data.get("metadata"))
            )
        raise ValueError("Familia de surse nu are sincronizare directă.")
    if action == "bootstrap":
        return bootstrap(stare)
    if action == "discover_econsultare":
        return descopera_econsultare(stare, data)
    raise ValueError("Acțiune registru necunoscută.")
