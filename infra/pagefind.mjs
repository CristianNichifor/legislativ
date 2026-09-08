// Build the search index from the records `scripts/export_cautare.py` writes.
//
// Why an external indexer at all: ranked search over the mounted corpus took 291 s, because bm25
// wants a document length per match and getting it meant ~1.000 scattered reads. Our own inverted
// index fixed the ranking cost but not the hydration — every result still went back to the corpus
// for a title and an excerpt, and a page of 25 measured 46,6 s. Pagefind keeps the excerpt in the
// index and its client fetches per-result fragments *in parallel*, which is the part our reader
// can never do: SQLite in Pyodide reads synchronously, so N results is always N serial round trips.
//
// It also brings Romanian stemming, which we had been approximating by matching a query token
// against the tokens it prefixes — the reason `achizitii` had to reach `achizitiile` by hand.
//
// Measured on 5.000 acts: 57,2 MB of index, and 0,1–0,35 s for a query including all 25 excerpts.
//
//   node infra/pagefind.mjs acte.jsonl web/pagefind
import * as pagefind from "pagefind";
import fs from "node:fs";
import readline from "node:readline";

const [, , sursa, tinta] = process.argv;
if (!sursa || !tinta) {
  console.error("folosire: node infra/pagefind.mjs <acte.jsonl> <director-iesire>");
  process.exit(2);
}

const t0 = Date.now();
// `forceLanguage` rather than per-record detection: every act is Romanian, and letting Pagefind
// guess would split the index by whatever it inferred from short titles.
const { index, errors } = await pagefind.createIndex({ forceLanguage: "ro" });
if (errors?.length) {
  console.error(errors);
  process.exit(1);
}

let n = 0;
const linii = readline.createInterface({
  input: fs.createReadStream(sursa),
  crlfDelay: Infinity,
});
for await (const linie of linii) {
  if (!linie.trim()) continue;
  const a = JSON.parse(linie);
  await index.addCustomRecord({
    // The app routes on the act id; the hash keeps it a same-page link.
    url: `#/act/${a.id}`,
    // The title is repeated into the body on purpose. Pagefind has no weighting for custom
    // records, and a law about public procurement says so in its title — without this, ranking
    // treats a mention buried in an annex the same as the subject of the act.
    content: `${a.titlu}\n${a.titlu}\n${a.text}`,
    language: "ro",
    meta: { title: a.titlu, id: a.id, tip: a.tip, an: String(a.an) },
    filters: { tip: [a.tip], an: [String(a.an)] },
    sort: { an: String(a.an) },
  });
  if (++n % 20000 === 0) {
    console.log(`  ${n} indexate · ${((Date.now() - t0) / 1000).toFixed(0)}s`);
  }
}

const tIndex = (Date.now() - t0) / 1000;
await index.writeFiles({ outputPath: tinta });
console.log(`${n} acte · indexare ${tIndex.toFixed(0)}s · scriere ${((Date.now() - t0) / 1000 - tIndex).toFixed(0)}s`);
console.log(`ieșire în ${tinta}`);
