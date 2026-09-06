"""Tests for the one pass that needs a model.

Everything here is about containment. The three deterministic layers say what happened; this one
argues about substance, which is where a model working in legal Romanian produces fluent,
correctly-typed findings about reasoning it never read.

Four properties carry it, and each is a way of not being believed.

**The model never searches.** Its context is assembled from findings the deterministic layers
already produced, so it reasons over a fixed dictionary. A finding citing anything outside it is
dropped by `validare.valideaza` — `test_a_model_that_cites_a_decision_it_was_not_given_is_rejected`.

**A pass that did not run says so.** An empty findings list and a model that was never configured
are the same screen; `a_rulat` is the difference, and the difference is the whole meaning of the
result.

**A model that fails is not a clean answer.** An exception means the pass did not run, not that
nothing was found.

**The rejection rate is reported.** It is the only honest measurement of whether a given model can
be trusted on this corpus, and hiding it would make a bad model look like a quiet one.

No network: the model is a callable, so a test passes a function.
"""

from __future__ import annotations

import json

from scripts.opinie import MAX_DECIZII, context_din_gasiri, opinie, raport

CONSIDERENTE = (
    "Curtea constată că textul de lege criticat instituie un tratament juridic diferit pentru "
    "persoane aflate în situații identice, fără o justificare obiectivă și rațională. "
    "Or, potrivit jurisprudenței constante, încalcă principiul egalității, consacrat în art. 16 "
    "din Constituție, orice reglementare care creează o asemenea distincție. "
    "În consecință, dispozițiile sunt neconstituționale."
)


def gasire(**kw) -> dict:
    return {
        "decizie": "decizie-114-1994",
        "act_id": "lege-88-1993",
        "locator": "art32",
        "considerente": CONSIDERENTE,
        "temeiuri": [
            {
                "fel": "incalcat",
                "eticheta": "art. 16 — egalitatea în drepturi",
                "citat": "încalcă principiul egalității, consacrat în art. 16 din Constituție",
            }
        ],
    } | kw


def model_bun(_: str) -> str:
    """A model that quotes what it was given, verbatim."""
    return json.dumps(
        [
            {
                "tip": "acelasi-viciu",
                "provizie": "decizie-114-1994",
                "citat": "instituie un tratament juridic diferit pentru persoane aflate în "
                "situații identice",
                "motiv": "Fragmentul creează aceeași distincție între categorii comparabile.",
                "fragment_proiect": "Art. 1 alin. (2)",
            }
        ],
        ensure_ascii=False,
    )


def model_care_inventeaza(_: str) -> str:
    """The realistic failure: fluent, correctly-typed, and about a decision never supplied."""
    return json.dumps(
        [
            {
                "tip": "acelasi-viciu",
                "provizie": "decizie-999-2021",
                "citat": "Curtea a statuat că orice restrângere trebuie să fie proporțională",
                "motiv": "Sună convingător și nu a fost trimis modelului.",
                "fragment_proiect": "Art. 1",
            }
        ],
        ensure_ascii=False,
    )


def model_care_citeaza_gresit(_: str) -> str:
    """Right decision, invented quote — the harder case, since the citation checks out."""
    return json.dumps(
        [
            {
                "tip": "acelasi-viciu",
                "provizie": "decizie-114-1994",
                "citat": "Curtea a reținut că textul afectează securitatea juridică a raporturilor",
                "motiv": "Citatul nu apare în considerentele trimise.",
                "fragment_proiect": "Art. 1",
            }
        ],
        ensure_ascii=False,
    )


DRAFT = "Articolul 1\n(2) Se instituie un regim diferit pentru persoane aflate în aceeași situație."


def test_a_finding_that_quotes_the_supplied_reasoning_is_kept():
    o = opinie(DRAFT, [gasire()], model=model_bun)
    assert o.a_rulat is True
    assert len(o.acceptate) == 1
    assert o.acceptate[0].provizie == "decizie-114-1994"
    assert o.respinse == ()
    assert o.severitate == "material", "a model's argument blocked a bill"
    assert o.increderea == "assumed"


def test_a_model_that_cites_a_decision_it_was_not_given_is_rejected():
    """The containment that makes this pass safe: the context is the authority, not the corpus.
    A decision that exists but was not supplied is still invented, because the model did not read
    it here."""
    o = opinie(DRAFT, [gasire()], model=model_care_inventeaza)
    assert o.a_rulat is True
    assert o.acceptate == ()
    assert len(o.respinse) == 1
    assert o.rata_de_respingere == 1.0


