"""Ligar corretamente quem é quem.

Estratégia, da evidência mais forte para a mais fraca:

1. ÂNCORA. Toda pessoa que aparece na World Curling tem um código oficial (Person/Details/{id}).
   Esse código vira a identidade dela aqui. Troca de sobrenome (casamento), grafias diferentes
   e mudança de seleção não quebram a ligação, porque o código continua o mesmo.

2. DECISÕES MANUAIS (data/overrides.toml). Sempre vencem qualquer cálculo.

3. LIGAÇÃO AUTOMÁTICA para fontes sem código (Grand Slam, placar ao vivo...). Cada candidato recebe
   uma nota a partir de evidências independentes:
     - nome: similaridade contra todas as grafias já vistas da pessoa (names.similarity)
     - gênero: diferente elimina o candidato
     - seleção: bate (+), diverge (-)
     - atividade: pessoa sem jogos há muitas temporadas perde pontos
     - companheiros de time: se os colegas já ligados jogaram com o candidato, a nota sobe bastante.
       É a evidência mais forte depois do código: homônimos raramente têm os mesmos colegas.
   Só liga sozinho quando a nota é alta E bem acima do segundo colocado. O resto vai para a fila de revisão.

4. DUPLICATAS DENTRO DA PRÓPRIA WORLD CURLING. Os dados antigos foram montados por voluntários e às vezes
   a mesma pessoa tem dois códigos. Só fundimos sozinhos quando nome e data de nascimento coincidem e as
   duas nunca aparecem no mesmo evento. Os demais casos vão para revisão.
"""
from __future__ import annotations

import json
import sqlite3
import tomllib
from collections import defaultdict
from pathlib import Path

from . import names

OVERRIDES = Path(__file__).resolve().parent.parent / "data" / "overrides.toml"

AUTO_MIN = 0.90      # nota mínima para ligar sozinho
AUTO_MARGIN = 0.10   # vantagem mínima sobre o segundo candidato


# ------------------------------------------------------------------ âncora World Curling

def add_name(con: sqlite3.Connection, person_id: int, raw: str, source: str) -> None:
    raw = names.display(raw)
    k = names.key(raw)
    if not k:
        return
    con.execute(
        "INSERT INTO person_name(person_id, raw, key, source) VALUES (?,?,?,?) "
        "ON CONFLICT(person_id, key) DO UPDATE SET seen = seen + 1",
        (person_id, raw, k, source))


def person_for_wcf(con: sqlite3.Connection, wcf_id: int, name: str) -> int:
    row = con.execute("SELECT id FROM person WHERE wcf_id = ?", (wcf_id,)).fetchone()
    if row:
        pid = row["id"]
    else:
        pid = con.execute("INSERT INTO person(wcf_id, name) VALUES (?, ?)", (wcf_id, names.display(name))).lastrowid
        con.execute("INSERT OR IGNORE INTO link(source, kind, key, entity_id, method, confidence) VALUES ('wcf','person',?,?,'anchor',1.0)",
                    (str(wcf_id), pid))
    add_name(con, pid, name, "wcf")
    return pid


def live_id(con: sqlite3.Connection, pid: int) -> int:
    """Segue fusões: se a pessoa foi fundida em outra, devolve a que ficou."""
    seen = set()
    while pid not in seen:
        seen.add(pid)
        r = con.execute("SELECT merged_into FROM person WHERE id = ?", (pid,)).fetchone()
        if not r or r["merged_into"] is None:
            return pid
        pid = r["merged_into"]
    return pid


# ------------------------------------------------------------------ contexto de cada pessoa

