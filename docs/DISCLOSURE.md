# Divulgare responsabilă — legislatie.just.ro

**Statut:** ciornă pregătită de întreținătorul proiectului. Nu a fost trimisă. Trimite-o tu, de la
o adresă pe care o controlezi, către contactul tehnic al portalului (Ministerul Justiției / STS).

Constatat incidental în timpul dezvoltării unui instrument civic (linter legislativ) care citește
legislația publică prin serviciul web oficial. Nu au fost exploatate; sunt raportate ca să fie
remediate.

## 1. Eroare SQL expusă la client (posibil SQL injection)

Endpointul `POST /Public/getReferitDe` (folosit de fișele de act pentru panourile de relații)
răspunde cu **HTTP 500 și mesajul SQL brut** la parametri care nu se potrivesc formei așteptate:

```
"Incorrect syntax near the keyword 'ORDER'."
"Incorrect syntax near the keyword 'and'."
```

Faptul că interogarea se rupe pe conținutul parametrilor — și că eroarea de bază de date ajunge
neschimbată la client — indică interpolare de string în SQL, adică expunere la SQL injection.

**Recomandare:** interogări parametrizate (prepared statements) pe toți parametrii; niciun mesaj de
eroare de bază de date către client (log intern, răspuns generic).

## 2. Listare de director activată pe `/apiws/`

`https://legislatie.just.ro/apiws/` returnează un **index de director**, expunând:

```
/apiws/bin/            (binarele serviciului)
/apiws/Web.config      (configurație — poate conține conexiuni/secrete)
/apiws/packages.config
/apiws/PrecompiledApp.config
```

**Recomandare:** dezactivează directory browsing (IIS: `<directoryBrowse enabled="false" />`) și
blochează accesul web la `*.config` și la `bin/`.

## Note

- Serviciul web în sine (`FreeWebService.svc/SOAP`, GetToken + Search) funcționează corect și este
  canalul potrivit pentru acces programatic — nimic de reproșat acolo.
- Bucuroși să oferim detalii sau pași de reproducere pe un canal privat, la cerere.

---

## Notă: surse de tehnică legislativă (nu vulnerabilități)

Regulile de redactare din `scripts/redactare.py` sunt codificate din documentele publice ale
Consiliului Legislativ (clr.ro): *Ghidul pentru elaborarea proiectelor de acte normative* (2025)
și Legea nr. 24/2000. Lista oficială a normelor de aplicare neelaborate (*SituatieNorme
Neindeplinite*) este ground-truth pentru raportul de vid legislativ și merită importată ca atare.
