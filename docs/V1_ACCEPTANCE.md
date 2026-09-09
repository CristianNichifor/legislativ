# V1 acceptance preparation

Status: proposed public-procurement pilot, pending the user's domain approval
requested by the coordinating workstream. Neither M7 nor M8 is accepted here.

## Bounded source set

Machine-readable scope and byte hashes: `data/v1_pilot.json`.
Only the two committed portal snapshots are imported: Legea 98/2016
(consolidated procurement law) and Legea 208/2022 (amending act).
These are authentic retrieved content, not newly retrieved or verified-current law.
Retrieval timestamps are unknown. The import timestamp `citit_la` is not a fetch date.
Legea 98's retrieval URL is supported by `tests/test_parsare.py`; Legea 208's
embedded portal identifier is recorded without inventing its original retrieval URL.
`sources/README.md` documents their origin and the absent republished-act fixture.

Legea 99/2016, Legea 100/2016, EU obligation texts, historical pre-2022 text,
republished versions and other domains are outside this corpus. A reference to them
does not establish their contents or applicability. No crawl is part of this pilot.

`data/etalon.json` is synthetic extractor ground truth. The rehearsal's finding,
replacement wording and schema-7 historical records are also synthetic.
`tests/test_consolidare_gold.py` uses authentic replacement payloads but a synthetic
pre-amendment placeholder; it cannot establish historical reconstruction accuracy.

## Measurement protocol

Run `python -m scripts.v1_rehearsal`, `python -m scripts.etalon`, and
`python -m scripts.etalon_real` offline. Preserve output with the tested commit,
Python/SQLite versions and manifest hash in the acceptance record.
The authentic reference etalon counts publisher S_LGI marks matched by normalized
text containment anywhere in the document. This is a proxy for reference recall,
not exact-span recall, precision, completeness, or legal correctness. No marks means
not measured; it must not be reported as perfect recall.

Before domain acceptance, freeze reviewer-approved expected items for each source
and locator, then classify every expected item and emitted candidate in the bounded
set. Use `data/v1_acceptance_measurements.csv`; blank counts mean unmeasured.
Record source hash, quoted evidence, expected/observed behavior, reviewer, date and
resolution. Keep synthetic controls out of authentic-domain denominators.

| Category | Denominator and classification |
| --- | --- |
| Missing source | Required documents/versions in approved scope; count absent, unreadable, stale or unknown separately. |
| Extraction | Independently labeled expected references/locators/payloads; count exact successes and misses. S_LGI proxy is separate. |
| False positive | All emitted candidates reviewed; confirmed false / adjudicated candidates. Unreviewed candidates are unknown. |
| Precision/recall | TP/(TP+FP), TP/(TP+FN) only after independent adjudication; zero denominators are N/A. |

## Remaining M7 gates

- User confirms domain, document/version boundary and intended research questions.
- Run an actual-document finding-to-proposal workflow without the synthetic bridge.
  The current issuer-filtered fixture report yields zero findings; that is not proof
  of absence of legal problems. Issuer spellings differ between the two documents.
- Record missing/extraction/false-positive cases and agreed tolerances; no invented
  passing threshold or accuracy claim. Resolve release-blocking findings and rerun.
- Integrate and assess M3 source-change, M4 applicability and M6 UX changes, plus
  bounded EU assessment where real obligation text is available.
- Record who accepted which results and remaining limitations. Legal-reliability
  claims need qualified independent evaluation; ordinary use does not require it.
