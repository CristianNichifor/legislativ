#!/usr/bin/env bash
# Descarcă corpusul publicat (release) și îl dezarhivează lângă cod.
# Folosire: scripts/ia_corpus.sh <url-release-base>
#   ex: scripts/ia_corpus.sh https://github.com/CristianNichifor/legislativ/releases/download/corpus-2026-09
set -euo pipefail
cd "$(dirname "$0")/.."
BAZA="${1:?dă adresa de bază a release-ului}"
for f in corpus.db initiative.db graf.db; do
  echo "descarc $f…"
  curl -fSL "$BAZA/$f.gz" -o "$f.gz"
  gunzip -f "$f.gz"
done
echo "gata. rulează ./ruleaza.sh"
