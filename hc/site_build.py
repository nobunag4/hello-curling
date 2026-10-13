"""Monta a versão do site para hospedagem comum (GitHub Pages) em _site/.

site/index.html é escrito no formato de página do claude.ai (sem <html>/<head>), que completa o esqueleto
ao publicar. Aqui completamos o esqueleto nós mesmos e copiamos os dados.

Cada atleta, cada seleção e cada par de seleções que já se enfrentou ganha o seu endereço (/atleta/{id}-{nome},
/selecao/{código}, /confronto/{a}-{b}), com título,
descrição e prévia de compartilhamento próprios, para o Google e para o WhatsApp. Todas essas páginas são
o mesmo site; o código e o estilo ficam em arquivos compartilhados (app.*.js / app.*.css), senão cada
uma das ~9 mil páginas repetiria os 150 KB do site inteiro.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://hellocurling.com"
HOME_TITLE = "Hello, Curling"
HOME_DESC = "Um jeito fácil de acompanhar o curling: jogos, agenda, seus times e o histórico completo de atletas e seleções."

HEAD = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta name="color-scheme" content="light dark">
<link rel="icon" href="/img/favicon.ico" sizes="48x48">
<link rel="icon" type="image/png" href="/img/logo-192.png">
<link rel="apple-touch-icon" href="/img/apple-touch-icon.png">
<link rel="canonical" href="{url}">{robots}
<meta property="og:type" content="{og_type}">
<meta property="og:site_name" content="Hello, Curling">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="{image}">{image_size}
<meta name="twitter:card" content="{card}">{ld}
<script type="module" src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='{{"token": "d2b08aa80f7a47afa17f896c7953a440"}}'></script>
<style>:root{{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}}body{{margin:0}}img{{max-width:100%}}[hidden]{{display:none!important}}</style>
<link rel="stylesheet" href="/{css}">
<script>window.HC_ROUTES = true;</script>
</head>
<body{body_attr}>
"""


# letras que não se decompõem em letra + acento (igual à tabela LETTERS da página)
LETTERS = str.maketrans({"ł": "l", "đ": "d", "ø": "o", "æ": "ae", "œ": "oe", "ß": "ss", "þ": "th", "ı": "i"})


def slugify(s: str) -> str:
    """Igual ao slugify da página (norm + troca do que não é letra/número por hífen)."""
    s = re.sub("[\\u0300-\\u036f]", "", unicodedata.normalize("NFD", s)).lower().translate(LETTERS)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _absolute(s: str) -> str:
    """Endereços relativos viram absolutos, para funcionarem também em /atleta/... e /selecao/..."""
    return re.sub(r"""(["'`])(data|img)/""", r"\1/\2/", s)


SHEET_CLOSED = '<div class="sheet" id="sheet" hidden>'
SHEET_OPEN = '<div class="sheet" id="sheet">'
SHEET_BODY = '<div id="sheet-body"></div>'
ROLE_PT = {"fourth": "quarto", "third": "terceiro", "second": "segundo", "lead": "lead", "alternate": "reserva", "player": "atleta",
           "coach": "técnico", "official": "dirigente"}
DIV_PT = {"Men": "masculino", "Women": "feminino", "Mixed Doubles": "duplas mistas", "Mixed": "misto"}
CAT_PT = {"m": "Masculino", "w": "Feminino", "md": "Duplas mistas", "x": "Misto", "jm": "Juvenil masculino", "jw": "Juvenil feminino",
          "jmd": "Juvenil duplas mistas", "sm": "Sênior masculino", "sw": "Sênior feminino", "smd": "Sênior duplas mistas",
          "wcx": "Cadeira de rodas", "wcmd": "Cadeira de rodas, duplas mistas"}
STAGE_PT = {"round_robin": "fase de grupos", "playoff": "mata-mata", "tiebreaker": "desempate", "bronze": "disputa do bronze",
            "final": "final", "classification": "classificação"}
MEDAL_PT = {1: "ouro", 2: "prata", 3: "bronze"}
LIST_MAX = 120   # linhas de carreira/jogos escritas na página; o resto o site mostra ao carregar
PEOPLE_MAX = 60  # atletas listados na página de uma seleção


