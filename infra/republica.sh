#!/usr/bin/env bash
# Republish the dataset: build the copies the browser reads, build the two search indexes, and
# upload the lot under a new dated prefix.
#
# The prefix is dated because the reader caches hard — shards are treated as immutable, and a
# republish that overwrote them in place would serve a mix of old and new to anyone mid-session.
# A new prefix is a new dataset; the old one keeps working until nothing points at it.
#
# The last line of output is the change to make in `.github/workflows/pages.yml`. Nothing here
# edits the live site configuration: the site follows `--depozit`, a one-line commit.
# Optional --latest advances /channel.json only after remote release verification.
#
#   CF_ACCOUNT=… CF_R2_TOKEN_OP=op://vault/item/credential ./infra/republica.sh
#
# Environment:
#   CF_ACCOUNT      Cloudflare account id                       (required)
#   CF_R2_TOKEN     API token value                             (or CF_R2_TOKEN_OP)
#   CF_R2_TOKEN_OP  op:// reference to read it at run time
#   LUCRU           working directory for the built copies      (default: ~/.local/share/legislativ)
#   CORPUS          the collected corpus                        (default: ./corpus.db)
#   BUCKET          R2 bucket                                   (default: legislativ)
#   PREFIX          dated prefix                                (default: today)
#   FELII           slices the search index is built in         (default: 8)
#   EU_PUBLIC_DB    explicitly curated standalone public EU DB (optional, never auto-discovered)
#   PUBLIC_REPORTS_DIR curated allowlisted reports, e.g. ue_acoperire.json (optional)

set -euo pipefail

LATEST=0
case "${1:-}" in
  "") ;;
  --latest) LATEST=1; shift ;;
  *) echo "usage: $0 [--latest]" >&2; exit 2 ;;
esac
[ "$#" -eq 0 ] || { echo "usage: $0 [--latest]" >&2; exit 2; }

LUCRU=${LUCRU:-$HOME/.local/share/legislativ}
CORPUS=${CORPUS:-corpus.db}
BUCKET=${BUCKET:-legislativ}
PREFIX=${PREFIX:-$(date +%F)}
FELII=${FELII:-8}
uv run python -c 'import sys; from scripts.dataset_release import validate_release_id; validate_release_id(sys.argv[1])' "$PREFIX"

[ -f "$CORPUS" ] || { echo "nu găsesc $CORPUS" >&2; exit 2; }
mkdir -p "$LUCRU"
# Every run builds fresh copies; missing companions must never reuse an older release.
LUCRU=$(mktemp -d "$LUCRU/release-$PREFIX.XXXXXX")
IDX="$LUCRU/idx"

