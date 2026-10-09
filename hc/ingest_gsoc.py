"""Grava no banco um Grand Slam encerrado (lido por hc.sources.gsoc.fetch_history).

Cada Slam vira dois eventos, um por naipe: 'gsoc:{tour}:m' e 'gsoc:{tour}:w'. Os times são do circuito
(chamados pelo sobrenome do skip, como no Slam); o país do time fica em entry.nation, mas o export não mistura
esses jogos com os das seleções.

Os jogadores do Slam não têm o código da World Curling. Cada um é ligado a uma pessoa nossa por
identity.resolve (nome, gênero, país, data de nascimento e companheiros de time). Quem não tem nenhum
candidato parecido vira pessoa nova; quem tem candidato duvidoso vai para a fila de revisão e, até ser
revisado, fica fora da escalação (nada é ligado em silêncio).
"""
from __future__ import annotations

import json
from collections import Counter
import re
import sqlite3
from datetime import datetime, timedelta

from . import identity, names
from .ingest import season_of
from .sources import gsoc

TYPE_ID, TYPE_NAME = 900, "Grand Slam of Curling"
NEW_PERSON_BELOW = 0.6   # sem candidato com nota acima disso: é gente nova no banco
STAGE = {None: "round_robin", "tb": "tiebreaker", "qf": "playoff", "sf": "playoff", "fin": "final"}
DRAW_LABEL = {"tb": "Tiebreaker", "qf": "Quarterfinal", "sf": "Semifinal", "fin": "Final"}


