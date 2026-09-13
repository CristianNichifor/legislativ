# V1 scope and acceptance dataset

This is the concrete v1 acceptance baseline for proving the app can run on a
curated Romanian/EU legislative drafting sample without publishing or downloading
multi-GB public datasets.

The checked-in machine contract is
[`data/v1_acceptance_dataset.json`](../data/v1_acceptance_dataset.json), validated
by [`scripts/v1_acceptance_dataset.py`](../scripts/v1_acceptance_dataset.py).

## Exact v1 scope

V1 acceptance means the local app can load a small curated sample and exercise the
main product surfaces with visible limitations:

- Romanian law text: two checked-in Portal Legislativ snapshots already used by
  the pilot fixture.
- Project lifecycle: one Camera placeholder and one Senat placeholder, enough to
  prove lifecycle rows and source states exist without crawling Parliament.
- Public consultation: one E-Consultare placeholder and one ministry consultation
  placeholder, enough to prove consultation records are represented.
- EU references: two CELEX placeholders cited by the procurement fixture, with
  official URLs but no local EU text.

V1 acceptance explicitly excludes:

- multi-GB dataset releases;
- portal-wide crawls, whole-EUR-Lex imports and full Monitorul Oficial mirrors;
- legal recall/precision adjudication;
- AI legal conclusions or automatic compliance verdicts.

## Acceptance manifest rows

The baseline has eight rows:

| Row | Family | Type | Mode | Purpose |
| --- | --- | --- | --- | --- |
| `v1-law-lege-98-2016` | Portal Legislativ | law | local fixture | primary procurement law text |
| `v1-law-lege-208-2022` | Portal Legislativ | law | local fixture | secondary Romanian law fixture |
| `v1-project-camera-procurement` | Camera | project | placeholder | project lifecycle shape |
| `v1-project-senat-procurement` | Senat | project | placeholder | second chamber lifecycle shape |
| `v1-consultare-econsultare-procurement` | E-Consultare | consultation | placeholder | public consultation shape |
| `v1-consultare-minister-procurement` | ministry consultation | consultation | placeholder | ministry metadata-first shape |
| `v1-celex-32014l0024` | EU Cellar/EUR-Lex | CELEX | placeholder | missing EU text remains visible |
| `v1-celex-32004l0018` | EU Cellar/EUR-Lex | CELEX | placeholder | second missing EU text signal |

Local fixture payloads must stay under 1 MiB total and must match their SHA-256
hashes. Placeholder rows must not claim local text or payload hashes.

## Acceptance checks

The focused tests assert:

- the JSON manifest matches its schema and runtime validator;
- the row count stays between five and ten;
- law, project, consultation and CELEX records are all represented;
- local fixture paths and hashes are real and bounded;
- placeholders cannot silently become fake payloads;
- large release work remains outside this v1 acceptance baseline.
