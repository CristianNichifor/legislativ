// legislativ-rescrieri — the plain-language rewrite service, hardened against abuse.
//
// It restates one provision of PUBLIC law in plain language (Danish style, docs/STIL_DANEZ.md) and
// caches the result so each provision is rewritten once, ever. The app's own draft never touches
// this — only public law does.
//
// Cost defences, so a bot cannot run up the AI bill:
//  1. Cache-first: a repeat request is a free KV read, no model call.
//  2. Small input only (MAX_CHARS): a provision is short, so a request carrying a big prompt is
//     refused — the endpoint cannot be used as a free general-purpose LLM.
//  3. Per-IP rate limit via the Workers rate-limiting binding (RL), when bound — native, no KV cost.
//  4. A soft daily cap (CAP_ZILNIC) on NEW generations, tracked in KV, as a hard ceiling on spend.
//  5. Origin allowlist (ORIGINI, comma-separated): only calls from the app's own pages are served.
//     Spoofable in theory, but it stops casual scripted abuse for free.
//  6. Belt-and-braces you set outside the code: a monthly spend cap on the Mistral account, and —
//     optionally — AI Gateway in front (free caching + rate limiting + cost analytics) by pointing
//     MISTRAL_URL at the gateway; the Batch API is ~half price for bulk pre-generation.
//
// GET  /rescrie?act=<id>&loc=<locator>       → cached rewrite, or 404 if not generated yet
// POST /rescrie {act, loc, text}             → cached rewrite, or generate + cache

const STIL = "danez-v1";
const MAX_CHARS = 4000; // a single provision; longer inputs are abuse, not law

function corsFor(request, env) {
  const origin = request.headers.get("Origin") || "";
  const lista = (env.ORIGINI || "*").split(",").map((s) => s.trim());
  const permis = lista.includes("*") ? "*" : (lista.includes(origin) ? origin : lista[0] || "");
  return {
    "Access-Control-Allow-Origin": permis,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Vary": "Origin",
  };
}

const SISTEM =
  "Ești un asistent care rescrie prevederi legale românești în limbaj clar, în stilul danez de " +
  "redactare (Vejledning om lovkvalitet): propoziții scurte, o idee pe propoziție; enunțul " +
  "principal la început (cine face ce), apoi condițiile; diateza activă, cu actorul numit; " +
  "propoziții relative în locul participiilor antepuse; fără duble negații; cifre pentru numere. " +
  "NU schimba sensul, nu adăuga și nu omite nimic; păstrează exact termenii definiți. Dacă o " +
  "reformulare fidelă nu e posibilă, rămâi aproape de textul original. Răspunde DOAR cu textul " +
  "rescris, fără explicații.";

function json(obj, cors, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...cors },
  });
}

const cheie = (act, loc) => `${STIL}/${act}/${loc || "act"}`;

function originPermis(request, env) {
  const lista = (env.ORIGINI || "*").split(",").map((s) => s.trim());
  if (lista.includes("*")) return true;
  const origin = request.headers.get("Origin") || "";
  return origin && lista.includes(origin);
}

async function subCap(env) {
  if (!env.CAP_ZILNIC) return true;
  const k = `_zi/${new Date().toISOString().slice(0, 10)}`;
  const n = parseInt((await env.RESCRIERI.get(k)) || "0", 10);
  if (n >= Number(env.CAP_ZILNIC)) return false;
  await env.RESCRIERI.put(k, String(n + 1), { expirationTtl: 172800 });
  return true;
}

async function genereaza(text, env) {
  if (!env.MISTRAL_API_KEY) {
    return { rescriere:
      "Rescrierea în limbaj clar nu este încă activată (lipsește cheia AI). " +
      "Textul original rămâne singurul autoritativ.", model: "stub" };
  }
  const r = await fetch((env.MISTRAL_URL || "https://api.mistral.ai/v1/chat/completions"), {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${env.MISTRAL_API_KEY}` },
    body: JSON.stringify({
      model: env.MISTRAL_MODEL || "mistral-small-latest",
      temperature: 0.2,
      messages: [ { role: "system", content: SISTEM }, { role: "user", content: text } ],
    }),
  });
  if (!r.ok) return { rescriere: null, model: "eroare", eroare: `mistral ${r.status}` };
  const d = await r.json();
  return { rescriere: (d.choices?.[0]?.message?.content || "").trim(), model: d.model || "mistral" };
}

export default {
  async fetch(request, env) {
    const cors = corsFor(request, env);
    if (request.method === "OPTIONS") return new Response(null, { headers: cors });

    const url = new URL(request.url);
    if (!url.pathname.endsWith("/rescrie")) return json({ error: "not found" }, cors, 404);
    if (!originPermis(request, env)) return json({ error: "origine nepermisă" }, cors, 403);

    if (env.RL) {
      const ip = request.headers.get("CF-Connecting-IP") || "0";
      const { success } = await env.RL.limit({ key: ip });
      if (!success) return json({ error: "prea multe cereri, încearcă mai târziu" }, cors, 429);
    }

    let act, loc, text;
    if (request.method === "GET") {
      act = url.searchParams.get("act"); loc = url.searchParams.get("loc");
    } else if (request.method === "POST") {
      const b = await request.json().catch(() => ({})); act = b.act; loc = b.loc; text = b.text;
    } else return json({ error: "method not allowed" }, cors, 405);
    if (!act) return json({ error: "lipsește 'act'" }, cors, 400);

    const k = cheie(act, loc);
    const cache = await env.RESCRIERI.get(k);
    if (cache) return json({ rescriere: cache, cached: true, stil: STIL }, cors);
    if (request.method === "GET") return json({ error: "negenerat", cached: false }, cors, 404);

    if (!text) return json({ error: "lipsește 'text'" }, cors, 400);
    if (text.length > MAX_CHARS) return json({ error: "text prea lung pentru o prevedere" }, cors, 413);
    if (!(await subCap(env))) return json({ error: "plafon zilnic atins; reîncearcă mâine" }, cors, 429);

    const { rescriere, model, eroare } = await genereaza(text, env);
    if (eroare || !rescriere) return json({ error: eroare || "generare eșuată" }, cors, 502);
    if (model !== "stub") await env.RESCRIERI.put(k, rescriere);
    return json({ rescriere, cached: false, model, stil: STIL }, cors);
  },
};
