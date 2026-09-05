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
- CORS is open (`*`) because it serves public law; the app's CSP already allows `https://*.workers.dev`.

## Cost

KV free tier covers it: reads are the common case (cache hits), writes happen once per new provision
viewed in online mode. Mistral is called only on a miss. At thousands of queries/month this is free
to a few euros — the whole point of caching the rewrite rather than regenerating per view.
