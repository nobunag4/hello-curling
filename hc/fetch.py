"""Baixador educado: cache em disco, no máximo 1 pedido por segundo e novas tentativas com espera.

Páginas de eventos encerrados não mudam, então o cache é permanente por padrão.
Use max_age para revalidar páginas que ainda podem mudar (eventos em andamento).
"""
from __future__ import annotations

import hashlib
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "raw"
USER_AGENT = "HelloCurling/0.1 (agregador pessoal, nao comercial; 1 req/s)"
MIN_INTERVAL = 1.0

_last = 0.0


def cache_path(url: str) -> Path:
    h = hashlib.sha1(url.encode()).hexdigest()
    return CACHE / h[:2] / f"{h}.html"


def get(url: str, max_age: float | None = None, retries: int = 3) -> str:
    """Devolve o HTML da URL, do cache se existir (e for novo o bastante)."""
    global _last
    p = cache_path(url)
    if p.exists() and (max_age is None or time.time() - p.stat().st_mtime < max_age):
        return p.read_text(encoding="utf-8")
    gone = p.with_suffix(".404")  # endereço que não existe (404, ou 403 em sites que escondem): lembrado por uma semana
    if gone.exists() and time.time() - gone.stat().st_mtime < 7 * 86400:
        raise urllib.error.HTTPError(url, 404, "Not Found (cache)", None, None)

    delay = 2.0
    for attempt in range(retries):
        wait = MIN_INTERVAL - (time.monotonic() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", errors="replace")
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(body, encoding="utf-8")
            tmp.replace(p)
            with (CACHE / "index.tsv").open("a", encoding="utf-8") as idx:
                idx.write(f"{p.name}\t{url}\n")
            return body
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                gone.parent.mkdir(parents=True, exist_ok=True)
                gone.write_text(url)
                raise
            if attempt == retries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
        time.sleep(delay)
        delay *= 2
    raise RuntimeError("inalcançável")
