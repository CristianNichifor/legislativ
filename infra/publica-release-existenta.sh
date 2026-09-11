#!/usr/bin/env bash
# Upload an already verified dataset release folder. This skips corpus/index rebuilds.

set -euo pipefail

USAGE="usage: RELEASE_DIR=/path/to/release PREFIX=2026-09-10 CF_ACCOUNT=... CF_R2_TOKEN_OP=op://... $0 [--latest]"
LATEST=0
case "${1:-}" in
  "") ;;
  --latest) LATEST=1; shift ;;
  *) echo "$USAGE" >&2; exit 2 ;;
esac
[ "$#" -eq 0 ] || { echo "$USAGE" >&2; exit 2; }

RELEASE_DIR=${RELEASE_DIR:?$USAGE}
PREFIX=${PREFIX:?$USAGE}
BUCKET=${BUCKET:-legislativ}
ORIGIN=${ORIGIN:-https://date.cristian-nichifor.com}

echo "verifying local release: $RELEASE_DIR"
uv run python -m scripts.dataset_release verify "$RELEASE_DIR"
echo "loading R2 credentials"
. infra/acreditari-r2.sh

r2() { rclone "$@" --no-traverse --retries 5 --low-level-retries 20 --stats 30s --stats-one-line --stats-log-level NOTICE; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
echo "checking target prefix: r2:$BUCKET/$PREFIX"
r2 lsf "r2:$BUCKET/$PREFIX" > "$tmp/remote-prefix.txt"
[ ! -s "$tmp/remote-prefix.txt" ] || { echo "prefix already exists: $PREFIX" >&2; exit 2; }

for payload in "$RELEASE_DIR"/*; do
  [ "${payload##*/}" = dataset-release.json ] && continue
  echo "uploading ${payload##*/}"
  r2 copyto "$payload" "r2:$BUCKET/$PREFIX/${payload##*/}" --immutable --s3-chunk-size 100M
done
echo "checking uploaded payloads"
r2 check "$RELEASE_DIR" "r2:$BUCKET/$PREFIX" --one-way --download --exclude dataset-release.json
echo "uploading dataset-release.json"
r2 copyto "$RELEASE_DIR/dataset-release.json" "r2:$BUCKET/$PREFIX/dataset-release.json" --immutable
echo "checking dataset-release.json"
r2 check "$RELEASE_DIR" "r2:$BUCKET/$PREFIX" --one-way --download --include dataset-release.json
echo "building channel"
uv run python -m scripts.dataset_release channel "$RELEASE_DIR" \
  --manifest-url "$ORIGIN/$PREFIX/dataset-release.json" \
  --output "$tmp/channel.json"
if [ "$LATEST" -eq 1 ]; then
  echo "promoting channel.json"
  r2 copyto "$tmp/channel.json" "r2:$BUCKET/channel.json"
fi
echo "published $ORIGIN/$PREFIX/dataset-release.json"
[ "$LATEST" -eq 0 ] || echo "promoted $ORIGIN/channel.json"
