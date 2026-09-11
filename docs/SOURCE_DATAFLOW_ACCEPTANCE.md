# Source data-flow acceptance

This acceptance slice keeps the public/local data flow understandable without a
backend account, paid AI, full rebuild or multi-GB release.

## Public dataset metadata

A public update starts from `channel.json`, which points to an immutable
`dataset-release.json`. The manifest must name the release, app contract and
bounded public files with byte size and SHA-256 hashes. Private workspace data is
not part of the manifest and is never uploaded by the local update manager.

## Source status

Source availability must remain explicit. Missing or unsupported official
sources are represented as `unavailable`, retryable fetch problems as `failed`,
rate limits as `rate_limited`, and ambiguous fetched sources as `needs_review`.
These states come from `scripts/source_sync.py` and apply to Romanian laws,
parliamentary projects, consultation pages, CCR decisions and EU CELEX sources.

## Update and rollback

Downloading a public dataset only stages verified public files. Activation
creates a new local public generation and a new private generation. Rollback
returns to the previous verified public generation while keeping private
workspace files under the local data directory.
