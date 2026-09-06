"""The gate between a language model's output and anything a person reads.

The model in this pipeline is small, free, and being asked to reason about legal Romanian —
the configuration in which a language model is most likely to produce a fluent, well-formatted,
correctly-typed finding about an article that does not exist. Downstream of this module a
finding gets shown to a researcher who may repeat it in a committee. So nothing reaches them
that the corpus cannot confirm.

Three rules, each of which has to be passed:

1. **The cited provision must be one that was put in the prompt.** Not one that exists — one
   that was *supplied*. A model that cites `art. 23 din Legea nr. 215/2001` when the context
   held six articles of Legea 98/2016 has invented the citation regardless of whether that
   article happens to exist, and a finding built on a citation the model reached for from
   memory is not a finding about this corpus.
2. **The quote must actually appear in that provision.** Verbatim, after folding case and
   diacritics and collapsing whitespace — nothing looser. Paraphrase is where a contradiction
   quietly becomes a contradiction between what the law says and what the model remembers the
   law saying.
3. **The quote must be substantial enough to check.** Three words matched against a long article
   proves nothing; the threshold exists so that passing rule 2 means something.

**Rejections are output, not errors.** The rejected list is the only honest measurement of how
much this model can be trusted on this corpus, and it is what tells a team whether to put the
contradiction pass in front of anyone at all. A validator that silently swallowed them would
make a bad model look like a quiet one.

**This does not make a surviving finding true.** It makes it *checkable*: a real provision, a
real quotation, and a link. Whether the contradiction is genuine remains a lawyer's judgement,
and the report says so.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from scripts.text import cheie, normalizeaza

MOTIVE: dict[str, str] = {
    "citat-lipsa": "Constatarea nu citează niciun text din lege.",
    "provizie-inexistenta": "Articolul citat nu se afla în contextul trimis modelului.",
    "citat-neregasit": "Citatul nu apare în textul articolului citat.",
    "citat-prea-scurt": "Citatul este prea scurt pentru a putea fi verificat.",
    "camp-lipsa": "Constatarea nu are forma cerută.",
    "duplicat": "Aceeași constatare, deja păstrată o dată.",
    "raspuns-neparsabil": "Răspunsul modelului nu a putut fi citit ca JSON.",
}


@dataclass(frozen=True)
class Constatare:
    """One finding as the model returned it, before anyone believes it."""

    tip: str
    provizie: str
    citat: str
    motiv: str
    fragment_proiect: str = ""
    incredere: float | None = None
    brut: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.tip}|{self.provizie}|{cheie(self.citat)[:120]}"


@dataclass(frozen=True)
class Respinsa:
    constatare: Constatare
    motiv_respingerii: str

    @property
    def explicatie(self) -> str:
        return MOTIVE.get(self.motiv_respingerii, self.motiv_respingerii)


@dataclass(frozen=True)
class Rezultat:
    acceptate: tuple[Constatare, ...]
    respinse: tuple[Respinsa, ...]

    @property
    def rata_de_respingere(self) -> float:
        total = len(self.acceptate) + len(self.respinse)
        return len(self.respinse) / total if total else 0.0

    def raport(self) -> str:
        linii = [
            f"{len(self.acceptate)} constatări verificabile, "
            f"{len(self.respinse)} respinse ({self.rata_de_respingere:.0%})."
        ]
        for r in self.respinse:
            linii.append(f"  ✗ [{r.constatare.provizie or '?'}] {r.explicatie}")
        return "\n".join(linii)


_DESCHIS = "<think>"
_INCHIS = "</think>"


def _fara_ganduri(brut: str) -> str:
    """Strip `<think>…</think>` blocks, scanning rather than matching.

    Written with `str.find` on purpose. The obvious version — `re.sub(r"<think>.*?</think>", …)` —
    backtracks quadratically on input with many unclosed `<think>` markers: for every opening tag
    the engine rescans forward looking for a close that is not there. CodeQL flagged it as
    `py/polynomial-redos` and was right to. On the browser path this string arrives straight from a
    client POST, so a reply of a few hundred kilobytes of `<think>` would hold the localhost server
    in one regex.

    The scan is linear: the cursor only ever moves forward. An unclosed block swallows the rest of
    the reply, which is correct — a model that ran out of tokens mid-thought never reached its JSON.
    """
    jos = brut.lower()
    bucati: list[str] = []
    i = 0
    while True:
        d = jos.find(_DESCHIS, i)
        if d < 0:
            bucati.append(brut[i:])
            break
        bucati.append(brut[i:d])
        inchis = jos.find(_INCHIS, d + len(_DESCHIS))
        if inchis < 0:
            break  # unclosed: everything after it is thought, and none of it is an answer
        i = inchis + len(_INCHIS)
    return " ".join(b for b in bucati if b.strip())


def _json_din(brut: str) -> Any | None:
    """The JSON a small model buried in whatever else it wanted to say.

    Three habits have to be tolerated, and the third is the one that mattered. Fenced blocks
    (```json …```) were always handled. Prose before the list is common. And **reasoning models
    emit a `<think>…</think>` block first** — Qwen3 and the DeepSeek-R1 distills do it by default,
    so every answer from them parsed as nothing at all.

    Returns `None` when there is no JSON to find, which the caller must report rather than treat as
    an empty answer: a model whose output could not be read has not told you there are no findings.
    """
    text = _fara_ganduri(brut).strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        text = text.removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Last resort: the outermost array or object anywhere in the reply.
    for deschis, inchis in (("[", "]"), ("{", "}")):
        i, j = text.find(deschis), text.rfind(inchis)
        if 0 <= i < j:
            try:
                return json.loads(text[i : j + 1])
            except json.JSONDecodeError:
                continue
    return None


def citeste(brut: str | list[dict[str, Any]]) -> tuple[list[Constatare], list[Respinsa]]:
    """Model output into findings, tolerating what small models actually emit."""
    if isinstance(brut, str):
        incarcat = _json_din(brut)
        if incarcat is None:
            # Not "no findings" — "no answer". Reported, because an unreadable reply and a clean
            # bill of health are the same empty list otherwise, and they mean opposite things.
            gol = Constatare(tip="", provizie="", citat="", motiv="")
            return [], [Respinsa(gol, "raspuns-neparsabil")]
    else:
        incarcat = brut
    if isinstance(incarcat, dict):
        incarcat = next((v for v in incarcat.values() if isinstance(v, list)), [])

    constatari: list[Constatare] = []
    respinse: list[Respinsa] = []
    for element in incarcat:
        if not isinstance(element, dict):
            continue
        c = Constatare(
            tip=str(element.get("tip") or element.get("type") or "contradictie"),
            provizie=str(element.get("provizie") or element.get("articol") or ""),
            citat=str(element.get("citat") or element.get("quote") or ""),
            motiv=str(element.get("motiv") or element.get("reason") or ""),
            fragment_proiect=str(element.get("fragment_proiect") or ""),
            incredere=(
                element.get("incredere")
                if isinstance(element.get("incredere"), int | float)
                else None
            ),
            brut=element,
        )
        if not c.provizie or not c.motiv:
            respinse.append(Respinsa(c, "camp-lipsa"))
        else:
            constatari.append(c)
    return constatari, respinse


def valideaza(
    constatari: list[Constatare],
    context: dict[str, str],
    cuvinte_minime: int = 5,
) -> Rezultat:
    """Keep only findings the supplied context can confirm.

    `context` maps provision id to the exact text handed to the model. It is the authority: a
    provision missing from it is treated as invented even if it exists in the corpus, because a
    model that produced it did not read it here.
    """
    acceptate: list[Constatare] = []
    respinse: list[Respinsa] = []
    vazute: set[str] = set()
    indexat = {cheie(k): (k, cheie(normalizeaza(v))) for k, v in context.items()}

    for c in constatari:
        potrivire = indexat.get(cheie(c.provizie))
        if potrivire is None:
            respinse.append(Respinsa(c, "provizie-inexistenta"))
            continue
        if not c.citat.strip():
            respinse.append(Respinsa(c, "citat-lipsa"))
            continue
        citat = cheie(c.citat)
        if len(citat.split()) < cuvinte_minime:
            respinse.append(Respinsa(c, "citat-prea-scurt"))
            continue
        if citat not in potrivire[1]:
            respinse.append(Respinsa(c, "citat-neregasit"))
            continue
        if c.id in vazute:
            respinse.append(Respinsa(c, "duplicat"))
            continue
        vazute.add(c.id)
        acceptate.append(c)
    return Rezultat(tuple(acceptate), tuple(respinse))
