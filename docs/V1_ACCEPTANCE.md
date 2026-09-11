# V1 acceptance preparation

Status: bounded public-procurement pilot runtime path recorded in
[`v1_acceptance_pilot_2026-09-11.json`](v1_acceptance_pilot_2026-09-11.json).
Neither M7 nor M8 is accepted here.

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

Run `python -m scripts.v1_rehearsal`, `python -m scripts.etalon`,
`python -m scripts.etalon_real` and `python -m scripts.etalon_precizie` offline.
For a prepared public dataset folder, run
`python -m scripts.acceptare_date_reale <release_dir> --pilot-act <act_id>`.
The acceptance runner activates the release through the production local-runtime
update path, searches the corpus unless skipped for a tiny fixture, creates a
private dossier, opens and saves a real law workbench run (`fisa-act-v1`), records
signal/finding counts, verifies private dossier data survives rollback, and emits
JSON. It does not synthesize a finding or proposal. Preserve output with the tested
commit, Python/SQLite versions and manifest hash in the acceptance record.

The 2026-09-11 pilot record built a valid public release from the two committed
authentic snapshots and ran the command for `lege-98-2016`. It passed activation,
search, workbench save and private rollback survival. The run measured 2 acts,
1,635 provisions, 3 search results, 8 EU references signaled and 0 reviewable
gap/CCR findings. Therefore the real finding-to-proposal save remains unexercised;
this is a data/review limitation, not an application pass/fail threshold.

The authentic etalon counts publisher S_LGI marks matched by normalized text
containment anywhere in the document. **Those marks are locators, not citations of
other acts**: over the committed fixtures, 808 of 822 are `lit. e)`-shaped and the
remaining 14 name the host act, so none points at a different act. The number is
therefore a proxy for *locator* recall — not exact-span recall, not reference recall,
not precision, completeness or legal correctness. This section described it as a
reference-recall proxy until 2026-09-10. No marks means not measured; it must not be
reported as perfect recall.

External reference recall is consequently **unmeasured**: nothing independent says
which citations of other acts a real document contains. Reference *precision* is
measured by adjudication — `data/etalon-precizie.json` holds a deterministic sample of
120 of the 283 claims the extractor makes over the fixtures, and
`data/etalon-precizie-verdicte.json` holds the verdicts. Both are empty of verdicts at
the time of writing, so precision reads `nemăsurată`, not 100%.

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
- Extend the approved release data or measurements enough to produce at least one
  authentic reviewable gap/CCR finding, then save reviewer-approved proposal
  wording from that finding. The 2026-09-11 run has
  `workbench.finding_to_proposal = not_exercised_no_authentic_gap_or_ccr_finding`.
- Record missing/extraction/false-positive cases and agreed tolerances; no invented
  passing threshold or accuracy claim. Resolve release-blocking findings and rerun.
- Integrate and assess M3 source-change, M4 applicability and M6 UX changes, plus
  bounded EU assessment where real obligation text is available.
- Record who accepted which results and remaining limitations. Legal-reliability
  claims need qualified independent evaluation; ordinary use does not require it.