echo "── 1/5 copiile publicate ────────────────────────────────────────"
# The corpus loses its build-time bulk; the companions only need the WAL folded in and a rebuild,
# because `immutable=1` refuses a database with a `-wal` sidecar.
uv run python -m scripts.publica --sursa "$CORPUS" --tinta "$LUCRU/publicat.db" --fel corpus
for pereche in "graf.db:graf-publicat.db" "initiative.db:initiative-publicat.db"; do
  sursa=${pereche%%:*}; tinta=${pereche##*:}
  if [ -f "$sursa" ]; then
    fel=auxiliar
    [ "$sursa" != initiative.db ] || fel=initiative-public
    uv run python -m scripts.publica --sursa "$sursa" --tinta "$LUCRU/$tinta" --fel "$fel"
  fi
done

echo "── 2/5 indexul vechi (felii) ────────────────────────────────────"
# Ranked search over the mounted corpus took 291 s — bm25 wants a document length per match. The
# inverted index answers the same query in two fetches; the corpus supplies titles and snippets.
rm -rf "$IDX"; mkdir -p "$IDX"
uv run python - "$LUCRU" <<'PY'
import sys
from scripts.shard import construieste_index, construieste_index_titluri

lucru = sys.argv[1]
jurnal = lambda m: print(m, flush=True)
construieste_index(f"{lucru}/publicat.db", f"{lucru}/idx",
                   graf_db=f"{lucru}/graf-publicat.db", log=jurnal)
construieste_index_titluri(f"{lucru}/publicat.db", f"{lucru}/idx", log=jurnal)
PY

echo "── 3/5 indexul de căutare (Pagefind) ────────────────────────────"
# Search no longer reads the corpus: the excerpt lives in the index and the client fetches
# per-result fragments in parallel. A page of 25 went from 46,6 s to 1,24 s.
if command -v node >/dev/null && [ -f infra/pagefind.mjs ]; then
  uv run python -m scripts.export_cautare --db "$LUCRU/publicat.db" --tinta "$LUCRU/acte.jsonl"
  # In slices, one process each: Pagefind keeps every record in memory until it writes, and this
  # corpus costs ~345 KB of memory per act — all 203.353 at once wants far more than a workstation
  # has. A machine with less does not stop, it swaps, and it took this one down mid-run. Eight
  # slices peak around 9 GB each, and every process gives its memory back when it exits.
  rm -rf pagefind pagefind-[0-9]*
  for f in $(seq 0 $((FELII - 1))); do
    echo "  felia $((f + 1))/$FELII"
    node infra/pagefind.mjs "$LUCRU/acte.jsonl" "pagefind-$f" "$f" "$FELII"
  done
  rm -f "$LUCRU/acte.jsonl"
else
  echo "  node sau infra/pagefind.mjs lipsesc — sar peste index; căutarea va cădea pe motor" >&2
fi

STAGE="$LUCRU/payload"
mkdir "$STAGE"
for name in graf initiative; do
  [ ! -f "$LUCRU/$name-publicat.db" ] || cp "$LUCRU/$name-publicat.db" "$STAGE/$name.db"
done
cp "$LUCRU/manifest.json" "$STAGE/manifest.json"
cp "$IDX/index.json" "$IDX/termeni.json" "$STAGE/"
release_args=(build "$STAGE" --release "$PREFIX" --published-corpus "$LUCRU/publicat.db")
[ -z "${EU_PUBLIC_DB:-}" ] || release_args+=(--published-eu "$EU_PUBLIC_DB")
[ -z "${PUBLIC_REPORTS_DIR:-}" ] || release_args+=(--public-reports "$PUBLIC_REPORTS_DIR")
uv run python -m scripts.dataset_release "${release_args[@]}"

echo "── 4/5 acreditări ───────────────────────────────────────────────"
. infra/acreditari-r2.sh

echo "── 5/5 încărcare în r2:$BUCKET/$PREFIX ──────────────────────────"
# `--stats-log-level NOTICE` or the stats flags print nothing: rclone logs them at INFO, and the
# default level is NOTICE. An upload of several GB should not look like a hung shell.
r2() { rclone "$@" --no-traverse --retries 5 --low-level-retries 20 --stats 30s --stats-one-line --stats-log-level NOTICE; }
# Fail closed on listing errors and refuse any occupied immutable prefix.
r2 lsf "r2:$BUCKET/$PREFIX" > "$LUCRU/remote-prefix.txt"
[ ! -s "$LUCRU/remote-prefix.txt" ] || { echo "prefix already exists: $PREFIX" >&2; exit 2; }
for payload in "$STAGE"/*; do
  [ "${payload##*/}" = dataset-release.json ] && continue
  r2 copyto "$payload" "r2:$BUCKET/$PREFIX/${payload##*/}" --immutable --s3-chunk-size 100M
done
r2 copy   "$IDX/idx"                      "r2:$BUCKET/$PREFIX/idx"           --transfers 32 --checkers 32
r2 copy   "$IDX/idx-titlu"                "r2:$BUCKET/$PREFIX/idx-titlu"     --transfers 32 --checkers 32
for d in pagefind pagefind-[0-9]*; do
  [ -d "$d" ] && r2 copy "$d" "r2:$BUCKET/$PREFIX/$d" --transfers 32 --checkers 32
done

# Download verification compares actual bytes, including multipart S3 objects without MD5.
r2 check "$STAGE" "r2:$BUCKET/$PREFIX" --one-way --download --exclude dataset-release.json
uv run python -m scripts.dataset_release verify "$STAGE"
r2 copyto "$STAGE/dataset-release.json" "r2:$BUCKET/$PREFIX/dataset-release.json" --immutable
r2 check "$STAGE" "r2:$BUCKET/$PREFIX" --one-way --download --include dataset-release.json
uv run python -m scripts.dataset_release channel "$STAGE" \
  --manifest-url "https://date.cristian-nichifor.com/$PREFIX/dataset-release.json" \
  --output "$LUCRU/channel.json"
if [ "$LATEST" -eq 1 ]; then
  r2 copyto "$LUCRU/channel.json" "r2:$BUCKET/channel.json"
fi
echo "channel proposal: $LUCRU/channel.json (publish only with explicit --latest)"

echo
echo "încărcat. Ultimul pas, un singur rând în .github/workflows/pages.yml:"
echo "  --depozit https://date.cristian-nichifor.com/$PREFIX"
