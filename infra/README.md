# infra — the plain-language rewrite service (Cloudflare, free)

The side-by-side "Limbaj clar" feature restates a provision of **public** law in plain language
(Danish style — see `docs/STIL_DANEZ.md`). It is a Cloudflare Worker that runs the rewrite on
**Workers AI** (Cloudflare's own hosted models — no external account, no key) and caches each result
in KV, so a provision is rewritten **once, ever**, then served from cache to everyone. The app's own
draft never touches it — only public law text is sent (and online mode confirms before sending).

Everything is on Cloudflare's **free tier**. Workers AI is billed in Neurons with a free daily
allocation, so day-to-day this costs **nothing**.

## What Cloudflare pieces we use

| Piece | Free? | Role | State |
|---|---|---|---|
| **Workers** | 100k req/day free | the rewrite service (`worker/src/index.js`) | **deployed** |
| **Workers AI** (`env.AI`) | free daily Neuron allocation | runs the rewrite (Llama 3.3 70B) | live |
| **Workers KV** `legislativ-rescrieri` | 100k reads / 1k writes / 1 GB free | the rewrite cache | live (`8a788c53…`) |
| **Rate-limiting binding** (`RL`) | free | per-IP limit, no KV cost | live |
| **AI Gateway** `law-legislation-project-gateway` | free | caching + analytics in front of Workers AI | live |
| **R2** | — | *planned* for the bulk data shards | not enabled |

Account: **CN Webify** `432316a05c0d6000c6e196fe32e47dd7`. Endpoint (already the app's default):
`https://legislativ-rescrieri.cn-webify.workers.dev/rescrie`.

## Deploy

Already deployed and working. To redeploy after a change:

```sh
cd infra/worker && npx wrangler deploy      # needs `npx wrangler login` once
```

No secret to set — Workers AI needs no key. The app already targets the endpoint above, so picking
"online (prin API)" in the AI settings just works (users can still override the endpoint in the UI).

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
- The app's CSP already allows `https://*.workers.dev`.

## Keeping it free and abuse-proof

1. **Cache-first (KV):** a repeat provision is a free KV read; the model is never called twice.
2. **AI Gateway cache** (once created): a second, free cache by request + cost analytics.
3. **Small input only** (`MAX_CHARS` 4000): a provision is short; big prompts are refused.
4. **Per-IP rate limit** (`RL` binding), native, no KV cost.
5. **Daily cap** (`CAP_ZILNIC`) on new generations, in KV.
6. **Origin allowlist** (`ORIGINI`) — only the app's own pages are served (add localhost here to test
   online mode locally).
