# Drept UE, CELEX și acoperire

`eu.db` este corpusul local pentru acte ale Uniunii Europene. Este separat de `corpus.db` și
`initiative.db`: verificarea unui proiect de lege rămâne locală, iar cereri externe apar doar când
întreținătorul importă explicit un act CELEX din Cellar.

## Ce face acum

Pasul **Drept UE** are două surse de potrivire:

- **referințe explicite** din textul proiectului: `CELEX:32018R1805`, URL-uri CELEX, `Regulamentul
  (UE) 2018/1805`, `Directiva 2014/24/UE`, `Regulamentul (CE) nr. 261/2004`;
- **căutare textuală** în prevederile UE deja importate local.

Referința explicită este tratată ca fapt de citare, nu ca verdict juridic. Dacă proiectul citează
un act UE importat, aplicația îl scoate în față și arată prevederi citable din `eu.db`. Dacă îl
citează dar actul nu este importat, aplicația listează CELEX-ul lipsă ca muncă de acoperire.

Interfața mai afișează o matrice scurtă de verificare UE. Ea separă:

- acte UE citate explicit;
- acoperirea locală din `eu.db`;
- potriviri textuale pe aceeași materie;
- formulări de derogare posibilă;
- lacună/obligație UE și contradicție UE, marcate explicit ca **necalculate**.

Matricea este o listă de lucru: arată ce poate fi verificat imediat și ce rămâne blocat de date sau
de analiză juridică punctuală.

## Import local din Cellar

Importul pornește de la CELEX, fie introdus manual, fie copiat din lista de acte citate dar
neimportate:

```bash
uv run python -m scripts.cellar 32018R1805 --db eu.db
```

Se pot importa mai multe acte în aceeași rulare:

```bash
uv run python -m scripts.cellar 32018R1805 32014L0024 32004R0261 --db eu.db
```

Implicit, importatorul cere manifestări oficiale în ordinea `RON,ENG`: preferă textul oficial în
română și cade pe engleză dacă româna nu este disponibilă la sursă. Limba aleasă rămâne vizibilă în
rezultat și în interfață. Aplicația nu traduce automat un act UE lipsit de manifestare românească.

Ordinea poate fi schimbată explicit:

```bash
uv run python -m scripts.cellar 32018R1805 --db eu.db --limbi RON,ENG
```

Pentru acte deja stocate, prevederile căutabile se pot reconstrui fără să se refacă descărcarea:

```bash
uv run python -m scripts.cellar --indexeaza --db eu.db
uv run python -m scripts.cellar --indexeaza 32018R1805 --db eu.db
```

Importatorul păstrează actul, manifestările găsite și prevederile împărțite în locatori precum
`preambul`, `considerent-1`, `art1`, `anexa-i`. Acestea sunt unitățile pe care interfața le poate
cita.

## Instantanee locale și dosare

Importurile noi păstrează în `eu_instantanee` textul extras și proveniența fiecărei observații:
CELEX, URI de work/expression/manifestation, limba, formatul, URL-ul principal, metadatele actului,
data colectării și SHA-256 al textului. Identitatea instantaneei include aceste metadate; o nouă
colectare poate produce alt identificator chiar dacă textul este identic. Nu este un identificator
oficial al unei versiuni juridice. Observațiile nu sunt suprascrise la import.

La primul import după actualizare, rândul local anterior este arhivat înainte de înlocuire.
Nu se recuperează versiuni dispărute înainte de această actualizare. O arhivare invalidă sau peste
8 MB oprește importul și păstrează actul și indexul anterior. Tranzacția include textul, indexul
și instantaneele; trigger-ele append-only nu protejează împotriva proprietarului bazei SQLite.

O rulare nouă de dosar capturează separat sursele UE **contextuale**, fără a crea constatări
juridice sau dependențe de reevaluat. Citește o singură tranzacție locală, fără rețea sau migrare.
Păstrează maximum 20 de referințe și 2 MB de instantanee serializate; sursele lipsă, corupte sau
prea mari au stări explicite, fără text ori amprentă parțială. Limita totală de 4 MB a rulării
rămâne aplicabilă. Datele sunt vizibile în analiza salvată și în exporturile revizuirii JSON și
Markdown. Dosarele vechi nu primesc retrospectiv textul curent drept dovadă istorică.

Capturile rețin textul extras, **nu octeții originali descărcați**, și URL-ul principal al
manifestării, nu o dovadă completă a extragerii fiecărui flux din documentele multipart.
Româna și alternativa engleză rămân distincte; schimbarea limbii nu dovedește modificarea sensului.
La verificarea explicită a dovezilor, sursele UE sunt comparate separat cu `eu.db` local.
Rezultatul păstrează amprentele și metadatele inițiale/curente, fără o nouă copie integrală a
textului curent. Textul schimbat, limba schimbată și metadatele schimbate sunt semnale distincte.
O limbă diferită blochează comparația textelor, nu dovedește o modificare a sensului juridic.
O simplă schimbare a datei colectării nu este prezentată drept schimbare de text.

Sursele lipsă, corupte, prea mari sau fără o captură inițială verificabilă rămân necomparabile.
O importare ulterioară nu completează retrospectiv dovada inițială. Nu sunt efectuate descărcări.
Rezultatele sunt păstrate în istoricul verificărilor și în exporturile revizuirii alături de
verificarea selectată. Selectarea unei verificări vechi nu recitește sursele. Verificările vechi
fără rezultate UE sunt etichetate ca atare, fără completare automată.

