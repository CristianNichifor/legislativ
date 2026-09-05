// legislativ-rescrieri — the plain-language rewrite service.
//
// It restates one provision of PUBLIC law in plain language, Danish style (see docs/STIL_DANEZ.md),
// and — crucially for cost — caches the result so each provision is rewritten once, ever, then
// served from cache to everyone. Because the input is public law, not a user's private draft,
// sending it here carries no privacy cost; the app's own draft never touches this Worker.
//
// GET  /rescrie?act=<id>&loc=<locator>          → cached rewrite, or 404 if not generated yet
// POST /rescrie {act, loc, text}                → cached rewrite, or generate+cache+return
//
// Storage: a KV namespace bound as RESCRIERI. Generation: Mistral (EU) when MISTRAL_API_KEY is set;
// otherwise a clearly-labelled stub, so the whole pipeline works before any key is added.

const STIL = "danez-v1"; // bump to invalidate every cached rewrite when the style changes

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

const SISTEM =
  "Ești un asistent care rescrie prevederi legale românești în limbaj clar, în stilul danez de " +
  "redactare (Vejledning om lovkvalitet): propoziții scurte, o idee pe propoziție; enunțul " +
  "principal la început (cine face ce), apoi condițiile; diateza activă, cu actorul numit; " +
  "propoziții relative în locul participiilor antepuse; fără duble negații; cifre pentru numere. " +
  "NU schimba sensul, nu adăuga și nu omite nimic; păstrează exact termenii definiți. Dacă o " +
  "reformulare fidelă nu e posibilă, rămâi aproape de textul original. Răspunde DOAR cu textul " +
  "rescris, fără explicații.";

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...CORS },
  });
}

function cheie(act, loc) {
  return `${STIL}/${act}/${loc || "act"}`;
}

async function genereaza(text, env) {
  if (!env.MISTRAL_API_KEY) {
    return {
      rescriere:
        "Rescrierea în limbaj clar nu este încă activată (lipsește cheia AI). " +
        "Textul original rămâne singurul autoritativ.",
      model: "stub",
    };
  }
  const r = await fetch("https://api.mistral.ai/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${env.MISTRAL_API_KEY}`,
    },
    body: JSON.stringify({
      model: env.MISTRAL_MODEL || "mistral-small-latest",
      temperature: 0.2,
      messages: [
        { role: "system", content: SISTEM },
        { role: "user", content: text },
      ],
    }),
  });
  if (!r.ok) {
    return { rescriere: null, model: "eroare", eroare: `mistral ${r.status}` };
  }
  const d = await r.json();
  return { rescriere: (d.choices?.[0]?.message?.content || "").trim(), model: d.model || "mistral" };
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });

    const url = new URL(request.url);
    if (!url.pathname.endsWith("/rescrie")) return json({ error: "not found" }, 404);

    let act, loc, text;
    if (request.method === "GET") {
      act = url.searchParams.get("act");
      loc = url.searchParams.get("loc");
    } else if (request.method === "POST") {
      const b = await request.json().catch(() => ({}));
      act = b.act;
      loc = b.loc;
      text = b.text;
    } else {
      return json({ error: "method not allowed" }, 405);
    }
    if (!act) return json({ error: "lipsește 'act'" }, 400);

    const k = cheie(act, loc);
    const cache = await env.RESCRIERI.get(k);
    if (cache) return json({ rescriere: cache, cached: true, stil: STIL });

    if (request.method === "GET") return json({ error: "negenerat", cached: false }, 404);
    if (!text) return json({ error: "lipsește 'text' pentru generare" }, 400);

    const { rescriere, model, eroare } = await genereaza(text, env);
    if (eroare || !rescriere) return json({ error: eroare || "generare eșuată" }, 502);

    // Cache only real generations, never the stub — so the stub is replaced the moment a key lands.
    if (model !== "stub") await env.RESCRIERI.put(k, rescriere);
    return json({ rescriere, cached: false, model, stil: STIL });
  },
};
