#!/usr/bin/env bash
# Upload the search index to an existing dated prefix, and nothing else.
#
# `republica.sh` rebuilds the whole dataset and uploads all of it. This does the last part alone,
# for when the index had to be rebuilt but the corpus under the prefix is already published — a
# rebuilt index is the only artefact that changes when indexing is what failed.
#
# The index is in slices (see infra/pagefind.mjs), so this uploads every `pagefind*` directory it
# finds. The slice count is not passed in: what is on disk is what gets published, and the page
# built by construieste_web.py counts the same directories.
#
#   CF_ACCOUNT=… CF_R2_TOKEN_OP=op://vault/item/credential PREFIX=2026-09-08 ./infra/incarca-felii.sh
#
# Environment:
#   CF_ACCOUNT      Cloudflare account id                      (required)
#   CF_R2_TOKEN     the API token value                        (or CF_R2_TOKEN_OP)
#   CF_R2_TOKEN_OP  an op:// reference, read at run time
#   BUCKET          bucket name                                (default: legislativ)
#   PREFIX          the dated prefix to publish under          (default: today)

set -euo pipefail

BUCKET=${BUCKET:-legislativ}
PREFIX=${PREFIX:-$(date +%F)}

cd "$(dirname "$0")/.."

felii=()
for d in pagefind pagefind-[0-9]*; do
  [ -d "$d" ] && felii+=("$d")
done
[ ${#felii[@]} -gt 0 ] || { echo "nu găsesc niciun director pagefind — rulează întâi indexarea" >&2; exit 2; }

echo "de încărcat: ${felii[*]}"
. infra/acreditari-r2.sh

for d in "${felii[@]}"; do
  echo "── $d → r2:$BUCKET/$PREFIX/$d ──"
  # Thousands of small fragments per slice: the cost is requests, not bytes, so transfers are
  # parallel and there is nothing worth chunking.
  rclone copy "$d" "r2:$BUCKET/$PREFIX/$d" \
    --transfers 32 --checkers 32 \
    --no-traverse --retries 5 --low-level-retries 20 --stats 30s --stats-one-line
done

echo
echo "sub r2:$BUCKET/$PREFIX:"
rclone size "r2:$BUCKET/$PREFIX"
