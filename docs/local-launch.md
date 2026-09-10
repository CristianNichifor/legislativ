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
Importul PDF al documentelor parlamentare necesita separat Poppler (`pdftotext`).
Pachetul nu include Poppler, modele AI sau un server Ollama; functiile respective
raman conditionate de configurarea lor explicita.

Datele persistente sunt separate de aplicatie:

- Linux: `$XDG_DATA_HOME/legislativ` sau `~/.local/share/legislativ`.
- macOS: `~/Library/Application Support/legislativ`.
- Windows: `%LOCALAPPDATA%\legislativ`.

Seturile publice stau in `datasets/<manifest-sha256>`, cu pointerul `active.json`.
Lucrul privat ramane in `private`. Actualizarea inseamna extragerea noului
pachet; nu sterge directorul de date. Pentru backup, opreste aplicatia si
copiaza directorul de date intr-un loc privat.

Optiuni: `--data-home "/cale/externa"`, `--port 8000`, `--fara-browser`,
`--data-channel "https://server.example/channel.json"`.
Canalul este configurat doar la pornire, nu prin cererile din interfata.
Un port ocupat este inlocuit cu unul liber. Daca alt proces ocupa portul intre
verificare si pornirea serverului, reporneste aplicatia. Asculta doar pe
`127.0.0.1`. `LEGISLATIV_PYTHON` poate indica executabilul Python dorit.

## Constructie si verificare

```sh
python3 -m unittest discover -s tests -p 'test_local_*.py'
python3 -m scripts.build_runtime --output dist/runtime
bash ruleaza.sh --fara-browser
```

Workflow-ul `Local runtime package` verifica artefacte pe Linux, Windows si
macOS la pull request pentru fisierele relevante, si la declansare manuala.
Nu publica un release. Un responsabil verifica artefactele
si aproba separat publicarea. Verifica `SHA256SUMS` inainte de distribuire.
Pachetul contine cod Python si resurse app (fonturi/module), fara baze de date
sau director privat. Codul este extras temporar la rulare.

Serverul accepta `--data-home ROOT`, `--data-channel HTTPS`, `--port PORT` si
`--fara-browser`. Fara `--data-home`, apelul direct al serverului pastreaza
comportamentul vechi. Managerul `scripts.date_locale` si interfata detin
descarcarea initiala; testul real de pornire este obligatoriu in workflow.

`GET /api/date` citeste starea locala. `POST /api/date` accepta un obiect JSON
de cel mult 4096 octeti cu `action`: `check`, `download`, `cancel`, `activate`
sau `rollback`. `download` si `activate` necesita si `sha256` din oferta
curenta. Host/Origin trebuie sa fie locale. Erorile de sursa, inclusiv un canal
inca nepublicat (HTTP 404), sunt erori de actualizare, nu o instalare reusita.

Procesul tine `runtime.lock` pana la incheierea cererilor si descarcarilor.
Activarea si rollback-ul creeaza o stare noua si o generatie privata UE noua;
restartul redeschide exact `private/eu-generations/<private_generation>/eu.db`.
Lipsa acestui fisier cere recuperare, fara revenire tacita la baza publica.
