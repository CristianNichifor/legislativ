# Project lifecycle and watchlist scaffold

This slice adds a shared lifecycle vocabulary for public consultations, government
drafting and parliamentary projects. It is intentionally small: it normalizes
known labels and marks missing/new labels as unavailable or unknown instead of
guessing.

## Lifecycle states

`scripts.lifecycle.normalize_stage_label()` returns one bounded state:

- `consultation_announced`
- `consultation_open`
- `consultation_closed`
- `drafting`
- `government_adopted`
- `sent_to_parliament`
- `registered`
- `committee`
- `report`
- `plenary_scheduled`
- `adopted`
- `rejected`
- `promulgated`
- `published`
- `withdrawn_archived`
- `unknown`
- `unavailable`

Every state carries:

- `key`
- `label`
- `order`
- `terminal`
- `available`
- `known`
- `raw`, when there was a source label

`unknown` means the source exposed a non-empty label the parser does not yet
recognize. `unavailable` means the source did not expose a usable label.

## Current wiring

The local parliamentary acquisition workspace now includes lifecycle metadata in
project list/detail responses:

- `lifecycle`: normalized state for `initiative.stadiu`
- `watchlist`: compact project watch payload

The act watch backend (`initiative_pe_act`) also includes `lifecycle` on each
project that targets the watched act.

No frontend migration is required for this PR. Existing UI can ignore the new
fields, while future watchlist screens can render them directly.

`GET /api/lifecycle-proiecte` exposes the same state as a feed for future
project and consultation tracking screens. Query parameters:

- `q`: optional literal search over project id/title
- `limit`: 1-100, default 50
- `offset`: pagination offset
- `stale_days`: how old `citit_la` may be before the row is marked stale

Each project in the response includes:

- `source_name`
- `project_id`
- `title`
- `status`
- `stage`
- `last_seen`
- `last_updated`
- `consultation_deadline`, currently `null` for parliamentary rows
- `url`
- `source_state`: `ok`, `stale`, `unknown` or `unavailable`
- `needs_attention`

The feed returns unavailable/empty/stale/review states explicitly, so a UI can
show missing source coverage without pretending the project has no lifecycle.

## Watchlist intent

The first watchlist scaffold marks a row as `needs_attention` when its lifecycle
is `unknown` or `unavailable`. That lets the app surface source/parser coverage
work without blocking users who only need the existing status text.

Future source collectors should emit the same lifecycle shape for:

- public consultation URLs;
- ministry/Government drafting pages;
- Parliament registration/procedure pages;
- committee/report/plenary events;
- promulgation and publication references.
