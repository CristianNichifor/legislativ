"""Read-only comparisons of contextual EU snapshots, separate from legal findings."""

import hashlib

from scripts import instantanee_ue


def _valid(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("stare") != "capturat":
        return False
    if snapshot.get("schema_version") != 1:
        return False
    if snapshot.get("algoritm") != "sha256-json-text-ue-v1":
        return False
    source = snapshot.get("sursa")
    if not isinstance(source, dict) or set(source) != set(instantanee_ue.FIELDS):
        return False
    text = source.get("text")
    if (
        not isinstance(text, str)
        or not text.strip()
        or source.get("celex") != snapshot.get("celex")
    ):
        return False
    payload = {k: snapshot[k] for k in ("schema_version", "algoritm", "sursa")}
    snapshot_hash = hashlib.sha256(instantanee_ue._json(payload).encode()).hexdigest()
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    return snapshot_hash == snapshot.get("id") and text_hash == source.get("text_sha256")


def _metadata(snapshot):
    if snapshot is None:
        return None
    source = snapshot.get("sursa")
    return {
        **{k: v for k, v in snapshot.items() if k != "sursa"},
        "sursa": {k: v for k, v in source.items() if k != "text"}
        if isinstance(source, dict)
        else {},
    }


def verifica(stare, evidence):
    baseline = evidence.get("surse_ue") or {}
    supported = baseline.get("schema_version") == 1
    references = evidence.get("referinte_ue") or []
    current = instantanee_ue.captureaza(stare, references) if supported else {}
    now = {s.get("celex"): s for s in current.get("instantanee", [])}
    previous = baseline.get("instantanee", []) if supported else []
    results = []
    for old in previous:
        new = now.get(old.get("celex"))
        status, language, text, metadata = "indisponibil", None, None, None
        if _valid(old) and _valid(new):
            a, b = old["sursa"], new["sursa"]
            language = a["limba"] != b["limba"]
            text = None if language else a["text_sha256"] != b["text_sha256"]
            metadata = any(a[k] != b[k] for k in a if k not in ("text", "text_sha256", "limba"))
            status = "schimbat" if language or text else "neschimbat"
        results.append(
            {
                "celex": old.get("celex"),
                "stare": status,
                "limba_schimbata": language,
                "text_schimbat": text,
                "metadate_schimbate": metadata,
                "salvat": _metadata(old),
                "curent": _metadata(new),
            }
        )
    return {
        "schema_version": 1,
        "manifest_disponibil": supported,
        "comparatie_incompleta": not supported
        or bool(baseline.get("trunchiat"))
        or bool(current.get("trunchiat"))
        or {r.get("celex") for r in references} != {r.get("celex") for r in previous}
        or any(r["stare"] == "indisponibil" for r in results),
        "surse": results,
        "totaluri": {
            s: sum(r["stare"] == s for r in results)
            for s in ("schimbat", "neschimbat", "indisponibil")
        },
        "limitari": [
            "Comparatie contextuala cu eu.db local; fara descarcare sau verdict juridic.",
            "Limba diferita: text necomparat, fara concluzii despre sensul juridic.",
            "Metadatele, inclusiv data colectarii, sunt semnalate separat de text.",
            "Rezultatele UE nu modifica numaratorile constatarilor sau coada lor de reevaluare.",
            "Verificarea pastreaza amprente si metadate, nu o noua copie a textului curent.",
        ],
    }
