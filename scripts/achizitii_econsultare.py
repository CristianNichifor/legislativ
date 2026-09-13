"""One-source acquisition for e-consultare public consultation pages."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from scripts.cdep import USER_AGENT

PARSER_VERSION = "achizitii_econsultare.v1"
MAX_BYTES = 2 * 1024 * 1024
HOSTS = {"e-consultare.gov.ro", "www.e-consultare.gov.ro"}
DATE = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def url_oficial(url: str) -> str:
    if not isinstance(url, str) or any(ord(c) < 33 for c in url) or "\\" in url:
        raise ValueError("Adresă e-consultare invalidă.")
    p = urlsplit(url)
    if p.scheme not in {"http", "https"} or p.hostname not in HOSTS or p.username or p.password:
        raise ValueError("Sunt permise doar pagini oficiale e-consultare.gov.ro.")
    if p.port not in (None, 80 if p.scheme == "http" else 443):
        raise ValueError("Port nepermis.")
    return urlunsplit(("https", p.hostname, p.path, p.query, ""))


def descarca(url: str, limita: int = MAX_BYTES) -> tuple[bytes, int]:
    req = urllib.request.Request(url_oficial(url), headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=20) as response:
        url_oficial(response.geturl())
        data = response.read(limita + 1)
        status = int(getattr(response, "status", 200))
    if len(data) > limita:
        raise ValueError("Pagina e-consultare depășește limita de descărcare.")
    return data, status


@dataclass
class _Parser(HTMLParser):
    baza: str
    title: str = ""
    heading: str = ""
    current_heading: str = ""
    current_link: dict | None = None
    links: dict[str, dict] = field(default_factory=dict)
    text_parts: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__(convert_charrefs=True)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"h1", "h2"}:
            self.current_heading = tag
        if tag == "a":
            href = attrs.get("href", "")
            if not href:
                return
            url = urljoin(self.baza, href)
            path = urlsplit(url).path.lower()
            if path.endswith((".pdf", ".doc", ".docx", ".odt", ".rtf", ".xls", ".xlsx")):
                self.current_link = {"url": url, "label": attrs.get("title", "")}

    def handle_data(self, data):
        text = " ".join(data.split())
        if not text:
            return
        self.text_parts.append(text)
        if self.current_heading == "h1" or (self.current_heading == "h2" and not self.heading):
            self.heading = (self.heading + " " + text).strip()
        if self.current_link:
            self.current_link["label"] = (self.current_link["label"] + " " + text).strip()

    def handle_endtag(self, tag):
        if tag in {"h1", "h2"}:
            self.current_heading = ""
        if tag == "a" and self.current_link:
            link = self.current_link
            link["label"] = (
                " ".join(link["label"].split())[:300] or Path(urlsplit(link["url"]).path).name
            )
            link["url"] = urlunsplit(urlsplit(link["url"])._replace(fragment=""))
            self.links.setdefault(link["url"], link)
            self.current_link = None


def _first_after(labels: tuple[str, ...], text: str) -> str:
    lowered = text.lower()
    for label in labels:
        pos = lowered.find(label)
        if pos < 0:
            continue
        fragment = text[pos + len(label) : pos + len(label) + 180]
        fragment = re.sub(r"^[\s:;-]+", "", fragment)
        fragment = re.split(r"\s{2,}|(?:Data|Termen|Autoritate|Instituție|Minister)\b", fragment)[0]
        if fragment.strip():
            return fragment.strip(" .,:;-")[:160]
    return ""


def _date_after(labels: tuple[str, ...], text: str) -> str:
    lowered = text.lower()
    for label in labels:
        pos = lowered.find(label)
        if pos < 0:
            continue
        match = DATE.search(text[pos : pos + 180])
        if match:
            return match.group(0)
    return ""


def parseaza(data: bytes, baza: str) -> dict:
    url = url_oficial(baza)
    html = data.decode("utf-8", errors="replace")
    parser = _Parser(url)
    parser.feed(html)
    text = " ".join(parser.text_parts)
    dates = DATE.findall(text)
    title = parser.heading or _first_after(("titlu", "denumire"), text)
    authority = _first_after(("autoritate inițiatoare", "instituția inițiatoare", "minister"), text)
    deadline = _date_after(("termen limită", "termen de transmitere", "până la data de"), text)
    if not deadline and dates:
        deadline = dates[-1]
    status = (
        "open"
        if re.search(r"\b(în consultare|consultare publică|termen limită)\b", text, re.I)
        else "unknown"
    )
    documents = [
        {"url": item["url"], "label": item["label"]}
        for item in sorted(parser.links.values(), key=lambda item: item["url"])[:100]
    ]
    return {
        "contract": "econsultare-source-snapshot-v1",
        "family": "consultare_econsultare",
        "url": url,
        "summary": {
            "title": title[:300],
            "authority": authority,
            "status": status,
            "deadline": deadline,
            "documents": len(documents),
            "truncated": len(parser.links) > 100,
        },
        "title": title[:300],
        "authority": authority,
        "status": status,
        "deadline": deadline,
        "documents": documents,
        "truncated": len(parser.links) > 100,
    }


def snapshot_hash(snapshot: dict) -> str:
    relevant = {
        "contract": snapshot["contract"],
        "url": snapshot["url"],
        "summary": snapshot["summary"],
        "documents": snapshot["documents"],
        "truncated": snapshot["truncated"],
    }
    return hashlib.sha256(
        json.dumps(relevant, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def _tracker_date(value: str | None, *, fallback: str | None = None) -> str:
    value = (value or "").strip()
    if not value:
        return fallback or datetime.now(UTC).isoformat()
    if DATE.fullmatch(value):
        day, month, year = re.split(r"[./-]", value)
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}T00:00:00+00:00"
    if ISO_DATE.fullmatch(value):
        return value + "T00:00:00+00:00"
    return value


def _attachment_hashes(documents: list[dict]) -> list[str]:
    hashes: list[str] = []
    for document in documents:
        value = document.get("content_hash") or document.get("hash") or document.get("sha256") or ""
        if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value):
            hashes.append(value)
    return hashes[:100]


def tracker_event_candidate(
    snapshot: dict,
    *,
    source_id: str = "",
    content_hash: str = "",
    observed_at: str | None = None,
) -> dict:
    """Return an add-ready tracker event candidate for one e-consultare snapshot."""
    summary = snapshot.get("summary") or {}
    status = str(summary.get("status") or snapshot.get("status") or "unknown").strip().lower()
    documents = snapshot.get("documents") if isinstance(snapshot.get("documents"), list) else []
    url = snapshot.get("url") or ""
    title = summary.get("title") or snapshot.get("title") or "Consultare publică"
    authority = summary.get("authority") or snapshot.get("authority", "")
    deadline = summary.get("deadline") or snapshot.get("deadline", "")
    fallback_date = observed_at or datetime.now(UTC).isoformat()
    event_type = (
        "public_consultation_closed" if status == "closed" else "public_consultation_opened"
    )
    payload = {
        "authority": authority,
        "project_url": url,
        "status": status or "unknown",
    }
    if event_type == "public_consultation_closed":
        payload["closed_at"] = _tracker_date(deadline, fallback=fallback_date)
    else:
        payload["deadline"] = _tracker_date(deadline, fallback=fallback_date) if deadline else ""
        payload["attachment_hashes"] = _attachment_hashes(documents)
        payload["documents"] = documents[:100]
    return {
        "event_type": event_type,
        "project_id": url or source_id,
        "source_family": "consultare_econsultare",
        "source_id": source_id,
        "source_url": url,
        "occurred_at": _tracker_date(deadline, fallback=fallback_date),
        "observed_at": observed_at or "",
        "title": title,
        "payload": {key: value for key, value in payload.items() if value not in (None, "")},
        "content_hash": content_hash,
    }


def sincronizeaza(url: str) -> dict:
    data, http_status = descarca(url)
    snapshot = parseaza(data, url)
    return {
        "http_status": http_status,
        "content_hash": snapshot_hash(snapshot),
        "snapshot": snapshot,
        "needs_review": not snapshot["title"] or snapshot["summary"]["documents"] == 0,
    }
