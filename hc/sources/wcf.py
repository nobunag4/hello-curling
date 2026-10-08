"""Leitores do site oficial de resultados da World Curling (results.worldcurling.org).

Páginas usadas:
  /Championship/Type/{type}             lista de edições de um tipo de campeonato
  /championship/Details/{tid}           classificação, escalações e grupos de uma edição
  /championship/DisplayResults?...&drawNumber=0   todos os jogos, com placar por end e quem jogou
  /Person/Details/{pid}                 dados pessoais e seleções de um atleta
"""
from __future__ import annotations

import re
from datetime import datetime

from .. import fetch
from ..dom import Node, clean, parse

BASE = "https://results.worldcurling.org"

# Tipos de campeonato do site (id -> nome curto e disciplina)
TYPES = {
    1: ("World Curling Championships", "teams"),
    2: ("European Curling Championships", "teams"),
    4: ("Olympic Games", "teams"),
    5: ("World Junior Curling Championships", "teams"),
    8: ("World Senior Curling Championships", "teams"),
    11: ("World Junior B Curling Championships", "teams"),
    22: ("World Mixed Doubles Curling Championships", "mixed_doubles"),
    24: ("European Curling Championships C-Division", "teams"),
    26: ("Olympic Qualifying Event", "teams"),
    27: ("World Mixed Curling Championship", "mixed"),
    32: ("World Mixed Doubles Qualification Event", "mixed_doubles"),
    33: ("European Curling Championships B Division", "teams"),
    34: ("Pre-Olympic Qualifying Event", "teams"),
    36: ("Pan Continental Curling Championships", "teams"),
    37: ("Pan Continental Curling Championships B-Division", "teams"),
    38: ("World Junior Mixed Doubles Championships", "mixed_doubles"),
    39: ("World Championship Pre-Qualifier", "teams"),
    40: ("World Championship Qualifier", "teams"),
    7: ("World Wheelchair Curling Championships", "wheelchair"),
    35: ("World Wheelchair Mixed Doubles Curling Championship", "wheelchair_md"),
    16: ("Paralympic Games", "wheelchair"),
}

FLAG_RE = re.compile(r"wcf-flags/([A-Za-z]{3})\.png")
PERSON_RE = re.compile(r"/Person/Details/(\d+)")
DETAILS_RE = re.compile(r"/championship/Details/(\d+)", re.I)


def _date(s: str):
    s = s.strip()
    for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _flag(node: Node | None) -> str | None:
    if node is None:
        return None
    img = node if node.tag == "img" else node.find("img")
    if img is None:
        return None
    m = FLAG_RE.search(img.attrs.get("src", ""))
    return m.group(1).upper() if m else None


def _person_links(node: Node) -> list[tuple[int, str, bool]]:
    """(id, nome, em_negrito) para cada link de pessoa dentro do nó."""
    out = []
    for a in node.find_all("a"):
        m = PERSON_RE.search(a.attrs.get("href", ""))
        if not m:
            continue
        bold = False
        p = a.parent
        while p is not None and p is not node:
            if p.tag in ("b", "strong"):
                bold = True
                break
            p = p.parent
        out.append((int(m.group(1)), a.text(), bold))
    return out


# ---------------------------------------------------------------- lista de edições

def type_url(type_id: int) -> str:
    return f"{BASE}/Championship/Type/{type_id}"


def parse_type_list(markup: str) -> list[dict]:
    """Uma linha por divisão (Men/Women/Mixed Doubles...) de cada edição."""
    root = parse(markup)
    out = []
    for tr in root.find_all("tr"):
        cells = {td.attrs.get("data-name"): td for td in tr.find_all("td")}
        if "Year" not in cells:
            continue
        start = _date(cells["StartDate"].text()) if "StartDate" in cells else None
        end = _date(cells["EndDate"].text()) if "EndDate" in cells else None
        for a in tr.find_all("a"):
            m = DETAILS_RE.search(a.attrs.get("href", ""))
            if not m:
                continue
            out.append({
                "tid": int(m.group(1)),
                "year": int(cells["Year"].text() or 0),
                "name": cells["Name"].text() if "Name" in cells else "",
                "city": cells["City"].text().title() if "City" in cells else "",
                "country": _flag(cells.get("Country.Name")),
                "start": start.date().isoformat() if start else None,
                "end": end.date().isoformat() if end else None,
                "division": a.text(),
            })
    return out


# ---------------------------------------------------------------- detalhes de uma edição

def details_url(tid: int) -> str:
    return f"{BASE}/championship/Details/{tid}"


ROLE_MAP = {
    "skip": "fourth", "fourth": "fourth", "third": "third", "second": "second", "lead": "lead",
    "alternate": "alternate", "team coach": "coach", "coach": "coach", "national coach": "coach",
    "team official": "official", "official": "official", "male": "player", "female": "player",
    "player": "player", "fifth": "alternate",
}


