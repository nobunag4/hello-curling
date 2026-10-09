// api.hellocurling.com: placar ao vivo do Grand Slam of Curling.
// O site do circuito não deixa outros sites lerem os dados direto do navegador; este serviço (Cloudflare Worker)
// busca o feed, enxuga para só o que a página usa e devolve com permissão para qualquer site ler.
// Rota única: GET /gsoc/{tour_id}  (ex.: /gsoc/tch_2026). Guarda a resposta por 10 segundos.
// Também é o relógio do robô: a cada 15 minutos (e às 6h30 UTC, com a parte diária) aciona o workflow
// "Atualizar dados" no GitHub, que pelo agendamento do próprio GitHub atrasa demais.
// O token do GitHub (só "Actions", só neste repositório) fica no segredo GH_TOKEN.

const FEED = "https://www.thegrandslamofcurling.com/default.aspx?methodtype=3&client=36f6377633&sport=31&league=0&timezone=-0000&language=en&tournament=";
// mesmos ajustes de nome de hc/sources/gsoc.py
const DISPLAY = { Hoesli: "Hösli", Paetz: "Pätz", Wrana: "Wranå", "Schwaller-Huerlimann": "Schwaller-Hürlimann" };
const HEADERS = { "access-control-allow-origin": "*", "content-type": "application/json; charset=utf-8" };

const real = n => !!n && !n.includes("TBD");
const utc = s => new Date(s.replace("-00:00", "Z")).toISOString().slice(0, 16) + "Z";

function slim(feed) {
  const out = [];
  for (const m of feed.matches || []) {
    const ps = m.participants || [];
    if (ps.length !== 2 || !real(ps[0].name) || !real(ps[1].name)) continue;
    const [a, b] = ps;
    const state = m.event_state === "R" ? "done" : m.event_state === "L" ? "live" : "pre";
    const ends = (m.ends || "").split(",").map(e => e.trim()).filter(e => /^\d+-\d+$/.test(e)).map(e => e.split("-").map(Number));
    const score = p => state !== "pre" && /^\d+$/.test(String(p.value ?? "")) ? Number(p.value) : null;
    out.push({
      t: utc(m.start_date), div: { Men: "m", Women: "w" }[m.event_group] || null,
      a: DISPLAY[a.name] || a.name, b: DISPLAY[b.name] || b.name, sa: score(a), sb: score(b), ends,
      hammer: a.lsfe === "true" ? "a" : b.lsfe === "true" ? "b" : null, state,
    });
  }
  return out;
}

const WORKFLOW = "https://api.github.com/repos/nobunag4/hello-curling/actions/workflows/atualizar.yml/dispatches";
const DAILY = "30 6 * * *";

export default {
  async scheduled(event, env) {
    // às 6h30 os dois horários disparam juntos; fica só o diário, que já faz tudo
    const at = new Date(event.scheduledTime);
    if (event.cron !== DAILY && at.getUTCHours() === 6 && at.getUTCMinutes() === 30) return;
    const r = await fetch(WORKFLOW, {
      method: "POST",
      headers: { authorization: `Bearer ${env.GH_TOKEN}`, accept: "application/vnd.github+json", "user-agent": "hellocurling.com",
        "x-github-api-version": "2022-11-28" },
      body: JSON.stringify({ ref: "main", inputs: { agendado: "true", completo: String(event.cron === DAILY) } }),
    });
    if (!r.ok) throw new Error(`GitHub ${r.status}: ${await r.text()}`);
  },

  async fetch(req, env, ctx) {
    if (req.method === "OPTIONS") return new Response(null, { headers: { ...HEADERS, "access-control-allow-methods": "GET" } });
    const m = new URL(req.url).pathname.match(/^\/gsoc\/([a-z]+_\d{4})$/);
    if (req.method !== "GET" || !m) return new Response('{"error":"not found"}', { status: 404, headers: HEADERS });
    const cache = caches.default, key = new Request(req.url);
    const hit = await cache.match(key);
    if (hit) return hit;
    const r = await fetch(FEED + m[1], { headers: { "user-agent": "hellocurling.com" } });
    if (!r.ok) return new Response('{"error":"upstream"}', { status: 502, headers: HEADERS });
    let body;
    try { body = JSON.stringify({ updated: new Date().toISOString(), games: slim(await r.json()) }); }
    catch { return new Response('{"error":"upstream"}', { status: 502, headers: HEADERS }); }
    const res = new Response(body, { headers: { ...HEADERS, "cache-control": "public, max-age=10" } });
    ctx.waitUntil(cache.put(key, res.clone()));
    return res;
  },
};