Aceste rezultate contextuale nu modifică deciziile, numărătorile constatărilor sau filtrele cozii
de reevaluare a constatărilor.

### Coada surselor UE între dosare

În biblioteca locală, **Surse UE între dosare** listează rulările cu referințe UE din toate
dosarele, câte 50 pe pagină. Endpoint-ul read-only `/api/dosare/coada-ue` folosește numai datele
salvate în baza dosarelor. Deschiderea, filtrarea și reîncărcarea listei nu citesc `eu.db`, nu
descarcă surse și nu salvează verificări. Baza lipsă produce o listă goală fără creare; citirea
schemelor vechi nu le migrează. Funcționalitatea nu este disponibilă în versiunea statică.

Se folosește ultima verificare salvată a fiecărei rulări, în ordinea inserării, chiar dacă acea
verificare nu conține rezultate UE. Lipsa rezultatelor UE înseamnă **Fără verificare UE**, nu text
neschimbat. O versiune necunoscută a rezultatului sau un set incomplet de comparații rămâne
incomplet. Modificarea surselor locale nu schimbă această listă până la o verificare explicită.

Filtrele separă texte schimbate, limbi schimbate, surse cu numai metadate schimbate, comparații
incomplete și lipsa verificării UE. Numărătorile descriu surse, nu constatări. Filtrele se pot
suprapune: o rulare poate avea o sursă schimbată și alta indisponibilă. **Fără schimbări semnalate**
cere o comparație completă fără schimbări de text, limbă sau metadate; nu certifică actualitatea.

Deschiderea unui rând selectează rularea și exact verificarea afișată în coadă, nu înlocuiește
acea verificare cu una salvată între timp. Instantaneele inițiale rămân în analiza salvată.
Notele nesalvate blochează navigarea din coadă. Verificările, sursele inițiale și deciziile nu sunt
modificate prin navigare; salvarea explicită a unei verificări reîncarcă și coada deschisă.

Backup-ul SQLite al dosarelor include textul UE capturat în rulări, dar nu tot istoricul de import.
Pentru acesta trebuie salvat și `eu.db`, folosind API-ul SQLite de backup pentru a include WAL.

## Ce nu decide

`Drept UE` nu spune singur că un proiect este compatibil sau incompatibil cu dreptul UE.

Un rezultat de tip **referință explicită** înseamnă doar: proiectul a citat acest act UE și textul
oficial importat local poate fi deschis la nivel de prevedere. Un rezultat de tip **potrivire text**
înseamnă doar: termenii proiectului seamănă cu o prevedere UE importată.

Verdictul de compatibilitate cere un pas separat, cu o grilă mai strictă:

- prevederea UE citată;
- prevederea națională sau proiectul analizat;
- domeniul juridic și rangul actului;
- motivul conflictului sau al derogării;
- limita factuală: act UE neimportat, text românesc lipsă, citare ambiguă, domeniu insuficient.

Orice model local sau online poate ajuta la formularea ipotezei, dar nu trebuie să fie sursa
verdictului fără citări verificabile. Modelul poate sugera, retrieverul și validarea trebuie să
arate ce texte au fost folosite.

## Raportul de acoperire

Raportul de acoperire spune ce acte UE sunt citate în datele locale și care dintre ele lipsesc din
`eu.db`. Este coada de import pentru întreținere, nu un verdict juridic automat.

Local, raportul se rulează așa:

```bash
uv run python -m scripts.acoperire_ue --corpus corpus.db --initiative initiative.db --eu eu.db
```

Pentru ieșire mașină-citibilă:

```bash
uv run python -m scripts.acoperire_ue --corpus corpus.db --initiative initiative.db --eu eu.db --json
```

În interfață, fila **Drept UE** are butonul **Acoperire import**, care citește același raport prin
`/api/ue/acoperire`. Butonul **Coadă import CELEX** citește `/api/ue/import-queue`: aceeași
acoperire, filtrată din nou prin starea curentă din `eu.db`, cu referințele locale, sursele
oficiale și comanda `scripts.cellar` în ordinea de limbi `RON,ENG`. Build-ul static scrie și
publică `web/data/ue_acoperire.json`, ca browserul să nu scaneze baze mari la fiecare vizită.

Raportul parcurge:

- legislația publicată din `corpus.db`;
- inițiativele din Parlament din `initiative.db`;

Pentru fiecare referință UE detectată, raportul arată:

- CELEX normalizat;
- forma citată în text;
- sursa unde apare citarea: act/proiect și locator, dacă există;
- dacă CELEX-ul există în `eu.db`;
- frecvența citării;
- exemple de context;
- comanda de import pentru CELEX-urile lipsă.

Ieșirea utilă pentru întreținere este o coadă de import:

```text
CELEX       citări  importat  limba  surse
32014L0024      9  nu        -      achiziții publice, proiecte CDEP
32018R1805      4  da        RON    confiscare, cooperare judiciară
```

Matricea actuală este primul strat determinist al analizei juridice: domeniu și rang normativ se
pot vedea doar unde textul le face verificabile, iar lacuna/contradicția UE rămân necalculate până
când există actul UE incident, prevederea națională comparată și motivarea punctuală. Fără
acoperire, o matrice completă ar confunda absența din `eu.db` cu absența unei obligații europene.