def _ld_json(x) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _crumbs(*items: tuple[str, str]) -> dict:
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i, "name": n, "item": SITE + u} for i, (n, u) in enumerate((("Hello, Curling", "/"),) + items, 1)]}


def _pre(body: str) -> str:
    return SHEET_BODY.replace("></div>", f'><article class="pre">{body}</article></div>')


def person_path(pid: int, name: str) -> str:
    return f"/atleta/{pid}-{slugify(name)}/"


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _nation_pt(src: str) -> dict[str, str]:
    block = re.search(r"const NATION_PT = \{(.*?)\};", src, re.S)
    return dict(re.findall(r'([A-Z]{3}):"([^"]+)"', block.group(1))) if block else {}


def _types_pt(src: str) -> dict[int, str]:
    block = re.search(r"const PT_TYPES = \{(.*?)\};", src, re.S)
    return {int(k): v for k, v in re.findall(r'(\d+): "([^"]+)"', block.group(1))} if block else {}


def _page(shell: str, *, title: str, desc: str, path: str, og_title: str | None = None, image: str | None = None,
          og_type: str = "website", noindex: bool = False, css: str, pre: str | None = None, ld: list | None = None) -> str:
    e = lambda s: html.escape(s, quote=True)
    big = image is None
    if pre:  # a ficha já vem aberta, com o essencial escrito; o site completa quando carrega
        shell = shell.replace(SHEET_CLOSED, SHEET_OPEN, 1).replace(SHEET_BODY, pre, 1)
    ld_tags = "".join(f'\n<script type="application/ld+json">{_ld_json(x)}</script>' for x in ld or [])
    head = HEAD.format(ld=ld_tags, body_attr=' style="overflow:hidden"' if pre else "",
        title=e(title), desc=e(desc), url=e(SITE + path), og_title=e(og_title or title), og_type=og_type, css=css,
        image=e(image or SITE + "/img/og.jpg"), card="summary_large_image" if big else "summary",
        image_size='\n<meta property="og:image:width" content="1200">\n<meta property="og:image:height" content="630">' if big else "",
        robots='\n<meta name="robots" content="noindex">' if noindex else "",
    )
    return head + shell


def _medals_txt(g: int, s: int, b: int) -> str:
    meds = [_plural(g, "ouro", "ouros"), _plural(s, "prata", "pratas"), _plural(b, "bronze", "bronzes")]
    return ", ".join(m for m, k in zip(meds, (g, s, b)) if k)


def _nation_link(code: str, nname) -> str:
    return f'<a href="/selecao/{code.lower()}/">{html.escape(nname(code))}</a>'


def _pairs(data: Path, nname, types_pt: dict[int, str]) -> list[tuple[str, dict]]:
    """Páginas de confronto direto, uma por par que já se enfrentou (somando todas as categorias)."""
    e = html.escape
    out = []
    for f in sorted((data / "vs").glob("*.json")):
        v = json.loads(f.read_text(encoding="utf-8"))
        a = v["code"]
        tot, by_cat, games = defaultdict(lambda: [0, 0]), defaultdict(dict), defaultdict(list)
        for cat, c in v["cats"].items():
            for o, r in c["vs"].items():
                tot[o][0] += r["w"]
                tot[o][1] += r["l"]
                by_cat[o][cat] = (r["w"], r["l"])
                games[o] += [(g, cat) for g in r["all"]]
        for b, (w, l) in sorted(tot.items()):
            if a >= b:  # cada par uma vez, em ordem alfabética
                continue
            na, nb, n = nname(a), nname(b), w + l
            desc = (f"{na} {w} x {l} {nb} em {_plural(n, 'jogo', 'jogos')} de campeonatos da World Curling. "
                    "Todos os confrontos, maiores vitórias e placar por end.")
            path = f"/confronto/{a.lower()}-{b.lower()}"
            gl = sorted(games[b], key=lambda x: -x[0][0])
            rows = "".join(
                f"<li><b>{g[0]}</b> {e(types_pt.get(g[1]) or v['types'].get(str(g[1]), ''))} · {e(CAT_PT.get(cat, cat).lower())}"
                f" · {STAGE_PT.get(g[2], g[2])}: {e(na)} {g[4]} x {g[5]} {e(nb)}</li>" for g, cat in gl[:LIST_MAX])
            cats = "".join(f"<li><b>{CAT_PT.get(c, c)}</b>: {cw} x {cl}</li>" for c, (cw, cl) in by_cat[b].items())
            pre = (f'<p class="pre-k"><a href="/">Hello, Curling</a> › Confronto direto</p><h1>{e(na)} x {e(nb)}</h1>'
                   f"<p>{_nation_link(a, nname)} {w} x {l} {_nation_link(b, nname)} em {_plural(n, 'jogo', 'jogos')} de campeonatos da World Curling.</p>"
                   f"<h2>Por categoria</h2><ul>{cats}</ul><h2>Todos os jogos</h2><ul>{rows}</ul>")
            out.append((path, {"title": f"{na} x {nb} no curling · Hello, Curling", "og_title": f"{na} x {nb} no curling", "desc": desc,
                               "pre": _pre(pre), "ld": [_crumbs((f"{na} x {nb}", path + "/"))]}))
    return out


