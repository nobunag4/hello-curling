"""Monta a versão do site para hospedagem comum (GitHub Pages) em _site/.

site/index.html é escrito no formato de página do claude.ai (sem <html>/<head>), que completa o esqueleto
ao publicar. Aqui completamos o esqueleto nós mesmos e copiamos os dados.

Cada atleta e cada seleção ganha o seu endereço (/atleta/{id}-{nome}, /selecao/{código}), com título,
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
<meta name="twitter:card" content="{card}">
<script type="module" src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='{{"token": "d2b08aa80f7a47afa17f896c7953a440"}}'></script>
<style>:root{{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}}body{{margin:0}}img{{max-width:100%}}[hidden]{{display:none!important}}</style>
<link rel="stylesheet" href="/{css}">
<script>window.HC_ROUTES = true;</script>
</head>
<body>
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


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _nation_pt(src: str) -> dict[str, str]:
    block = re.search(r"const NATION_PT = \{(.*?)\};", src, re.S)
    return dict(re.findall(r'([A-Z]{3}):"([^"]+)"', block.group(1))) if block else {}


def _page(shell: str, *, title: str, desc: str, path: str, og_title: str | None = None, image: str | None = None,
          og_type: str = "website", noindex: bool = False, css: str) -> str:
    e = lambda s: html.escape(s, quote=True)
    big = image is None
    head = HEAD.format(
        title=e(title), desc=e(desc), url=e(SITE + path), og_title=e(og_title or title), og_type=og_type, css=css,
        image=e(image or SITE + "/img/og.jpg"), card="summary_large_image" if big else "summary",
        image_size='\n<meta property="og:image:width" content="1200">\n<meta property="og:image:height" content="630">' if big else "",
        robots='\n<meta name="robots" content="noindex">' if noindex else "",
    )
    return head + shell


def _profiles(data: Path, names_pt: dict[str, str]) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]]]:
    """Páginas de atletas e seleções: (endereço, campos do <head>)."""
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
        name = nname(n["code"])
        meds = [_plural(n["gold"], "ouro", "ouros"), _plural(n["silver"], "prata", "pratas"), _plural(n["bronze"], "bronze", "bronzes")]
        medal_txt = ", ".join(m for m, k in zip(meds, ("gold", "silver", "bronze")) if n[k])
        desc = (f"{name} no curling: {_plural(n['entries'], 'campeonato', 'campeonatos')} desde {n['first']}"
                + (f", com {medal_txt}" if medal_txt else "") + ". Melhores resultados, atletas e jogos recentes.")
        nations.append((f"/selecao/{n['code'].lower()}", {"title": f"{name} no curling · Hello, Curling", "og_title": f"{name} no curling",
                                                          "desc": desc}))
    athletes = []
    for pid, p in sorted(people.items()):
        play = [c for c in p["career"] if c["role"] not in ("coach", "official")]
        if not play and not p["career"]:
            continue
        meds = [sum(1 for c in play if c.get("medal") == m) for m in (1, 2, 3)]
        medal_txt = ", ".join(t for t, k in zip((_plural(meds[0], "ouro", "ouros"), _plural(meds[1], "prata", "pratas"),
                                                 _plural(meds[2], "bronze", "bronzes")), meds) if k)
        where = " / ".join(nname(c) for c in p["nations"])
        desc = (f"{p['name']} ({where}) no curling: {_plural(len(play), 'campeonato', 'campeonatos')}, {_plural(p['games'], 'jogo', 'jogos')}"
                + (f", {medal_txt}" if medal_txt else "") + ". Carreira completa, parceiros de time e resultados.")
        ph = photos.get(str(pid))
        athletes.append((f"/atleta/{pid}-{slugify(p['name'])}", {
            "title": f"{p['name']} · Hello, Curling", "og_title": p["name"], "desc": desc, "og_type": "profile",
            "image": f"{SITE}/img/people/{ph[0]}" if ph else None}))
    return athletes, nations


def build(out: Path = ROOT / "_site") -> Path:
    src = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    style = re.search(r"<style>(.*?)</style>", src, re.S)
    script = re.search(r"<script>(.*)</script>", src, re.S)
    css_text, js_text = style.group(1), _absolute(script.group(1))
    markup = _absolute(src[style.end():script.start()])
    tag = lambda s: hashlib.sha256(s.encode()).hexdigest()[:10]
    css, js = f"app.{tag(css_text)}.css", f"app.{tag(js_text)}.js"
    shell = markup + f'<script src="/{js}"></script>\n</body>\n</html>\n'

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / css).write_text(css_text, encoding="utf-8")
    (out / js).write_text(js_text, encoding="utf-8")
    (out / "index.html").write_text(_page(shell, title=HOME_TITLE, desc=HOME_DESC, path="/", css=css), encoding="utf-8")
    (out / "404.html").write_text(_page(shell, title=HOME_TITLE, desc=HOME_DESC, path="/", noindex=True, css=css), encoding="utf-8")
    data = ROOT / "site" / "data"
    if data.exists():
        shutil.copytree(data, out / "data")
    if (ROOT / "site" / "img").exists():
        shutil.copytree(ROOT / "site" / "img", out / "img")

    urls = ["/"]
    if (data / "index.json").exists():
        athletes, nations = _profiles(data, _nation_pt(src))
        for path, fields in nations + athletes:
            d = out / path.lstrip("/")
            d.mkdir(parents=True, exist_ok=True)
            (d / "index.html").write_text(_page(shell, path=path + "/", css=css, **fields), encoding="utf-8")
            urls.append(path + "/")
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"<url><loc>{SITE}{u}</loc></url>\n" for u in urls) + "</urlset>\n", encoding="utf-8")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n", encoding="utf-8")
    (out / ".nojekyll").write_text("")
    return out


if __name__ == "__main__":
    print(build())
