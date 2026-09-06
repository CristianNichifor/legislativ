"""The Court's reasoning, read against a draft — the one pass that needs a model.

The three deterministic layers say what happened: `coliziune.py` that the draft touches a struck
provision, `reluare.py` that it repeats struck wording, `temeiuri.py` on what ground the Court
struck. None of them can say the thing a drafter actually wants to know — *does my text have the
same defect* — because that is an argument about substance, and substance is where a rule can be
worded quite differently and fail for exactly the same reason.

So this pass exists, and everything about it is built to contain it.

**The model never searches.** Its context is assembled entirely from findings the deterministic
layers already produced: the struck norm, the ground, and an excerpt of the reasoning around the
Court's own statement of violation. It cannot reach for a provision it was not given, because it
is given a fixed dictionary and `validare.valideaza` drops any finding citing something outside it.
A model asked to *retrieve and reason* will do the first badly; asked only to reason over supplied
text, its failure mode collapses to one the validator can catch.

**Nothing leaves the device.** The draft is an unpublished bill, and the page's Content-Security-
Policy is written so it cannot be sent anywhere. The existing cloud path handles *public* law text
only. This pass therefore runs on-device or not at all — a local model over a localhost endpoint,
or WebLLM in the tab. That is a real limitation and it is the right one: an MP pasting a draft
should not have to trust a promise about a server, when the alternative is a guarantee about a
socket that is never opened.

**A pass that did not run says so.** An empty findings list and a model that was never configured
are the same screen, and the difference is the whole meaning of the result. `Opinie.a_rulat`
carries it, and `motiv` says which.

**Every finding is experimental, and none of them blocks.** A model working in legal Romanian will
produce fluent, correctly-typed findings about reasoning it did not read. The validator drops the
ones that quote nothing supplied; it cannot drop the ones that quote correctly and reason badly.
So the rejection rate is reported next to the findings — it is the only honest measurement of
whether a given model can be trusted on this corpus, and hiding it would make a bad model look
like a quiet one.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

from scripts.validare import Constatare, Rezultat, citeste, valideaza

# How much reasoning travels per decision. The considerente run to 12 000 characters at the median
# and 898 000 at the worst; sending them whole would be most of a context window for one decision
# and would bury the passage that matters. The excerpt is cut around the Court's own statement of
# violation, which `temeiuri.py` already located.
FEREASTRA: Final[int] = 1600

# How many decisions one request may carry. A draft touching a dozen struck provisions would
# otherwise assemble a prompt no local model can hold, and the deterministic layers have already
# ranked them.
MAX_DECIZII: Final[int] = 4

PROMPT: Final[str] = """Ești asistentul unui jurist care pregătește un proiect de act normativ.

Ai mai jos, în CONTEXT, considerentele unor decizii ale Curții Constituționale — motivarea pentru
care Curtea a declarat neconstituționale anumite prevederi — și fragmentul din proiect care se
apropie de ele.

Întrebarea: are fragmentul din proiect ACELAȘI viciu pentru care Curtea a lovit prevederea?

REGULI, în ordinea importanței:
1. Poți cita EXCLUSIV din secțiunea CONTEXT. Nu invoca nicio decizie și niciun articol care nu
   apare acolo, nici dacă îl cunoști.
2. Fiecare constatare conține un citat LITERAL, copiat cuvânt cu cuvânt din considerentele citate.
   Nu reformula. O constatare fără citat literal va fi aruncată.
3. Dacă motivarea Curții nu se aplică fragmentului, nu inventa o legătură. Lista goală este un
   răspuns corect și preferabil unei presupuneri.

Răspunde exclusiv cu JSON, o listă de obiecte cu cheile:
  tip       - "acelasi-viciu"
  provizie  - identificatorul deciziei, exact cum apare în CONTEXT
  citat     - citatul literal din considerentele acelei decizii
  motiv     - de ce viciul se aplică (sau nu) fragmentului din proiect
  fragment_proiect - fragmentul din proiect la care se referă

CONTEXT:
{context}