def _person_page(p: dict, nname, photo: str | None) -> tuple[str, dict]:
    e = html.escape
    play = [c for c in p["career"] if c["role"] not in ("coach", "official")]
    meds = [sum(1 for c in play if c.get("medal") == m) for m in (1, 2, 3)]
    medal_txt = _medals_txt(*meds)
    where = " / ".join(nname(c) for c in p["nations"])
    desc = (f"{p['name']} ({where}) no curling: {_plural(len(play), 'campeonato', 'campeonatos')}, {_plural(p['games'], 'jogo', 'jogos')}"
            + (f", {medal_txt}" if medal_txt else "") + ". Carreira completa, parceiros de time e resultados.")
    path = person_path(p["id"], p["name"]).rstrip("/")

    def row(c):
        team = f"Grand Slam · Team {c['team']}" if c.get("slam") else nname(c["nation"]) if c.get("nation") else c.get("team") or ""
        bits = [x for x in (DIV_PT.get(c.get("division"), c.get("division")), ROLE_PT.get(c["role"], c["role"]) + (" (skip)" if c.get("skip") else "")) if x]
        res = (f"{c['rank']}º lugar" if c.get("rank") else "") + (f", {MEDAL_PT[c['medal']]}" if c.get("medal") in MEDAL_PT else "")
        wl = f"{c['w']}–{c['l']}" if c.get("w") is not None and c["role"] not in ("coach", "official") else ""
        return (f"<li><b>{c['year']}</b> {e(c['name'])} · {e(team)} · {e(', '.join(bits))}"
                + "".join(f" · {x}" for x in (res, wl) if x) + "</li>")

    nations = ", ".join(_nation_link(c, nname) for c in p["nations"])
    rec = f"{_plural(p['games'], 'jogo', 'jogos')}, {_plural(p.get('wins', 0), 'vitória', 'vitórias')}" if p["games"] else ""
    summary = " · ".join(x for x in (nations, _plural(len(play), "campeonato", "campeonatos") if play else "", rec, medal_txt) if x)
    mates = "".join(f'<li><a href="{person_path(q, nm)}">{e(nm)}</a> · {_plural(n, "campeonato", "campeonatos")} juntos</li>'
                    for q, n, nm in p.get("mates", [])[:24])
    pre = (f'<p class="pre-k"><a href="/">Hello, Curling</a> › Atletas</p><h1>{e(p["name"])}</h1><p>{summary}</p>'
           f"<h2>Carreira</h2><ul>{''.join(row(c) for c in p['career'][:LIST_MAX])}</ul>"
           + (f"<h2>Parceiros de time</h2><ul>{mates}</ul>" if mates else ""))
    person = {"@context": "https://schema.org", "@type": "Person", "name": p["name"], "url": SITE + path + "/",
              "nationality": [{"@type": "Country", "name": nname(c)} for c in p["nations"]], "knowsAbout": "Curling"}
    if p.get("gender") in ("M", "F"):
        person["gender"] = "Male" if p["gender"] == "M" else "Female"
    if photo:
        person["image"] = f"{SITE}/img/people/{photo}"
    if p.get("wcf"):
        person["sameAs"] = [f"https://results.worldcurling.org/Person/Details/{p['wcf']}"]
    return path, {"title": f"{p['name']} · Hello, Curling", "og_title": p["name"], "desc": desc, "og_type": "profile",
                  "image": f"{SITE}/img/people/{photo}" if photo else None, "pre": _pre(pre),
                  "ld": [person, _crumbs((p["name"], path + "/"))]}


