"""Baixa as fotos livres dos atletas (Wikidata + Commons) para site/img/people/<id da pessoa>.<ext>.

Só baixa de novo quando a foto escolhida no Wikidata muda. Quem perdeu a foto no Wikidata perde aqui também.
"""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .db import ROOT
from .sources import wikimedia

OUT = ROOT / "site" / "img" / "people"
MAX_BYTES = 400_000


def _shrink(path: Path) -> None:
    """JPEG leve de até 330x440, cortado de cima (onde fica o rosto). O Commons às vezes devolve PNG com nome .jpg."""
    magick = shutil.which("magick") or shutil.which("convert")
    if not magick:
        return
    tmp = path.with_suffix(".tmp")
    subprocess.run([magick, str(path), "-background", "white", "-alpha", "remove", "-alpha", "off", "-strip",
                    "-resize", "330x>", "-gravity", "north", "-crop", "330x440+0+0", "+repage",
                    "-sampling-factor", "4:2:0", "-interlace", "JPEG", "-quality", "78", f"JPG:{tmp}"], check=True)
    tmp.replace(path)


def run(con: sqlite3.Connection, out: Path = OUT, limit: int | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    wanted = wikimedia.athletes_with_photo()
    by_wcf = {r["wcf_id"]: (r["merged_into"] or r["id"]) for r in con.execute("SELECT id, wcf_id, merged_into FROM person WHERE wcf_id IS NOT NULL")}
    pick = {}
    for w in wanted:
        pid = by_wcf.get(w["wcf"])
        if pid and pid not in pick:
            pick[pid] = w
    have = {r["person_id"]: dict(r) for r in con.execute("SELECT * FROM photo")}
    todo = [pid for pid, w in pick.items() if not (pid in have and have[pid]["file"] == w["file"] and (out / have[pid]["path"]).exists())]
    if limit:
        todo = todo[:limit]
    info = wikimedia.image_info(sorted({pick[p]["file"] for p in todo}))
    stats = {"wikidata": len(wanted), "ligadas": len(pick), "baixadas": 0, "falhas": 0, "removidas": 0}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for pid in todo:
        w, meta = pick[pid], info.get(pick[pid]["file"])
        if not meta or not meta["thumb"]:
            stats["falhas"] += 1
            continue
        try:
            blob = wikimedia.download(meta["thumb"])
        except Exception as e:
            print(f"  falhou {w['file']}: {e}")
            stats["falhas"] += 1
            continue
        if len(blob) > MAX_BYTES:
            stats["falhas"] += 1
            continue
        path = f"{pid}.jpg"
        if pid in have and have[pid]["path"] != path:
            (out / have[pid]["path"]).unlink(missing_ok=True)
        (out / path).write_bytes(blob)
        try:
            _shrink(out / path)
        except Exception as e:
            print(f"  não reduziu {path}: {e}")
        con.execute("INSERT OR REPLACE INTO photo (person_id, wcf_id, qid, file, path, page, author, license, license_url, fetched_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (pid, w["wcf"], w["qid"], w["file"], path, meta["page"], meta["author"], meta["license"], meta["license_url"], now))
        stats["baixadas"] += 1
        time.sleep(0.5)
    for pid, row in have.items():
        if pid not in pick:
            (out / row["path"]).unlink(missing_ok=True)
            con.execute("DELETE FROM photo WHERE person_id = ?", (pid,))
            stats["removidas"] += 1
    con.commit()
    return stats
