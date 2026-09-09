# Rulare locala

Pachetul `legislativ-local.zip` necesita Python 3.12+, instalat separat de la
https://www.python.org/downloads/. Python nu este inclus. Nu sunt necesare
uv, pip, dependinte de dezvoltare sau un cont.

1. Dezarhiveaza integral pachetul.
2. Windows: deschide `ruleaza.cmd`. Linux/macOS: ruleaza `bash ruleaza.sh`
   din directorul extras. Alternativ: `python3 legislativ.pyz`.
3. Browserul se deschide pe localhost. La prima pornire, descarca setul public
   de date folosind actiunea din interfata.
4. Pastreaza terminalul deschis; Ctrl-C opreste aplicatia.

Pornirea nu descarca date, nu colecteaza surse si nu apeleaza inferenta platita.
Descarcarea necesita internet si o actiune explicita in interfata. Fara date,
analiza care necesita corpus ramane indisponibila.

Datele persistente sunt separate de aplicatie:

- Linux: `$XDG_DATA_HOME/legislativ` sau `~/.local/share/legislativ`.
- macOS: `~/Library/Application Support/legislativ`.
- Windows: `%LOCALAPPDATA%\legislativ`.

Seturile publice stau in `datasets/<release>`, cu pointerul `active.json`.
Lucrul privat ramane in `private`. Actualizarea inseamna extragerea noului
pachet; nu sterge directorul de date. Pentru backup, opreste aplicatia si
copiaza directorul de date intr-un loc privat.

Optiuni: `--data-home "/cale/externa"`, `--port 8000`, `--fara-browser`.
Un port ocupat este inlocuit cu unul liber. Daca alt proces ocupa portul intre
verificare si pornirea serverului, reporneste aplicatia. Asculta doar pe
`127.0.0.1`. `LEGISLATIV_PYTHON` poate indica executabilul Python dorit.

## Constructie si verificare

```sh
python3 -m unittest discover -s tests -p 'test_local_launch.py'
python3 -m scripts.build_runtime --output dist/runtime
bash ruleaza.sh --fara-browser
```

Workflow-ul manual `Local runtime package` verifica artefacte pe Linux,
Windows si macOS. Nu publica un release. Un responsabil verifica artefactele
si aproba separat publicarea. Verifica `SHA256SUMS` inainte de distribuire.
Pachetul contine cod Python si resurse app (fonturi/module), fara baze de date
sau director privat. Codul este extras temporar la rulare.

Integrare necesara: `scripts.server` trebuie sa accepte `--data-home ROOT`,
`--port PORT`, `--fara-browser` si sa serveasca interfata fara corpus.
Managerul `scripts.date_locale` si interfata detin descarcarea initiala.
Testul real de pornire este obligatoriu in workflow; pe baza veche fara aceasta
integrare este omis local, iar lansarea nu este inca functionala.
