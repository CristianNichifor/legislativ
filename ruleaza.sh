#!/usr/bin/env bash
# Pornește linterul legislativ local. Un singur pas pentru echipa de cercetare:
#   ./ruleaza.sh
# Se deschide în browser la http://127.0.0.1:8000. Proiectul lipit nu părăsește mașina.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "Lipsește 'uv'. Instalează: https://docs.astral.sh/uv/  (curl -LsSf https://astral.sh/uv/install.sh | sh)"
  exit 1
fi

uv sync --all-groups >/dev/null

if [ ! -f corpus.db ]; then
  cat <<'MSG'
Nu există corpus.db. Ai nevoie de corpusul de legislație. Două opțiuni:
  1. Descarcă-l (dacă a fost publicat ca release):  scripts/ia_corpus.sh
  2. Construiește-l local (câteva ore):             uv run python -m scripts.colector --db corpus.db
                                                    uv run python -m scripts.cdep --db initiative.db
Apoi rulează din nou ./ruleaza.sh
MSG
  exit 1
fi

# Graful se derivă din corpus; îl construim dacă lipsește sau e mai vechi decât corpusul.
if [ ! -f graf.db ] || [ corpus.db -nt graf.db ]; then
  echo "Construiesc graful de amendamente din corpus…"
  uv run python -m scripts.graf --corpus corpus.db --graf graf.db >/dev/null
fi

echo "Pornesc linterul. Închide cu Ctrl-C."
exec uv run python -m scripts.server
