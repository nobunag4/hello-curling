"""Grava no banco o que os leitores extraíram das fontes. Cada evento é regravado por inteiro (idempotente)."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime

from . import identity
from .sources import wcf


def season_of(d: str | None, year: int | None = None) -> str | None:
    """Temporada de curling vai de agosto a julho: 2025-10-07 -> '2025-26'."""
    if d:
        y, m = int(d[:4]), int(d[5:7])
    elif year:
        y, m = year, 1
    else:
        return None
    start = y if m >= 8 else y - 1
    return f"{start}-{str(start + 1)[2:]}"


def stage_of(draw: str | None) -> str:
    d = (draw or "").lower()
    if re.match(r"draw #?\d+", d) or d.startswith("session") or d.startswith("round robin"):
        return "round_robin"
    if "tie" in d:
        return "tiebreaker"
    if "bronze" in d:
        return "bronze"
    if "gold" in d or "silver" in d or d in ("final", "finals") or d.startswith("final"):
        return "final"
    return "playoff"


def ingest_wcf_event(con: sqlite3.Connection, meta: dict, details: dict, games: list[dict]) -> dict:
    tid = meta["tid"]
    eid = f"wcf:{tid}"
    type_name, discipline = wcf.TYPES.get(meta.get("type_id"), (meta.get("type_name"), "teams"))
    if meta.get("division") == "Mixed Doubles":
        discipline = "mixed_doubles" if discipline == "teams" else discipline

    start = details.get("start") or meta.get("start")
    end = details.get("end") or meta.get("end")
    finished = bool(end) and end < date.today().isoformat()
    complete = finished and bool(games) and all(s["total"] is not None for g in games for s in g["sides"])

    # regrava o evento do zero
    old_entries = [r[0] for r in con.execute("SELECT id FROM entry WHERE event_id=?", (eid,))]
    con.execute("DELETE FROM game_player WHERE game_id IN (SELECT id FROM game WHERE event_id=?)", (eid,))
    con.execute("DELETE FROM game WHERE event_id=?", (eid,))
    if old_entries:
        con.execute(f"DELETE FROM entry_member WHERE entry_id IN ({','.join('?' * len(old_entries))})", old_entries)
    con.execute("DELETE FROM entry WHERE event_id=?", (eid,))
    con.execute(
        "INSERT OR REPLACE INTO event(id, source, type_id, type_name, discipline, division, name, year, season, venue, city, country, "
        "start_date, end_date, complete, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (eid, "wcf", meta.get("type_id"), type_name, discipline, details.get("division") or meta.get("division"),
         details.get("title") or meta.get("name"), meta.get("year"), season_of(start, meta.get("year")),
         details.get("venue"), details.get("city") or meta.get("city"), meta.get("country"), start, end,
         int(complete), datetime.now().isoformat(timespec="seconds")))

    group_of = {n: g for g, names_ in details.get("groups", {}).items() for n in names_}
    entry_ids: dict[str, int] = {}

    def entry_for(name: str, code: str | None = None, **kw) -> int:
        if name in entry_ids:
            return entry_ids[name]
        cur = con.execute("INSERT INTO entry(event_id, name, nation, rank, wins, losses, grp) VALUES (?,?,?,?,?,?,?)",
                          (eid, name, code, kw.get("rank"), kw.get("wins"), kw.get("losses"), group_of.get(name)))
        entry_ids[name] = cur.lastrowid
        return cur.lastrowid

    for e in details.get("entries", []):
        code = e["code"] or details["lineups"].get(e["name"], {}).get("code")
        eid_ = entry_for(e["name"], code, rank=e["rank"], wins=e["wins"], losses=e["losses"])
        lineup = details["lineups"].get(e["name"], {}).get("members")
        members = lineup or [{"pid": p["pid"], "name": p["name"], "role": "player", "skip": p["skip"], "label": None} for p in e["players"]]
        for i, m in enumerate(members):
            pid = identity.person_for_wcf(con, m["pid"], m["name"])
            con.execute("INSERT OR IGNORE INTO entry_member(entry_id, person_id, role, is_skip, ord, label) VALUES (?,?,?,?,?,?)",
                        (eid_, pid, m["role"], int(m["skip"]), i, m.get("label")))
            _gender_from_label(con, pid, m.get("label"))
    # times que aparecem nas escalações mas não na classificação
    for name, lu in details.get("lineups", {}).items():
        if name not in entry_ids:
            eid_ = entry_for(name, lu.get("code"))
            for i, m in enumerate(lu["members"]):
                pid = identity.person_for_wcf(con, m["pid"], m["name"])
                con.execute("INSERT OR IGNORE INTO entry_member(entry_id, person_id, role, is_skip, ord, label) VALUES (?,?,?,?,?,?)",
                            (eid_, pid, m["role"], int(m["skip"]), i, m.get("label")))

    for i, g in enumerate(games, 1):
        if len(g["sides"]) != 2:
            continue
        a, b = g["sides"]
        e1, e2 = entry_for(a["name"]), entry_for(b["name"])
        gid = f"{eid}:{i}"
        hammer = 1 if a["hammer"] else 2 if b["hammer"] else None
        con.execute("INSERT INTO game(id, event_id, ord, draw, stage, start_local, sheet, entry1, entry2, score1, score2, hammer, ends1, ends2) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (gid, eid, i, g["draw"], stage_of(g["draw"]), g["when"], g["sheet"], e1, e2, a["total"], b["total"], hammer,
                     json.dumps(a["ends"]), json.dumps(b["ends"])))
        for side, ent in ((a, e1), (b, e2)):
            for m in side["lineup"]:
                pid = identity.person_for_wcf(con, m["pid"], m["name"])
                con.execute("INSERT OR IGNORE INTO game_player(game_id, entry_id, person_id, role, is_skip, played) VALUES (?,?,?,?,?,?)",
                            (gid, ent, pid, m["role"], int(m["skip"]), None if m["played"] is None else int(m["played"])))
    return {"event": eid, "entries": len(entry_ids), "games": len(games), "complete": complete}


def _gender_from_label(con, pid: int, label: str | None) -> None:
    """Nas duplas mistas a escalação diz 'Male' / 'Female': aproveitamos para preencher o gênero."""
    if label in ("Male", "Female"):
        con.execute("UPDATE person SET gender=? WHERE id=? AND gender IS NULL", ("M" if label == "Male" else "F", pid))


def update_person_profile(con: sqlite3.Connection, person_id: int, prof: dict) -> None:
    con.execute("UPDATE person SET gender=COALESCE(?, gender), born=COALESCE(?, born), delivery=COALESCE(?, delivery), "
                "nations=?, profile_at=datetime('now') WHERE id=?",
                (prof.get("gender"), prof.get("born"), prof.get("delivery"), json.dumps(prof.get("nations") or []), person_id))
    if prof.get("name"):
        identity.add_name(con, person_id, prof["name"], "wcf-profile")
        con.execute("UPDATE person SET name=? WHERE id=?", (identity.names.display(prof["name"]), person_id))
