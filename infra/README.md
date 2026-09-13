# infra — optional plain-language rewrite service (Cloudflare, free)

The side-by-side "Limbaj clar" feature restates a provision of **public** law in plain language
(Danish style — see `docs/STIL_DANEZ.md`). This Worker is an optional endpoint that a user or
deployment owner can run with their own Cloudflare account. It runs the rewrite on **Workers AI**
(Cloudflare's own hosted models — no external account, no key) and caches each result in KV, so a
provision is rewritten **once**, then served from cache.

The browser app no longer defaults to a project-owned endpoint. Online AI is BYOK: users pick a
provider or paste their own Worker endpoint, and private draft text is sent only after confirmation.

The Worker can fit on Cloudflare's **free tier**. Workers AI is billed in Neurons with a free daily
allocation, so light use can cost **nothing**.

## What Cloudflare pieces we use

| Piece | Free? | Role | State |
|---|---|---|---|
| **Workers** | 100k req/day free | the rewrite service (`worker/src/index.js`) | **deployed** |
| **Workers AI** (`env.AI`) | free daily Neuron allocation | runs the rewrite (Llama 3.3 70B) | live |
| **Workers KV** `legislativ-rescrieri` | 100k reads / 1k writes / 1 GB free | the rewrite cache | live (`8a788c53…`) |
| **Rate-limiting binding** (`RL`) | free | per-IP limit, no KV cost | live |
| **AI Gateway** `law-legislation-project-gateway` | free | caching + analytics in front of Workers AI | live |
| **R2** `legislativ` | 10 GB / 1M class A ops per month free | the corpus and the search index, read by the browser over Range | **live** on `date.cristian-nichifor.com` — see the cost model below |

Account: **CN Webify** `432316a05c0d6000c6e196fe32e47dd7`. Existing maintainer endpoint:
`https://legislativ-rescrieri.cn-webify.workers.dev/rescrie`. It is not used as the public app
default.

## R2 — what a republish actually costs

Measured 2026-09-13, bucket `legislativ`: **three dated prefixes**, each carrying a 6,69 GB
`corpus.db` plus its search index. Almost all of the object count is the index — a corpus file is
one object, a Pagefind slice is thousands of fragments.

| prefix | read by |
|---|---|
| `2026-09-11` | `channel.json` → `dataset-release.json` |
| `2026-09-10` | nothing found; superseded by `2026-09-11` |
| `2026-09-08` | the published page — `--depozit` in `.github/workflows/pages.yml` |

**Two different prefixes are live at once, for two different consumers.** The page serves its
corpus and its eight search slices from `2026-09-08`; the dataset channel points readers at
`2026-09-11`. Whether that is intended is a separate question from storage — but it is the reason
no lifecycle rule may be set on this bucket (below).

The 2026-09-10 note in an earlier revision of this file said there was a single prefix and that
nothing had yet accumulated. That stopped being true on the next publish.

A republish writes a **new** dated prefix, so each one costs roughly:

| | per republish | free tier |
|---|---|---|
| Class A operations (writes) | ~256.000 | 1.000.000 / month |
| Storage added | ~10 GB, cumulative | 10 GB total |

Three republishes a month is free. **Daily republishing is ~7,7M class A operations, about
$30/month**, and storage grows by ~10 GB every time because nothing deletes the old prefixes.

Two things follow, and one thing that looks like a fix is not one:

- **Storage needs pruning — and a lifecycle rule is the wrong tool for it.** R2 lifecycle rules
  expire objects by *age*. They cannot tell the prefix the page is serving right now from an
  abandoned one. A rule saying "delete anything older than 7 days" would today remove
  `2026-09-08` — the corpus and all eight search slices the live page reads — while leaving the
  channel's `2026-09-11` untouched. Search would answer from nothing, and the dataset channel
  would still look healthy. That is the most expensive kind of outage: silent on the surface.

  `infra/curata-prefixe.sh` does the pruning instead. It reads the prefix out of `channel.json`
  and the `--depozit` pin out of `pages.yml`, keeps both plus the most recent `PASTREAZA` (2 by
  default), and refuses to run at all if it cannot determine either reference. Without
  `CONFIRMA=da` it only reports. Run today it protects all three prefixes and deletes nothing,
  which is the correct answer — the prefixes are not garbage yet, they are in use.

  The bucket already carries R2's *Default Multipart Abort Rule* (7 days), which is the one
  lifecycle rule that cannot lose committed data. Leave it; add no object-expiry rule.
- **The operation count is inherent to the dated-prefix design**, not to a flag. A new prefix is
  empty, so every fragment is a new object no matter how it is uploaded.
- **`--no-traverse` is not the cause.** It skips listing the destination, and the destination is a
  fresh prefix with nothing in it to skip. Removing it would add class B list operations and save
  nothing. It is correct where it is.

Publishing the index under a content-stable prefix instead, so unchanged fragments could be
skipped, does **not** work here either: `infra/pagefind.mjs` slices the corpus **by position in the
file**, so adding acts shifts every later record into a different slice and changes essentially
every fragment. Making that pay off would mean slicing by a stable key first, which is a real
change and not currently worth it — the corpus is republished rarely.

## Deploy

Already deployed and working. To redeploy after a change:

```sh
cd infra/worker && npx wrangler deploy      # needs `npx wrangler login` once
```

No secret to set — Workers AI needs no key. In the app, pick "online (BYOK)" → "Worker propriu" and
paste your own `/rescrie` endpoint.

### AI Gateway (optional, free — for caching + analytics)

The Worker routes Workers AI calls through the gateway `AIG_ID` (`law-legislation-project-gateway`,
already created) and **falls back to Workers AI directly if that gateway doesn't exist**, so it works
with or without it. The gateway is live with caching on (300s TTL); **logging is off** — flip "Logs"
on in the gateway settings for the per-request analytics dashboard.

To create a fresh gateway elsewhere:

- **Dashboard:** AI → AI Gateway → **Create Gateway**, then set `AIG_ID` to its id.
- **Or** with an API token that has **Account · AI Gateway · Edit**:
  `CLOUDFLARE_API_TOKEN=… ./infra/deploy.sh` (its step 1 creates the gateway, then deploys).

`wrangler login` alone can't create the gateway (its OAuth scope doesn't include AI Gateway Edit),
which is why this one step is a dashboard/API-token action.

