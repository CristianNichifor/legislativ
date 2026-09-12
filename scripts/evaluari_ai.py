"""Deterministic evaluation harness for saved AI drafting outputs.

The harness never calls a model. It scores already-saved outputs against bounded
source snippets, so local, BYOK and future MCP providers can be compared with the
same contract and without paid API calls in tests.
"""

import argparse
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1
ENGINE_VERSION = "ai-eval-deterministic-v1"
MAX_CASES = 200
MAX_OUTPUT_CHARS = 20_000
MAX_SOURCE_CHARS = 80_000

CRITERIA = (
    "source_faithfulness",
    "citation_correctness",
    "hallucinated_legal_claims",
    "useful_structure",
    "romanian_drafting_quality",
    "uncertainty",
)

LEGAL_CLAIM_WORDS = {
    "abroga",
    "amenda",
    "aplica",
    "conflict",
    "contradict",
    "deroga",
    "exceptie",
    "interzis",
    "legal",
    "lege",
    "modifica",
    "neconstitutional",
    "nul",
    "obliga",
    "prevede",
    "sanctiune",
    "termen",
    "transpune",
}
UNCERTAINTY_WORDS = {
    "posibil",
    "necesita verificare",
    "nu certifica",
    "ipoteza",
    "incert",
    "pare",
    "trebuie verificat",
    "limitare",
}
VERDICT_WORDS = {
    "este ilegal",
    "este neconstitutional",
    "incalca sigur",
    "cert incalca",
    "garantat",
    "fara dubiu",
}
STRUCTURE_WORDS = {
    "surse",
    "constatare",
    "ipoteza",
    "risc",
    "limitari",
    "incertitudini",
    "recomandare",
    "amendament",
    "comparatie",
    "temei",
}
ROMANIAN_STOPWORDS = {
    "acest",
    "aceasta",
    "ale",
    "articol",
    "care",
    "cele",
    "cu",
    "din",
    "este",
    "fara",
    "lege",
    "pentru",
    "prin",
    "sau",
    "se",
    "si",
    "sunt",
    "un",
}


def _text(value, limit, *, required=True):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise ValueError("Text invalid sau prea lung.")
    value = value.strip()
    if required and not value:
        raise ValueError("Text obligatoriu.")
    return value


def _tokens(text):
    return re.findall(r"[a-z0-9ăâîșț]+", text.lower())


def _content_tokens(text):
    return {
        t for t in _tokens(text) if len(t) >= 4 and t not in ROMANIAN_STOPWORDS and not t.isdigit()
    }


