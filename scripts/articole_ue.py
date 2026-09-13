"""Article-boundary helpers for retained CELEX text snapshots.

The metadata here is provenance for human review. It is not a classifier for EU
obligations, transposition, applicability or legal effect.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict

from scripts import cellar

ARTICLE_BOUNDARY_CONTRACT = "celex-article-boundary-v1"


def sha_text(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()


def body_text(article: dict) -> str:
    """Return article body without parser heading/title lines."""
    lines = article["text"].splitlines()[1:]
    if lines and article.get("titlu") and lines[0].strip() == article["titlu"].strip():
        lines = lines[1:]
    return "\n".join(lines).strip()


def _line_bounds(full_text: str, block_text: str) -> dict:
    """Best-effort line boundaries in the retained extracted text."""
    source_lines = [line.strip() for line in cellar.normalizeaza(full_text).splitlines()]
    block_lines = [line.strip() for line in cellar.normalizeaza(block_text).splitlines()]
    block_lines = [line for line in block_lines if line]
    if not block_lines:
        return {"start_line": None, "end_line": None, "boundary_status": "unavailable"}
    for start in range(0, len(source_lines) - len(block_lines) + 1):
        if source_lines[start : start + len(block_lines)] == block_lines:
            return {
                "start_line": start + 1,
                "end_line": start + len(block_lines),
                "boundary_status": "line_exact",
            }
    return {"start_line": None, "end_line": None, "boundary_status": "parser_block_only"}


def articles_from_snapshot(
    snapshot: dict, *, max_blocks: int = 1000
) -> tuple[list[dict], list[dict]]:
    source = snapshot["sursa"]
    blocks = cellar.provizii_din_text(source["celex"], source["text"], source["limba"])
    if len(blocks) > max_blocks:
        return [], [{"side": "eu", "code": "capture_limit"}]
    articles = []
    for block in blocks:
        if block.fel != "articol":
            continue
        data = asdict(block)
        body = body_text(data)
        base = re.sub(r"-\d+$", "", block.locator)
        ambiguous = any(b.locator.startswith(base + "-") for b in blocks)
        boundary = {
            "contract": ARTICLE_BOUNDARY_CONTRACT,
            "celex": source["celex"],
            "snapshot_id": snapshot["id"],
            "locator": block.locator,
            "language": source["limba"],
            "source_text_sha256": source["text_sha256"],
            "article_sha256": sha_text(block.text),
            "body_sha256": sha_text(body),
            "heading": block.text.splitlines()[0].strip() if block.text.splitlines() else "",
            "title": block.titlu,
            "chars": len(block.text),
            "body_chars": len(body),
            **_line_bounds(source["text"], block.text),
        }
        articles.append(
            {
                **data,
                "selectabil": not ambiguous,
                "body": body,
                "boundary": boundary,
            }
        )
    return articles, []


def summary(snapshot: dict, *, page_size: int = 80, max_blocks: int = 1000) -> dict:
    if snapshot.get("stare") != "capturat":
        return {"total": 0, "randuri": [], "trunchiat": False}
    try:
        articles, blockers = articles_from_snapshot(snapshot, max_blocks=max_blocks)
    except (KeyError, TypeError, ValueError):
        return {"total": 0, "randuri": [], "trunchiat": False, "stare": "indisponibil"}
    if blockers:
        return {"total": 0, "randuri": [], "trunchiat": False, "blockers": blockers}
    return {
        "contract": ARTICLE_BOUNDARY_CONTRACT,
        "total": len(articles),
        "randuri": [
            {
                "locator": a["locator"],
                "titlu": a["titlu"],
                "limba": a["limba"],
                "ord": a["ord"],
                "sha256": a["boundary"]["article_sha256"],
                "boundary": a["boundary"],
            }
            for a in articles[:page_size]
        ],
        "trunchiat": len(articles) > page_size,
    }
