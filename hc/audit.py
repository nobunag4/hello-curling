"""Auditoria do banco: regras que precisam valer em TODOS os registros.

Cada verificação devolve (nome, total verificado, problemas, exemplos). Problemas não são corrigidos aqui:
o objetivo é medir a qualidade e achar defeitos de leitura (nossos) ou de origem (da fonte).
"""
from __future__ import annotations

import json
import random
import sqlite3
from collections import Counter, defaultdict

from . import names


def _ends(s):
    return json.loads(s) if s else []


def check_totals(con):
    """Placar total = soma dos ends (quando a fonte publicou os ends)."""
    n, bad = 0, []
    for g in con.execute("SELECT id, event_id, draw, score1, score2, ends1, ends2 FROM game WHERE score1 IS NOT NULL AND score2 IS NOT NULL"):
        e1, e2 = _ends(g["ends1"]), _ends(g["ends2"])
        if not e1 and not e2:
            continue
        n += 1
        s1, s2 = sum(x or 0 for x in e1), sum(x or 0 for x in e2)
        if (s1, s2) != (g["score1"], g["score2"]):
            bad.append(f"{g['id']} {g['draw']}: total {g['score1']}-{g['score2']}, ends somam {s1}-{s2}")
    return "Placar total = soma dos ends", n, bad


def check_one_scorer_per_end(con):
    """Num end só um time pontua."""
    n, bad = 0, []
    for g in con.execute("SELECT id, ends1, ends2 FROM game WHERE ends1 IS NOT NULL"):
        e1, e2 = _ends(g["ends1"]), _ends(g["ends2"])
        for i, (a, b) in enumerate(zip(e1, e2), 1):
            n += 1
            if (a or 0) > 0 and (b or 0) > 0:
                bad.append(f"{g['id']} end {i}: {a}-{b}")
    return "Só um time pontua por end", n, bad


def check_hammer(con):
    """Quem tem o hammer pontua na maioria dos ends com pontos (no curling de elite, cerca de 2 em cada 3).
    Se o hammer gravado estivesse invertido, essa taxa cairia para perto de 1 em 3. Medimos por década."""
    by_dec = defaultdict(lambda: [0, 0])
    q = ("SELECT g.hammer, g.ends1, g.ends2, e.discipline, e.year FROM game g JOIN event e ON e.id = g.event_id "
         "WHERE g.hammer IS NOT NULL AND g.ends1 IS NOT NULL")
    n = 0
    for g in con.execute(q):
        e1, e2 = _ends(g["ends1"]), _ends(g["ends2"])
        if not e1:
            continue
        n += 1
        h = g["hammer"]
        md = g["discipline"] in ("mixed_doubles", "wheelchair_md")
        dec = (g["year"] or 0) // 10 * 10
        for a, b in zip(e1, e2):
            a, b = a or 0, b or 0
            if a == 0 and b == 0:
                h = (3 - h) if md else h
                continue
            scorer = 1 if a > 0 else 2
            by_dec[dec][0] += 1
            by_dec[dec][1] += scorer == h
            h = 3 - scorer
    bad = [f"anos {d}: quem tem o hammer pontua em só {w / t:.0%} dos ends com pontos" for d, (t, w) in sorted(by_dec.items()) if t >= 200 and w / t < 0.55]
    resumo = ", ".join(f"{d}s {w / t:.0%}" for d, (t, w) in sorted(by_dec.items()) if t >= 200)
    return f"Hammer coerente ({resumo})", n, bad