def parse_role(label: str) -> tuple[str, bool]:
    """'Lead (Skip)' -> ('lead', True); 'Skip' -> ('fourth', True); 'Third' -> ('third', False)."""
    l = clean(label).lower()
    is_skip = "skip" in l
    base = re.sub(r"\(.*?\)", "", l).strip()
    role = ROLE_MAP.get(base)
    if role is None:
        role = "coach" if "coach" in base else "official" if "official" in base else "player"
    return role, is_skip


def parse_details(markup: str) -> dict:
    root = parse(markup)
    out: dict = {"entries": [], "groups": {}}

    title = root.find("h2", cls="t-ice")
    out["title"] = title.text() if title else ""

    # Bloco lateral: divisão, local, cidade/país, datas
    side = None
    for h3 in root.find_all("h3"):
        if h3.text() in ("Men", "Women", "Mixed Doubles", "Mixed", "Wheelchair", "Wheelchair Mixed Doubles") or (
                h3.parent is not None and "col-md-12" in h3.parent.classes and h3.parent.parent is not None
                and "col-md-3" in h3.parent.parent.classes):
            side = h3.parent.parent
            out["division"] = h3.text()
            break
    if side is not None:
        blocks = [d for d in side.element_children() if d.tag == "div"]
        texts = [b.text() for b in blocks]
        venue = next((b for b in blocks if b.find("b") is not None), None)
        out["venue"] = venue.text() if venue is not None else ""
        loc = next((b for b in blocks if b.find("br") is not None), None)
        if loc is not None:
            parts = [clean(c) for c in loc.children if isinstance(c, str) and clean(c)]
            out["city"] = parts[0].title() if parts else ""
            out["country_name"] = parts[1] if len(parts) > 1 else ""
        m = re.search(r"(\d+/\d+/\d{4})\s*-\s*(\d+/\d+/\d{4})", " ".join(texts))
        if m:
            out["start"] = _date(m.group(1)).date().isoformat()
            out["end"] = _date(m.group(2)).date().isoformat()

    # Classificação final
    rank_tab = root.find(id="inforankings")
    if rank_tab is not None:
        for tr in rank_tab.find_all("tr"):
            tds = [c for c in tr.element_children() if c.tag == "td"]
            if len(tds) < 4:
                continue
            pos = tds[0].text()
            rec = re.match(r"(\d+)\s*-\s*(\d+)", tds[1].text())
            name_div = tds[3].find("div", cls="country")
            out["entries"].append({
                "rank": int(pos) if pos.isdigit() else None,
                "wins": int(rec.group(1)) if rec else None,
                "losses": int(rec.group(2)) if rec else None,
                "code": _flag(tds[2]),
                "name": name_div.text() if name_div else tds[3].text(),
                "players": [{"pid": pid, "name": n, "skip": b} for pid, n, b in _person_links(tds[3])],
            })

    # Escalações com posição (aba Teams)
    lineups: dict[str, list] = {}
    teams_tab = root.find(id="infoteams")
    if teams_tab is not None:
        for block in teams_tab.find_all("div", cls="col-md-6"):
            cdiv = block.find("div", cls="country")
            if cdiv is None:
                continue
            name = cdiv.text()
            members, pending = [], None
            for d in block.iter():
                if d.tag != "div":
                    continue
                if d.classes == {"col-md-3"} and not d.find("img"):
                    pending = d.text()
                elif d.classes == {"col-md-9"} and pending is not None:
                    links = _person_links(d)
                    if links:
                        pid, pname, bold = links[0]
                        role, is_skip = parse_role(pending)
                        members.append({"pid": pid, "name": pname, "role": role, "skip": is_skip or (bold and role != "coach"),
                                        "label": pending})
                    pending = None
            lineups[name] = {"code": _flag(block), "members": members}
    out["lineups"] = lineups

    # Grupos
    groups_tab = root.find(id="infogroups")
    if groups_tab is not None:
        for h4 in groups_tab.find_all("h4"):
            panel = h4.parent
            names = []
            for tr in panel.find_all("tr"):
                tds = [c for c in tr.element_children() if c.tag == "td"]
                if len(tds) >= 3:
                    names.append(tds[2].text())
            out["groups"][h4.text()] = names
    return out


# ---------------------------------------------------------------- jogos

def games_url(tid: int) -> str:
    return f"{BASE}/championship/DisplayResults?tournamentId={tid}&associationId=0&teamNumber=0&drawNumber=0"


def _end_value(s: str):
    s = s.strip()
    if s.isdigit():
        return int(s)
    return None  # 'X' (não jogado), vazio


