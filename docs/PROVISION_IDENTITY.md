# Provision identity contract

This is the first law-as-code identity layer. It gives every addressable legal
unit one stable key before any graph, matrix or executable rule is built on top.

## Contract

`scripts.provision_identity.resolve(con, act_id, locator)` returns:

- `contract`: `provision-identity-v1`
- `status`: `available` or `unavailable`
- `provision_id`: `ro:{act_id}#{canonical_locator}`
- `act_id`
- `locator`
- `kind`: `document`, `anexa`, `articol`, `alineat`, `litera` or `punct`
- `parts`: parsed locator components
- `source_url`
- `captured_at`
- `source_hash`: SHA-256 of the local provision text rows
- `source_version`: currently the capture timestamp
- `rows`: number of local rows with the exact locator
- `exact`
- `unavailable_reason`, when missing

The identity key is intentionally independent from the text hash. A changed
source updates `source_hash`; it does not create a different provision identity.

## Supported locators

Canonical locators use the existing corpus shape:

- `text`
- `art7`
- `art7.alin2`
- `art7.alin2.litb`
- `art7.alin2.litb.pct3`
- `anx1`
- `anx1.art2`

Romanian display forms normalize to the same shape, for example:

- `art. 7 alin. (2) lit. b)` -> `art7.alin2.litb`
- `Articolul II` -> `artII`
- `Anexa nr. 1 art. 2` -> `anx1.art2`

## Refusals

The helper rejects unsupported or ambiguous locators instead of guessing:

- `alin. (2)` without an article;
- `lit. b)` without an article;
- `pct. 3` without a letter/article chain;
- chapter or section labels that are not stored as addressable provision rows.

Missing rows return `status=unavailable` with a canonical `provision_id`, so a
review queue can keep pointing at the same intended unit after source coverage
improves.

## Why this matters

The law-as-code layer needs durable legal objects before it can safely add:

- graph edges between provisions;
- domain matrix cells;
- candidate obligations, prohibitions, deadlines and exceptions;
- executable deterministic checks.

Every one of those later layers must be able to point back to the same exact
official text snapshot, or explicitly say the source is unavailable.
