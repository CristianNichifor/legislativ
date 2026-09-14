"""Deterministic UX acceptance gate for the Civic UI surface."""

from __future__ import annotations

import argparse
import html
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

CONTRACT = "ux-acceptance-gate-v1"
INTERNAL_WORDING = ("rebuild", "index", "reload", "cache", "manifest", "shard")
TECHNICAL_PROVENANCE_WARNING_TERMS = ("Source hash", "stale")
TECHNICAL_PROVENANCE_ALLOWED_AREAS = (
    "details",
    "data-raw-contract",
    "data-debug",
    "debug",
)
VOID_HTML_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class UXAcceptanceError(RuntimeError):
    """User-facing UX acceptance has blockers."""


@dataclass(frozen=True)
class Finding:
    kind: str
    message: str
    evidence: list[str]

    def as_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message, "evidence": self.evidence}


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored: list[str] = []
        self.text: list[str] = []
        self.links: list[str] = []
        self.body_classes = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag in {"script", "style", "template", "svg"}:
            self._ignored.append(tag)
        if tag == "link" and (attrs_dict.get("rel") or "").lower() == "stylesheet":
            self.links.append(attrs_dict.get("href") or "")
        if tag == "body":
            self.body_classes = attrs_dict.get("class") or ""

    def handle_endtag(self, tag: str) -> None:
        if self._ignored and self._ignored[-1] == tag:
            self._ignored.pop()

    def handle_data(self, data: str) -> None:
        if not self._ignored:
            normalized = " ".join(html.unescape(data).split())
            if normalized:
                self.text.append(normalized)