FRAGMENT DIN PROIECT:
{proiect}
"""


@dataclass(frozen=True)
class Opinie:
    """What the model pass produced, or why it produced nothing."""

    a_rulat: bool
    motiv: str  # why it did not run, when it did not
    acceptate: tuple[Constatare, ...] = ()
    respinse: tuple = ()
    context: dict[str, str] = field(default_factory=dict)

    @property
    def rata_de_respingere(self) -> float:
        total = len(self.acceptate) + len(self.respinse)
        return len(self.respinse) / total if total else 0.0

    @property
    def severitate(self) -> str:
        """Never blocking, whatever the model says. This is an argument about substance produced
        by a machine that cannot be held to it."""
        return "material"

    @property
    def increderea(self) -> str:
        return "assumed"


def _fereastra(considerente: str, ancora: str) -> str:
    """The passage around the Court's statement of violation, or the opening if it cannot be found.

    Anchored rather than truncated: the grounds live in the middle of the reasoning, after the
    recital of procedure and the parties' submissions, so the first 1 600 characters of a decision
    are reliably the least useful 1 600 characters in it.
    """
    if not considerente:
        return ""
    text = re.sub(r"\s+", " ", considerente).strip()
    pozitie = -1
    if ancora:
        cheie = re.sub(r"\s+", " ", ancora).strip()[:60]
        pozitie = text.find(cheie)
    if pozitie < 0:
        return text[:FEREASTRA]
    start = max(0, pozitie - FEREASTRA // 3)
    return text[start : start + FEREASTRA]


def context_din_gasiri(gasiri: list[dict], maxim: int = MAX_DECIZII) -> dict[str, str]:
    """The reasoning handed to the model, which is also what the validator will hold it to.

    Built from what the deterministic layers found — never from a search. Keyed by decision, so a
    provision struck by several decisions contributes several entries and a model citing anything
    else is citing something it was not given.
    """
    context: dict[str, str] = {}
    for g in gasiri:
        decizie = g.get("decizie") or ""
        if not decizie or decizie in context:
            continue
        considerente = g.get("considerente") or ""
        temeiuri = g.get("temeiuri") or []
        incalcate = [t for t in temeiuri if t.get("fel") == "incalcat"]
        ancora = (incalcate[0] if incalcate else (temeiuri[0] if temeiuri else {})).get("citat", "")
        fereastra = _fereastra(considerente, ancora)
        if not fereastra:
            continue
        context[decizie] = fereastra
        if len(context) >= maxim:
            break
    return context


def cerere(fragment: str, gasiri: list[dict]) -> tuple[str, dict[str, str]]:
    """The prompt and the context it was built from, without calling anything.

    Split out because the two surfaces run the model in different languages: on localhost it is a
    Python callable over a localhost endpoint, in the browser it is WebLLM in JavaScript. The
    browser therefore asks for the prompt, runs it, and posts the raw reply back to be validated —
    and the context is **recomputed** on the way back rather than round-tripped. A client that
    could supply the context could supply one containing its own hallucination, and the context is
    exactly what the validator holds the model to.
    """
    context = context_din_gasiri(gasiri)
    if not context:
        return "", {}
    return (
        PROMPT.format(
            context="\n\n".join(f"[{k}] {v}" for k, v in context.items()),
            proiect=fragment.strip(),
        ),
        context,
    )


def opinie(
    fragment: str,
    gasiri: list[dict],
    model: Callable[[str], str] | None = None,
    brut: str | None = None,
) -> Opinie:
    """Ask a model whether the draft has the defect the Court found, and believe little of it.

    `model` is any callable taking a prompt and returning its output — Ollama over localhost,
    WebLLM in the tab, or a recorded fixture in a test. Left a plain callable for the same reason
    `linter.analizeaza` does: the three are the same shape and a framework between them would be
    one more thing to debug.
    """
    if model is None and brut is None:
        return Opinie(False, "niciun model configurat — pasul nu a rulat")
    if not fragment.strip():
        return Opinie(False, "fragment gol")

    prompt, context = cerere(fragment, gasiri)
    if not context:
        return Opinie(
            False,
            "niciun considerent disponibil pentru deciziile găsite — nu s-a trimis nimic modelului",
        )

    if brut is None:
        try:
            brut = model(prompt)
        except Exception as e:  # a model that fails is a pass that did not run, not a clean answer
            return Opinie(False, f"modelul nu a răspuns: {type(e).__name__}", context=context)

    constatari, respinse_forma = citeste(brut)
    rezultat: Rezultat = valideaza(constatari, context)
    return Opinie(
        a_rulat=True,
        motiv="",
        acceptate=rezultat.acceptate,
        respinse=(*respinse_forma, *rezultat.respinse),
        context=context,
    )


def model_local(
    baza: str | None = None, nume: str | None = None, termen: float = 120.0
) -> Callable[[str], str] | None:
    """A model on this machine, over an OpenAI-compatible endpoint. `None` when none is configured.

    Deliberately localhost-shaped and deliberately not a cloud client. The draft is an unpublished
    bill; the page's CSP is written so it cannot leave the tab, and this is the server-side half of
    the same promise. Ollama and llama.cpp both speak this shape, so `LEGISLATIV_MODEL=llama3.1`
    with Ollama running is the whole of the setup.

    Returning `None` rather than raising is the point: an absent model must reach `opinie` as "did
    not run", not as an error a caller might mistake for a clean answer.
    """
    import json as _json
    import os
    import urllib.request

    nume = nume or os.environ.get("LEGISLATIV_MODEL", "")
    if not nume:
        return None
    baza = baza or os.environ.get("LEGISLATIV_MODEL_URL", "http://127.0.0.1:11434/v1")

    def cheama(prompt: str) -> str:
        cerere = urllib.request.Request(
            baza.rstrip("/") + "/chat/completions",
            data=_json.dumps(
                {
                    "model": nume,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(cerere, timeout=termen) as raspuns:
            corp = _json.loads(raspuns.read().decode("utf-8", "replace"))
        return corp["choices"][0]["message"]["content"]

    return cheama


def raport(o: Opinie) -> str:
    if not o.a_rulat:
        return f"Nu a rulat: {o.motiv}."
    linii = [
        f"{len(o.acceptate)} constatări verificabile, {len(o.respinse)} respinse "
        f"({o.rata_de_respingere:.0%}) — experimental, nu blochează."
    ]
    for c in o.acceptate:
        linii.append(f"  [{c.provizie}] {c.motiv}")
        linii.append(f'      „{c.citat[:160]}"')
    for r in o.respinse:
        linii.append(f"  ✗ [{getattr(r.constatare, 'provizie', '?') or '?'}] {r.explicatie}")
    return "\n".join(linii)
