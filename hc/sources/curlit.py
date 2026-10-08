"""Calendário automático a partir do sistema oficial de placares da World Curling (CURLIT).

A página principal (livescores.worldcurling.org) lista o torneio em andamento e os próximos, com cidade e datas.
Cada torneio tem um ou mais eventos (masculino, feminino, duplas mistas) e, para cada um, um resumo com todas as
sessões: horário local da sede, confrontos e placares. Os confrontos dos próximos torneios costumam ser publicados
semanas antes, então o site passa a mostrar a tabela sem ninguém digitar nada.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .. import fetch
from ..dom import parse

BASE = "https://livescores.worldcurling.org"
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
CODE = re.compile(r"^[A-Z]{3}$")

# Fuso da sede. Países com um fuso só pelo nome; nos grandes, pela província/estado ou pela cidade.
COUNTRY_TZ = {
    "Czechia": "Europe/Prague", "Czech Republic": "Europe/Prague", "Scotland": "Europe/London", "England": "Europe/London",
    "Wales": "Europe/London", "Ireland": "Europe/Dublin", "Sweden": "Europe/Stockholm", "Norway": "Europe/Oslo",
    "Finland": "Europe/Helsinki", "Denmark": "Europe/Copenhagen", "Switzerland": "Europe/Zurich", "Italy": "Europe/Rome",
    "Germany": "Europe/Berlin", "Austria": "Europe/Vienna", "Netherlands": "Europe/Amsterdam", "Belgium": "Europe/Brussels",
    "France": "Europe/Paris", "Spain": "Europe/Madrid", "Portugal": "Europe/Lisbon", "Poland": "Europe/Warsaw",
    "Slovenia": "Europe/Ljubljana", "Slovakia": "Europe/Bratislava", "Hungary": "Europe/Budapest", "Latvia": "Europe/Riga",
    "Lithuania": "Europe/Vilnius", "Estonia": "Europe/Tallinn", "Turkey": "Europe/Istanbul", "Türkiye": "Europe/Istanbul",
    "Russia": "Europe/Moscow", "Ukraine": "Europe/Kyiv", "Romania": "Europe/Bucharest", "Bulgaria": "Europe/Sofia",
    "Croatia": "Europe/Zagreb", "Serbia": "Europe/Belgrade", "Andorra": "Europe/Andorra", "Iceland": "Atlantic/Reykjavik",
    "Japan": "Asia/Tokyo", "Korea": "Asia/Seoul", "South Korea": "Asia/Seoul", "China": "Asia/Shanghai",
    "Kazakhstan": "Asia/Almaty", "New Zealand": "Pacific/Auckland", "Brazil": "America/Sao_Paulo",
}
REGION_TZ = {
    # Canadá
    "BC": "America/Vancouver", "AB": "America/Edmonton", "SK": "America/Regina", "MB": "America/Winnipeg",
    "ON": "America/Toronto", "QC": "America/Toronto", "NB": "America/Moncton", "NS": "America/Halifax",
    "PE": "America/Halifax", "NL": "America/St_Johns", "YT": "America/Whitehorse", "NT": "America/Edmonton",
    # Estados Unidos
    "WA": "America/Los_Angeles", "OR": "America/Los_Angeles", "CA": "America/Los_Angeles", "NV": "America/Los_Angeles",
    "CO": "America/Denver", "UT": "America/Denver", "ID": "America/Denver", "MT": "America/Denver", "AZ": "America/Phoenix",
    "NM": "America/Denver", "WY": "America/Denver", "ND": "America/Chicago", "SD": "America/Chicago", "MN": "America/Chicago",
    "WI": "America/Chicago", "IL": "America/Chicago", "MO": "America/Chicago", "TX": "America/Chicago", "IA": "America/Chicago",
    "MI": "America/Detroit", "OH": "America/New_York", "NY": "America/New_York", "PA": "America/New_York",
    "MA": "America/New_York", "VT": "America/New_York", "NH": "America/New_York", "ME": "America/New_York", "CT": "America/New_York",
}
CITY_TZ = {
    "Calgary": "America/Edmonton", "Edmonton": "America/Edmonton", "Vancouver": "America/Vancouver", "Penticton": "America/Vancouver",
    "Kelowna": "America/Vancouver", "Winnipeg": "America/Winnipeg", "Regina": "America/Regina", "Saskatoon": "America/Regina",
    "Toronto": "America/Toronto", "Ottawa": "America/Toronto", "Halifax": "America/Halifax", "Saint John": "America/Moncton",
    "Moncton": "America/Moncton", "Fredericton": "America/Moncton", "St. John's": "America/St_Johns", "Victoria": "America/Vancouver",
    "Ogden": "America/Denver", "Lafayette": "America/Denver", "Denver": "America/Denver", "Las Vegas": "America/Los_Angeles",
    "Seattle": "America/Los_Angeles", "Everett": "America/Los_Angeles", "Minneapolis": "America/Chicago", "Duluth": "America/Chicago",
    "Saint Paul": "America/Chicago", "St. Paul": "America/Chicago", "Grand Forks": "America/Chicago", "Fargo": "America/Chicago",
    "Bemidji": "America/Chicago", "Utica": "America/New_York", "Schenectady": "America/New_York",
}


def tz_for(place: str) -> str | None:
    """'Ostrava, Czechia' / 'Lafayette, CO, USA' / 'Saint John, NB' / 'Calgary, Canada' -> fuso IANA."""
    parts = [p.strip() for p in place.split(",") if p.strip()]
    if not parts:
        return None
    if parts[0] in CITY_TZ:
        return CITY_TZ[parts[0]]
    for p in parts[1:]:
        if p in REGION_TZ:
            return REGION_TZ[p]
    return COUNTRY_TZ.get(parts[-1])


# ---------------- página principal: torneios atuais e próximos

def parse_index(markup: str) -> list[dict]:
    root = parse(markup)
    out = []
    for section, cid in (("current", "current-events-carousel"), ("upcoming", "upcoming-events-carousel"),
                         ("previous", "lastseason-events-carousel")):
        box = next(iter(root.find_all("div", id=cid)), None)
        if box is None:
            continue
        for a in box.find_all("a"):
            m = re.match(r"https?://livescores\.worldcurling\.org/([\w-]+)/?$", a.attrs.get("href", ""))
            title = next(iter(a.find_all("div", "event-tile-title")), None)
            when = next(iter(a.find_all("div", "event-tile-dates")), None)
            if not (m and title and when):
                continue
            place, _, span = when.text().rpartition("|")
            start, end = _span(span.strip())
            out.append({"slug": m.group(1), "name": title.text(), "place": place.strip(), "start": start, "end": end,
                        "section": section})
    return out


def _span(s: str) -> tuple[date | None, date | None]:
    """'Oct 27 - Nov 1, 2026' / 'Dec 8 - Dec 21, 2026' -> (início, fim)."""
    m = re.match(r"([A-Z][a-z]{2}) (\d{1,2}) - ([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", s)
    if not m:
        return None, None
    y = int(m.group(5))
    end = date(y, MONTHS[m.group(3)], int(m.group(4)))
    start = date(y, MONTHS[m.group(1)], int(m.group(2)))
    if start > end:  # torneio que atravessa o ano
        start = start.replace(year=y - 1)
    return start, end


# ---------------- página de resumo de um evento

def summary_url(slug: str, event_id: int) -> str:
    return f"{BASE}/{slug}/aspnet/summary?EventID={event_id}"


def api_url(slug: str) -> str:
    return f"{BASE}/{slug}/aspnet/gamecenter?GameID=1"


def parse_api_keys(markup: str) -> dict:
    """Temporada e código do torneio na API de placar ao vivo (campos escondidos da central de jogos)."""
    get = lambda k: (re.search(rf'id="ContentMain_Hidden{k}" value="([^"]*)"', markup) or [None, None])[1]
    return {"season": get("Season"), "comp": get("Competition")}


def parse_meta(markup: str) -> dict:
    """Os eventos do torneio (1 = Men, 2 = Women...)."""
    root = parse(markup)
    events = []
    for a in root.find_all("a"):
        m = re.search(r"EventID=(\d+)$", a.attrs.get("href", ""))
        if m and re.fullmatch(r"TreeView\d+t0", a.attrs.get("id", "")) and int(m.group(1)) > 0:
            events.append({"event_id": int(m.group(1)), "title": a.attrs.get("title") or a.text()})
    return {"events": events}


WD = r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
HEADER = re.compile(
    r"(Play-?off (?:Session|Game|Round) ?\d+|(?:Session|Draw|Round)\s*[A-Z]?\d+[A-Z]?(?:,? (?:Group|Pool) [A-Z])?|Quarter-?finals?|Semi-?finals?|Finals?|"
    r"Bronze(?: Medal)?(?: Games?)?|Gold(?: Medal)?(?: Games?)?|Medal Games?|Tie-?breakers?|Page \S+|Play-?offs?|"
    r"Qualification(?: Games?)?(?: \S+)?|Classification(?: Games?)?|Relegation(?: Games?)?|Crossover(?: Games?)?)"
    r"\s+" + WD + r" (\d{1,2}) ([A-Z][a-z]{2}) (\d{1,2}:\d{2})")
STANDINGS = re.compile(r"(?:^|\s)(?:Group|Pool) ([A-Z])\s+")


def stage_key(label: str) -> tuple[str | int, str | None]:
    """'Session 7' -> (7, None); 'Session A1' / 'Session 1, Group A' -> (1, 'A'); 'Semi-finals' -> ('sf', None)...
    (as chaves que o site traduz)."""
    low = label.lower()
    if low.startswith("play"):
        return "po", None
    m = re.match(r"(?:Session|Draw|Round)\s*([A-Z])?(\d+)([A-Z])?(?:,? (?:Group|Pool) ([A-Z]))?", label)
    if m:
        return int(m.group(2)), m.group(1) or m.group(3) or m.group(4)
    return _stage_word(low), None


def _stage_word(low: str) -> str:
    if low.startswith("quarter"):
        return "qf"
    if low.startswith("semi"):
        return "sf"
    if low.startswith("tie"):
        return "tb"
    if low.startswith("bronze"):
        return "bronze"
    if low.startswith(("final", "gold", "medal")):
        return "fin"
    if low.startswith("page"):
        return "po"
    return label


def parse_sessions(markup: str, start: date, tz: str) -> list[dict]:
    text = parse(markup).text()
    i = text.find("Time in")
    text = text[i:] if i >= 0 else text
    j = text.find("Round Robin Standings")
    text = text[:j] if j >= 0 else text
    heads = list(HEADER.finditer(text))
    out = []
    for k, h in enumerate(heads):
        body = text[h.end(): heads[k + 1].start() if k + 1 < len(heads) else len(text)]
        toks = body.split()
        mon, day = MONTHS[h.group(3)], int(h.group(2))
        # o ano certo é o que deixa a data perto do torneio (torneios de dezembro a janeiro)
        y = min((start.year - 1, start.year, start.year + 1), key=lambda yy: abs((date(yy, mon, day) - start).days))
        hh, mm = map(int, h.group(4).split(":"))
        local = datetime(y, mon, day, hh, mm, tzinfo=ZoneInfo(tz))
        games, n = [], 0
        while n + 1 < len(toks) and CODE.match(toks[n]) and CODE.match(toks[n + 1]):
            a, b = toks[n], toks[n + 1]
            n += 2
            sa = sb = None
            if n + 1 < len(toks) and re.fullmatch(r"\*?\d+", toks[n]) and re.fullmatch(r"\*?\d+", toks[n + 1]):
                sa, sb = int(toks[n].lstrip("*")), int(toks[n + 1].lstrip("*"))
                n += 2
            games.append({"a": a, "b": b, "sa": sa, "sb": sb})
        key, group = stage_key(h.group(1))
        out.append({"label": h.group(1), "key": key, "group": group,
                    "t": local.astimezone(ZoneInfo("UTC")).isoformat(timespec="minutes").replace("+00:00", "Z"), "games": games})
    return out


def parse_groups(markup: str) -> list[dict]:
    """Grupos da fase de classificação: [{'group': 'A', 'teams': [...]}] (na ordem da tabela)."""
    text = parse(markup).text()
    j = text.find("Round Robin Standings")
    if j < 0:
        return []
    text = text[j:]
    out = []
    for m in STANDINGS.finditer(text):
        teams = []
        for tok in text[m.end():].split():
            if CODE.match(tok):
                teams.append(tok)
            elif tok.isdigit() or tok == "Q" or tok in ("Team", "Wins", "Losses"):
                continue
            else:
                break
        if teams:
            out.append({"group": m.group(1), "teams": teams})
    return out


# ---------------- tudo junto

def site_id(slug: str, start: date | None) -> str:
    """'ecc' + 2026 -> 'ecc26'; slugs que já trazem o ano ficam como estão ('wmdqe26')."""
    if re.search(r"\d{2}$", slug) or not start:
        return slug
    return f"{slug}{start.year % 100:02d}"


def division_of(title: str) -> str | None:
    t = title.lower()
    if "women" in t:
        return "w"
    if "men" in t:
        return "m"
    return None


def fetch_competition(c: dict, max_age: float) -> dict | None:
    tz = tz_for(c["place"])
    if not tz or not c["start"]:
        return None
    first = fetch.get(summary_url(c["slug"], 1), max_age=max_age)
    meta = {**parse_meta(first), **parse_api_keys(fetch.get(api_url(c["slug"]), max_age=24 * 3600))}
    events = meta["events"] or [{"event_id": 1, "title": ""}]
    split = len({division_of(e["title"]) for e in events} - {None}) > 1
    draws: dict[str, dict] = {}
    groups = []
    for e in events:
        markup = first if e["event_id"] == 1 else fetch.get(summary_url(c["slug"], e["event_id"]), max_age=max_age)
        div = division_of(e["title"]) if split else None
        for s in parse_sessions(markup, c["start"], tz):
            d = draws.setdefault(s["t"], {"t": s["t"], "key": s["key"], "group": s["group"], "label": s["label"], "games": [], "divs": []})
            if div and div not in d["divs"]:
                d["divs"].append(div)
            d["games"] += [{**g, "div": div} if div else g for g in s["games"]]
        groups += [{**g, "div": div} for g in parse_groups(markup)]
    return {
        "id": site_id(c["slug"], c["start"]), "slug": c["slug"], "name": c["name"], "place": c["place"], "tz": tz,
        "start": c["start"].isoformat(), "end": c["end"].isoformat(), "section": c["section"],
        "curlit": {"season": meta["season"], "comp": meta["comp"], "events": [e["event_id"] for e in events]},
        "split": split, "md": any("mixed doubles" in e["title"].lower() for e in events) or "mixed doubles" in c["name"].lower(),
        "draws": sorted(draws.values(), key=lambda d: d["t"]), "groups": groups,
    }


def competitions(max_age: float = 6 * 3600) -> list[dict]:
    return parse_index(fetch.get(BASE + "/", max_age=max_age))