class _PrimaryVisibleTextParser(HTMLParser):
    """Visible text parser that skips accepted machine-detail areas."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored: list[str] = []
        self._allowed_depth = 0
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag in {"script", "style", "template", "svg"}:
            self._ignored.append(tag)
        if tag in VOID_HTML_TAGS:
            return
        if self._allowed_depth or self._is_allowed_area(tag, attrs_dict):
            self._allowed_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._ignored and self._ignored[-1] == tag:
            self._ignored.pop()
        if self._allowed_depth and tag not in VOID_HTML_TAGS:
            self._allowed_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored or self._allowed_depth:
            return
        normalized = " ".join(html.unescape(data).split())
        if normalized:
            self.text.append(normalized)

    @staticmethod
    def _is_allowed_area(tag: str, attrs: dict[str, str | None]) -> bool:
        if tag == "details":
            return True
        if "data-raw-contract" in attrs or "data-debug" in attrs:
            return True
        class_name = attrs.get("class") or ""
        element_id = attrs.get("id") or ""
        return "debug" in class_name.split() or "debug" in element_id.lower()


def _without_html_comments(source: str) -> str:
    return re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)


def _without_js_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"(^|[^:])//.*", r"\1", source)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def _visible_html(html_text: str) -> tuple[str, list[str], str]:
    parser = _VisibleTextParser()
    parser.feed(_without_html_comments(html_text))
    return "\n".join(parser.text), parser.links, parser.body_classes


def _primary_visible_html(html_text: str) -> str:
    parser = _PrimaryVisibleTextParser()
    parser.feed(_without_html_comments(html_text))
    return "\n".join(parser.text)


def _js_string_literals(source: str) -> list[str]:
    literals: list[str] = []
    pattern = re.compile(
        r"""
        (?P<quote>['"`])
        (?P<body>(?:\\.|(?! (?P=quote) ).)*?)
        (?P=quote)
        """,
        re.VERBOSE,
    )
    for match in pattern.finditer(_without_js_comments(source)):
        body = match.group("body")
        normalized = " ".join(body.replace("\\n", " ").split())
        if not normalized:
            continue
        if not re.search(r"[A-Za-zĂÂÎȘȚăâîșț]", normalized):
            continue
        if normalized.startswith(("/", "#", ".", "[", "data-", "api/")):
            continue
        if len(normalized) <= 2:
            continue
        literals.append(normalized)
    return literals


def _visible_fragment_text(fragment: str) -> str:
    fragment = re.sub(r"\$\{.*?\}", " ", fragment, flags=re.DOTALL)
    parser = _VisibleTextParser()
    parser.feed(fragment)
    return " ".join(parser.text)


def _js_visible_text(html_text: str) -> list[str]:
    lines: list[str] = []
    visible_markers = (
        "innerHTML",
        "insertAdjacentHTML",
        "textContent",
        "setFirstRunStatus(",
        "return `",
        "return '",
        'return "',
    )
    for line in _without_js_comments(html_text).splitlines():
        if not any(marker in line for marker in visible_markers):
            continue
        for item in _js_string_literals(line):
            if re.search(r"<[a-zA-Z][^>]*>", item):
                text = _visible_fragment_text(item)
            else:
                text = " ".join(re.sub(r"\$\{.*?\}", " ", item).split())
            if not text or "=>" in text or "function " in text:
                continue
            if text.startswith(("/", "#", ".", "[", "data-", "api/")):
                continue
            if re.search(r"\s|[ĂÂÎȘȚăâîșț]", text):
                lines.append(text)
    return lines


def _js_primary_visible_text(html_text: str) -> list[str]:
    return [line for line in _js_visible_text(html_text) if not _is_machine_detail_fragment(line)]


def _is_machine_detail_fragment(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ("data-raw-contract", "data-debug"))


def _user_visible_text(html_text: str) -> str:
    visible_text, _, _ = _visible_html(html_text)
    return "\n".join([visible_text, *_js_visible_text(html_text)])


def _primary_user_visible_text(html_text: str) -> str:
    visible_text = _primary_visible_html(html_text)
    return "\n".join([visible_text, *_js_primary_visible_text(html_text)])


def _has_all(text: str, needles: tuple[str, ...]) -> bool:
    return all(needle in text for needle in needles)


def _missing_needles(text: str, needles: tuple[str, ...]) -> list[str]:
    return [needle for needle in needles if needle not in text]


def _context(text: str, word: str) -> list[str]:
    found: list[str] = []
    pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
    for match in pattern.finditer(text):
        start = max(0, match.start() - 70)
        end = min(len(text), match.end() + 70)
        found.append(" ".join(text[start:end].split()))
        if len(found) == 5:
            break
    return found


def _block(kind: str, message: str, evidence: list[str] | None = None) -> Finding:
    return Finding(kind=kind, message=message, evidence=evidence or [])


def report(root: Path | None = None) -> dict:
    root = root or _repo_root()
    blockers: list[Finding] = []
    warnings: list[Finding] = []

    try:
        html_text = _read(root, "app/index.html")
    except FileNotFoundError:
        html_text = ""
        blockers.append(_block("missing_index_html", "Missing app/index.html."))

    try:
        adapter_css = _read(root, "app/civic-ui-adapter.css")
    except FileNotFoundError:
        adapter_css = ""
        blockers.append(_block("missing_civic_ui_adapter", "Missing app/civic-ui-adapter.css."))

    visible_text, stylesheet_links, body_classes = _visible_html(html_text)
    user_visible = _user_visible_text(html_text)
    primary_user_visible = _primary_user_visible_text(html_text)

    internal_hits: dict[str, list[str]] = {}
    for word in INTERNAL_WORDING:
        contexts = _context(user_visible, word)
        if contexts:
            internal_hits[word] = contexts
    if internal_hits:
        blockers.append(
            _block(
                "internal_wording_visible",
                "Internal build/runtime wording is visible to users.",
                [
                    f"{word}: {sample}"
                    for word, samples in internal_hits.items()
                    for sample in samples
                ],
            )
        )

    civic_checks = {
        "stylesheet_link": "civic-ui-adapter.css" in stylesheet_links,
        "body_scope": "civic-legislativ" in body_classes,
        "adapter_scope": ".civic-legislativ" in adapter_css,
        "adapter_tokens": _has_all(
            adapter_css,
            ("--civic-bg", "--civic-surface", "--civic-text", "--civic-action"),
        ),
        "search_controls": _has_all(
            html_text,
            ("civic-input", "civic-select", "vendor/civic-ui/styles.css"),
        ),
    }
    if not all(civic_checks.values()):
        blockers.append(
            _block(
                "missing_civic_ui_adapter",
                "Civic UI adapter is not fully mounted on the user-facing shell.",
                [name for name, ok in civic_checks.items() if not ok],
            )
        )

    source_needles = (
        "Acoperirea surselor",
        "surse lipsă",
        "surse parțiale",
        "revizuibile",
        "Calitate sursă",
        "sursă necunoscută",
        "Ultima verificare salvată",
    )
    missing_source = _missing_needles(html_text, source_needles)
    if missing_source:
        blockers.append(
            _block(
                "missing_source_status_explanations",
                "Source status states are not explained in visible UX copy.",
                missing_source,
            )
        )

    ai_needles = (
        "AI/MCP este explicit",
        "handoff aprobat",
        "BYOK",
        "Cheile API rămân doar în sesiunea browserului",
        "confirmare explicită necesară",
    )
    missing_ai = _missing_needles(html_text, ai_needles)
    if missing_ai:
        blockers.append(
            _block(
                "missing_ai_mcp_approval_copy",
                "AI/MCP copy does not make user approval and key boundaries explicit.",
                missing_ai,
            )
        )

    verdict_needles = (
        "nu verdict juridic",
        "candidați, nu verdict juridic",
        "revizie umană",
        "necesită jurist",
    )
    missing_verdict = _missing_needles(html_text, verdict_needles)
    if missing_verdict:
        blockers.append(
            _block(
                "missing_no_verdict_candidate_review_wording",
                "Candidate/review flows do not preserve no-verdict wording.",
                missing_verdict,
            )
        )

    workflow_needles = (
        'id="legislative-workflow"',
        'data-workflow-step="source"',
        'data-workflow-step="note"',
        'data-workflow-step="evidence"',
        'data-workflow-step="draft"',
        'data-workflow-step="export"',
        "data-workflow-open-search",
        "data-workflow-open-matrix",
        "data-workflow-open-dossier",
        "data-workflow-open-note",
        "data-workflow-open-draft",
        "data-workflow-open-export",
    )
    missing_workflow = _missing_needles(html_text, workflow_needles)
    if missing_workflow:
        blockers.append(
            _block(
                "missing_workflow_anchors",
                "Basic daily workflow anchors are missing.",
                missing_workflow,
            )
        )

    for word in TECHNICAL_PROVENANCE_WARNING_TERMS:
        contexts = _context(primary_user_visible, word)
        if contexts:
            warnings.append(
                _block(
                    "technical_wording_visible",
                    f"Technical wording remains visible: {word}.",
                    contexts,
                )
            )

    status = "blocked" if blockers else "warning" if warnings else "ready"
    return {
        "contract": CONTRACT,
        "status": status,
        "acceptance_allowed": not blockers,
        "blockers": [item.as_dict() for item in blockers],
        "warnings": [item.as_dict() for item in warnings],
        "checks": {
            "civic_ui": civic_checks,
            "source_status_explanations": {
                "required": list(source_needles),
                "missing": missing_source,
            },
            "ai_mcp_approval": {"required": list(ai_needles), "missing": missing_ai},
            "no_verdict_candidate_review": {
                "required": list(verdict_needles),
                "missing": missing_verdict,
            },
            "workflow_anchors": {"required": list(workflow_needles), "missing": missing_workflow},
            "internal_wording": {"forbidden": list(INTERNAL_WORDING), "hits": internal_hits},
            "technical_provenance_warning_policy": {
                "prefer": "Romanian user-facing labels",
                "warning_terms": list(TECHNICAL_PROVENANCE_WARNING_TERMS),
                "allowed_machine_detail_areas": list(TECHNICAL_PROVENANCE_ALLOWED_AREAS),
            },
        },
        "visible_in": {
            "docs": "docs/UX_ACCEPTANCE.md",
            "cli": "python -m scripts.ux_acceptance --require-complete",
            "inputs": ["app/index.html", "app/civic-ui-adapter.css"],
        },
    }


def assert_complete(data: dict) -> None:
    if data.get("acceptance_allowed"):
        return
    blockers = data.get("blockers") or []
    summary = "; ".join(
        f"{item.get('kind', 'blocker')}: {', '.join(item.get('evidence') or [])}"
        for item in blockers
    )
    raise UXAcceptanceError("UX acceptance gate blocked: " + summary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report Civic UI UX acceptance status")
    parser.add_argument(
        "--root",
        type=Path,
        default=_repo_root(),
        help="Repository root to inspect. Defaults to this checkout.",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Exit non-zero when user-visible UX acceptance has blockers.",
    )
    args = parser.parse_args(argv)
    data = report(args.root)
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
    if args.require_complete:
        try:
            assert_complete(data)
        except UXAcceptanceError:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
