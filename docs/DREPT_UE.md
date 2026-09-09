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