def _context(con: sqlite3.Connection, pid: int) -> dict:
    p = con.execute("SELECT * FROM person WHERE id = ?", (pid,)).fetchone()
    seasons = [r[0] for r in con.execute(
        "SELECT DISTINCT e.season FROM entry_member m JOIN entry en ON en.id = m.entry_id "
        "JOIN event e ON e.id = en.event_id WHERE m.person_id = ? AND m.role NOT IN ('coach','official')", (pid,))]
    entry_nations = {r[0] for r in con.execute(
        "SELECT DISTINCT en.nation FROM entry_member m JOIN entry en ON en.id = m.entry_id WHERE m.person_id = ?", (pid,)) if r[0]}
    gender = p["gender"]
    if gender is None:  # deduz pelo naipe dos eventos disputados
        divs = {r[0] for r in con.execute(
            "SELECT DISTINCT e.division FROM entry_member m JOIN entry en ON en.id = m.entry_id "
            "JOIN event e ON e.id = en.event_id WHERE m.person_id = ? AND m.role NOT IN ('coach','official','player')", (pid,))}
        if divs == {"Men"}:
            gender = "M"
        elif divs == {"Women"}:
            gender = "F"
    nations = set(json.loads(p["nations"])) if p["nations"] else set()
    return {"id": pid, "name": p["name"], "gender": gender, "nations": nations | entry_nations,
            "last_season": max(seasons) if seasons else None,
            "aliases": [r[0] for r in con.execute("SELECT raw FROM person_name WHERE person_id = ?", (pid,))]}


def _teammates(con: sqlite3.Connection, pid: int, since_season: str | None = None) -> set[int]:
    q = ("SELECT DISTINCT m2.person_id FROM entry_member m1 JOIN entry_member m2 ON m2.entry_id = m1.entry_id "
         "JOIN entry en ON en.id = m1.entry_id JOIN event e ON e.id = en.event_id "
         "WHERE m1.person_id = ? AND m2.person_id != ?")
    args = [pid, pid]
    if since_season:
        q += " AND e.season >= ?"
        args.append(since_season)
    return {r[0] for r in con.execute(q, args)}


def _season_start(season: str | None) -> int | None:
    return int(season[:4]) if season else None


# ------------------------------------------------------------------ candidatos e nota

class NameIndex:
    """Índice em memória: token do nome -> pessoas."""

    def __init__(self, con: sqlite3.Connection):
        self.by_token: dict[str, set[int]] = defaultdict(set)
        for r in con.execute("SELECT person_id, key FROM person_name"):
            for t in r["key"].split():
                if len(t) >= 3:
                    self.by_token[t].add(r["person_id"])

    def candidates(self, name: str) -> set[int]:
        toks = [t for t in names.tokens(name) if len(t) >= 3 and t not in names._PARTICLES]
        out: set[int] = set()
        for t in toks:
            out |= self.by_token.get(t, set())
        return out


def score(con, cand: dict, name: str, gender=None, nation=None, season=None, teammates: set[int] = frozenset()) -> tuple[float, list[str]]:
    why = []
    s = max(names.similarity(name, a) for a in cand["aliases"] or [cand["name"]])
    why.append(f"nome {s:.2f}")
    if gender and cand["gender"]:
        if gender != cand["gender"]:
            return 0.0, why + ["gênero diferente"]
        s += 0.03
        why.append("mesmo gênero")
    if nation and cand["nations"]:
        if nation in cand["nations"]:
            s += 0.05
            why.append("mesma seleção")
        else:
            s -= 0.25
            why.append("seleção diferente")
    if season and cand["last_season"]:
        gap = _season_start(season) - _season_start(cand["last_season"])
        if gap > 6:
            s -= 0.15
            why.append(f"sem jogos há {gap} temporadas")
    if teammates:
        since = f"{_season_start(season) - 8}-00" if season else None
        common = teammates & _teammates(con, cand["id"], since)
        if common:
            bonus = min(0.3, 0.12 * len(common))
            s += bonus
            why.append(f"{len(common)} companheiro(s) em comum")
    return round(min(s, 1.2), 3), why


