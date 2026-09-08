#!/usr/bin/env bash
# Republish the dataset: build the copies the browser reads, build the two search indexes, and
# upload the lot under a new dated prefix.
#
# The prefix is dated because the reader caches hard — shards are treated as immutable, and a
# republish that overwrote them in place would serve a mix of old and new to anyone mid-session.
# A new prefix is a new dataset; the old one keeps working until nothing points at it.
#
# The last line of output is the change to make in `.github/workflows/pages.yml`. Nothing here
# touches the live site: the site follows `--depozit`, and that is a one-line commit.
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

set -euo pipefail

LUCRU=${LUCRU:-$HOME/.local/share/legislativ}
CORPUS=${CORPUS:-corpus.db}
BUCKET=${BUCKET:-legislativ}
PREFIX=${PREFIX:-$(date +%F)}
FELII=${FELII:-8}
IDX="$LUCRU/idx"

[ -f "$CORPUS" ] || { echo "nu găsesc $CORPUS" >&2; exit 2; }
mkdir -p "$LUCRU"

echo "── 1/5 copiile publicate ────────────────────────────────────────"
# The corpus loses its build-time bulk; the companions only need the WAL folded in and a rebuild,
# because `immutable=1` refuses a database with a `-wal` sidecar.
uv run python -m scripts.publica --sursa "$CORPUS" --tinta "$LUCRU/publicat.db" --fel corpus
for pereche in "graf.db:graf-publicat.db" "initiative.db:initiative-publicat.db"; do
  sursa=${pereche%%:*}; tinta=${pereche##*:}
  [ -f "$sursa" ] && uv run python -m scripts.publica --sursa "$sursa" --tinta "$LUCRU/$tinta" --fel auxiliar
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

echo "── 4/5 acreditări ───────────────────────────────────────────────"
. infra/acreditari-r2.sh

echo "── 5/5 încărcare în r2:$BUCKET/$PREFIX ──────────────────────────"
r2() { rclone "$@" --no-traverse --retries 5 --low-level-retries 20 --stats 30s --stats-one-line; }
r2 copyto "$LUCRU/publicat.db"            "r2:$BUCKET/$PREFIX/corpus.db"     --s3-chunk-size 100M --s3-upload-concurrency 4
r2 copyto "$LUCRU/graf-publicat.db"       "r2:$BUCKET/$PREFIX/graf.db"       --s3-chunk-size 100M
r2 copyto "$LUCRU/initiative-publicat.db" "r2:$BUCKET/$PREFIX/initiative.db" --s3-chunk-size 100M
r2 copyto "$LUCRU/manifest.json"          "r2:$BUCKET/$PREFIX/manifest.json"
r2 copyto "$IDX/index.json"               "r2:$BUCKET/$PREFIX/index.json"
r2 copyto "$IDX/termeni.json"             "r2:$BUCKET/$PREFIX/termeni.json"
r2 copy   "$IDX/idx"                      "r2:$BUCKET/$PREFIX/idx"           --transfers 32 --checkers 32
r2 copy   "$IDX/idx-titlu"                "r2:$BUCKET/$PREFIX/idx-titlu"     --transfers 32 --checkers 32
for d in pagefind pagefind-[0-9]*; do
  [ -d "$d" ] && r2 copy "$d" "r2:$BUCKET/$PREFIX/$d" --transfers 32 --checkers 32
done

echo
echo "încărcat. Ultimul pas, un singur rând în .github/workflows/pages.yml:"
echo "  --depozit https://date.cnwebify.dev/$PREFIX"