def test_a_correct_citation_with_an_invented_quote_is_rejected():
    """The harder failure: the decision checks out, so only the quote can catch it."""
    o = opinie(DRAFT, [gasire()], model=model_care_citeaza_gresit)
    assert o.acceptate == ()
    assert "citat" in o.respinse[0].motiv_respingerii


def test_no_model_configured_is_reported_not_silently_empty():
    """An empty list and a pass that never ran are the same screen otherwise."""
    o = opinie(DRAFT, [gasire()], model=None)
    assert o.a_rulat is False
    assert "niciun model" in o.motiv
    assert o.acceptate == ()
    assert "Nu a rulat" in raport(o)


def test_a_model_that_raises_did_not_run_rather_than_found_nothing():
    def cade(_: str) -> str:
        raise TimeoutError("nu răspunde")

    o = opinie(DRAFT, [gasire()], model=cade)
    assert o.a_rulat is False
    assert "TimeoutError" in o.motiv
    assert o.acceptate == ()


def test_nothing_is_sent_when_there_is_no_reasoning_to_send():
    """Without considerente there is no context, so there is nothing to reason over — and the
    prompt is never built, which is also the cheapest way to not waste a model call."""
    apeluri = []

    def numara(p: str) -> str:
        apeluri.append(p)
        return "[]"

    o = opinie(DRAFT, [gasire(considerente="")], model=numara)
    assert o.a_rulat is False
    assert apeluri == [], "sent a prompt with no reasoning in it"
    assert "considerent" in o.motiv


def test_the_context_is_capped_so_a_prompt_stays_holdable():
    """A draft touching a dozen struck provisions would otherwise assemble a prompt no local model
    can hold, and the deterministic layers have already ranked them."""
    multe = [gasire(decizie=f"decizie-{i}-2000") for i in range(MAX_DECIZII + 6)]
    assert len(context_din_gasiri(multe)) == MAX_DECIZII


def test_one_entry_per_decision_however_many_findings_point_at_it():
    """Two provisions struck by one decision is one piece of reasoning, not two copies of it."""
    doua = [gasire(locator="art32"), gasire(locator="art33")]
    assert list(context_din_gasiri(doua)) == ["decizie-114-1994"]


def test_the_excerpt_is_cut_around_the_courts_statement_of_violation():
    """The grounds sit in the middle, after the recital of procedure — so the opening of a decision
    is reliably the least useful part of it."""
    preambul = "Pe rol se află soluționarea excepției. " * 60
    ctx = context_din_gasiri([gasire(considerente=preambul + CONSIDERENTE)])
    assert "încalcă principiul egalității" in ctx["decizie-114-1994"]


def test_an_excerpt_with_no_locatable_anchor_still_travels():
    """A decision whose ground this cannot anchor on is not dropped — it is sent from the top,
    which is worse and not nothing."""
    ctx = context_din_gasiri([gasire(temeiuri=[])])
    assert ctx and CONSIDERENTE[:40] in ctx["decizie-114-1994"]


def test_the_rejection_rate_travels_with_the_findings():
    """The only honest measurement of whether a model can be trusted on this corpus."""
    o = opinie(DRAFT, [gasire()], model=model_care_inventeaza)
    assert "respinse" in raport(o)
    assert "100%" in raport(o)


def test_an_empty_draft_does_not_reach_the_model():
    apeluri = []
    opinie("   ", [gasire()], model=lambda p: apeluri.append(p) or "[]")
    assert apeluri == []


def test_no_local_model_configured_yields_no_callable(monkeypatch):
    """`model_local` returns None rather than raising, because an absent model has to reach
    `opinie` as "did not run" — an exception is something a caller might mistake for an answer."""
    from scripts.opinie import model_local

    monkeypatch.delenv("LEGISLATIV_MODEL", raising=False)
    assert model_local() is None
    assert opinie(DRAFT, [gasire()], model=model_local()).a_rulat is False


def test_a_configured_model_is_called_on_this_machine(monkeypatch):
    """The endpoint is localhost-shaped on purpose: this is the server-side half of the promise
    the page's CSP makes, that an unpublished bill does not leave the device."""
    from scripts.opinie import model_local

    monkeypatch.setenv("LEGISLATIV_MODEL", "llama3.1")
    monkeypatch.delenv("LEGISLATIV_MODEL_URL", raising=False)
    assert callable(model_local())
