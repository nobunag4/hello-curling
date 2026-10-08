"""Leitor do placar ao vivo da World Curling (livescores.worldcurling.org, sistema CURLIT).

Usado para a temporada atual: tabela de jogos com placar, atualizada durante o evento.
As fichas de time trazem nome completo, gênero e mão de lançamento, mas não o código oficial do atleta,
então cada pessoa é ligada ao banco pelo identity.resolve.
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import fetch
from ..dom import parse

BASE = "https://livescores.worldcurling.org"
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}

# Eventos acompanhados ao vivo: slug do site -> (id no nosso site, fuso da sede, ano de início, primeiro dia, último dia)
EVENTS = {
    "wmdqe26": ("wmdqe26", "America/Denver", 2026, "2026-10-01", "2026-10-09"),
}

HEADER = re.compile(
    r"(Session \d+|Draw \d+|Quarter-?finals?|Semi-?finals?|Finals?|Bronze(?: Medal)?(?: Game)?|Gold(?: Medal)?(?: Game)?|"
    r"Tie-?breakers?|Page \S+|Qualification \S*)\s+(Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d{1,2}) ([A-Z][a-z]{2}) (\d{1,2}:\d{2})")
CODE = re.compile(r"^[A-Z]{3}$")


def summary_url(slug: str) -> str:
    return f"{BASE}/{slug}/aspnet/summary?EventID=1"


def parse_summary(markup: str, year: int, tz: str) -> list[dict]:
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
        mon = MONTHS[h.group(4)]
        y = year if mon >= 7 else year + 1
        hh, mm = map(int, h.group(5).split(":"))
        start = datetime(y, mon, int(h.group(3)), hh, mm, tzinfo=ZoneInfo(tz))
        games, n = [], 0
        while n + 1 < len(toks) and CODE.match(toks[n]) and CODE.match(toks[n + 1]):
            a, b = toks[n], toks[n + 1]
            n += 2
            sa = sb = None
            if n + 1 < len(toks) and re.fullmatch(r"\*?\d+", toks[n]) and re.fullmatch(r"\*?\d+", toks[n + 1]):
                sa, sb = int(toks[n].lstrip("*")), int(toks[n + 1].lstrip("*"))
                n += 2
            games.append({"a": a, "b": b, "sa": sa, "sb": sb})
        out.append({"label": h.group(1), "start_utc": start.astimezone(ZoneInfo("UTC")).isoformat(), "games": games})
    return out


def teams_url(slug: str) -> str:
    return f"{BASE}/{slug}/aspnet/teams.aspx?EventID=1"


def parse_teams(markup: str) -> list[dict]:
    root = parse(markup)
    out = []
    for a in root.find_all("a"):
        m = re.search(r"teamDetail\.aspx\?EventID=1&TeamID=(\d+)", a.attrs.get("href", ""))
        if not m:
            continue
        tr = a.parent.parent
        cells = [td.text() for td in tr.element_children() if td.tag == "td"]
        code = next((c.split()[-1] for c in cells[1:2] if c), None)
        out.append({"team_id": int(m.group(1)), "country": a.text(), "code": code, "label": cells[2] if len(cells) > 2 else ""})
    return out


def team_detail_url(slug: str, team_id: int) -> str:
    return f"{BASE}/{slug}/aspnet/teamDetail.aspx?EventID=1&TeamID={team_id}"


def split_name(raw: str) -> str:
    """'SUMI Elen Naomi' -> 'Elen Naomi Sumi' (sobrenome em caixa alta vem primeiro)."""
    toks = raw.split()
    fam = [t for t in toks if t.isupper() and len(t) > 1]
    giv = [t for t in toks if t not in fam]
    return " ".join(giv + [f.title() for f in fam]) if fam else raw


def parse_team_detail(markup: str) -> list[dict]:
    """Escalação original do time. Colunas: Name | Position | Function | Delivery | Gender.
    Nas duplas mistas a coluna Function traz M/F (homem/mulher) e Gender fica vazia; técnicos têm Function = C."""
    root = parse(markup)
    header = next((tr for tr in root.find_all("tr")
                   if [td.text() for td in tr.element_children()][:1] == ["Name"]), None)
    if header is None:
        return []
    cols = [td.text() for td in header.element_children()]
    idx = {c: i for i, c in enumerate(cols)}
    out = []
    for tr in header.parent.find_all("tr"):
        if tr is header:
            continue
        cells = [td.text() for td in tr.element_children() if td.tag == "td"]
        if len(cells) != len(cols) or not cells[0]:
            continue
        get = lambda c: cells[idx[c]] if c in idx else ""
        func, gender = get("Function"), get("Gender")
        if func in ("M", "F") and not gender:
            gender = func
        out.append({"raw": cells[0], "name": split_name(cells[0]), "gender": gender or None,
                    "delivery": {"R": "right", "L": "left"}.get(get("Delivery")),
                    "function": "coach" if func == "C" else "alternate" if func == "A" else "player",
                    "position": get("Position") or None})
    return out


def fetch_event(slug: str, max_age: float = 120) -> dict:
    site_id, tz, year = EVENTS[slug][:3]
    sessions = parse_summary(fetch.get(summary_url(slug), max_age=max_age), year, tz)
    teams = parse_teams(fetch.get(teams_url(slug), max_age=6 * 3600))
    for t in teams:
        t["members"] = parse_team_detail(fetch.get(team_detail_url(slug, t["team_id"]), max_age=24 * 3600))
    return {"slug": slug, "site_id": site_id, "tz": tz, "sessions": sessions, "teams": teams}
