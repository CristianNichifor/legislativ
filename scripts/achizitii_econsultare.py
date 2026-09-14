"""One-source acquisition for e-consultare public consultation pages."""

from __future__ import annotations

import hashlib
import html
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
LISTING_URL = "https://e-consultare.gov.ro/Consultare-public%C4%83"
ACTIONGRID_URL = (
    "https://e-consultare.gov.ro/DesktopModules/DnnSharp/ActionGrid/Api.ashx?"
    "TabId=155&language=en-US&_url=https%3a%2f%2fe-consultare.gov.ro%2f"
    "Default.aspx%3fTabId%3d155%26language%3den-US&referrer=&_aliasid=3"
    "&_mid=883&_tabid=155&method=GetData"
)
DATE = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HREF = re.compile(r'href=["\']([^"\']+)["\']', re.I)
TAG = re.compile(r"<[^>]+>")
DOCUMENT_EXTENSIONS = (".pdf", ".doc", ".docx", ".odt", ".rtf", ".xls", ".xlsx")


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


def descarca_actiongrid(url: str = ACTIONGRID_URL, limita: int = MAX_BYTES) -> tuple[bytes, int]:
    return descarca(url, limita)


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
            if path.endswith(DOCUMENT_EXTENSIONS):
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


def normalizeaza_data(value: str | None) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if DATE.fullmatch(value):
        day, month, year = re.split(r"[./-]", value)
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    if ISO_DATE.fullmatch(value):
        return value
    return ""


def normalizeaza_status(value: str | None) -> str:
    text = " ".join((value or "").strip().lower().split())
    if not text:
        return "unknown"
    if text in {"open", "opened", "deschisa", "deschisă"}:
        return "open"
    if text in {"closed", "inchisa", "închisă"}:
        return "closed"
    if text in {"announced", "anuntata", "anunțată"}:
        return "announced"
    if any(term in text for term in ("închis", "inchis", "finalizat", "expirat", "arhivat")):
        return "closed"
    if any(
        term in text
        for term in (
            "consultare public",
            "în consultare",
            "in consultare",
            "deschis",
            "activ",
            "termen limită",
            "termen limita",
        )
    ):
        return "open"
    if any(term in text for term in ("anunț", "anunt", "publicat", "transparen")):
        return "announced"
    return "unknown"


def _document_metadata(documents: list[dict]) -> dict:
    by_type: dict[str, int] = {}
    hashed = 0
    for document in documents:
        path = urlsplit(document.get("url", "")).path.lower()
        suffix = Path(path).suffix.lstrip(".") or "unknown"
        by_type[suffix] = by_type.get(suffix, 0) + 1
        value = document.get("content_hash") or document.get("hash") or document.get("sha256") or ""
        if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value):
            hashed += 1
    return {
        "total": len(documents),
        "by_type": dict(sorted(by_type.items())),
        "with_hash": hashed,
        "labels": [
            document.get("label", "") for document in documents[:10] if document.get("label")
        ],
    }


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
    status = normalizeaza_status(text)
    documents = [
        {"url": item["url"], "label": item["label"]}
        for item in sorted(parser.links.values(), key=lambda item: item["url"])[:100]
    ]
    deadline_iso = normalizeaza_data(deadline)
    document_summary = _document_metadata(documents)
    return {
        "contract": "econsultare-source-snapshot-v1",
        "family": "consultare_econsultare",
        "url": url,
        "summary": {
            "title": title[:300],
            "authority": authority,
            "status": status,
            "deadline": deadline,
            "deadline_iso": deadline_iso,
            "documents": len(documents),
            "document_metadata": document_summary,
            "truncated": len(parser.links) > 100,
        },
        "title": title[:300],
        "authority": authority,
        "status": status,
        "deadline": deadline,
        "deadline_iso": deadline_iso,
        "documents": documents,
        "document_metadata": document_summary,
        "truncated": len(parser.links) > 100,
    }


def _plain_html(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value or "", flags=re.I)
    value = TAG.sub(" ", value)
    return " ".join(html.unescape(value).split())


