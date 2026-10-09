"""Monta a versão do site para hospedagem comum (GitHub Pages) em _site/.

site/index.html é escrito no formato de página do claude.ai (sem <html>/<head>), que completa o esqueleto
ao publicar. Aqui completamos o esqueleto nós mesmos e copiamos os dados.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HEAD = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="Um jeito fácil de acompanhar o curling: jogos, agenda, seus times e o histórico completo de atletas e seleções.">
<meta name="color-scheme" content="light dark">
<link rel="icon" href="img/favicon.ico" sizes="48x48">
<link rel="icon" type="image/png" href="img/logo-192.png">
<link rel="apple-touch-icon" href="img/apple-touch-icon.png">
<meta property="og:type" content="website">
<meta property="og:url" content="https://hellocurling.com/">
<link rel="canonical" href="https://hellocurling.com/">
<meta property="og:title" content="Hello, Curling">
<meta property="og:description" content="Um jeito fácil de acompanhar o curling.">
<meta property="og:image" content="https://hellocurling.com/img/og.jpg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>
"""


def build(out: Path = ROOT / "_site") -> Path:
    src = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    m = re.search(r"</style>\s*", src)  # fim do bloco de estilos: o resto é o corpo
    head_part, body_part = src[: m.end()], src[m.end():]
    html = HEAD + head_part + "</head>\n<body>\n" + body_part + "\n</body>\n</html>\n"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    if (ROOT / "site" / "data").exists():
        shutil.copytree(ROOT / "site" / "data", out / "data")
    if (ROOT / "site" / "img").exists():
        shutil.copytree(ROOT / "site" / "img", out / "img")
    (out / ".nojekyll").write_text("")
    return out


if __name__ == "__main__":
    print(build())