def resolve(con: sqlite3.Connection, source: str, key: str, name: str, *, gender=None, nation=None,
            season=None, teammates: set[int] = frozenset(), index: NameIndex | None = None) -> tuple[int | None, float]:
    """Liga uma pessoa de uma fonte sem código a uma pessoa nossa. Devolve (id, confiança) ou (None, nota)."""
    row = con.execute("SELECT entity_id, confidence FROM link WHERE source=? AND kind='person' AND key=?", (source, key)).fetchone()
    if row:
        return live_id(con, row["entity_id"]), row["confidence"]

    index = index or NameIndex(con)
    ranked = []
    # fichas unificadas apontam para a mesma pessoa: cada pessoa entra uma vez só na disputa
    for pid in {live_id(con, c) for c in index.candidates(name)}:
        cand = _context(con, pid)
        sc, why = score(con, cand, name, gender, nation, season, teammates)
        if sc > 0.3:
            ranked.append((sc, pid, cand["name"], why))
    ranked.sort(reverse=True)

    best = ranked[0] if ranked else None
    second = ranked[1][0] if len(ranked) > 1 else 0.0
    if best and best[0] >= AUTO_MIN and best[0] - second >= AUTO_MARGIN:
        con.execute("INSERT INTO link(source, kind, key, entity_id, method, confidence, note) VALUES (?,?,?,?,?,?,?)",
                    (source, "person", key, best[1], "auto", min(best[0], 1.0), "; ".join(best[3])))
        add_name(con, best[1], name, source)
        return best[1], min(best[0], 1.0)

    subject = json.dumps({"source": source, "key": key, "name": name, "gender": gender, "nation": nation, "season": season},
                         ensure_ascii=False, sort_keys=True)
    cands = json.dumps([{"id": pid, "name": n, "score": sc, "why": w} for sc, pid, n, w in ranked[:5]], ensure_ascii=False)
    con.execute("INSERT OR IGNORE INTO review(kind, subject, candidates) VALUES ('person_link', ?, ?)", (subject, cands))
    return None, best[0] if best else 0.0


# ------------------------------------------------------------------ duplicatas na World Curling

def find_wcf_duplicates(con: sqlite3.Connection) -> dict:
    """Procura pares com o mesmo nome. Funde quando a data de nascimento confirma; senão manda para revisão."""
    groups = defaultdict(list)
    for r in con.execute("SELECT n.key, p.id FROM person_name n JOIN person p ON p.id = n.person_id "
                         "WHERE p.merged_into IS NULL AND p.wcf_id IS NOT NULL"):
        groups[r["key"]].append(r["id"])
    merged = queued = 0
    for k, ids in groups.items():
        ids = sorted(set(ids))
        if len(ids) < 2:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = live_id(con, ids[i]), live_id(con, ids[j])
                if a == b:
                    continue
                if _same_event(con, a, b):
                    continue  # estiveram juntos no mesmo evento: são pessoas diferentes
                pa = con.execute("SELECT * FROM person WHERE id=?", (a,)).fetchone()
                pb = con.execute("SELECT * FROM person WHERE id=?", (b,)).fetchone()
                if pa["gender"] and pb["gender"] and pa["gender"] != pb["gender"]:
                    continue
                subj = json.dumps({"a": pa["wcf_id"], "b": pb["wcf_id"], "name": pa["name"]}, ensure_ascii=False, sort_keys=True)
                # Sem nascimento publicado: mesma seleção + 2 ou mais colegas de time em comum bastam
                if not (pa["born"] and pb["born"]):
                    na, nb = _nations_of(con, a), _nations_of(con, b)
                    common = _mate_names(con, a) & _mate_names(con, b)
                    born_ok = not (pa["born"] and pb["born"])
                    if na and nb and na & nb and len(common) >= 2 and born_ok:
                        merge(con, keep=a, drop=b,
                              reason=f"mesmo nome, mesma seleção ({', '.join(sorted(na & nb))}) e {len(common)} colegas em comum")
                        merged += 1
                        con.execute("UPDATE review SET status='merged' WHERE kind='person_duplicate' AND subject=?", (subj,))
                        continue
                if pa["born"] and pb["born"]:
                    if pa["born"] == pb["born"]:
                        merge(con, keep=a, drop=b, reason=f"mesmo nome e nascimento ({pa['born']})")
                        merged += 1
                        con.execute("UPDATE review SET status='merged' WHERE kind='person_duplicate' AND subject=?", (subj,))
                    else:  # nascimentos diferentes: pessoas diferentes
                        con.execute("UPDATE review SET status='distinct' WHERE kind='person_duplicate' AND subject=?", (subj,))
                    continue
                subject = json.dumps({"a": pa["wcf_id"], "b": pb["wcf_id"], "name": pa["name"]}, ensure_ascii=False, sort_keys=True)
                cands = json.dumps([dict(id=x["id"], wcf=x["wcf_id"], name=x["name"], born=x["born"]) for x in (pa, pb)], ensure_ascii=False)
                cur = con.execute("INSERT OR IGNORE INTO review(kind, subject, candidates) VALUES ('person_duplicate', ?, ?)", (subject, cands))
                queued += cur.rowcount
    return {"merged": merged, "queued": queued}