## Contract

- `POST /rescrie {act, loc, text, stil?, model?}` → `{rescriere, cached, model, stil}`; generates on
  a cache miss, stores it, returns it.
- `GET /rescrie?act=&loc=&stil=` → cached rewrite or `404 negenerat`.
- `stil`: `nou` (plain-language / Danish, default) or `actual` (current legal register, Legea
  24/2000). It namespaces the cache so the two norms never collide.
- `model` is honored only from an allowlist (`@cf/meta/llama-3.3-70b-instruct-fp8-fast`,
  `@cf/meta/llama-3.1-8b-instruct`); anything else uses `WAI_MODEL`. This is what the app's online
  **model** picker sends.
- `POST {text, stil?, model?}` **without `act`** is a general rewrite of the caller's own text — never
  cached, still rate-limited / size-capped / daily-capped. The app uses this for the Redactează block
  text and the draft "Limbaj clar" (and confirms before sending).
- The app's CSP allows `https://*.workers.dev` for user-owned Worker endpoints.

## Keeping it free and abuse-proof

1. **Cache-first (KV):** a repeat provision is a free KV read; the model is never called twice.
2. **AI Gateway cache** (once created): a second, free cache by request + cost analytics.
3. **Small input only** (`MAX_CHARS` 4000): a provision is short; big prompts are refused.
4. **Per-IP rate limit** (`RL` binding), native, no KV cost.
5. **Daily cap** (`CAP_ZILNIC`) on new generations, in KV.
6. **Origin allowlist** (`ORIGINI`) — only the app's own pages are served (add localhost here to test
   online mode locally).