def parse_games(markup: str) -> list[dict]:
    """Todos os jogos da página, na ordem em que aparecem."""
    root = parse(markup)
    games: list[dict] = []
    draw, when = None, None
    cur_game, cur_side, pending = None, None, None

    for n in root.iter():
        if n.tag == "h3":
            draw, when = n.text(), None
        elif n.tag == "b" and re.fullmatch(r"\d+/\d+/\d{4}( \d+:\d+ [AP]M)?", n.text()):
            when = _date(n.text())
        elif n.tag == "table" and "game-table" in n.classes:
            rows = [tr for tr in n.find_all("tr") if tr.find("td", cls="game-team")]
            sides, sheet = [], None
            for tr in rows:
                sh = tr.find("td", cls="game-sheet")
                if sh is not None:
                    sheet = sh.text() or None
                ends = [_end_value(td.text()) for td in tr.find_all("td") if any(c.startswith("game-end") for c in td.classes)]
                tot = tr.find("td", cls="game-total").text()
                while ends and ends[-1] is None:
                    ends.pop()
                # O site escreve "-" no total quando o time fez 0 pontos
                total = int(tot) if tot.isdigit() else (sum(e or 0 for e in ends) if ends and tot == "-" else None)
                sides.append({
                    "name": tr.find("td", cls="game-team").text(),
                    "hammer": tr.find("td", cls="game-hammer").text() == "*",
                    "ends": ends,
                    "total": total,
                    "lineup": [],
                })
            cur_game = {"draw": draw, "when": when.isoformat(sep=" ") if when else None, "sheet": sheet, "sides": sides}
            games.append(cur_game)
            cur_side, pending = None, None
        elif cur_game is not None and n.tag == "h5":
            nm = n.text()
            cur_side = next((s for s in cur_game["sides"] if s["name"] == nm), None)
        elif cur_side is not None and n.tag == "div" and n.classes == {"col-md-3"}:
            pending = n.text()
        elif cur_side is not None and n.tag == "a" and pending is not None:
            m = PERSON_RE.search(n.attrs.get("href", ""))
            if m:
                role, is_skip = parse_role(pending)
                cur_side["lineup"].append({"pid": int(m.group(1)), "name": n.text(), "role": role, "skip": is_skip, "played": None})
                pending = None
        elif cur_side is not None and n.tag == "div" and "col-md-1" in n.classes and cur_side["lineup"]:
            t = n.text()
            if t in ("Played", "-"):
                cur_side["lineup"][-1]["played"] = t == "Played"
    return games


# ---------------------------------------------------------------- pessoa

def person_url(pid: int) -> str:
    return f"{BASE}/Person/Details/{pid}"


def parse_person(markup: str) -> dict:
    root = parse(markup)
    h2 = root.find("h2", cls="t-ice")
    out = {"name": h2.text() if h2 else "", "nations": [], "born": None, "gender": None, "delivery": None}
    info_h = next((h for h in root.find_all() if h.tag in ("h2", "h3", "h4") and h.text() == "Personal information"), None)
    scope = info_h.parent.parent if info_h is not None else root
    for img in scope.find_all("img"):
        c = _flag(img)
        if c and c not in out["nations"]:
            out["nations"].append(c)
    txt = scope.text()
    m = re.search(r"Born:\s*(\d+/\d+/\d{4})", txt)
    if m:
        out["born"] = _date(m.group(1)).date().isoformat()
    m = re.search(r"Gender:\s*(Male|Female)", txt)
    if m:
        out["gender"] = "M" if m.group(1) == "Male" else "F"
    m = re.search(r"Delivery:\s*(Right|Left)", txt)
    if m:
        out["delivery"] = m.group(1).lower()
    return out


# ---------------------------------------------------------------- atalhos com rede

def fetch_type(type_id: int, max_age=None) -> list[dict]:
    """Todas as edições de um tipo. A lista do site vem em páginas de 10 (grid-page)."""
    first = fetch.get(type_url(type_id), max_age=max_age)
    pages = [int(n) for n in re.findall(r"grid-page=(\d+)", first)]
    out = parse_type_list(first)
    for n in range(2, max(pages, default=1) + 1):
        out += parse_type_list(fetch.get(f"{type_url(type_id)}?id={type_id}&grid-page={n}", max_age=max_age))
    return out


def fetch_event(tid: int, max_age=None) -> tuple[dict, list[dict]]:
    d = parse_details(fetch.get(details_url(tid), max_age=max_age))
    g = parse_games(fetch.get(games_url(tid), max_age=max_age))
    return d, g


def fetch_person(pid: int, max_age=None) -> dict:
    return parse_person(fetch.get(person_url(pid), max_age=max_age))
