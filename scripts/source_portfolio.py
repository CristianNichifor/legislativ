"""Source portfolio and storage sizing for MP law-writing workflows."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal

R2_STANDARD_USD_PER_GB_MONTH = 0.015
R2_FREE_GB_MONTH = 10
CENT = Decimal("0.01")


@dataclass(frozen=True)
class SourceFamily:
    key: str
    label: str
    priority: int
    ingest_policy: str
    purpose: str
    rough_gb_min: int
    rough_gb_max: int
    first_slice: str


@dataclass(frozen=True)
class TrackerEvent:
    key: str
    label: str
    source_family: str
    fields: tuple[str, ...]


SOURCE_FAMILIES: tuple[SourceFamily, ...] = (
    SourceFamily(
        "legislatie_ro",
        "Portal Legislativ",
        1,
        "full_text_incremental",
        "published and consolidated Romanian law text",
        5,
        30,
        "act text, Monitorul Oficial reference and consolidation metadata",
    ),
    SourceFamily(
        "camera",
        "Camera Deputaților",
        2,
        "metadata_and_documents_incremental",
        "PL-x lifecycle, committees, reports, agendas and votes",
        10,
        60,
        "project ficha, committee/report links, agenda and vote events",
    ),
    SourceFamily(
        "senat",
        "Senat",
        3,
        "metadata_and_documents_incremental",
        "L/B/BP lifecycle, consultation list, committees and opinions",
        10,
        50,
        "project list/detail, consultation deadline and status events",
    ),
    SourceFamily(
        "consultare_econsultare",
        "E-Consultare",
        4,
        "metadata_first_documents_on_demand",
        "draft normative acts before or outside Parliament",
        5,
        40,
        "consultation id, authority, deadline, attachments and state",
    ),
    SourceFamily(
        "consultare_minister",
        "Ministry consultation pages",
        5,
        "adapter_by_adapter",
        "draft acts that are not reliably mirrored elsewhere",
        10,
        80,
        "one ministry page adapter and public-deadline parser",
    ),
    SourceFamily(
        "ue_cellar",
        "EU Cellar / EUR-Lex",
        6,
        "celex_on_demand",
        "official EU text and metadata for compatibility/transposition checks",
        20,
        100,
        "CELEX referenced by dossiers or Romanian acts, Romanian then English",
    ),
    SourceFamily(
        "ccr",
        "CCR",
        7,
        "full_text_incremental",
        "constitutional risk and invalidated provisions",
        5,
        30,
        "decision metadata, operative part, affected provisions",
    ),
    SourceFamily(
        "avize",
        "Institutional opinions / avize",
        8,
        "metadata_first_documents_on_demand",
        "Consiliul Legislativ, CES, CSM and other required opinions",
        5,
        40,
        "issuer, positive/negative/observations, document hash",
    ),
    SourceFamily(
        "monitorul_oficial_pi",
        "Monitorul Oficial Partea I",
        9,
        "full_text_incremental_pdf_retained_selectively",
        "official publication proof for normative acts",
        50,
        200,
        "Part I index, text extraction, law-publication links",
    ),
    SourceFamily(
        "monitorul_oficial_other_parts",
        "Monitorul Oficial Parts II-VII",
        10,
        "metadata_or_domain_trigger_only",
        "announcements and non-core material; avoid full ingestion by default",
        100,
        1000,
        "metadata and user-requested/domain-triggered documents only",
    ),
    SourceFamily(
        "monitorul_oficial_local",
        "Monitorul Oficial Local",
        11,
        "registry_then_opt_in_packs",
        "local acts, HCL, dispositions, local regulations and urbanism",
        100,
        2000,
        "MDLPA/UAT registry, per-UAT source state, opt-in local packs",
    ),
)

TRACKER_EVENTS: tuple[TrackerEvent, ...] = (
    TrackerEvent(
        "public_consultation_opened",
        "public consultation opened",
        "consultare_econsultare",
        ("authority", "deadline", "project_url", "attachment_hashes"),
    ),
    TrackerEvent(
        "public_consultation_closed",
        "public consultation closed",
        "consultare_econsultare",
        ("authority", "closed_at", "project_url"),
    ),
    TrackerEvent(
        "committee_assignment",
        "committee assignment",
        "camera/senat",
        ("committee", "role", "deadline", "project_id", "source_url"),
    ),
    TrackerEvent(
        "opinion_received",
        "aviz/opinion received",
        "avize",
        ("issuer", "position", "observations", "document_hash", "source_url"),
    ),
    TrackerEvent(
        "report_filed",
        "committee report filed",
        "camera/senat",
        ("committee", "position", "document_hash", "filed_at", "source_url"),
    ),
    TrackerEvent(
        "plenary_agenda",
        "plenary agenda",
        "camera/senat",
        ("chamber", "agenda_date", "project_id", "source_url"),
    ),
    TrackerEvent(
        "vote_recorded",
        "vote recorded",
        "camera/senat",
        ("chamber", "vote_date", "result", "for", "against", "abstain", "nominal_url"),
    ),
    TrackerEvent(
        "promulgated",
        "promulgated",
        "presedinte",
        ("decree_number", "date", "source_url"),
    ),
    TrackerEvent(
        "published_in_monitor",
        "published in Monitorul Oficial",
        "monitorul_oficial_pi",
        ("part", "number", "date", "act_id", "source_hash"),
    ),
)


def portfolio() -> dict:
    families = [asdict(item) for item in sorted(SOURCE_FAMILIES, key=lambda item: item.priority)]
    return {
        "contract": "source-portfolio-v1",
        "families": families,
        "tracker_events": [
            {**asdict(item), "fields": list(item.fields)} for item in TRACKER_EVENTS
        ],
        "monitorul_oficial_policy": {
            "part_i": "ingest",
            "part_ii": "metadata_or_selective",
            "parts_iii_vii": "do_not_full_ingest_by_default",
            "local": "registry_first_opt_in_packs",
        },
    }


def estimate_storage(profile: str = "serious") -> dict:
    selected = {
        "v1": {
            "legislatie_ro",
            "camera",
            "senat",
            "consultare_econsultare",
            "ue_cellar",
            "ccr",
        },
        "serious": {
            item.key
            for item in SOURCE_FAMILIES
            if item.key not in {"monitorul_oficial_other_parts", "monitorul_oficial_local"}
        },
        "everything": {item.key for item in SOURCE_FAMILIES},
    }.get(profile)
    if selected is None:
        raise ValueError("Profil necunoscut. Folosește v1, serious sau everything.")
    families = [item for item in SOURCE_FAMILIES if item.key in selected]
    gb_min = sum(item.rough_gb_min for item in families)
    gb_max = sum(item.rough_gb_max for item in families)
    billable_min = max(0, gb_min - R2_FREE_GB_MONTH)
    billable_max = max(0, gb_max - R2_FREE_GB_MONTH)
    return {
        "contract": "source-storage-estimate-v1",
        "profile": profile,
        "gb_min": gb_min,
        "gb_max": gb_max,
        "r2_standard_usd_month_min": _usd(billable_min),
        "r2_standard_usd_month_max": _usd(billable_max),
        "families": [item.key for item in families],
        "assumptions": [
            "compressed text and metadata are retained first",
            "raw PDFs are retained selectively unless the profile includes everything",
            "operation costs depend on object count/read pattern and are not included",
        ],
    }


def _usd(gb: int) -> float:
    return float(
        (Decimal(gb) * Decimal(str(R2_STANDARD_USD_PER_GB_MONTH))).quantize(
            CENT, rounding=ROUND_HALF_UP
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--estimate", choices=("v1", "serious", "everything"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    out = estimate_storage(args.estimate) if args.estimate else portfolio()
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
