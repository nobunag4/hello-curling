"""Linha de comando.

  python3 -m hc sync-wcf [--types 1,22] [--since 2010]   baixa e grava campeonatos da World Curling
  python3 -m hc sync-schedule                             calendário automático (torneios atuais e próximos) -> site/data/schedule.json
  python3 -m hc sync-live                                 placar ao vivo da temporada atual -> site/data/live.json
  python3 -m hc persons [--nations BRA,ITA] [--since 2018-19] [--limit N]   lê páginas pessoais
  python3 -m hc reingest                                  regrava tudo a partir das cópias locais
  python3 -m hc audit                                     confere as regras do curling em todo o banco
  python3 -m hc dupes                                     procura a mesma pessoa com dois códigos
  python3 -m hc overrides                                 aplica data/overrides.toml
  python3 -m hc review                                    mostra a fila de casos duvidosos
  python3 -m hc stats                                     números do banco
  python3 -m hc photos                                    fotos livres dos atletas (Wikidata + Commons)
  python3 -m hc export                                    gera os arquivos JSON do site
  python3 -m hc build-site                                monta _site/ para o GitHub Pages
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date

from . import db, identity, ingest
from .sources import wcf

DEFAULT_TYPES = [1, 2, 4, 22, 32, 26, 34, 36, 37, 39, 40, 33, 24, 5, 38, 11, 27, 8, 7, 35, 16]


def cmd_sync_wcf(a):
    con = db.connect()
    types = [int(x) for x in a.types.split(",")] if a.types else DEFAULT_TYPES
    today = date.today().isoformat()
    done = skipped = 0
    for t in types:
        try:
            editions = wcf.fetch_type(t, max_age=86400)
        except Exception as e:  # noqa: BLE001
            print(f"tipo {t}: falhou ({e})", file=sys.stderr)
            continue
        for ed in editions:
            ed["type_id"] = t
            if a.since and ed["year"] < a.since:
                continue
            if ed["start"] and ed["start"] > today:
                skipped += 1
                continue  # ainda não começou
            ev = con.execute("SELECT complete FROM event WHERE id=?", (f"wcf:{ed['tid']}",)).fetchone()
            if ev and ev["complete"] and not a.force:
                continue
            recent = ed["end"] and ed["end"] >= today
            try:
                d, g = wcf.fetch_event(ed["tid"], max_age=600 if recent else None)
                r = ingest.ingest_wcf_event(con, ed, d, g)
                con.commit()
                done += 1
                print(f"[{t}] {ed['year']} {ed['division']:<14} {d.get('title','')[:60]:<60} times={r['entries']:>2} jogos={r['games']:>3}")
            except Exception as e:  # noqa: BLE001
                con.rollback()
                print(f"[{t}] {ed['tid']} falhou: {e}", file=sys.stderr)
    print(f"\n{done} eventos gravados, {skipped} futuros ignorados.")


def cmd_reingest(a):
    """Regrava todos os eventos a partir das cópias locais (data/raw), sem acessar o site. Use após corrigir um leitor."""
    con = db.connect()
    evs = con.execute("SELECT * FROM event WHERE source='wcf' ORDER BY id").fetchall()
    n = 0
    for e in evs:
        tid = int(e["id"].split(":")[1])
        meta = {"tid": tid, "type_id": e["type_id"], "year": e["year"], "division": e["division"], "name": e["name"],
                "city": e["city"], "country": e["country"], "start": e["start_date"], "end": e["end_date"]}
        try:
            d, g = wcf.fetch_event(tid)  # vem do cache
            ingest.ingest_wcf_event(con, meta, d, g)
            n += 1
        except Exception as ex:  # noqa: BLE001
            print(f"{e['id']}: {ex}", file=sys.stderr)
        if n % 50 == 0:
            con.commit()
    con.commit()
    # pessoas que deixaram de aparecer em qualquer lugar (eram de times duplicados) continuam no banco, sem vínculos
    print(f"{n} eventos regravados")


def cmd_audit(a):
    from . import audit
    con = db.connect()
    for r in audit.run(con, examples=a.examples):
        ok = (1 - r["problems"] / r["checked"]) * 100 if r["checked"] else 100
        print(f"\n[{r['problems']:>5} problemas / {r['checked']:>7} verificados · {ok:6.2f}% ok] {r['check']}")
        for x in r["examples"]:
            print("       ", x)


def cmd_persons(a):
    con = db.connect()
    q = ("SELECT DISTINCT p.id, p.wcf_id, p.name FROM person p JOIN entry_member m ON m.person_id = p.id "
         "JOIN entry en ON en.id = m.entry_id JOIN event e ON e.id = en.event_id WHERE p.wcf_id IS NOT NULL "
         "AND p.merged_into IS NULL AND m.role NOT IN ('coach','official')")
    args = []
    if not a.refresh:
        q += " AND p.profile_at IS NULL"
    if a.review:
        ids = set()
        for r in con.execute("SELECT subject FROM review WHERE kind='person_duplicate' AND status='open'"):
            d = json.loads(r["subject"])
            ids |= {d["a"], d["b"]}
        q += f" AND p.wcf_id IN ({','.join(str(int(i)) for i in ids) or '0'})"
    if a.nations:
        q += f" AND en.nation IN ({','.join('?' * len(a.nations.split(',')))})"
        args += a.nations.split(",")
    if a.since:
        q += " AND e.season >= ?"
        args.append(a.since)
    rows = con.execute(q + " ORDER BY e.start_date DESC", args).fetchall()
    if a.limit:
        rows = rows[: a.limit]
    print(f"{len(rows)} páginas pessoais para ler (~{len(rows) // 60 + 1} min)")
    for i, r in enumerate(rows, 1):
        try:
            prof = wcf.fetch_person(r["wcf_id"], max_age=None if not a.refresh else 30 * 86400)
            ingest.update_person_profile(con, r["id"], prof)
        except Exception as e:  # noqa: BLE001
            print(f"  {r['name']} ({r['wcf_id']}): {e}", file=sys.stderr)
        if i % 50 == 0:
            con.commit()
            print(f"  {i}/{len(rows)}")
    con.commit()


def cmd_dupes(a):
    con = db.connect()
    r = identity.find_wcf_duplicates(con)
    con.commit()
    print(f"fundidas automaticamente: {r['merged']} · enviadas para revisão: {r['queued']}")


def cmd_overrides(a):
    con = db.connect()
    print(f"{identity.apply_overrides(con)} decisões aplicadas")
    con.commit()


def cmd_review(a):
    con = db.connect()
    rows = con.execute("SELECT * FROM review WHERE status='open' ORDER BY kind, id").fetchall()
    if not rows:
        print("Fila vazia.")
    for r in rows:
        print(f"#{r['id']} [{r['kind']}] {r['subject']}")
        for c in json.loads(r["candidates"]):
            print("     ", c)


def cmd_stats(a):
    con = db.connect()
    for t in ("event", "entry", "game", "person", "person_name", "game_player", "link", "review"):
        print(f"{t:<12} {con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:>8}")
    print("pessoas com perfil:", con.execute("SELECT COUNT(*) FROM person WHERE profile_at IS NOT NULL").fetchone()[0])
    print("fundidas:", con.execute("SELECT COUNT(*) FROM person WHERE merged_into IS NOT NULL").fetchone()[0])


def cmd_sync_schedule(a):
    """Torneios em andamento e próximos do placar oficial, com todas as sessões, confrontos e placares."""
    from .sources import curlit
    from datetime import datetime, timezone, timedelta
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "site" / "data" / "schedule.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"events": {}}
    events = {}
    today = date.today()
    for c in curlit.competitions(max_age=a.max_age):
        if c["section"] not in ("current", "upcoming") or not c["start"]:
            continue
        # em andamento: placar fresco; próximos: a tabela muda pouco
        live_now = c["start"] - timedelta(days=1) <= today <= c["end"] + timedelta(days=1)
        try:
            ev = curlit.fetch_competition(c, max_age=a.max_age if live_now else 6 * 3600)
        except Exception as e:  # um torneio com página quebrada não derruba os outros
            print(f"{c['slug']}: falhou ({e})")
            continue
        if not ev:
            print(f"{c['slug']}: sem fuso conhecido para '{c['place']}', ignorado")
            continue
        events[ev["id"]] = ev
        print(f"{ev['id']}: {len(ev['draws'])} sessões, {sum(len(d['games']) for d in ev['draws'])} jogos, "
              f"{sum(g['sa'] is not None for d in ev['draws'] for g in d['games'])} com placar")
    # torneios que saíram da lista continuam por duas semanas depois do fim (resultados recentes)
    for k, ev in old.get("events", {}).items():
        if k not in events and date.fromisoformat(ev["end"]) >= today - timedelta(days=14):
            events[k] = ev
    if events == old.get("events"):
        print("Nada mudou no calendário.")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "events": events},
                               ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"gravado {path}")


def cmd_sync_live(a):
    """Lê o placar ao vivo, liga os atletas ao banco e grava site/data/live.json."""
    from .sources import live
    from . import names
    from pathlib import Path
    con = db.connect()
    index = identity.NameIndex(con)
    out = {"updated": None, "events": {}}
    today = date.today()
    slugs = a.slugs.split(",") if a.slugs else [s for s, v in live.EVENTS.items()
                                                 if date.fromisoformat(v[3]) <= today <= date.fromisoformat(v[4])]
    if not slugs:
        print("Nenhum evento ao vivo hoje.")
    for slug in slugs:
        ev = live.fetch_event(slug, max_age=a.max_age)
        season = ingest.season_of(f"{live.EVENTS[slug][2]}-10-01")
        linked, pending = 0, 0
        people = {}
        for team in ev["teams"]:
            ids = []
            # 1ª passada sem colegas; 2ª usa os colegas já ligados como evidência extra
            for pass_ in (1, 2):
                for m in team["members"]:
                    key = f"{slug}:{team['code']}:{names.key(m['name'])}"
                    if key in people and people[key]:
                        continue
                    pid, conf = identity.resolve(con, "wcf-live", key, m["name"], gender=m["gender"], nation=team["code"],
                                                 season=season, teammates=set(i for i in ids if i), index=index)
                    people[key] = pid
                    if pid and pid not in ids:
                        ids.append(pid)
            for m in team["members"]:
                pid = people[f"{slug}:{team['code']}:{names.key(m['name'])}"]
                m["person"] = pid
                linked += bool(pid)
                pending += not pid
        con.commit()
        games = [{"t": s_["start_utc"], "label": s_["label"], **g} for s_ in ev["sessions"] for g in s_["games"]]
        out["events"][ev["site_id"]] = {"slug": slug, "games": games,
                                       "teams": {t["code"]: [{"name": m["name"], "person": m["person"], "role": m["function"]} for m in t["members"]] for t in ev["teams"]}}
        print(f"{slug}: {len(games)} jogos, {sum(g['sa'] is not None for g in games)} com placar · atletas ligados {linked}, pendentes {pending}")
    from datetime import datetime, timezone
    out["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = Path(__file__).resolve().parent.parent / "site" / "data" / "live.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"events": {}}
    merged = {**old.get("events", {}), **out["events"]}
    if merged == old.get("events"):
        print("Nada mudou no placar.")
        return
    path.write_text(json.dumps({"updated": out["updated"], "events": merged}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"gravado {path}")


def cmd_photos(a):
    from . import photos
    con = db.connect()
    print(photos.run(con, limit=a.limit))


def cmd_export(a):
    from . import export
    export.run(a)


def cmd_build_site(a):
    from . import site_build
    print(f"site montado em {site_build.build()}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="hc", description="Hello, Curling: coleta e organização de dados")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync-wcf"); s.add_argument("--types"); s.add_argument("--since", type=int); s.add_argument("--force", action="store_true")
    s.set_defaults(f=cmd_sync_wcf)
    s = sub.add_parser("persons"); s.add_argument("--nations"); s.add_argument("--since"); s.add_argument("--limit", type=int)
    s.add_argument("--refresh", action="store_true")
    s.add_argument("--review", action="store_true", help="só os atletas da fila de duplicatas")
    s.set_defaults(f=cmd_persons)
    s = sub.add_parser("sync-schedule"); s.add_argument("--max-age", type=float, default=120); s.set_defaults(f=cmd_sync_schedule)
    s = sub.add_parser("sync-live"); s.add_argument("--slugs"); s.add_argument("--max-age", type=float, default=120)
    s.set_defaults(f=cmd_sync_live)
    sub.add_parser("reingest").set_defaults(f=cmd_reingest)
    s = sub.add_parser("audit"); s.add_argument("--examples", type=int, default=5); s.set_defaults(f=cmd_audit)
    sub.add_parser("dupes").set_defaults(f=cmd_dupes)
    sub.add_parser("overrides").set_defaults(f=cmd_overrides)
    sub.add_parser("review").set_defaults(f=cmd_review)
    sub.add_parser("stats").set_defaults(f=cmd_stats)
    sub.add_parser("build-site").set_defaults(f=cmd_build_site)
    s = sub.add_parser("photos"); s.add_argument("--limit", type=int); s.set_defaults(f=cmd_photos)
    s = sub.add_parser("export"); s.add_argument("--out", default="site/data"); s.set_defaults(f=cmd_export)
    a = p.parse_args(argv)
    t0 = time.time()
    a.f(a)
    print(f"({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