def _field(row: dict, name: str) -> str:
    for item in row.get("fields") or []:
        if item.get("Name") == name:
            return str(item.get("FormattedValue") or item.get("Value") or "")
    return ""


def _authority_from_details(value: str) -> str:
    match = re.search(r"<small>\s*[^<]*-\s*([^<]+)</small>", value or "", re.I)
    if match:
        return _plain_html(match.group(1))[:300]
    text = _plain_html(value)
    if " - " in text:
        return text.rsplit(" - ", 1)[-1][:300]
    return ""


def _first_href(value: str, baza: str) -> str:
    match = HREF.search(value or "")
    if not match:
        return ""
    return url_oficial(urljoin(baza, html.unescape(match.group(1))))


def _deadline_from_terms(value: str) -> str:
    text = _plain_html(value)
    deadline = _date_after(("termen limită transmitere propuneri",), text)
    if deadline:
        return deadline
    dates = DATE.findall(text)
    return dates[-1] if dates else ""


def _status_from_grid(value: str) -> str:
    return normalizeaza_status(_plain_html(value))


def actiongrid_row_hash(row: dict) -> str:
    return hashlib.sha256(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def snapshot_din_actiongrid(row: dict, *, listing_url: str) -> dict:
    """Normalize one official e-consultare ActionGrid row into our source snapshot."""
    if not isinstance(row, dict):
        raise ValueError("Rând e-consultare invalid.")
    official_listing_url = url_oficial(listing_url)
    details = _field(row, "Detaliiproiect")
    title_html = _field(row, "Detalii1")
    terms = _field(row, "Termeneproiectlegislativ")
    title = _plain_html(re.split(r"<br\s*/?>", title_html, maxsplit=1, flags=re.I)[0])[:300]
    url = _first_href(details, official_listing_url) or official_listing_url
    authority = _authority_from_details(title_html)
    status = _status_from_grid(_field(row, "StatusProiect"))
    deadline = _deadline_from_terms(terms)
    deadline_iso = normalizeaza_data(deadline)
    source_hash = actiongrid_row_hash(row)
    document_summary = _document_metadata([])
    return {
        "contract": "econsultare-source-snapshot-v1",
        "family": "consultare_econsultare",
        "url": url,
        "summary": {
            "title": title,
            "authority": authority,
            "status": status,
            "deadline": deadline,
            "deadline_iso": deadline_iso,
            "documents": 0,
            "document_metadata": document_summary,
            "truncated": False,
        },
        "title": title,
        "authority": authority,
        "status": status,
        "deadline": deadline,
        "deadline_iso": deadline_iso,
        "documents": [],
        "document_metadata": document_summary,
        "truncated": False,
        "source_metadata": {
            "contract": "econsultare-actiongrid-row-v1",
            "listing_url": official_listing_url,
            "row_id": str(row.get("id") or ""),
            "date_published": str(row.get("datePublished") or ""),
            "published": _field(row, "StartConsDesc"),
            "status_label": _plain_html(_field(row, "StatusProiect")),
            "terms": _plain_html(terms),
            "source_hash": source_hash,
            "parser_version": PARSER_VERSION,
        },
        "limitations": [
            "Snapshot dintr-un singur rând ActionGrid e-consultare; nu descarcă atașamente.",
            "Nu clasifică efecte juridice și nu decide compatibilitatea proiectului.",
        ],
    }


def parseaza_actiongrid(data: bytes, *, listing_url: str) -> list[dict]:
    payload = json.loads(data.decode("utf-8"))
    rows = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Răspuns ActionGrid e-consultare invalid.")
    return [snapshot_din_actiongrid(row, listing_url=listing_url) for row in rows]


def descopera_actiongrid(*, limit: int = 50) -> dict:
    if not 1 <= limit <= 300:
        raise ValueError("Limită e-consultare invalidă.")
    data, http_status = descarca_actiongrid()
    snapshots = parseaza_actiongrid(data, listing_url=LISTING_URL)[:limit]
    return {
        "contract": "econsultare-actiongrid-discovery-v1",
        "listing_url": url_oficial(LISTING_URL),
        "endpoint_url": url_oficial(ACTIONGRID_URL),
        "http_status": http_status,
        "snapshots": snapshots,
        "total": len(snapshots),
        "limit": limit,
        "limitations": [
            "Descoperă rânduri din lista oficială e-consultare; nu descarcă atașamente.",
            "Fiecare rând devine sursă punctuală ce poate fi urmărită și sincronizată separat.",
        ],
    }


def snapshot_hash(snapshot: dict) -> str:
    relevant = {
        "contract": snapshot["contract"],
        "url": snapshot["url"],
        "summary": snapshot["summary"],
        "document_metadata": snapshot.get("document_metadata", {}),
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


def _event_date(value: str | None, fallback: str) -> str:
    return _tracker_date(value, fallback=fallback)


def _attachment_hashes(documents: list[dict]) -> list[str]:
    hashes: list[str] = []
    for document in documents:
        value = document.get("content_hash") or document.get("hash") or document.get("sha256") or ""
        if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value):
            hashes.append(value)
    return hashes[:100]


def _missing_fields(summary: dict) -> list[str]:
    missing = []
    if not (summary.get("authority") or "").strip():
        missing.append("authority")
    if normalizeaza_status(str(summary.get("status") or "")) == "unknown":
        missing.append("status")
    if not (summary.get("deadline_iso") or normalizeaza_data(str(summary.get("deadline") or ""))):
        missing.append("deadline")
    return missing


def _document_key(document: dict) -> str:
    return str(
        document.get("content_hash")
        or document.get("hash")
        or document.get("sha256")
        or document.get("url")
        or document.get("label")
        or ""
    )


def tracker_event_candidate(
    snapshot: dict,
    *,
    source_id: str = "",
    content_hash: str = "",
    observed_at: str | None = None,
) -> dict:
    """Return an add-ready tracker event candidate for one e-consultare snapshot."""
    candidates = tracker_event_candidates(
        snapshot,
        source_id=source_id,
        content_hash=content_hash,
        observed_at=observed_at,
    )
    for event in candidates:
        if event["event_type"] in {"public_consultation_opened", "public_consultation_closed"}:
            return event
    return candidates[0]


def tracker_event_candidates(
    snapshot: dict,
    *,
    source_id: str = "",
    content_hash: str = "",
    observed_at: str | None = None,
    previous_snapshot: dict | None = None,
    source_family: str = "consultare_econsultare",
) -> list[dict]:
    """Return add-ready tracker events for one consultation snapshot."""
    summary = snapshot.get("summary") or {}
    status = normalizeaza_status(str(summary.get("status") or snapshot.get("status") or "unknown"))
    documents = snapshot.get("documents") if isinstance(snapshot.get("documents"), list) else []
    url = snapshot.get("url") or ""
    title = summary.get("title") or snapshot.get("title") or "Consultare publică"
    authority = summary.get("authority") or snapshot.get("authority", "")
    deadline = (
        summary.get("deadline_iso")
        or snapshot.get("deadline_iso")
        or summary.get("deadline")
        or snapshot.get("deadline", "")
    )
    fallback_date = observed_at or datetime.now(UTC).isoformat()
    project_id = snapshot.get("project_id") or url or source_id
    base_payload = {
        "authority": authority,
        "project_url": url,
        "status": status or "unknown",
    }
    events = [
        {
            "event_type": "public_consultation_announced",
            "project_id": project_id,
            "source_family": source_family,
            "source_id": source_id,
            "source_url": url,
            "occurred_at": _event_date(
                (snapshot.get("source_metadata") or {}).get("published")
                or (snapshot.get("source_metadata") or {}).get("date_published"),
                fallback_date,
            ),
            "observed_at": observed_at or "",
            "title": title,
            "payload": {key: value for key, value in base_payload.items() if value not in ("", [])},
            "content_hash": content_hash,
        }
    ]
    if status == "closed":
        payload = {**base_payload, "closed_at": _event_date(deadline, fallback_date)}
        event_type = "public_consultation_closed"
    else:
        payload = {
            **base_payload,
            "deadline": _event_date(deadline, fallback_date) if deadline else "",
            "attachment_hashes": _attachment_hashes(documents),
            "documents": documents[:100],
            "document_metadata": (
                snapshot.get("document_metadata") or summary.get("document_metadata") or {}
            ),
        }
        event_type = "public_consultation_opened"
    events.append(
        {
            "event_type": event_type,
            "project_id": project_id,
            "source_family": source_family,
            "source_id": source_id,
            "source_url": url,
            "occurred_at": _event_date(deadline, fallback_date),
            "observed_at": observed_at or "",
            "title": title,
            "payload": {key: value for key, value in payload.items() if value not in ("", [])},
            "content_hash": content_hash,
        }
    )
    if previous_snapshot:
        previous_summary = previous_snapshot.get("summary") or {}
        previous_deadline = (
            previous_summary.get("deadline_iso")
            or previous_snapshot.get("deadline_iso")
            or previous_summary.get("deadline")
            or previous_snapshot.get("deadline")
            or ""
        )
        if normalizeaza_data(str(previous_deadline)) != normalizeaza_data(str(deadline)):
            events.append(
                {
                    "event_type": "public_consultation_deadline_changed",
                    "project_id": project_id,
                    "source_family": source_family,
                    "source_id": source_id,
                    "source_url": url,
                    "occurred_at": _event_date(deadline, fallback_date),
                    "observed_at": observed_at or "",
                    "title": title,
                    "payload": {
                        **base_payload,
                        "previous_deadline": (
                            _event_date(previous_deadline, fallback_date)
                            if previous_deadline
                            else ""
                        ),
                        "deadline": _event_date(deadline, fallback_date) if deadline else "",
                    },
                    "content_hash": content_hash,
                }
            )
        previous_docs = {
            _document_key(document)
            for document in previous_snapshot.get("documents", [])
            if _document_key(document)
        }
        added_documents = [
            document
            for document in documents
            if _document_key(document) and _document_key(document) not in previous_docs
        ][:100]
        if added_documents:
            events.append(
                {
                    "event_type": "public_consultation_document_added",
                    "project_id": project_id,
                    "source_family": source_family,
                    "source_id": source_id,
                    "source_url": url,
                    "occurred_at": fallback_date,
                    "observed_at": observed_at or "",
                    "title": title,
                    "payload": {
                        **base_payload,
                        "documents": added_documents,
                        "attachment_hashes": _attachment_hashes(added_documents),
                    },
                    "content_hash": content_hash,
                }
            )
    missing = _missing_fields(summary)
    if missing:
        events.append(
            {
                "event_type": "public_consultation_metadata_review",
                "project_id": project_id,
                "source_family": source_family,
                "source_id": source_id,
                "source_url": url,
                "occurred_at": fallback_date,
                "observed_at": observed_at or "",
                "title": title,
                "payload": {**base_payload, "deadline": deadline, "missing": missing},
                "content_hash": content_hash,
            }
        )
    return events


def tracker_event_source_unavailable(
    *,
    source_id: str,
    source_url: str,
    source_family: str = "consultare_econsultare",
    reason: str = "fetch_failed",
    observed_at: str | None = None,
) -> dict:
    stamp = observed_at or datetime.now(UTC).isoformat()
    return {
        "event_type": "public_consultation_source_unavailable",
        "project_id": source_url or source_id,
        "source_family": source_family,
        "source_id": source_id,
        "source_url": source_url,
        "occurred_at": stamp,
        "observed_at": stamp,
        "title": "Sursă consultare indisponibilă",
        "payload": {
            "project_url": source_url,
            "reason": reason[:120],
            "missing": ["source"],
        },
        "content_hash": "",
    }


def sincronizeaza(url: str) -> dict:
    data, http_status = descarca(url)
    snapshot = parseaza(data, url)
    return {
        "http_status": http_status,
        "content_hash": snapshot_hash(snapshot),
        "snapshot": snapshot,
        "needs_review": bool(_missing_fields(snapshot["summary"])),
    }