def check_records(con):
    """Campanha publicada na classificação (V-D) x jogos gravados.
    A classificação da World Curling conta todos os jogos (grupos e fase final); aceitamos também só os grupos."""
    n, bad = 0, []
    rr = defaultdict(lambda: [0, 0])
    allg = defaultdict(lambda: [0, 0])
    for g in con.execute("SELECT entry1, entry2, score1, score2 FROM game WHERE score1 IS NOT NULL AND score2 IS NOT NULL"):
        if g["score1"] > g["score2"]:
            allg[g["entry1"]][0] += 1; allg[g["entry2"]][1] += 1
        elif g["score2"] > g["score1"]:
            allg[g["entry2"]][0] += 1; allg[g["entry1"]][1] += 1
    for g in con.execute("SELECT entry1, entry2, score1, score2 FROM game WHERE stage='round_robin' AND score1 IS NOT NULL AND score2 IS NOT NULL"):
        if g["score1"] > g["score2"]:
            rr[g["entry1"]][0] += 1; rr[g["entry2"]][1] += 1
        elif g["score2"] > g["score1"]:
            rr[g["entry2"]][0] += 1; rr[g["entry1"]][1] += 1
    for en in con.execute("SELECT en.id, en.name, en.wins, en.losses, e.id ev, e.name evn FROM entry en JOIN event e ON e.id = en.event_id "
                          "WHERE en.wins IS NOT NULL AND EXISTS (SELECT 1 FROM game g WHERE g.event_id = e.id)"):
        n += 1
        pub = (en["wins"], en["losses"])
        if pub not in (tuple(rr[en["id"]]), tuple(allg[en["id"]])):
            bad.append(f"{en['ev']} {en['evn'][:40]} · {en['name']}: classificação {pub[0]}-{pub[1]}, jogos {allg[en['id']][0]}-{allg[en['id']][1]}")
    return "Campanha da classificação = jogos gravados", n, bad


def check_person_twice(con):
    """Ninguém joga por dois times no mesmo campeonato."""
    rows = con.execute(
        "SELECT en.event_id, COALESCE(p.merged_into, p.id) pid, COUNT(DISTINCT en.id) c, GROUP_CONCAT(DISTINCT en.name) teams, p.name "
        "FROM entry_member m JOIN entry en ON en.id = m.entry_id JOIN person p ON p.id = m.person_id "
        "WHERE m.role NOT IN ('coach','official') GROUP BY en.event_id, pid HAVING c > 1").fetchall()
    n = con.execute("SELECT COUNT(*) FROM entry_member WHERE role NOT IN ('coach','official')").fetchone()[0]
    return "Atleta em um só time por campeonato", n, [f"{r['event_id']} {r['name']}: {r['teams']}" for r in rows]


def check_skips(con):
    """Times de 4 têm exatamente um skip; duplas mistas têm 1 homem e 1 mulher."""
    n, bad = 0, []
    for en in con.execute("SELECT en.id, en.name, e.id ev, e.discipline, e.year FROM entry en JOIN event e ON e.id = en.event_id"):
        ms = con.execute("SELECT m.role, m.is_skip, m.label FROM entry_member m WHERE m.entry_id = ? AND m.role NOT IN ('coach','official')", (en["id"],)).fetchall()
        if not ms:
            continue
        n += 1
        if en["discipline"] in ("mixed_doubles", "wheelchair_md"):
            labels = Counter(m["label"] for m in ms)
            if labels.get("Male", 0) != 1 or labels.get("Female", 0) != 1:
                if set(labels) & {"Male", "Female"}:
                    bad.append(f"{en['ev']} {en['name']}: {dict(labels)}")
        else:
            skips = sum(m["is_skip"] for m in ms)
            if skips != 1:
                bad.append(f"{en['ev']} ({en['year']}) {en['name']}: {skips} skips em {len(ms)} atletas")
    return "Um skip por time / duplas mistas com 1 homem e 1 mulher", n, bad


def check_games_shape(con):
    n = con.execute("SELECT COUNT(*) FROM game").fetchone()[0]
    bad = [f"{r['id']}: {r['why']}" for r in con.execute(
        "SELECT id, CASE WHEN entry1 = entry2 THEN 'time contra si mesmo' WHEN score1 IS NULL OR score2 IS NULL THEN 'placar faltando' END why "
        "FROM game WHERE entry1 = entry2 OR ((score1 IS NULL) <> (score2 IS NULL))")]
    return "Jogos bem formados (dois times diferentes, placar dos dois lados)", n, bad