def _sentences(text):
    return [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", text) if p.strip()]


def _legal_claims(text):
    claims = []
    for sentence in _sentences(text):
        low = sentence.lower()
        if any(word in low for word in LEGAL_CLAIM_WORDS):
            claims.append(sentence)
    return claims


def _clamp(value):
    return round(max(0.0, min(1.0, value)), 3)


def _load_json(path):
    with Path(path).open(encoding="utf-8") as fh:
        return json.load(fh)


def _source_index(case):
    sources = case.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("Cazul nu are surse.")
    total = 0
    ids = set()
    text_parts = []
    for source in sources:
        ident = _text(source.get("id"), 80)
        if ident in ids:
            raise ValueError("Sursa duplicata.")
        ids.add(ident)
        text = _text(source.get("text"), MAX_SOURCE_CHARS, required=False)
        total += len(text)
        if total > MAX_SOURCE_CHARS:
            raise ValueError("Sursele depasesc limita.")
        text_parts.append(text)
    return ids, _content_tokens("\n".join(text_parts)), "\n".join(text_parts).lower()


def _case_by_id(cases):
    if not isinstance(cases, list) or len(cases) > MAX_CASES:
        raise ValueError("Lista de cazuri este invalida.")
    out = {}
    for case in cases:
        ident = _text(case.get("id"), 120)
        if ident in out:
            raise ValueError("Caz duplicat.")
        out[ident] = case
    return out


def _score_faithfulness(output, source_tokens):
    claims = _legal_claims(output)
    if not claims:
        return 0.0, ["Nu exista afirmatii juridice evaluabile."]
    supported = 0
    unsupported = []
    for claim in claims:
        overlap = _content_tokens(claim) & source_tokens
        if len(overlap) >= 2:
            supported += 1
        else:
            unsupported.append(claim[:220])
    return supported / len(claims), unsupported[:5]


def _score_citations(output, source_ids, required):
    citations = re.findall(r"\[([A-Za-z0-9_.:-]+)\]", output)
    valid = [c for c in citations if c.split(":", 1)[0] in source_ids]
    invalid = [c for c in citations if c.split(":", 1)[0] not in source_ids]
    required = set(required or [])
    cited_source_ids = {c.split(":", 1)[0] for c in valid}
    missing = sorted(required - cited_source_ids)
    if not citations:
        return 0.0, ["Lipsesc citarile explicite."]
    validity = len(valid) / len(citations)
    coverage = 1.0 if not required else (len(required - set(missing)) / len(required))
    score = validity * 0.65 + coverage * 0.35
    notes = []
    if invalid:
        notes.append("Citari necunoscute: " + ", ".join(invalid[:5]))
    if missing:
        notes.append("Surse obligatorii necitate: " + ", ".join(missing[:5]))
    return score, notes


def _score_hallucinations(output, case, source_text, source_tokens):
    forbidden = [
        term
        for term in case.get("forbidden_claim_terms", [])
        if isinstance(term, str) and term.lower() in output.lower()
    ]
    faithfulness, unsupported = _score_faithfulness(output, source_tokens)
    verdicts = [word for word in VERDICT_WORDS if word in output.lower()]
    unsupported_ratio = 1.0 - faithfulness
    score = 1.0 - min(1.0, unsupported_ratio * 0.65 + len(forbidden) * 0.2 + len(verdicts) * 0.25)
    notes = []
    if forbidden:
        notes.append("Termeni de concluzie nepermisi: " + ", ".join(forbidden[:5]))
    if verdicts:
        notes.append("Verdicte tari fara spatiu de incertitudine: " + ", ".join(verdicts[:5]))
    if unsupported:
        notes.append("Afirmatii slab sustinute de surse.")
    if case.get("must_not_claim_absent") and any(
        term.lower() not in source_text for term in case["must_not_claim_absent"]
    ):
        notes.append("Exista capcane de absenta care trebuie evitate.")
    return score, notes


def _score_structure(output):
    low = output.lower()
    headings = len(re.findall(r"(^|\n)\s*(#{1,3}\s*)?[A-ZĂÂÎȘȚa-zăâîșț ]{3,35}\s*:", output))
    bullets = len(re.findall(r"(^|\n)\s*(-|\d+[.)])\s+", output))
    labels = sum(1 for word in STRUCTURE_WORDS if word in low)
    score = min(1.0, headings * 0.18 + bullets * 0.08 + labels * 0.12)
    notes = [] if score >= 0.65 else ["Structura este greu de scanat pentru revizuire."]
    return score, notes


def _score_romanian(output):
    tokens = _tokens(output)
    if len(tokens) < 25:
        return 0.25, ["Raspuns prea scurt pentru o redactare utila."]
    diacritics = len(re.findall(r"[ăâîșțĂÂÎȘȚ]", output))
    english = len(re.findall(r"\b(the|therefore|however|must|shall|article)\b", output.lower()))
    romanian_markers = len([t for t in tokens if t in ROMANIAN_STOPWORDS])
    score = (
        0.45
        + min(0.25, diacritics / 80)
        + min(0.25, romanian_markers / 60)
        - min(0.35, english * 0.08)
    )
    notes = []
    if english:
        notes.append("Contine termeni englezesti in redactarea romana.")
    if diacritics < 4:
        notes.append("Diacritice putine pentru un raspuns romanesc.")
    return score, notes


def _score_uncertainty(output, case):
    low = output.lower()
    markers = sum(1 for word in UNCERTAINTY_WORDS if word in low)
    verdicts = sum(1 for word in VERDICT_WORDS if word in low)
    required = case.get("requires_uncertainty", True)
    if required:
        score = min(1.0, markers * 0.35 + (0.3 if "nu este consultanta juridica" in low else 0))
        score -= min(0.45, verdicts * 0.2)
    else:
        score = 0.8 + min(0.2, markers * 0.05) - min(0.3, verdicts * 0.1)
    notes = [] if score >= 0.65 else ["Incertitudinea si limitele nu sunt suficient marcate."]
    return score, notes


def evaluate_case(case, candidate):
    output = _text(candidate.get("output"), MAX_OUTPUT_CHARS)
    source_ids, source_tokens, source_text = _source_index(case)
    scores = {}
    notes = {}
    scoring = {
        "source_faithfulness": _score_faithfulness(output, source_tokens),
        "citation_correctness": _score_citations(
            output, source_ids, case.get("required_citations", [])
        ),
        "hallucinated_legal_claims": _score_hallucinations(
            output, case, source_text, source_tokens
        ),
        "useful_structure": _score_structure(output),
        "romanian_drafting_quality": _score_romanian(output),
        "uncertainty": _score_uncertainty(output, case),
    }
    for key, (score, key_notes) in scoring.items():
        scores[key] = _clamp(score)
        notes[key] = key_notes
    overall = _clamp(sum(scores.values()) / len(CRITERIA))
    return {
        "case_id": case["id"],
        "task_type": case.get("task_type", "unknown"),
        "provider": _text(candidate.get("provider", "unknown"), 80, required=False) or "unknown",
        "model": _text(candidate.get("model", "unknown"), 120, required=False) or "unknown",
        "overall": overall,
        "scores": scores,
        "notes": notes,
        "limits": [
            "Scor euristic determinist; nu certifica acuratete juridica.",
            "Evalueaza raspunsuri salvate; nu apeleaza modele sau API-uri platite.",
            "Suportul surselor este aproximat prin suprapuneri lexicale si citari declarate.",
        ],
    }


def evaluate_run(cases_doc, run_doc):
    if (
        cases_doc.get("schema_version") != SCHEMA_VERSION
        or run_doc.get("schema_version") != SCHEMA_VERSION
    ):
        raise ValueError("Versiune schema incompatibila.")
    cases = _case_by_id(cases_doc.get("cases"))
    candidates = run_doc.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("Lista de raspunsuri este invalida.")
    results = []
    for candidate in candidates:
        case_id = _text(candidate.get("case_id"), 120)
        if case_id not in cases:
            raise ValueError("Raspuns pentru caz necunoscut.")
        results.append(evaluate_case(cases[case_id], candidate))
    providers = defaultdict(list)
    for result in results:
        providers[(result["provider"], result["model"])].append(result["overall"])
    comparison = [
        {
            "provider": provider,
            "model": model,
            "cases": len(values),
            "overall": _clamp(sum(values) / len(values)),
        }
        for (provider, model), values in sorted(providers.items())
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "run_id": _text(run_doc.get("run_id", "manual"), 120, required=False) or "manual",
        "criteria": list(CRITERIA),
        "results": results,
        "comparison": comparison,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", required=True, help="Path to AI eval cases JSON.")
    parser.add_argument("--run", required=True, help="Path to saved provider outputs JSON.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args(argv)
    result = evaluate_run(_load_json(args.cases), _load_json(args.run))
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
