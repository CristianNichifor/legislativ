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
#   FISIER          the file or directory to upload            (default: publicat.db)
#   PREFIX          dated prefix for the object                (default: today)
#   CHEIE           key under the bucket                       (default: $PREFIX/corpus.db)

set -euo pipefail

BUCKET=${BUCKET:-legislativ}
FISIER=${FISIER:-publicat.db}
PREFIX=${PREFIX:-$(date +%F)}
CHEIE=${CHEIE:-$PREFIX/corpus.db}

[ -n "${CF_ACCOUNT:-}" ] || { echo "lipsește CF_ACCOUNT" >&2; exit 2; }
[ -e "$FISIER" ] || { echo "nu găsesc $FISIER — rulează întâi scripts/publica.py" >&2; exit 2; }

. "$(dirname "$0")/acreditari-r2.sh"

echo "încarc $FISIER → r2:$BUCKET/$CHEIE"
if [ -d "$FISIER" ]; then
  # A directory is a search index slice: thousands of small fragments, where the cost is the number
  # of requests rather than the number of bytes. Parallel transfers, and no chunking to speak of.
  rclone copy "$FISIER" "r2:$BUCKET/$CHEIE" \
    --transfers 32 --checkers 32 \
    --no-traverse --stats 30s --stats-one-line --progress
else
  # 100 MiB parts: ~67 for a 6,7 GB file, well inside the 10.000-part ceiling and the 1M free
  # class A operations per month. --no-traverse skips listing a bucket we are only writing to.
  rclone copyto "$FISIER" "r2:$BUCKET/$CHEIE" \
    --s3-chunk-size 100M --s3-upload-concurrency 4 \
    --no-traverse --stats 30s --stats-one-line --progress
fi

echo
echo "sub r2:$BUCKET/$PREFIX:"
# Scoped to the prefix and summarised: a published index is thousands of fragments, and listing
# them one by one says less than their count and their weight.
rclone size "r2:$BUCKET/$PREFIX"
echo
echo "acum construiește cu:  --depozit https://<domeniu>/$PREFIX"
