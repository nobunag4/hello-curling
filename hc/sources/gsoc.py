"""Calendário automático do Grand Slam of Curling (thegrandslamofcurling.com).

O site do circuito publica arquivos de dados abertos: a lista de torneios da temporada, todos os jogos de cada
torneio (horário em UTC, rodada, fase, placar end a end, quem começa com o hammer) e a ficha de cada time
(com o país). Os times do circuito são chamados pelo sobrenome do skip ("Hasselborg"), como no próprio Slam.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .. import fetch

BASE = "https://www.thegrandslamofcurling.com"
FEED = (BASE + "/default.aspx?methodtype=3&client=36f6377633&sport=31&league=0&timezone=-0000&language=en&tournament={tour}")
SERIES = BASE + "/curling/static/json/series_list.json"
TEAM = BASE + "/curling/static/json/{id}_team.json"
SQUAD = BASE + "/curling/static/json/{series}_{team}_squad.json"   # formação do time naquele torneio
MATCH = BASE + "/curling/live/json/{id}.json"                       # ficha do jogo: quem entrou no gelo
# Os cinco Slams da temporada (o mesmo site também publica Brier, Scotties, Olimpíadas e Mundial, que não entram).
SLAM_PREFIX = {"tch", "cco", "kio", "wfg", "plc"}
POSITION = {"LEAD": "lead", "SECOND": "second", "THIRD": "third", "FOURTH": "fourth", "SKIP": "skip",
            "ALTERNATE": "alternate", "ALT": "alternate", "FIFTH": "alternate", "COACH": "coach"}

# torneio-mãe do circuito -> id no nosso site
PARENT_ID = {"GSOC Invitational": "gsoc-inv", "GSOC Masters": "gsoc-masters", "GSOC National": "gsoc-national",
             "GSOC Open": "gsoc-open", "GSOC Players' Cup": "gsoc-players"}
# o feed escreve sem acentos
DISPLAY = {"Hoesli": "Hösli", "Paetz": "Pätz", "Wrana": "Wranå", "Schwaller-Huerlimann": "Schwaller-Hürlimann"}
COUNTRY = {
    "Canada": "CAN", "Scotland": "SCO", "Sweden": "SWE", "Switzerland": "SUI", "Italy": "ITA", "Japan": "JPN", "Korea": "KOR",
    "South Korea": "KOR", "Republic of Korea": "KOR", "Norway": "NOR", "Denmark": "DEN", "Germany": "GER", "USA": "USA",
    "United States": "USA", "United States of America": "USA", "China": "CHN", "Netherlands": "NED", "Czechia": "CZE",
    "Czech Republic": "CZE", "Estonia": "EST", "Latvia": "LAT", "England": "ENG", "Austria": "AUT", "Turkey": "TUR",
    "Türkiye": "TUR", "Australia": "AUS", "New Zealand": "NZL", "Finland": "FIN", "Poland": "POL", "Hungary": "HUN",
    "Spain": "ESP", "France": "FRA", "Ireland": "IRL", "Wales": "WAL", "Hong Kong": "HKG", "Chinese Taipei": "TPE",
}
STAGE = {"round robin": None, "tiebreaker": "tb", "quarter final": "qf", "quarterfinal": "qf", "semi final": "sf",
         "semifinal": "sf", "final": "fin"}


def division_of(group: str | None) -> str | None:
    """'Men' / 'Women'. Os Slams com mais times trazem dois níveis: 'Men Tier 1' é o Slam; o 'Tier 2' é um torneio
    paralelo de acesso, que fica de fora (None)."""
    m = re.fullmatch(r"(Men|Women)(?: Tier 1)?", (group or "").strip())
    return {"Men": "m", "Women": "w"}[m.group(1)] if m else None


def _name(n: str) -> str:
    return DISPLAY.get(n, n)


def _real(n: str) -> bool:
    return bool(n) and "TBD" not in n


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("-00:00", "+00:00"))


def parse_series(raw: str) -> list[dict]:
    return json.loads(raw)["data"]


def current_slams(series: list[dict], today) -> list[dict]:
    """Torneios do Grand Slam que ainda não acabaram (ou acabaram há pouco)."""
    out = []
    for s in series:
        pid = PARENT_ID.get(s.get("parent_name"))
        if not pid or s.get("league_type_name") != "Grand Slam of Curling":
            continue
        end = datetime.strptime(s["end_date"], "%m/%d/%Y").date()
        start = datetime.strptime(s["start_date"], "%m/%d/%Y").date()
        if (end - today).days < -14 or (start - today).days > 120:
            continue
        out.append({**s, "site_id": pid, "start": start, "end": end})
    return out


def parse_feed(raw: str) -> list[dict]:
    """Jogos do feed: horário UTC, divisão, fase, times, placar e ends."""
    out = []
    for m in json.loads(raw).get("matches", []):
        ps = m.get("participants") or []
        if len(ps) != 2:
            continue
        if m.get("event_group") and division_of(m.get("event_group")) is None:
            continue  # torneio paralelo (Tier 2)
        a, b = ps
        stage = STAGE.get(m.get("stage", "").strip().lower(), m.get("stage"))
        draw = re.match(r"Draw (\d+)", m.get("match_draw") or "")
        done, live = m.get("event_state") == "R", m.get("event_state") == "L"
        ends = []
        for e in (m.get("ends") or "").split(","):
            if re.fullmatch(r"\d+-\d+", e.strip()):
                x, y = e.strip().split("-")
                ends.append([int(x), int(y)])
        score = lambda p: int(p["value"]) if str(p.get("value", "")).isdigit() and (done or live) else None
        out.append({
            "t": _utc(m["start_date"]).astimezone(timezone.utc).isoformat(timespec="minutes").replace("+00:00", "Z"),
            "div": division_of(m.get("event_group")),
            "stage": stage, "draw": int(draw.group(1)) if draw else None,
            "a": _name(a["name"]), "b": _name(b["name"]), "ida": a.get("id"), "idb": b.get("id"),
            "real": _real(a["name"]) and _real(b["name"]),
            "sa": score(a), "sb": score(b), "ends": ends or None,
            "hammer": "a" if a.get("lsfe") == "true" else "b" if b.get("lsfe") == "true" else None,
            "state": "done" if done else "live" if live else "pre",
        })
    return out


def build(slam: dict, matches: list[dict], countries: dict[str, str]) -> dict:
    """No mesmo formato do calendário da World Curling (hc.sources.curlit.fetch_competition)."""
    draws: dict[str, dict] = {}
    for m in sorted(matches, key=lambda m: m["t"]):
        key = m["draw"] if m["stage"] is None and m["draw"] else (m["stage"] or "po")
        d = draws.setdefault(m["t"], {"t": m["t"], "key": key, "group": None, "label": f"Draw {m['draw']}" if m["draw"] else str(key),
                                      "games": [], "divs": []})
        if m["div"] and m["div"] not in d["divs"]:
            d["divs"].append(m["div"])
        if typeof_num(d["key"]) and not typeof_num(key):
            d["key"] = key  # sessão com jogo de fase final: vale a fase
        if not m["real"]:
            continue
        g = {"a": m["a"], "b": m["b"], "sa": m["sa"], "sb": m["sb"], "div": m["div"]}
        if m["ends"]:
            g["ends"] = m["ends"]
        if m["hammer"]:
            g["hammer"] = m["hammer"]
        if m["state"] == "live":
            g["live"] = True
        d["games"].append(g)
    teams = sorted({(m["a"], m["div"]) for m in matches if m["real"]} | {(m["b"], m["div"]) for m in matches if m["real"]})
    return {
        "id": slam["site_id"], "slug": slam["tour_id"], "name": slam["series_name"], "place": slam["city"], "tz": None,
        "start": slam["start"].isoformat(), "end": slam["end"].isoformat(), "section": "gsoc", "source": "gsoc",
        "curlit": None, "split": True, "md": False,
        "draws": sorted(draws.values(), key=lambda d: d["t"]),
        "groups": [{"group": "", "div": dv, "teams": [n for n, x in teams if x == dv]} for dv in ("m", "w") if any(x == dv for _, x in teams)],
        "teams": {n: countries[n] for n, _ in teams if countries.get(n)},
    }


def typeof_num(x) -> bool:
    return isinstance(x, int)


def team_country(raw: str) -> str | None:
    bio = json.loads(raw).get("bio", {})
    return COUNTRY.get((bio.get("country") or "").strip())


def fetch_slams(today, max_age: float) -> list[dict]:
    out = []
    for s in current_slams(parse_series(fetch.get(SERIES, max_age=6 * 3600)), today):
        matches = parse_feed(fetch.get(FEED.format(tour=s["tour_id"]), max_age=max_age))
        if not matches:
            continue
        countries = {}
        ids = {(m["a"], m["ida"]) for m in matches if m["real"]} | {(m["b"], m["idb"]) for m in matches if m["real"]}
        for n, tid in ids:
            try:
                cc = team_country(fetch.get(TEAM.format(id=tid), max_age=7 * 86400))
            except Exception:
                cc = None
            if cc:
                countries[n] = cc
        out.append(build(s, matches, countries))
    return out


# ------------------------------------------------------------------ histórico (banco)

def finished_slams(series: list[dict], today) -> list[dict]:
    """Slams já encerrados, com todos os jogos registrados. O site só tem dados a partir de 2024-25."""
    out = []
    for s in series:
        if s.get("league_type_name") != "Grand Slam of Curling" or s["tour_id"].split("_")[0] not in SLAM_PREFIX:
            continue
        end = datetime.strptime(s["end_date"], "%m/%d/%Y").date()
        if end >= today or not s.get("match_count") or s.get("completed_matches") != s.get("match_count"):
            continue
        out.append({**s, "start": datetime.strptime(s["start_date"], "%m/%d/%Y").date(), "end": end})
    return out


def roles(players: list[dict]) -> list[tuple[dict, str, bool]]:
    """Posição de cada jogador. Quem é 'SKIP' joga a 4ª pedra, a não ser que o time tenha também um 'FOURTH'
    (aí o skip lança a 3ª, como fazem alguns times)."""
    pos = [POSITION.get((p.get("position_name") or p.get("position") or "").upper(), "player") for p in players]
    has_fourth = "fourth" in pos
    return [(p, ("third" if has_fourth else "fourth") if r == "skip" else r, r == "skip") for p, r in zip(players, pos)]


def fetch_history(s: dict) -> dict:
    """Tudo de um Slam encerrado: jogos, formação de cada time, ficha de cada jogo e país de cada time.
    São arquivos que não mudam mais: ficam no cache para sempre."""
    raw = json.loads(fetch.get(FEED.format(tour=s["tour_id"])))["matches"]
    team_ids = {p["id"] for m in raw for p in m.get("participants") or [] if _real(p.get("name", ""))}
    squads, countries, details = {}, {}, {}
    for tid in team_ids:
        try:
            squads[tid] = json.loads(fetch.get(SQUAD.format(series=s["series_id"], team=tid)))["squads"]
        except Exception:  # noqa: BLE001
            squads[tid] = None
        try:
            countries[tid] = team_country(fetch.get(TEAM.format(id=tid)))
        except Exception:  # noqa: BLE001
            countries[tid] = None
    for m in raw:
        if m.get("event_state") == "R" and m.get("game_id"):
            try:
                details[str(m["game_id"])] = json.loads(fetch.get(MATCH.format(id=m["game_id"])))
            except Exception:  # noqa: BLE001
                pass
    return {"series": s, "matches": raw, "squads": squads, "countries": countries, "details": details}
