#!/usr/bin/env bash
# Instalează verificarea zilnică a legislației ca timer systemd de utilizator.
#
# Instalarea copiază unitățile și reîncarcă systemd. **Nu pornește nimic**: un job care cere zilnic
# de la serverul unui minister este un angajament, iar activarea lui rămâne o comandă pe care o dai
# tu, cu ochii pe ea. Ultima secțiune spune exact care e.
#
# Ce face rularea, o dată pe zi: re-parcurge coada enumerării (paginile noi, plus o margine peste
# ultima pagină, care e aproape sigur parțială), citește datele de publicare pentru ce a intrat,
# extrage loviturile din deciziile noi ale Curții și reconstruiește muchiile doar pentru actele
# atinse. În mod normal, secunde — costul e al legii noi, nu al corpusului.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

echo "repo:      $REPO"
echo "instalez în: $DEST"
mkdir -p "$DEST"

for u in legislativ-actualizare.service legislativ-actualizare.timer; do
  # `%h` din unitate se extinde la home; dacă repo-ul nu e unde presupune unitatea, spune-o acum,
  # nu peste o săptămână când timer-ul eșuează tăcut în jurnal.
  install -m 0644 "$REPO/infra/systemd/$u" "$DEST/$u"
  echo "  ✓ $u"
done

asteptat="$HOME/Work/Dev/Repos/engineering/legislativ"
if [[ "$REPO" != "$asteptat" ]]; then
  echo
  echo "ATENȚIE: unitatea presupune $asteptat, dar repo-ul e la $REPO."
  echo "         Editează WorkingDirectory și ReadWritePaths în $DEST/legislativ-actualizare.service."
fi

systemctl --user daemon-reload
echo "  ✓ daemon-reload"

echo
if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null || echo no)" != "yes" ]]; then
  cat <<'AVERTISMENT'
ATENȚIE: „linger" e dezactivat pentru acest utilizator.

Fără el, unitățile de utilizator rulează doar cât ai o sesiune deschisă — deci un timer zilnic
NU se declanșează când ești delogat, și nu spune nimic despre asta. Un corpus care crede că se
actualizează și nu o face e mai rău decât unul despre care știi că e vechi.

  loginctl enable-linger $USER

AVERTISMENT
fi

cat <<'PORNIRE'
Instalat, dar inactiv. Ca să pornești verificarea zilnică:

  systemctl --user enable --now legislativ-actualizare.timer

Ca să vezi când urmează să ruleze:

  systemctl --user list-timers legislativ-actualizare.timer

Ca să rulezi o dată, acum, și să te uiți la ea:

  systemctl --user start legislativ-actualizare.service
  journalctl --user -u legislativ-actualizare.service -f

Ca să oprești:

  systemctl --user disable --now legislativ-actualizare.timer
PORNIRE
