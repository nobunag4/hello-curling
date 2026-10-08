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
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 26 26'%3E%3Ccircle cx='13' cy='13' r='12.5' fill='%23002664'/%3E%3Ccircle cx='13' cy='13' r='9' fill='white'/%3E%3Ccircle cx='13' cy='13' r='6.2' fill='%23d80007'/%3E%3Ccircle cx='13' cy='13' r='2.6' fill='white'/%3E%3C/svg%3E">
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
    (out / ".nojekyll").write_text("")
    return out


if __name__ == "__main__":
    print(build())
