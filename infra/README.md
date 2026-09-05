# infra — the plain-language rewrite service

The side-by-side "Limbaj clar" feature restates a provision of **public** law in plain language
(Danish style — see `docs/STIL_DANEZ.md`). It is a Cloudflare Worker backed by a KV cache, so each
provision is rewritten **once, ever**, then served from cache to everyone. The app's own draft never
touches it — only public law text is sent.

## What's already provisioned

- **KV namespace** `legislativ-rescrieri` (`id 8a788c5315bf4c61a72c23d3ef5f46d9`) — the cache.
- The Worker code and config are in `infra/worker/`. (R2 is the plan for the *bulk data shards*
  later; it needs a one-time enable in the Cloudflare dashboard. The rewrite cache uses KV, which
  needs no enabling.)

## Deploy (one time)

```
cd infra/worker
npx wrangler deploy                     # publishes to https://legislativ-rescrieri.<you>.workers.dev
npx wrangler secret put MISTRAL_API_KEY # paste an EU Mistral key; until then the Worker returns a
                                        # clearly-labelled stub and caches nothing
```

Then point the app at it: set `RESCRIERE_ENDPOINT` in `app/index.html` to
`https://legislativ-rescrieri.<you>.workers.dev/rescrie` and rebuild (`construieste_web`). Empty =
the feature stays hidden, so the site works with or without the Worker.

## Contract

- `POST /rescrie {act, loc, text}` → `{rescriere, cached, model, stil}`; generates on a cache miss,
  stores the result, returns it. Real generations are cached; the stub is not (so it's replaced the
  moment a key is added).
- `GET /rescrie?act=&loc=` → cached rewrite or `404 negenerat`.
- The app's CSP already allows `https://*.workers.dev`.

## Protecting the AI bill against bots

A public rewrite endpoint that calls a paid model is a bill waiting to be abused. The Worker layers
cheap, mostly-free defences (all configured in `wrangler.toml`):

1. **Cache-first** — a repeat request is a free KV read; the model is never called twice for the same
   provision.
2. **Small input only** (`MAX_CHARS`, 4000) — a provision is short, so a request carrying a big prompt
   is refused. The endpoint cannot be used as a free general-purpose LLM.
3. **Per-IP rate limit** via the native Workers rate-limiting binding (`RL`) — no KV cost.
4. **Daily cap** (`CAP_ZILNIC`) on new generations, in KV — a hard ceiling on spend.
5. **Origin allowlist** (`ORIGINI`) — only the app's own pages are served.
6. **Account spend cap** — set a monthly limit on the Mistral account. This is the backstop that
   makes the ceiling absolute regardless of anything above.

## Cheaper / better inference

- **AI Gateway** (Cloudflare, free): point `MISTRAL_URL` at a gateway URL to get response caching,
  rate limiting and cost analytics in front of Mistral, with no code change.
- **Batch APIs** (~50% cheaper) for **bulk pre-generation** — Mistral's Batch API, or Cloudflare
  **Workers AI Batch**. Use these to pre-warm the popular codes (Fiscal, Civil, Penal, Labour) into
  KV ahead of time; on-demand single rewrites stay on the cache-first path here.

## Cost

Cache-first + once-per-provision means the model is paid at most once per provision, ever. KV free
tier (100k reads/day, 1k writes/day, 1 GB) covers it — reads dominate; a write happens only on a new
generation. Mistral Small is ~$0.0003 per rewrite; the whole corpus rewritten over time is a few
dollars, one-time. Day-to-day: effectively free.