def _nation_page(n: dict, nat: dict, nname, rivals: list[tuple[str, int, int]]) -> tuple[str, dict]:
    e = html.escape
    code, name = n["code"], nname(n["code"])
    medal_txt = _medals_txt(n["gold"], n["silver"], n["bronze"])
    desc = (f"{name} no curling: {_plural(n['entries'], 'campeonato', 'campeonatos')} desde {n['first']}"
            + (f", com {medal_txt}" if medal_txt else "") + ". Melhores resultados, atletas e jogos recentes.")
    path = f"/selecao/{code.lower()}"
    hist = "".join(
        f"<li><b>{h['year']}</b> {e(h['name'])} · {e(DIV_PT.get(h.get('division'), h.get('division') or ''))}"
        + (f" · {h['rank']}º lugar" if h.get("rank") else "") + (f", {MEDAL_PT[h['medal']]}" if h.get("medal") in MEDAL_PT else "")
        + f" · {h['w']}–{h['l']}</li>" for h in nat["history"][:LIST_MAX])
    # quem mais jogou pela seleção
    people = sorted((p for p in nat["people"].values() if code in p["nations"]), key=lambda p: (-p["games"], p["name"]))[:PEOPLE_MAX]
    plist = "".join(f'<li><a href="{person_path(p["id"], p["name"])}">{e(p["name"])}</a> · {_plural(p["games"], "jogo", "jogos")}</li>' for p in people)
    rlist = "".join(f'<li><a href="/confronto/{"-".join(sorted((code.lower(), o.lower())))}/">{e(name)} x {e(nname(o))}</a> · {w} x {l}</li>'
                    for o, w, l in rivals)
    pre = (f'<p class="pre-k"><a href="/">Hello, Curling</a> › Seleções</p><h1>{e(name)}</h1>'
           f"<p>{_plural(n['entries'], 'campeonato', 'campeonatos')} da World Curling, de {n['first']} a {n['last']}"
           + (f" · {medal_txt}" if medal_txt else "") + "</p>"
           f"<h2>Campeonatos</h2><ul>{hist}</ul>" + (f"<h2>Atletas</h2><ul>{plist}</ul>" if plist else "")
           + (f"<h2>Confrontos diretos</h2><ul>{rlist}</ul>" if rlist else ""))
    team = {"@context": "https://schema.org", "@type": "SportsTeam", "name": f"{name} (curling)", "sport": "Curling", "url": SITE + path + "/"}
    return path, {"title": f"{name} no curling · Hello, Curling", "og_title": f"{name} no curling", "desc": desc,
                  "pre": _pre(pre), "ld": [team, _crumbs((name, path + "/"))]}


def _rivals(data: Path, code: str, n: int = 12) -> list[tuple[str, int, int]]:
    f = data / "vs" / f"{code}.json"
    if not f.exists():
        return []
    tot = defaultdict(lambda: [0, 0])
    for c in json.loads(f.read_text(encoding="utf-8"))["cats"].values():
        for o, r in c["vs"].items():
            tot[o][0] += r["w"]
            tot[o][1] += r["l"]
    return [(o, w, l) for o, (w, l) in sorted(tot.items(), key=lambda x: -sum(x[1]))[:n]]