def _nations_of(con, pid: int) -> set[str]:
    return {r[0] for r in con.execute(
        "SELECT DISTINCT en.nation FROM entry_member m JOIN entry en ON en.id = m.entry_id WHERE m.person_id = ? AND en.nation IS NOT NULL", (pid,))}


def _mate_names(con, pid: int) -> set[str]:
    """Nomes (normalizados) de quem já esteve no mesmo time. Usamos nomes, e não códigos, porque
    colegas que trocaram de código junto com a pessoa também têm códigos novos."""
    return {r[0] for r in con.execute(
        "SELECT DISTINCT n.key FROM entry_member m1 JOIN entry_member m2 ON m2.entry_id = m1.entry_id "
        "JOIN person_name n ON n.person_id = m2.person_id WHERE m1.person_id = ? AND m2.person_id != ?", (pid, pid))}


def _same_event(con, a: int, b: int) -> bool:
    return con.execute(
        "SELECT 1 FROM entry_member m1 JOIN entry e1 ON e1.id = m1.entry_id "
        "JOIN entry_member m2 ON m2.person_id = ? JOIN entry e2 ON e2.id = m2.entry_id "
        "WHERE m1.person_id = ? AND e1.event_id = e2.event_id LIMIT 1", (b, a)).fetchone() is not None


def merge(con: sqlite3.Connection, keep: int, drop: int, reason: str) -> None:
    con.execute("UPDATE person SET merged_into = ? WHERE id = ?", (keep, drop))
    con.execute("UPDATE person SET merged_into = ? WHERE merged_into = ?", (keep, drop))
    for r in con.execute("SELECT raw, source FROM person_name WHERE person_id = ?", (drop,)).fetchall():
        add_name(con, keep, r["raw"], r["source"])
    con.execute("INSERT OR REPLACE INTO link(source, kind, key, entity_id, method, confidence, note) VALUES ('merge','person',?,?,?,1.0,?)",
                (str(drop), keep, "auto" if "nascimento" in reason else "override", reason))


# ------------------------------------------------------------------ decisões manuais

def apply_overrides(con: sqlite3.Connection, path: Path = OVERRIDES) -> int:
    """[[merge]] keep_wcf/drop_wcf · [[link]] source/key/wcf · [[distinct]] a_wcf/b_wcf"""
    if not path.exists():
        return 0
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    n = 0
    by_wcf = lambda w: con.execute("SELECT id FROM person WHERE wcf_id=?", (w,)).fetchone()
    for m in data.get("merge", []):
        a, b = by_wcf(m["keep_wcf"]), by_wcf(m["drop_wcf"])
        if a and b:
            merge(con, a["id"], b["id"], m.get("reason", "decisão manual"))
            n += 1
    for l in data.get("link", []):
        p = by_wcf(l["wcf"])
        if p:
            con.execute("INSERT OR REPLACE INTO link(source, kind, key, entity_id, method, confidence, note) "
                        "VALUES (?, 'person', ?, ?, 'override', 1.0, ?)", (l["source"], l["key"], p["id"], l.get("reason")))
            con.execute("UPDATE review SET status='resolved' WHERE kind='person_link' AND status='open' AND subject LIKE ?",
                        (f'%"key": {json.dumps(l["key"], ensure_ascii=False)}%',))
            n += 1
    for d in data.get("distinct", []):
        subject = json.dumps({"a": d["a_wcf"], "b": d["b_wcf"]}, sort_keys=True)
        con.execute("UPDATE review SET status='distinct' WHERE kind='person_duplicate' AND subject LIKE ?",
                    (f'%"a": {d["a_wcf"]}, "b": {d["b_wcf"]}%',))
        n += 1
    return n