def _born(p: dict) -> str | None:
    d = p.get("date_of_birth") or ""
    for fmt in ("%Y-%m-%d", "%m-%d-%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(d[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return None


# Gênero: o campo do Slam não é confiável (atletas de times femininos aparecem como "m"). Vale o naipe do torneio
# para quem está na formação inscrita do time; quem só aparece na ficha de um jogo (reserva, técnico) fica sem.


ON_ICE = {"LEAD", "SECOND", "THIRD", "FOURTH", "SKIP"}


def _on_ice(p: dict, squad: list[dict]) -> bool:
    """Entrou no gelo? Pela marca de titular; nos Slams em que a ficha não marca ninguém, pela posição."""
    if any(q.get("starter") for q in squad):
        return bool(p.get("starter") or (p.get("is_substitute") and p.get("minutes_played")))
    return (p.get("position") or "").upper() in ON_ICE


def _roster_from_games(bundle: dict, tid: str) -> list[dict]:
    """Alguns Slams não publicam a formação inscrita: montamos pelas fichas dos jogos, com quem aparece em pelo
    menos duas partidas pelo time (quem apareceu uma vez, como reserva de outro time, fica de fora), na posição
    mais comum."""
    seen: dict[str, dict] = {}
    for det in bundle["details"].values():
        for t in ((det.get("teams") or {}).get("team") or []):
            if str(t.get("id")) != str(tid):
                continue
            for p in t.get("squad") or []:
                if _on_ice(p, t.get("squad") or []):
                    r = seen.setdefault(str(p.get("id")), {"p": p, "n": 0, "pos": Counter()})
                    r["n"] += 1
                    r["pos"][p.get("position")] += 1
    order = {"LEAD": 0, "SECOND": 1, "THIRD": 2, "FOURTH": 3, "SKIP": 4}
    out = [{**r["p"], "player_id": r["p"].get("id"), "position_name": r["pos"].most_common(1)[0][0]} for r in seen.values() if r["n"] >= 2]
    return sorted(out, key=lambda p: order.get(p["position_name"], 9))


class People:
    """Liga os jogadores do Slam a pessoas nossas, guardando o resultado por código do Slam."""

    def __init__(self, con: sqlite3.Connection):
        self.con, self.index, self.cache = con, identity.NameIndex(con), {}
        self.linked, self.new, self.doubt = set(), set(), set()

    def get(self, p: dict, *, div: str, nation: str | None, season: str, mates: set[int], roster: bool = False) -> int | None:
        key = str(p.get("player_id") or p.get("id"))
        if key in self.cache:
            return self.cache[key]
        name = p.get("display_name") or p.get("name") or p.get("full_name")
        if not name:
            return None
        nat = gsoc.COUNTRY.get((p.get("nationality") or "").strip()) or nation
        born, gender = _born(p), (("M" if div == "m" else "F") if roster else None)
        pid, sc = identity.resolve(self.con, "gsoc", key, name, gender=gender, nation=nat, season=season,
                                   teammates=mates, index=self.index, born=born)
        if pid is None and sc < NEW_PERSON_BELOW and self._same_name_exists(name):
            self.doubt.add(key)  # mesmo nome já existe, só divergiu em algo (gênero, data): revisão, nunca duplicar
            return None
        if pid is None and sc < NEW_PERSON_BELOW:
            pid = self.con.execute("INSERT INTO person(name, gender, born, nations) VALUES (?,?,?,?)",
                                   (name, gender, born, json.dumps([nat]) if nat else None)).lastrowid
            self.con.execute("INSERT INTO link(source, kind, key, entity_id, method, confidence, note) VALUES ('gsoc','person',?,?,'new',1.0,?)",
                             (key, pid, f"sem candidato (melhor nota {sc:.2f})"))
            self.con.execute("DELETE FROM review WHERE kind='person_link' AND json_extract(subject,'$.source')='gsoc' "
                             "AND json_extract(subject,'$.key')=?", (key,))
            identity.add_name(self.con, pid, name, "gsoc")
            self.new.add(key)
        elif pid is None:
            self.doubt.add(key)
            return None  # sem cache: na próxima rodada, com mais colegas ligados, pode resolver
        else:
            self.linked.add(key)
            if born:
                self.con.execute("UPDATE person SET born = COALESCE(born, ?) WHERE id = ?", (born, pid))
        self.cache[key] = pid
        return pid

    def _same_name_exists(self, name: str) -> bool:
        for c in self.index.candidates(name):
            for (raw,) in self.con.execute("SELECT raw FROM person_name WHERE person_id = ?", (c,)):
                if names.similarity(name, raw) >= 0.95:
                    return True
        return False

    def summary(self) -> str:
        doubt = self.doubt - self.linked - self.new
        return f"{len(self.linked)} ligados a atletas do banco, {len(self.new)} novos, {len(doubt)} para revisão"

    def squad(self, players: list[dict], *, div: str, nation: str | None, season: str) -> dict[str, int]:
        """Liga um time inteiro em duas passadas: os colegas ligados na primeira ajudam a decidir os outros."""
        out: dict[str, int] = {}
        for _ in range(2):
            for p in players:
                k = str(p.get("player_id") or p.get("id"))
                if k not in out:
                    pid = self.get(p, div=div, nation=nation, season=season, mates=set(out.values()), roster=True)
                    if pid:
                        out[k] = pid
        return out


def _local(utc: str, offset: str | None) -> str:
    t = datetime.fromisoformat(utc.replace("-00:00", "+00:00")).replace(tzinfo=None)
    m = re.fullmatch(r"([+-])(\d\d):(\d\d)", offset or "")
    if m:
        delta = timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
        t = t + delta if m.group(1) == "+" else t - delta
    return t.strftime("%Y-%m-%d %H:%M:%S")


def ingest_slam(con: sqlite3.Connection, bundle: dict, people: People) -> list[dict]:
    s = bundle["series"]
    tour, season = s["tour_id"], season_of(s["start"].isoformat())
    venue_country = None
    for d in bundle["details"].values():
        venue_country = gsoc.COUNTRY.get(((d.get("match_detail") or {}).get("venue") or {}).get("country", ""))
        if venue_country:
            break
    by_div: dict[str, list[dict]] = {}
    for m in bundle["matches"]:
        div = gsoc.division_of(m.get("event_group"))
        ps = m.get("participants") or []
        if div and len(ps) == 2 and all(gsoc._real(p.get("name", "")) for p in ps):
            by_div.setdefault(div, []).append(m)

    results = []
    for div, matches in by_div.items():
        eid = f"gsoc:{tour}:{div}"
        old = [r[0] for r in con.execute("SELECT id FROM entry WHERE event_id=?", (eid,))]
        con.execute("DELETE FROM game_player WHERE game_id IN (SELECT id FROM game WHERE event_id=?)", (eid,))
        con.execute("DELETE FROM game WHERE event_id=?", (eid,))
        if old:
            con.execute(f"DELETE FROM entry_member WHERE entry_id IN ({','.join('?' * len(old))})", old)
        con.execute("DELETE FROM entry WHERE event_id=?", (eid,))
        con.execute(
            "INSERT OR REPLACE INTO event(id, source, type_id, type_name, discipline, division, name, year, season, venue, city, country, "
            "start_date, end_date, complete, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (eid, "gsoc", TYPE_ID, TYPE_NAME, "teams", "Men" if div == "m" else "Women", s["series_name"], s["end"].year, season,
             (s.get("venues") or [{}])[0].get("name"), s.get("city"), venue_country, s["start"].isoformat(), s["end"].isoformat(), 1,
             datetime.now().isoformat(timespec="seconds")))

        # times, com a formação do torneio
        entries: dict[str, int] = {}
        roster: dict[str, dict[str, int]] = {}
        team_ids = {p["id"]: p["name"] for m in matches for p in m["participants"]}
        for tid, tname in team_ids.items():
            nation = bundle["countries"].get(tid)
            ent = con.execute("INSERT INTO entry(event_id, name, nation) VALUES (?,?,?)", (eid, gsoc._name(tname), nation)).lastrowid
            entries[tid] = ent
            sq = bundle["squads"].get(tid)
            players = ((sq or {}).get("squad") or {}).get("players") or _roster_from_games(bundle, tid)
            linked = people.squad(players, div=div, nation=nation, season=season)
            roster[tid] = linked
            for i, (p, role, skip) in enumerate(gsoc.roles(players)):
                pid = linked.get(str(p.get("player_id")))
                if pid:
                    con.execute("INSERT OR IGNORE INTO entry_member(entry_id, person_id, role, is_skip, ord) VALUES (?,?,?,?,?)",
                                (ent, pid, role, int(skip), i))

        # jogos
        rec = {tid: [0, 0] for tid in team_ids}
        place: dict[str, int] = {}
        for i, m in enumerate(sorted(matches, key=lambda m: (m["start_date"], m.get("sheet") or "")), 1):
            a, b = m["participants"]
            stage_key = gsoc.STAGE.get((m.get("stage") or "").strip().lower(), "qf")
            stage = STAGE.get(stage_key, "playoff")
            draw = m.get("match_draw") if stage_key is None else DRAW_LABEL.get(stage_key, m.get("stage"))
            sa = int(a["value"]) if str(a.get("value", "")).isdigit() else None
            sb = int(b["value"]) if str(b.get("value", "")).isdigit() else None
            ends = [e.strip().split("-") for e in (m.get("ends") or "").split(",") if re.fullmatch(r"\d+-\d+", e.strip())]
            hammer = 1 if a.get("lsfe") == "true" else 2 if b.get("lsfe") == "true" else None
            gid = f"gsoc:{tour}:{m['game_id']}"
            con.execute("INSERT INTO game(id, event_id, ord, draw, stage, start_local, sheet, entry1, entry2, score1, score2, hammer, ends1, ends2) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (gid, eid, i, draw, stage, _local(m["start_date"], m.get("venue_gmt_offset")), m.get("sheet"),
                         entries[a["id"]], entries[b["id"]], sa, sb, hammer,
                         json.dumps([int(x) for x, _ in ends]), json.dumps([int(y) for _, y in ends])))
            if sa is not None and sb is not None and sa != sb:
                win, lose = (a["id"], b["id"]) if sa > sb else (b["id"], a["id"])
                rec[win][0] += 1
                rec[lose][1] += 1
                if stage_key == "fin":
                    place[win], place[lose] = 1, 2
                elif stage_key == "sf":
                    place.setdefault(lose, 3)
                elif stage_key == "qf":
                    place.setdefault(lose, 5)
            # quem entrou no gelo, pela ficha do jogo
            det = bundle["details"].get(str(m["game_id"])) or {}
            for t in ((det.get("teams") or {}).get("team") or []):
                tid = str(t.get("id"))
                if tid not in entries:
                    continue
                for p, role, skip in gsoc.roles(t.get("squad") or []):
                    k = str(p.get("id"))
                    pid = roster.get(tid, {}).get(k) or people.get(
                        p, div=div, nation=bundle["countries"].get(tid), season=season, mates=set(roster.get(tid, {}).values()))
                    if not pid:
                        continue
                    played = int(_on_ice(p, t.get("squad") or []))
                    con.execute("INSERT OR IGNORE INTO game_player(game_id, entry_id, person_id, role, is_skip, played) VALUES (?,?,?,?,?,?)",
                                (gid, entries[tid], pid, role, int(skip), played))
        for tid, ent in entries.items():
            con.execute("UPDATE entry SET wins=?, losses=?, rank=? WHERE id=?", (rec[tid][0], rec[tid][1], place.get(tid), ent))
        results.append({"event": eid, "entries": len(entries), "games": len(matches)})
    return results
