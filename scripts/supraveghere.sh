#!/usr/bin/env bash
# Ține colectarea în mișcare și repornește procesul dacă încetează să mai scrie pagini.
#
# Scris când colectorul se împotmolea după ~150 de pagini. Cauza s-a dovedit a fi tokenul: expiră
# după ~114 cereri, iar serviciul anunță asta cu `HTTP 500`, nu cu un fault, deci clientul reîncerca
# la nesfârșit un token deja aruncat. Asta e reparat în `api.py`, iar supravegherea nu mai e
# mecanismul care duce colectarea la capăt — e plasa de siguranță pentru ce nu s-a întâmplat încă.
#
# Colectorul e reluabil și idempotent: `progres` reține fiecare pagină scrisă, iar o repornire
# continuă de unde a rămas. O repornire nu costă decât munca necomisă din ultimul lot de 20.
#
# Ritmul e măsurat, nu presupus. Cu indexul fts reparat: 2 lucrători/pauză 0,3 → 173 pagini/min,
# 0 × 503; 3/0,2 → 230, 0 × 503; 4/0,1 → 280, dar **51 × 503 în patru minute**. Serviciul cere
# spațiu, iar colector.py o spune deja: o rulare care provoacă 503-uri nu e mai rapidă, fiindcă
# retragerea mănâncă tot câștigul, pe lângă că e nepoliticoasă cu serverul unui minister. 3 și 0,2
# e cel mai rapid punct care nu-l supără.
#
# Rulare:  scripts/supraveghere.sh [--db corpus.db] [--lucratori 3] [--pauza 0.2] [--stagnare 120]
# Oprire:  Ctrl-C, sau `kill` pe PID-ul acestui script — copilul e oprit odată cu el.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="${REPO}/corpus.db"
# Secunde fără nicio pagină nouă înainte de a considera procesul blocat. Trebuie să fie
# comod mai mare decât intervalul dintre două commit-uri ale colectorului (20 de pagini), plus
# căutarea binară a sfârșitului de la pornire: un prag prea strâns omoară un proces care lucrează
# și îi aruncă munca necomisă, iar colectarea nu mai înaintează deloc — exact ce s-a întâmplat
# la 180 s peste un corpus deja existent, unde rescrierea unui act e de câteva ori mai lentă.
# Măsurat: un proces care lucrează comite la fiecare 20 de pagini, adică la 30-40 s. Unul blocat
# nu mai comite niciodată. 120 s separă limpede cele două cazuri, iar fereastra nu mai e cheltuială
# curată: la 300 s fiecare ciclu pierdea 5 minute de așteptare peste 4 minute de lucru real.
STAGNARE=120
INTERVAL=20           # cât de des verificăm progresul
PAUZA_CICLU=5         # răgaz între cicluri, ca să nu batem serviciul la repornire
CICLURI_MAX=600       # plasă de siguranță: ~600 × ~100 pagini acoperă corpusul de câteva ori

# Cititori concurenți. Măsurătorile din colector.py: patru susțin ~5 pagini/s fără 503, șase iau
# 503 imediat. Costul rețelei e 0,81 s pe pagină, deci un singur lucrător e limitat de latență,
# nu de serviciu — concurența e singurul lucru care schimbă durata. Se urcă în trepte, cu 503-urile
# vizibile în jurnal: dacă apar, se coboară. Serverul e al unui minister, nu al nostru.
LUCRATORI=3

# Răgazul dintre pagini, în firul principal. Nu e o politețe gratuită: la 173 pagini/min bugetul
# serial e de 0,347 s pe pagină, din care scrierea ia 0,047 s — restul de 0,3 s e somn curat, adică
# 86% din tavan. Guvernatorul de ritm rămâne, dar mutat unde nu mai e singurul lucru care
# limitează: ținta e ~5 pagini/s, exact nivelul măsurat ca sigur în colector.py.
PAUZA=0.2

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db) DB="$2"; shift 2 ;;
    --stagnare) STAGNARE="$2"; shift 2 ;;
    --lucratori) LUCRATORI="$2"; shift 2 ;;
    --pauza) PAUZA="$2"; shift 2 ;;
    *) echo "argument necunoscut: $1" >&2; exit 2 ;;
  esac
done

pagini() { sqlite3 "$DB" "select count(*) from progres" 2>/dev/null || echo ""; }
acte()   { sqlite3 "$DB" "select count(*) from acte"    2>/dev/null || echo "?"; }
acum()   { date +%H:%M:%S; }

copil=""
opreste() {
  if [[ -n "$copil" ]] && kill -0 "$copil" 2>/dev/null; then
    pkill -TERM -P "$copil" 2>/dev/null
    kill -TERM "$copil" 2>/dev/null
    sleep 2
    pkill -KILL -P "$copil" 2>/dev/null
    kill -KILL "$copil" 2>/dev/null
  fi
  # firele abandonate de `_cu_termen` supraviețuiesc procesului-părinte `uv run`
  pkill -f "\.venv/bin/python3 -u -m scripts\.colector" 2>/dev/null
}
trap 'echo "[$(acum)] oprit de utilizator"; opreste; exit 0' INT TERM

start_pagini=$(pagini); [[ -z "$start_pagini" ]] && start_pagini=0
t_start=$SECONDS
echo "[$(acum)] pornesc supravegherea · $start_pagini pagini în corpus · stagnare=${STAGNARE}s"

for ciclu in $(seq 1 "$CICLURI_MAX"); do
  inainte=$(pagini)
  cd "$REPO" || exit 1
  uv run python -u -m scripts.colector --db "$DB" --lucratori "$LUCRATORI" --pauza "$PAUZA" \
      >> "${REPO}/colector-supravegheat.log" 2>&1 &
  copil=$!

  ultima_schimbare=$SECONDS
  reper=$inainte
  iesit=""
  while true; do
    sleep "$INTERVAL"
    if ! kill -0 "$copil" 2>/dev/null; then
      wait "$copil"; iesit=$?
      break
    fi
    n=$(pagini)
    if [[ -n "$n" && "$n" -gt "$reper" ]]; then
      reper=$n
      ultima_schimbare=$SECONDS
    elif (( SECONDS - ultima_schimbare >= STAGNARE )); then
      echo "[$(acum)] ciclul $ciclu: blocat la $reper pagini după ${STAGNARE}s — repornesc"
      opreste
      iesit="blocat"
      break
    fi
  done

  dupa=$(pagini)
  castig=$(( ${dupa:-0} - ${inainte:-0} ))
  scurs=$(( SECONDS - t_start ))
  total=$(( ${dupa:-0} - start_pagini ))
  echo "[$(acum)] ciclul $ciclu: +$castig pagini (total $dupa · $(acte) acte) · sesiune +$total în $((scurs/60)) min · ieșire=$iesit"

  # Colectorul se întoarce cu 0 doar după ce a parcurs tot ce avea de făcut.
  if [[ "$iesit" == "0" ]]; then
    echo "[$(acum)] colectare terminată: $dupa pagini, $(acte) acte"
    exit 0
  fi
  # Un ciclu care nu aduce nimic și nici nu se blochează înseamnă că nu mai e nimic de luat.
  if [[ "$castig" -eq 0 && "$iesit" != "blocat" ]]; then
    echo "[$(acum)] ciclu fără câștig și fără blocaj — mă opresc, verifică jurnalul"
    exit 1
  fi
  sleep "$PAUZA_CICLU"
done

echo "[$(acum)] am atins limita de $CICLURI_MAX cicluri"