def _profiles(data: Path, names_pt: dict[str, str], types_pt: dict[int, str] | None = None):
    """Páginas de atletas, seleções e confrontos: (endereço, campos do <head> e da ficha já aberta)."""
    index = json.loads((data / "index.json").read_text(encoding="utf-8"))
    photos = index.get("photos", {})
    nat_en = {n["code"]: n["name"] for n in index["nations"]}
    nname = lambda c: names_pt.get(c) or nat_en.get(c) or c
    people: dict[int, dict] = {}
    nations = []
    for n in index["nations"]:
        f = data / "nation" / f"{n['code']}.json"
        if not f.exists():
            continue
        nat = json.loads(f.read_text(encoding="utf-8"))
        for p in nat["people"].values():
            people.setdefault(p["id"], p)
        nations.append(_nation_page(n, nat, nname, _rivals(data, n["code"])))
    athletes = []
    for pid, p in sorted(people.items()):
        if not p["career"]:
            continue
        ph = photos.get(str(pid))
        athletes.append(_person_page(p, nname, ph[0] if ph else None))
    pairs = _pairs(data, nname, types_pt or {}) if (data / "vs").exists() else []
    return athletes, nations, pairs


def _nations_nav(data: Path, nname) -> str:
    """Todas as seleções no rodapé: um caminho para cada uma a partir de qualquer página."""
    index = json.loads((data / "index.json").read_text(encoding="utf-8"))
    links = sorted(((nname(n["code"]), n["code"]) for n in index["nations"]), key=lambda x: unicodedata.normalize("NFD", x[0]))
    return ('<nav class="fnats" aria-label="Seleções">' + " ".join(f'<a href="/selecao/{c.lower()}/" data-nation="{c}">{html.escape(nm)}</a>' for nm, c in links)
            + "</nav>\n")


def version() -> str:
    """Identifica o código do site (página + montagem). Vai para /version.txt; o robô compara com o que está no ar
    para republicar quando uma publicação se perdeu (ex.: cancelada na fila do GitHub)."""
    h = hashlib.sha256()
    for f in (ROOT / "site" / "index.html", Path(__file__)):
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def build(out: Path = ROOT / "_site") -> Path:
    src = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    style = re.search(r"<style>(.*?)</style>", src, re.S)
    script = re.search(r"<script>(.*)</script>", src, re.S)
    css_text, js_text = style.group(1), _absolute(script.group(1))
    markup = _absolute(src[style.end():script.start()])
    tag = lambda s: hashlib.sha256(s.encode()).hexdigest()[:10]
    css, js = f"app.{tag(css_text)}.css", f"app.{tag(js_text)}.js"
    shell = markup + f'<script src="/{js}"></script>\n</body>\n</html>\n'
    data = ROOT / "site" / "data"
    if (data / "index.json").exists():
        nat_en = {n["code"]: n["name"] for n in json.loads((data / "index.json").read_text(encoding="utf-8"))["nations"]}
        names_pt = _nation_pt(src)
        shell = shell.replace("</footer>", _nations_nav(data, lambda c: names_pt.get(c) or nat_en.get(c) or c) + "</footer>", 1)

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / css).write_text(css_text, encoding="utf-8")
    (out / js).write_text(js_text, encoding="utf-8")
    (out / "index.html").write_text(_page(shell, title=HOME_TITLE, desc=HOME_DESC, path="/", css=css, ld=[
        {"@context": "https://schema.org", "@type": "WebSite", "name": HOME_TITLE, "url": SITE + "/", "inLanguage": "pt-BR"}]), encoding="utf-8")
    (out / "404.html").write_text(_page(shell, title=HOME_TITLE, desc=HOME_DESC, path="/", noindex=True, css=css), encoding="utf-8")
    if data.exists():
        shutil.copytree(data, out / "data")
    if (ROOT / "site" / "img").exists():
        shutil.copytree(ROOT / "site" / "img", out / "img")

    urls = ["/"]
    if (data / "index.json").exists():
        athletes, nations, pairs = _profiles(data, _nation_pt(src), _types_pt(src))
        for path, fields in nations + pairs + athletes:
            d = out / path.lstrip("/")
            d.mkdir(parents=True, exist_ok=True)
            (d / "index.html").write_text(_page(shell, path=path + "/", css=css, **fields), encoding="utf-8")
            urls.append(path + "/")
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"<url><loc>{SITE}{u}</loc></url>\n" for u in urls) + "</urlset>\n", encoding="utf-8")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n", encoding="utf-8")
    (out / "version.txt").write_text(version() + "\n")
    (out / ".nojekyll").write_text("")
    return out


if __name__ == "__main__":
    print(build())
