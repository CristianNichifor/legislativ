# infra — the plain-language rewrite service (Cloudflare, free tier)

The side-by-side "Limbaj clar" feature restates a provision of **public** law in plain language
(Danish style — see `docs/STIL_DANEZ.md`). It is a Cloudflare Worker backed by a KV cache, so each
provision is rewritten **once, ever**, then served from cache to everyone. The app's own draft never
touches it — only public law text is sent (and online mode confirms before sending even that).

Everything here is designed to sit on Cloudflare's **free tier**. The only paid piece is Mistral, and
cache-first + a daily cap keep that to a few dollars, one-time.

## What Cloudflare pieces we use

| Piece | Free? | Role | State |
|---|---|---|---|
| **Workers** | 100k req/day free | the rewrite service (`worker/src/index.js`) | code here, deploy below |
| **Workers KV** `legislativ-rescrieri` | 100k reads / 1k writes / 1 GB free | the rewrite cache | namespace exists (`8a788c53…`) |
| **Rate-limiting binding** (`RL`) | free | per-IP limit, no KV cost | in `wrangler.toml` |
| **AI Gateway** `legislativ` | free | caching + analytics + a safety rate limit in front of Mistral | create in step 1 |
| **R2** | — | *planned* for the bulk data shards | not enabled (needs a dashboard toggle) |

Account: **CN Webify** `432316a05c0d6000c6e196fe32e47dd7`. Deployed Worker URL (fixed, already the
app's default): `https://legislativ-rescrieri.cn-webify.workers.dev/rescrie`.

## Deploy (three commands, one time)

You need `wrangler` authenticated to the account (`npx wrangler login`, or a write-scoped
`CLOUDFLARE_API_TOKEN`), then:

```sh
cd infra/worker

# 1. (recommended, free) create the AI Gateway "legislativ" — caching + analytics + rate limit.
#    The Worker points MISTRAL_URL at it but falls back to api.mistral.ai if it's missing, so this
#    step is optional; do it to light up the free caching and the analytics dashboard.
curl -sS -X POST \
  "https://api.cloudflare.com/client/v4/accounts/432316a05c0d6000c6e196fe32e47dd7/ai-gateway/gateways" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"id":"legislativ","cache_ttl":86400,"cache_invalidate_on_update":false,"collect_logs":true,"rate_limiting_interval":60,"rate_limiting_limit":100,"rate_limiting_technique":"fixed"}'

# 2. deploy the Worker (wrangler.toml carries the KV binding, the rate limit and the vars).
npx wrangler deploy

# 3. add the Mistral key. Until it is set the Worker returns a clearly-labelled stub and caches
#    nothing, so the whole pipeline works end to end before any spend.
npx wrangler secret put MISTRAL_API_KEY   # paste an EU Mistral key
```

`infra/deploy.sh` runs steps 1–2 for you (step 3 is interactive). The app already targets the URL
above (`RESCRIERE_ENDPOINT` in `app/index.html`), so **nothing needs changing in the app** — pick
"online (prin API)" in the AI settings and it works. Users can still override the endpoint in the UI.

## Contract

- `POST /rescrie {act, loc, text, stil?, model?}` → `{rescriere, cached, model, stil}`; generates on
  a cache miss, stores it, returns it.
- `GET /rescrie?act=&loc=&stil=` → cached rewrite or `404 negenerat`.
- `stil` picks the drafting norm: `nou` (plain-language / Danish, default) or `actual` (current legal
  register, Legea 24/2000). It also namespaces the cache so the two norms never collide.
- `model` is honored only from an allowlist (`mistral-small-latest`, `mistral-large-latest`); anything
  else uses the `MISTRAL_MODEL` default. This is what the app's online **model** picker sends.
- `POST {text, stil?, model?}` **without `act`** is a general rewrite of the caller's own text — never
  cached (no public key to cache under), still rate-limited / size-capped / daily-capped. The app uses
  this for the Redactează block text and the draft "Limbaj clar" (and confirms before sending).
- The app's CSP already allows `https://*.workers.dev`.

## Keeping the AI bill near zero

1. **Cache-first (KV):** a repeat provision is a free KV read; the model is never called twice.
2. **AI Gateway cache:** a second, free cache by request — identical rewrites are served without
   touching Mistral, and every call is logged for cost analytics.
3. **Small input only** (`MAX_CHARS` 4000): a provision is short; big prompts are refused.
4. **Per-IP rate limit** (`RL` binding) + **gateway rate limit** (100/min): native, no KV cost.
5. **Daily cap** (`CAP_ZILNIC`) on new generations, in KV — a hard ceiling on spend.
6. **Origin allowlist** (`ORIGINI`) — only the app's own pages are served.
7. **Account spend cap** — set a monthly limit on the Mistral account. The absolute backstop.

## Cost

Cache-first + once-per-provision means the model is paid at most once per provision, ever. The KV
free tier (100k reads/day, 1k writes/day, 1 GB) covers it — reads dominate; a write happens only on a
new generation. Mistral Small is ~$0.0003 per rewrite; the whole corpus rewritten over time is a few
dollars, one-time. Day-to-day: effectively free. Cheaper still for bulk pre-generation: Mistral's
Batch API or Workers AI Batch (~half price) to pre-warm the popular codes into KV.
