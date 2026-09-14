# Operare (ghidul echipei de cercetare)

Ghidul complet de folosire, în română. Pornirea și corpusul sunt în
[README](../README.md#quick-start); aici sunt pașii care nu încap acolo.

## Pornire

Un singur pas, local, fără să trimită nimic în afara mașinii — proiectul lipit rămâne pe calculatorul
tău, iar verificarea nu face nicio cerere externă:

```bash
./ruleaza.sh
```

Se deschide în browser la `http://127.0.0.1:8000`. Lipești textul unui proiect de act normativ și
vezi patru lucruri, fiecare cu sursa lui: **ce atinge** (ce legi modifică și de câte ori au fost deja
amendate), **termenele** de implementare pe care le impune, **terminologia** față de termenii definiți
în lege, și **inițiativele în lucru** care s-ar putea suprapune — ca să amendezi una existentă în loc
să depui un duplicat.

## Corpusul

Ai nevoie o singură dată de corpus (baza de legislație). Fie îl descarci, dacă a fost publicat:

```bash
scripts/ia_corpus.sh https://github.com/CristianNichifor/legislativ/releases/download/<versiune>
```

fie îl construiești local (câteva ore, o singură dată, reia de unde a rămas dacă se oprește):

```bash
uv run python -m scripts.colector --db corpus.db      # legislația
uv run python -m scripts.cdep     --db initiative.db   # inițiativele din Parlament
```

Odată colectat, îl ții la zi re-parcurgând coada — enumerarea serviciului e cronologică, așa că
legile noi apar pe pagini noi la sfârșit, iar o lege modificată sosește ca act modificator nou.
Serviciul nu are filtru „modificat după", deci actualizarea re-descoperă sfârșitul și re-colectează
coada (ultima pagină, adesea parțială, plus paginile noi), apoi reconstruiește graful:

```bash
uv run python -m scripts.colector --db corpus.db --actualizeaza --graf graf.db
```

Graful de amendamente se construiește singur din corpus la prima pornire. Cine întreține proiectul
împachetează corpusul pentru echipă cu `python -m scripts.impacheteaza` și îl atașează la un release.

## Paginile actelor (structura pe articole)

Serviciul SOAP întoarce textul deja aplatizat — fără titluri de articol în care să te încrezi și
fără alineate — așa că pagina HTML a documentului se aduce separat, **o singură dată per document**,
și se păstrează în corpus. De acolo `parsare.py` citește arborele real de articole:

```bash
uv run python -m scripts.surse --db corpus.db                 # aduce paginile actelor lovite
uv run python -m scripts.surse --db corpus.db --toate         # …sau ale întregului corpus
uv run python -m scripts.surse --db corpus.db --imbogateste   # structurează ce s-a adus
```

Lista implicită e îngustă și intenționat: actele lovite de o decizie a Curții, unde un text
aplatizat costă o constatare. `--toate` cere paginile întregului corpus și e un pas separat, ca
nimeni să nu pornească din greșeală o traversare de 30 000 de pagini pe serverul unui minister.
`--paralel` deschide mai multe conexiuni, `--rata` e plafonul pe care îl împart: conexiuni care
așteaptă la același ceas înmulțesc debitul la aceeași sarcină pe server, conexiuni care dorm fiecare
pe cont propriu înmulțesc sarcina.

## Parlamentul

Parlamentul e o a doua sursă, cu propriile ei comenzi — parcursul unei inițiative de pe Fișa ei,
apoi dezbaterea de la punctul ședinței pe care pasul îl indică:

```bash
uv run python -m scripts.parcurs --db initiative.db --paralel 12 --rata 8
uv run python -m scripts.stenograme --db initiative.db --paralel 12 --rata 8
```

## Dreptul UE

Dreptul UE intră separat, prin Cellar / CELEX. Primul pas doar aduce sursa oficială: caută
manifestările Cellar, preferă textul românesc (`RON`) și cade pe engleză (`ENG`) dacă româna nu e
disponibilă, apoi împarte textul în prevederi căutabile (`considerent-1`, `art1`, `anexa-i`).
Verificarea arată referințe UE explicite și potriviri textuale în ce este importat local; nu decide
încă dacă un proiect contrazice dreptul UE. Fluxul complet este în [`DREPT_UE.md`](DREPT_UE.md):

```bash
uv run python -m scripts.cellar 32018R1805 --db eu.db
uv run python -m scripts.cellar --indexeaza --db eu.db   # pentru texte UE importate înainte
```

## Matricea

Fila **Matrice** grupează semnale verificabile pe emitent, tip de act și rang normativ. Rangul este
dedus doar din tipul actului (`lege`, `oug`, `hg`, `ordin` etc.); pentru `lege`, aplicația marchează
explicit că organic/ordinar nu este precizat în corpus.

## Reparații pe un corpus deja adunat

Stau separat, fiindcă o migrare care se rulează singură pe un orar e una pe care nimeni nu poate
decide să n-o ruleze:

```bash
uv run python -m scripts.curatare --db corpus.db --emitenti   # pune la loc ș și ț în emitenți
uv run python -m scripts.omonime --db corpus.db               # dă înapoi rândul actelor omonime
```

`scripts.actualizare` face ambele ca parte din rularea zilnică, plafonat, ca durata jobului să nu
depindă de cât a trecut de la ultima rulare.

## Pasul cu model

Verificarea de constituționalitate rulează **fără model** și offline. Pasul care cere un model —
„are proiectul meu același viciu pentru care Curtea a lovit textul?" — rulează **doar pe mașina ta**,
fiindcă proiectul e un text nepublicat și nu pleacă nicăieri:

```bash
LEGISLATIV_MODEL=llama3.1 ./ruleaza.sh     # cu Ollama pornit local
```

Fără variabilă, pasul raportează că nu a rulat — nu că nu a găsit nimic.

## Actualizare offline (delta)

Cine e offline nu re-descarcă releaseul ca să afle ce s-a publicat ieri. Copia își știe poziția,
iar pachetul e doar ce s-a scris de atunci încoace (386 de acte ≈ 2,8 MB comprimat, față de 742 MB):

```bash
uv run python -m scripts.delta versiune --db copie.db                    # unde e copia
uv run python -m scripts.delta construieste --de-la <poziție> --tinta delta.db
uv run python -m scripts.delta aplica --db copie.db --pachet delta.db --graf graf.db
```

## Ce e măsurat local

Pentru un inventar read-only al bazelor disponibile efectiv pe mașină:

```bash
uv run python -m scripts.inventar_surse
```

sau `/api/inventar-surse` pe serverul local. Datele lipsă și datele necunoscute nu sunt raportate ca
zero măsurat. Populațiile și limitările sunt în [`INVENTAR_SURSE.md`](INVENTAR_SURSE.md); inventarul
nu certifică nici completitudinea corpusului, nici compatibilitatea juridică.
