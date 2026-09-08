#!/usr/bin/env bash
# Upload the published corpus to R2, so a browser can read it without downloading it.
#
# The object is written under a dated prefix. That is deliberate: the reader caches chunks
# aggressively, and a dated key means a republish points at a new prefix instead of fighting
# stale caches. `--depozit` in construieste_web.py must name the same prefix.
#
# Credentials are never stored. R2's S3 credentials are derived from a Cloudflare API token:
# the Access Key ID is the token's id, the Secret Access Key is the SHA-256 of the token value
# (https://developers.cloudflare.com/r2/api/tokens/). Give the token **Object Read & Write**
# scoped to this one bucket; it will not be able to ListBuckets, which is correct and expected.
#
#   CF_R2_TOKEN=…                     ./infra/incarca-r2.sh
#   CF_R2_TOKEN_OP=op://vault/item/f  ./infra/incarca-r2.sh    # read from 1Password at run time
#
# Environment:
#   CF_ACCOUNT      Cloudflare account id                      (required)
#   CF_R2_TOKEN     the API token value                        (or CF_R2_TOKEN_OP)
#   CF_R2_TOKEN_OP  an op:// reference to read it from         (needs the 1Password CLI)
#   BUCKET          bucket name                                (default: legislativ)
#   FISIER          the file to upload                         (default: publicat.db)
#   PREFIX          dated prefix for the object                (default: today)

set -euo pipefail

BUCKET=${BUCKET:-legislativ}
FISIER=${FISIER:-publicat.db}
PREFIX=${PREFIX:-$(date +%F)}
CHEIE="$PREFIX/corpus.db"

[ -n "${CF_ACCOUNT:-}" ] || { echo "lipsește CF_ACCOUNT" >&2; exit 2; }
[ -f "$FISIER" ] || { echo "nu găsesc $FISIER — rulează întâi scripts/publica.py" >&2; exit 2; }

if [ -z "${CF_R2_TOKEN:-}" ]; then
  [ -n "${CF_R2_TOKEN_OP:-}" ] || { echo "lipsește CF_R2_TOKEN sau CF_R2_TOKEN_OP" >&2; exit 2; }
  command -v op >/dev/null || { echo "CF_R2_TOKEN_OP cere CLI-ul 1Password (op)" >&2; exit 2; }
  CF_R2_TOKEN=$(op read "$CF_R2_TOKEN_OP")
fi

AKID=$(curl -fsS -H "Authorization: Bearer $CF_R2_TOKEN" \
  https://api.cloudflare.com/client/v4/user/tokens/verify |
  python3 -c "import json,sys; print(json.load(sys.stdin)['result']['id'])") ||
  { echo "tokenul nu se verifică la Cloudflare" >&2; exit 1; }

export RCLONE_CONFIG_R2_TYPE=s3
export RCLONE_CONFIG_R2_PROVIDER=Cloudflare
export RCLONE_CONFIG_R2_REGION=auto
export RCLONE_CONFIG_R2_ENDPOINT="https://$CF_ACCOUNT.r2.cloudflarestorage.com"
export RCLONE_CONFIG_R2_ACCESS_KEY_ID="$AKID"
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=$(printf %s "$CF_R2_TOKEN" | sha256sum | cut -d' ' -f1)
# The token is scoped to one bucket, so rclone must not try to check for the bucket's existence.
export RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true
unset CF_R2_TOKEN

echo "încarc $FISIER → r2:$BUCKET/$CHEIE"
# 100 MiB parts: ~67 for a 6,7 GB file, well inside the 10.000-part ceiling and the 1M free
# class A operations per month. --no-traverse skips listing a bucket we are only writing to.
rclone copyto "$FISIER" "r2:$BUCKET/$CHEIE" \
  --s3-chunk-size 100M --s3-upload-concurrency 4 \
  --no-traverse --stats 30s --stats-one-line --progress

echo
echo "în bucket:"
rclone ls "r2:$BUCKET"
echo
echo "acum construiește cu:  --depozit https://<domeniu>/$PREFIX"
