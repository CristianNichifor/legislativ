"""Bounded textual comparison of immutable imported versions, without legal equivalence claims."""

import difflib
import re

from scripts.amendamente import amendamente
from scripts.contradictii_termene import _DURATA
from scripts.parsare_text import _HDR
from scripts.suprapuneri_autoritati import atributie_comparabila

MAX_TEXT = 60_000


def _unitati(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    heads = list(_HDR.finditer(text))
    if not heads or len({m[1] for m in heads}) != len(heads):
        return {"document": text}, True
    out = {}
    if text[: heads[0].start()].strip():
        out["preambul"] = text[: heads[0].start()].strip()
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out["art" + m[1]] = text[m.end() : end].strip()
    return out, False


def _spatii(text):
    return " ".join(text.split())


def _fragmente(a, b):
    x, y = re.findall(r"\s+|\S+", a), re.findall(r"\s+|\S+", b)
    if max(len(x), len(y)) > 2000:
        return [], True
    return [
        {"fel": tag, "a": "".join(x[i:j]), "b": "".join(y[k:end])}
        for tag, i, j, k, end in difflib.SequenceMatcher(None, x, y).get_opcodes()
    ], False


def _semnale(text, blocks):
    targets = sorted(
        {f"{a.act_tinta.id} / {a.locator.id} / {a.fel}" for a in amendamente(text) if a.act_tinta}
    )
    authorities = sorted(
        {a["autoritate"] for t in blocks.values() if (a := atributie_comparabila(t))}
    )
    return {
        "Ținte de amendare": targets,
        "Termene explicite": sorted({m.group(0) for m in _DURATA.finditer(text)}),
        "Autorități recunoscute": authorities,
    }


def compara(a, b):
    if a["plx_id"] != b["plx_id"]:
        raise ValueError("Versiunile trebuie să aparțină aceleiași inițiative.")
    if a["status"] != "extras" or b["status"] != "extras":
        raise ValueError("Versiunile necesită OCR sau verificare manuală înainte de comparare.")
    if max(len(a["text"]), len(b["text"])) > MAX_TEXT:
        raise ValueError("Comparația acceptă maximum 60000 caractere pe versiune, fără trunchiere.")
    left, la = _unitati(a["text"])
    right, lb = _unitati(b["text"])
    warnings = ["Comparație textuală; verifică numerotarea și erorile de extragere PDF."]
    warnings.append("Ordinea este aleasă de utilizator; data importului nu este data adoptării.")
    if a["url"] != b["url"]:
        warnings.append("Surse diferite: verifică dacă documentele sunt versiuni comparabile.")
    if la or lb:
        left, right = {"document": a["text"]}, {"document": b["text"]}
        warnings.append("Titluri de articol lipsă sau duplicate: aliniere structurală incertă.")
    bodies = {}
    for loc, text in left.items():
        bodies.setdefault(_spatii(text), set()).add(loc)
    if any(
        _spatii(t) and any(old != loc for old in bodies.get(_spatii(t), set()))
        for loc, t in right.items()
    ):
        warnings.append("Renumerotare posibilă: texte identice apar la numere diferite.")
    changes = []
    counts = {"adaugat": 0, "eliminat": 0, "modificat": 0}
    for loc in dict.fromkeys([*left, *right]):
        old, new = left.get(loc, ""), right.get(loc, "")
        if loc in left and loc in right and _spatii(old) == _spatii(new):
            continue
        kind = "adaugat" if loc not in left else "eliminat" if loc not in right else "modificat"
        counts[kind] += 1
        if len(changes) < 100:
            fragments, limited = _fragmente(old, new)
            changes.append(
                {
                    "locator": loc,
                    "fel": kind,
                    "a": old,
                    "b": new,
                    "fragmente": fragments,
                    "detaliu_limitat": limited,
                }
            )
    sa, sb = _semnale(a["text"], left), _semnale(b["text"], right)
    out = {
        "a": {k: v for k, v in a.items() if k != "text"},
        "b": {k: v for k, v in b.items() if k != "text"},
        "schimbari": changes,
        "rezumat": counts,
        "trunchiat": sum(counts.values()) > len(changes),
        "limitari": warnings,
        "semnale": [{"tip": k, "a": sa[k], "b": sb[k]} for k in sa if sa[k] != sb[k]],
    }
    lines = [f"# Comparație versiuni: {a['plx_id']}"]
    for label, doc in (("Înainte", a), ("După", b)):
        lines.append(f"{label}: {doc['url']} | {doc['preluat_la']} | SHA-256: {doc['sha256']}")
    for s in out["semnale"]:
        lines += [f"## {s['tip']}", "Înainte: " + "; ".join(s["a"]), "După: " + "; ".join(s["b"])]
    for c in changes:
        lines += [f"## {c['locator']} ({c['fel']})", "Înainte:", c["a"], "După:", c["b"]]
    if out["trunchiat"]:
        lines.append("Raport parțial: maximum 100 de unități schimbate.")
    out["markdown"] = "\n\n".join(lines + warnings)
    return out
