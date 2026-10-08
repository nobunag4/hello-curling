"""Fotos de atletas com licença livre: Wikidata + Wikimedia Commons.

O Wikidata guarda o código oficial da World Curling de cada atleta (propriedade P3557), o mesmo código que é a
âncora de identidade no nosso banco. Então a foto (propriedade P18) chega ligada à pessoa certa sem depender
de comparar nomes. Do Commons vêm a miniatura, o autor e a licença, que mostramos como crédito.
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request

UA = "HelloCurling/0.1 (https://github.com/nobunag4/hello-curling; agregador de curling sem fins comerciais)"
SPARQL = "https://query.wikidata.org/sparql"
COMMONS = "https://commons.wikimedia.org/w/api.php"
THUMB_WIDTH = 330  # largura padrão de miniatura do Commons (larguras fora do padrão são recusadas)

QUERY = """
SELECT ?item ?wcf ?img WHERE {
  ?item wdt:P3557 ?wcf ;
        wdt:P18 ?img .
}
"""


def _get(url: str, params: dict | None = None, accept: str = "application/json", retries: int = 4) -> bytes:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    for k in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception:
            if k == retries - 1:
                raise
            time.sleep(3 * (k + 1))
    raise RuntimeError("inalcançável")


def athletes_with_photo() -> list[dict]:
    """[{qid, wcf, file}] para todo atleta do Wikidata que tem código da World Curling e foto."""
    data = json.loads(_get(SPARQL, {"query": QUERY, "format": "json"}, "application/sparql-results+json"))
    out, seen = [], set()
    for b in data["results"]["bindings"]:
        wcf = b["wcf"]["value"].strip()
        if not wcf.isdigit():
            continue
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        file = urllib.parse.unquote(b["img"]["value"].rsplit("/", 1)[-1]).replace("_", " ")
        if (qid, wcf) in seen:  # pessoa com várias fotos: fica a primeira
            continue
        seen.add((qid, wcf))
        out.append({"qid": qid, "wcf": int(wcf), "file": file})
    return out


def _plain(markup: str | None) -> str | None:
    if not markup:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", "", markup))
    return re.sub(r"\s+", " ", text).strip() or None


def _author(artist: str | None, credit: str | None) -> str | None:
    """Nome curto para o crédito. 'Credit' às vezes traz um aviso jurídico inteiro: aí fica sem nome
    (o crédito aponta para a página do arquivo, que tem todos os detalhes)."""
    for v in (artist, credit):
        if v and re.fullmatch(r"https?://\S+", v):  # só um endereço: fica o nome do site
            v = urllib.parse.urlparse(v).netloc.removeprefix("www.")
        if v and len(v) <= 80 and "license" not in v.lower():
            return v
    return None


def image_info(files: list[str]) -> dict[str, dict]:
    """Miniatura, autor e licença de cada arquivo do Commons (em lotes de 50)."""
    out = {}
    for i in range(0, len(files), 50):
        batch = files[i:i + 50]
        data = json.loads(_get(COMMONS, {
            "action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url|extmetadata",
            "iiurlwidth": THUMB_WIDTH, "titles": "|".join("File:" + f for f in batch),
        }))
        q = data.get("query", {})
        back = {n["to"]: n["from"] for n in q.get("normalized", [])}
        for page in q.get("pages", {}).values():
            ii = (page.get("imageinfo") or [None])[0]
            if not ii:
                continue
            title = back.get(page["title"], page["title"])
            meta = ii.get("extmetadata", {})
            val = lambda k: (meta.get(k) or {}).get("value")
            out[title.removeprefix("File:")] = {
                "thumb": ii.get("thumburl") or ii.get("url"),
                "page": ii.get("descriptionurl"),
                "author": _author(_plain(val("Artist")), _plain(val("Credit"))),
                "license": _plain(val("LicenseShortName")),
                "license_url": val("LicenseUrl"),
            }
        time.sleep(1)
    return out


def download(url: str) -> bytes:
    return _get(url, accept="image/*")