def check_ranks(con):
    n, bad = 0, []
    # só campeonatos com medalha; nos qualificatórios todos os classificados aparecem como 1º
    for ev in con.execute("SELECT id, name FROM event WHERE type_id IN (1,2,4,5,7,8,16,22,27,35,36,38) AND complete = 1"):
        ranks = [r[0] for r in con.execute("SELECT rank FROM entry WHERE event_id=? AND rank IS NOT NULL", (ev["id"],))]
        if not ranks:
            continue
        n += 1
        if 1 not in ranks:
            bad.append(f"{ev['id']} {ev['name'][:50]}: sem 1º lugar")
        # dois bronzes é legítimo (anos sem disputa de 3º lugar); ouro ou prata repetidos não
        dup = [r for r, c in Counter(ranks).items() if c > 1 and r <= 2]
        if dup:
            bad.append(f"{ev['id']} {ev['name'][:50]}: posições repetidas no pódio {dup}")
    return "Classificação com um campeão e um vice", n, bad


def check_dates(con):
    n, bad = 0, []
    for g in con.execute("SELECT g.id, g.start_local, e.start_date, e.end_date FROM game g JOIN event e ON e.id = g.event_id WHERE g.start_local IS NOT NULL"):
        n += 1
        d = g["start_local"][:10]
        if e_s := g["start_date"]:
            if d < e_s or (g["end_date"] and d > g["end_date"]):
                bad.append(f"{g['id']}: jogo em {d}, evento {g['start_date']}..{g['end_date']}")
    return "Data de cada jogo dentro do período do evento", n, bad


def check_name_twins(con):
    """Mesmo nome em códigos diferentes (candidatos a duplicata)."""
    groups = defaultdict(set)
    for r in con.execute("SELECT n.key, COALESCE(p.merged_into, p.id) pid FROM person_name n JOIN person p ON p.id = n.person_id"):
        groups[r["key"]].add(r["pid"])
    twins = {k: v for k, v in groups.items() if len(v) > 1}
    n = len(groups)
    return "Nomes iguais em códigos diferentes (para revisão, não é erro em si)", n, [f"{k}: {len(v)} códigos" for k, v in list(twins.items())]


CHECKS = [check_games_shape, check_totals, check_one_scorer_per_end, check_hammer, check_records, check_person_twice,
          check_skips, check_ranks, check_dates, check_name_twins]


def run(con: sqlite3.Connection, examples: int = 5) -> list[dict]:
    out = []
    for f in CHECKS:
        name, n, bad = f(con)
        out.append({"check": name, "checked": n, "problems": len(bad), "examples": bad[:examples]})
    return out


def sample(con: sqlite3.Connection, k: int = 8, seed: int = 2026) -> list[dict]:
    """Sorteia campeonatos para conferir contra uma fonte independente (pódio e final)."""
    rnd = random.Random(seed)
    evs = [dict(r) for r in con.execute("SELECT id, name, year, division FROM event WHERE type_id IN (1,2,4,22,5) ORDER BY id")]
    picked = rnd.sample(evs, min(k, len(evs)))
    for e in picked:
        e["podium"] = [dict(r) for r in con.execute("SELECT rank, name FROM entry WHERE event_id=? AND rank<=3 ORDER BY rank", (e["id"],))]
        fin = con.execute("SELECT g.draw, a.name n1, b.name n2, g.score1, g.score2 FROM game g JOIN entry a ON a.id=g.entry1 JOIN entry b ON b.id=g.entry2 "
                          "WHERE g.event_id=? AND g.stage='final' ORDER BY g.ord DESC LIMIT 1", (e["id"],)).fetchone()
        e["final"] = dict(fin) if fin else None
        skip = con.execute("SELECT p.name FROM entry en JOIN entry_member m ON m.entry_id=en.id JOIN person p ON p.id=m.person_id "
                           "WHERE en.event_id=? AND en.rank=1 AND m.is_skip=1", (e["id"],)).fetchone()
        e["champion_skip"] = skip[0] if skip else None
    return picked
