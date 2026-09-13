#!/usr/bin/env bash
# Șterge prefixele datate vechi din R2, fără să atingă vreunul din care citește cineva.
#
# `incarca-r2.sh` scrie sub un prefix datat nou la fiecare republicare și nimic nu șterge
# prefixele vechi. La 6,7 GB corpusul plus feliile de index, fiecare republicare adaugă ~10 GB
# peste cele 10 GB gratuite. Curățenia trebuie făcută — dar nu de o regulă de lifecycle.
#
# De ce nu o regulă de lifecycle: regulile R2 expiră după *vârstă*. Ele nu pot deosebi prefixul
# pe care site-ul îl servește chiar acum de unul abandonat. Site-ul este construit cu un prefix
# fixat în `.github/workflows/pages.yml` (`--depozit`), iar canalul de date trimite cititorii
# către prefixul din `channel.json`; cele două pot fi diferite, și au fost. O regulă „șterge ce
# e mai vechi de N zile" ar fi ștears exact prefixul pe care se sprijină căutarea, lăsând
# canalul intact — o cădere care arată sănătoasă din afară.
#
# Scriptul citește ambele referințe și refuză să ruleze dacă nu le poate determina. Fără
# CONFIRMA=da nu șterge nimic; doar spune ce ar șterge.
#
#   ./infra/curata-prefixe.sh                    # doar raportează
#   CONFIRMA=da ./infra/curata-prefixe.sh        # șterge candidații
#
# Mediu:
#   CF_ACCOUNT      id-ul contului Cloudflare                      (obligatoriu)
#   CF_R2_TOKEN     valoarea tokenului API                         (sau CF_R2_TOKEN_OP)
#   CF_R2_TOKEN_OP  o referință op:// din care să fie citit
#   BUCKET          numele bucketului                              (implicit: legislativ)
#   DOMENIU         domeniul public al bucketului                  (implicit: date.cristian-nichifor.com)
#   PASTREAZA       câte prefixe recente se păstrează oricum       (implicit: 2)
#   CONFIRMA        „da" ca să se șteargă cu adevărat              (implicit: nu)

set -euo pipefail

BUCKET=${BUCKET:-legislativ}
DOMENIU=${DOMENIU:-date.cristian-nichifor.com}
PASTREAZA=${PASTREAZA:-2}
CONFIRMA=${CONFIRMA:-nu}
FLUX_PAGES=${FLUX_PAGES:-.github/workflows/pages.yml}

[ -n "${CF_ACCOUNT:-}" ] || { echo "lipsește CF_ACCOUNT" >&2; exit 2; }

. "$(dirname "$0")/acreditari-r2.sh"

# R2 răspunde 403 la cereri fără un User-Agent de browser, așa că cererile de mai jos poartă unul.
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"

# 1. Prefixul din care citește canalul de date.
canal=$(curl -fsS -A "$UA" "https://$DOMENIU/channel.json" || true)
[ -n "$canal" ] || { echo "nu pot citi https://$DOMENIU/channel.json — nu șterg nimic" >&2; exit 3; }
prefix_canal=$(printf '%s' "$canal" | grep -oE '"manifest"[^"]*"[^"]*"' | grep -oE '20[0-9]{2}-[0-9]{2}-[0-9]{2}' | head -1)
[ -n "$prefix_canal" ] || { echo "nu găsesc un prefix datat în channel.json — nu șterg nimic" >&2; exit 3; }

# 2. Prefixul pe care e construit site-ul. Acesta ține corpusul *și* feliile de căutare.
prefix_site=$(grep -oE -- '--depozit https://[^ ]*/20[0-9]{2}-[0-9]{2}-[0-9]{2}' "$FLUX_PAGES" 2>/dev/null \
  | grep -oE '20[0-9]{2}-[0-9]{2}-[0-9]{2}' | head -1 || true)
[ -n "$prefix_site" ] || { echo "nu găsesc --depozit în $FLUX_PAGES — nu șterg nimic" >&2; exit 3; }

# 3. Tot ce e în bucket, cel mai nou primul.
mapfile -t toate < <(rclone lsd "r2:$BUCKET" | awk '{print $NF}' | grep -E '^20[0-9]{2}-[0-9]{2}-[0-9]{2}$' | sort -r)
[ "${#toate[@]}" -gt 0 ] || { echo "niciun prefix datat în r2:$BUCKET" >&2; exit 0; }

recente=("${toate[@]:0:$PASTREAZA}")

protejat() {
  local p=$1
  [ "$p" = "$prefix_canal" ] && { echo "channel.json"; return; }
  [ "$p" = "$prefix_site" ] && { echo "pages.yml --depozit"; return; }
  for r in "${recente[@]}"; do [ "$p" = "$r" ] && { echo "între cele mai recente $PASTREAZA"; return; }; done
  echo ""
}

echo "bucket:        r2:$BUCKET"
echo "canal:         $prefix_canal"
echo "site:          $prefix_site"
echo "păstrez și:    cele mai recente $PASTREAZA"
echo

candidati=()
for p in "${toate[@]}"; do
  motiv=$(protejat "$p")
  if [ -n "$motiv" ]; then
    printf '  %s  păstrat  (%s)\n' "$p" "$motiv"
  else
    printf '  %s  candidat\n' "$p"
    candidati+=("$p")
  fi
done
echo

if [ "${#candidati[@]}" -eq 0 ]; then
  echo "nimic de șters."
  exit 0
fi

if [ "$CONFIRMA" != "da" ]; then
  echo "aș șterge ${#candidati[@]}: ${candidati[*]}"
  echo "rulează din nou cu CONFIRMA=da dacă asta vrei."
  exit 0
fi

for p in "${candidati[@]}"; do
  echo "șterg r2:$BUCKET/$p"
  # `purge` șterge conținutul prefixului dintr-o dată; `delete` ar parcurge fiecare fragment.
  rclone purge "r2:$BUCKET/$p" --stats 30s --stats-one-line
done

echo
echo "rămase:"
rclone lsd "r2:$BUCKET" | awk '{print "  " $NF}'
