#!/usr/bin/env bash
# Deploy the plain-language rewrite service to Cloudflare (free tier).
#
# Steps 1–2 are automated; step 3 (the Mistral secret) is interactive and optional — until it is set
# the Worker returns a labelled stub and costs nothing. Run from anywhere in the repo.
#
#   CLOUDFLARE_API_TOKEN=<write-scoped token>  ./infra/deploy.sh
#   # or, if you use `wrangler login` for deploy, the token is only needed for the AI Gateway step.
set -euo pipefail

ACCOUNT="432316a05c0d6000c6e196fe32e47dd7"   # CN Webify
GATEWAY="legislativ"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/worker" && pwd)"
cd "$here"

echo "==> 1/3  AI Gateway '$GATEWAY' (free caching + analytics + rate limit)"
if [ -n "${CLOUDFLARE_API_TOKEN:-}" ]; then
  code=$(curl -sS -o /tmp/gw.json -w '%{http_code}' -X POST \
    "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT/ai-gateway/gateways" \
    -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json" \
    -d '{"id":"'"$GATEWAY"'","cache_ttl":86400,"cache_invalidate_on_update":false,"collect_logs":true,"rate_limiting_interval":60,"rate_limiting_limit":100,"rate_limiting_technique":"fixed"}') || true
  if [ "$code" = "200" ]; then echo "    created."
  elif grep -q "already exists\|duplicate" /tmp/gw.json 2>/dev/null; then echo "    already exists — ok."
  else echo "    skipped (HTTP $code): $(cat /tmp/gw.json 2>/dev/null)"; echo "    the Worker falls back to api.mistral.ai, so deploy continues."; fi
else
  echo "    CLOUDFLARE_API_TOKEN not set — skipping (create it in the dashboard, or set the token)."
  echo "    The Worker falls back to Mistral directly, so this is optional."
fi

echo "==> 2/3  wrangler deploy"
npx wrangler deploy

echo "==> 3/3  Mistral key (optional; stub until set)"
echo "    Run when ready:  npx wrangler secret put MISTRAL_API_KEY"
echo
echo "Done. Endpoint: https://legislativ-rescrieri.cn-webify.workers.dev/rescrie"
echo "The app already targets it — pick 'online (prin API)' in the AI settings."
