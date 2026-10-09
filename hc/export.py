"""Gera os arquivos JSON que o site lê.

  site/data/index.json          busca: pessoas (id, nome, seleções) e seleções disponíveis
  site/data/nation/XXX.json     tudo de uma seleção: histórico por campeonato, atletas com carreira e jogos recentes
  site/data/vs/XXX.json         para a página de um jogo: retrospecto contra cada adversário e a última formação,
                                separados por categoria (masculino, feminino, duplas mistas, juvenil, cadeira de rodas...)

Um arquivo por seleção mantém cada download pequeno: o site só baixa a seleção que a pessoa abrir.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from . import db

ROOT = Path(__file__).resolve().parent.parent

# Campeonatos em que 1º/2º/3º lugar são medalhas (qualificatórios não contam)
MEDAL_TYPES = {1, 2, 4, 5, 7, 8, 16, 22, 27, 35, 36, 38}
PLAYING = ("fourth", "third", "second", "lead", "alternate", "player")
RECENT_SEASONS = 3
VS_LAST = 6   # últimos confrontos guardados com placar por end; os demais vão só com o resultado


def category(division: str | None, type_name: str | None) -> str | None:
    """Categoria de comparação: 'm', 'w', 'md', 'x' com prefixo j (juvenil), s (sênior) ou wc (cadeira de rodas).
    Igual a gameCat() na página."""
    base = {"Men": "m", "Women": "w", "Mixed Doubles": "md", "Mixed": "x"}.get(division or "")
    if not base:
        return None
    tn = type_name or ""
    pre = "j" if "Junior" in tn else "s" if "Senior" in tn else "wc" if ("heelchair" in tn or "Paralympic" in tn) else ""
    return pre + base


def _dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    path.write_text(data, encoding="utf-8")
    return len(data.encode())


def run(args) -> None:
    out = ROOT / getattr(args, "out", "site/data")
    con = db.connect()
    live = {r["id"]: (r["merged_into"] or r["id"]) for r in con.execute("SELECT id, merged_into FROM person")}

    persons = {r["id"]: r for r in con.execute("SELECT * FROM person WHERE merged_into IS NULL")}
    aliases = defaultdict(set)
    for r in con.execute("SELECT person_id, raw FROM person_name"):
        aliases[live[r["person_id"]]].add(r["raw"])

    events = {r["id"]: dict(r) for r in con.execute("SELECT * FROM event")}
    entries = {r["id"]: dict(r) for r in con.execute("SELECT * FROM entry")}

    # vitórias/derrotas por time a partir dos jogos (inclui fase final)
    rec = defaultdict(lambda: [0, 0])
    games_by_entry = defaultdict(list)
    for g in con.execute("SELECT * FROM game ORDER BY event_id, ord"):
        g = dict(g)
        if g["score1"] is None or g["score2"] is None:
            continue
        for me, other, sm, so in ((g["entry1"], g["entry2"], g["score1"], g["score2"]), (g["entry2"], g["entry1"], g["score2"], g["score1"])):
            if sm > so:
                rec[me][0] += 1
            elif sm < so:
                rec[me][1] += 1
            games_by_entry[me].append((g, other, sm, so))

    members = defaultdict(list)       # entry -> [(person, role, skip)]
    careers = defaultdict(list)       # person -> [entry]
    for r in con.execute("SELECT * FROM entry_member ORDER BY entry_id, ord"):
        pid = live[r["person_id"]]
        members[r["entry_id"]].append((pid, r["role"], r["is_skip"]))
        careers[pid].append((r["entry_id"], r["role"], r["is_skip"]))

    played = defaultdict(lambda: [0, 0])  # person -> [jogos, vitórias] contando só quem entrou no gelo
    for r in con.execute("SELECT gp.person_id, gp.entry_id, gp.played, gp.role, g.entry1, g.score1, g.score2 FROM game_player gp "
                         "JOIN game g ON g.id = gp.game_id WHERE g.score1 IS NOT NULL AND g.score2 IS NOT NULL"):
        if r["played"] == 0 or (r["played"] is None and r["role"] in ("alternate", "coach", "official")):
            continue
        pid = live[r["person_id"]]
        mine, theirs = (r["score1"], r["score2"]) if r["entry_id"] == r["entry1"] else (r["score2"], r["score1"])
        played[pid][0] += 1
        played[pid][1] += int(mine > theirs)

    def ev_brief(eid):
        e = events[eid]
        return {"id": eid, "name": e["name"], "year": e["year"], "season": e["season"], "division": e["division"],
                "discipline": e["discipline"], "type": e["type_id"], "typeName": e["type_name"], "city": e["city"],
                "country": e["country"], "start": e["start_date"], "end": e["end_date"]}

    def medal(entry):
        e = events[entry["event_id"]]
        return entry["rank"] if e["type_id"] in MEDAL_TYPES and entry["rank"] in (1, 2, 3) else None

    # ---------------- arquivo por seleção
    # Só os campeonatos de seleções contam para a seleção. Os times do Grand Slam são de clube: entram na carreira
    # de cada atleta, mas não no histórico, nas medalhas nem no confronto direto do país.
    by_nation = defaultdict(list)
    for en in entries.values():
        if en["nation"] and events[en["event_id"]]["source"] == "wcf":
            by_nation[en["nation"]].append(en)
    # atletas que só aparecem no Grand Slam ficam no arquivo do país deles
    slam_only = defaultdict(set)
    for en in entries.values():
        if events[en["event_id"]]["source"] != "wcf":
            for p, _, _ in members[en["id"]]:
                pr = persons.get(p)
                codes = json.loads(pr["nations"]) if pr and pr["nations"] else [en["nation"]] if en["nation"] else []
                for c in codes:
                    slam_only[c].add(p)

    latest_season = max((e["season"] for e in events.values() if e["season"]), default="0000-00")
    recent_cut = f"{int(latest_season[:4]) - RECENT_SEASONS + 1}-00"
    nation_index, total = [], 0
    for code, ens in by_nation.items():
        ens.sort(key=lambda en: (events[en["event_id"]]["start_date"] or "", en["id"]), reverse=True)
        hist, people = [], {}
        medals = Counter()
        for en in ens:
            m = medal(en)
            if m:
                medals[m] += 1
            w, l = rec[en["id"]]
            hist.append({**ev_brief(en["event_id"]), "entry": en["id"], "team": en["name"], "club": en.get("club"), "rank": en["rank"], "medal": m,
                         "w": w, "l": l, "members": [[p, role, sk] for p, role, sk in members[en["id"]]]})
            for p, _, _ in members[en["id"]]:
                people[p] = None
        for p in slam_only.get(code, ()):
            people.setdefault(p, None)
        # atletas e técnicos que passaram pela seleção
        for p in people:
            pr = persons.get(p)
            if pr is None:
                continue
            car = []
            for entry_id, role, skip in careers[p]:
                en = entries[entry_id]
                w, l = rec[entry_id]
                car.append({"event": en["event_id"], "nation": en["nation"], "team": en["name"], "role": role, "skip": skip,
                            "slam": events[en["event_id"]]["source"] == "gsoc",
                            "rank": en["rank"], "medal": medal(en), "w": w, "l": l,
                            "year": events[en["event_id"]]["year"], "name": events[en["event_id"]]["name"],
                            "division": events[en["event_id"]]["division"]})
            car.sort(key=lambda c: (events[c["event"]]["start_date"] or ""), reverse=True)
            mates = Counter()
            for entry_id, role, _ in careers[p]:
                if role in PLAYING:
                    for q, r2, _ in members[entry_id]:
                        if q != p and r2 in PLAYING:
                            mates[q] += 1
            people[p] = {"id": p, "name": pr["name"], "gender": pr["gender"], "born": pr["born"], "delivery": pr["delivery"],
                         "nations": json.loads(pr["nations"]) if pr["nations"] else sorted({c["nation"] for c in car if c["nation"]}),
                         "wcf": pr["wcf_id"], "games": played[p][0], "wins": played[p][1],
                         "career": car, "mates": [[q, n, persons[q]["name"]] for q, n in mates.most_common(8) if q in persons]}
        # jogos recentes da seleção, com placar por end
        recent = []
        for en in ens:
            if (events[en["event_id"]]["season"] or "") < recent_cut:
                continue
            for g, other, sm, so in games_by_entry[en["id"]]:
                op = entries.get(other, {})
                recent.append({"event": en["event_id"], "draw": g["draw"], "stage": g["stage"], "when": g["start_local"],
                               "team": en["name"], "opp": op.get("name"), "oppNation": op.get("nation"), "for": sm, "against": so,
                               "hammer": (g["hammer"] == 1) if g["entry1"] == en["id"] else (g["hammer"] == 2) if g["hammer"] else None,
                               "ends": json.loads(g["ends1"] if g["entry1"] == en["id"] else g["ends2"]),
                               "endsOpp": json.loads(g["ends2"] if g["entry1"] == en["id"] else g["ends1"])})
        recent.sort(key=lambda r: r["when"] or "", reverse=True)
        events_used = {h["id"] for h in hist}
        size = _dump(out / "nation" / f"{code}.json", {
            "code": code, "medals": {"gold": medals[1], "silver": medals[2], "bronze": medals[3]},
            "history": hist, "people": {str(k): v for k, v in people.items() if v}, "recent": recent[:120],
            "events": len(events_used)})
        total += size
        names_seen = Counter(en["name"] for en in ens)
        nation_index.append({"code": code, "name": names_seen.most_common(1)[0][0], "entries": len(ens), "gold": medals[1], "silver": medals[2], "bronze": medals[3],
                             "first": min((events[e["event_id"]]["year"] or 9999) for e in ens),
                             "last": max((events[e["event_id"]]["year"] or 0) for e in ens)})

    # ---------------- retrospecto e última formação, por seleção e categoria
    vs = defaultdict(lambda: defaultdict(lambda: {"vs": defaultdict(lambda: [0, 0, [], []]), "lineup": None}))
    names_needed = defaultdict(set)
    types_used = defaultdict(dict)
    ordered = sorted(entries.values(), key=lambda en: (events[en["event_id"]]["start_date"] or "", en["id"]), reverse=True)
    for en in ordered:
        e = events[en["event_id"]]
        if e["source"] != "wcf":
            continue
        cat, code = category(e["division"], e["type_name"]), en["nation"]
        if not cat or not code:
            continue
        slot = vs[code][cat]
        if slot["lineup"] is None and any(r in PLAYING for _, r, _ in members[en["id"]]):
            slot["lineup"] = {"year": e["year"], "type": e["type_id"], "typeName": e["type_name"], "name": e["name"],
                              "members": [[p, r, sk] for p, r, sk in members[en["id"]] if p in persons]}
            names_needed[code].update(p for p, _, _ in members[en["id"]] if p in persons)
        for g, other, sm, so in reversed(games_by_entry[en["id"]]):
            opp = entries.get(other, {}).get("nation")
            if not opp or opp == code:
                continue
            rec_ = slot["vs"][opp]
            rec_[0 if sm > so else 1] += sm != so
            rec_[3].append([e["year"], e["type_id"], g["stage"], g["draw"], sm, so])
            types_used[code][e["type_id"]] = e["type_name"]
            if len(rec_[2]) < VS_LAST:
                mine = g["entry1"] == en["id"]
                rec_[2].append({"y": e["year"], "type": e["type_id"], "typeName": e["type_name"], "stage": g["stage"], "draw": g["draw"],
                                "when": (g["start_local"] or "")[:10], "f": sm, "a": so,
                                "h": (g["hammer"] == (1 if mine else 2)) if g["hammer"] else None,
                                "e": json.loads(g["ends1"] if mine else g["ends2"]), "o": json.loads(g["ends2"] if mine else g["ends1"])})
    for code, cats in vs.items():
        total += _dump(out / "vs" / f"{code}.json", {
            "code": code,
            "cats": {c: {"vs": {o: {"w": r[0], "l": r[1], "last": r[2], "all": r[3]} for o, r in s["vs"].items()}, "lineup": s["lineup"]}
                     for c, s in cats.items()},
            "names": {str(p): persons[p]["name"] for p in names_needed[code]},
            "types": {str(k): v for k, v in types_used[code].items()},  # all: [ano, tipo, fase, rodada, pontos, contra]
        })

    # ---------------- índice de busca
    idx_people = []
    for p, pr in persons.items():
        car = careers.get(p)
        if not car or not any(role in PLAYING for _, role, _ in car):
            continue
        nats = json.loads(pr["nations"]) if pr["nations"] else sorted({entries[e]["nation"] for e, _, _ in car if entries[e]["nation"]})
        last = max((events[entries[e]["event_id"]]["year"] or 0) for e, _, _ in car)
        alias = sorted(a for a in aliases[p] if a != pr["name"])
        idx_people.append([p, pr["name"], nats, last, alias] if alias else [p, pr["name"], nats, last])
    idx_people.sort(key=lambda x: -x[3])
    # fotos: só de quem está no índice e com o arquivo presente; [arquivo, autor, licença, página do Commons]
    in_index = {x[0] for x in idx_people}
    img_dir = out.parent / "img" / "people"
    photos = {str(r["person_id"]): [r["path"], r["author"], r["license"], r["page"]]
              for r in con.execute("SELECT * FROM photo") if r["person_id"] in in_index and (img_dir / r["path"]).exists()}
    size = _dump(out / "index.json", {"generated": latest_season, "people": idx_people, "photos": photos, "nations": sorted(nation_index, key=lambda n: n["code"]),
                                      "events": len(events), "games": sum(len(v) for v in games_by_entry.values()) // 2})
    total += size
    print(f"{len(nation_index)} seleções, {len(idx_people)} atletas no índice, {total / 1e6:.1f} MB no total")
