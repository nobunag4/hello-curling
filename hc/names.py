"""Normalização e comparação de nomes de pessoas.

O mesmo atleta aparece escrito de formas diferentes em cada fonte:
"Florian KRAMLINGER", "Kramlinger Florian", "F. Kramlinger", "Mads Nørgaard" / "Mads Norgaard".
Estas funções reduzem as variações a chaves comparáveis.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

# Letras que o NFKD não decompõe
_FOLD = str.maketrans({
    "ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe", "ß": "ss", "ł": "l", "Ł": "l",
    "đ": "d", "Đ": "d", "ð": "d", "þ": "th", "ı": "i", "’": "'", "‘": "'",
})
# Partículas que podem ou não aparecer, e que não ajudam a distinguir pessoas
_PARTICLES = {"van", "von", "de", "der", "den", "da", "di", "du", "le", "la", "del", "dos", "das", "do"}
# Apelidos comuns no circuito norte-americano que não são começo do nome ('Chris' de 'Christopher' já é coberto)
_NICK = {"mike": "michael", "bob": "robert", "rob": "robert", "bill": "william", "will": "william", "jim": "james",
         "jimmy": "james", "joe": "joseph", "dick": "richard", "rick": "richard", "ted": "edward", "ed": "edward",
         "andy": "andrew", "drew": "andrew", "kate": "katherine", "katie": "katherine", "liz": "elizabeth",
         "beth": "elizabeth", "becca": "rebecca", "becky": "rebecca", "jenn": "jennifer", "jen": "jennifer",
         "peggy": "margaret", "maggie": "margaret", "tony": "anthony", "jack": "john", "johnny": "john",
         "danny": "daniel", "dan": "daniel", "benny": "benjamin", "charlie": "charles", "chuck": "charles", "matt": "matthew", "tom": "thomas", "tommy": "thomas", "nick": "nicholas"}


def fold(s: str) -> str:
    """minúsculas, sem acentos, só letras/dígitos/espaços."""
    s = s.translate(_FOLD)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", " ", s).lower()
    return re.sub(r"\s+", " ", s).strip()


def display(raw: str) -> str:
    """Corrige sobrenomes em CAIXA ALTA para exibição: 'Florian KRAMLINGER' -> 'Florian Kramlinger'."""
    raw = re.sub(r"\s+", " ", raw).strip()
    out = []
    for tok in raw.split(" "):
        letters = [c for c in tok if c.isalpha()]
        if len(letters) > 1 and all(c.isupper() for c in letters):
            tok = "-".join(p[:1] + p[1:].lower() for p in tok.split("-"))
        out.append(tok)
    return " ".join(out)


def tokens(s: str) -> list[str]:
    return [t for t in fold(s).split() if t]


def key(s: str) -> str:
    """Chave independente de ordem: 'Pfister Marc' e 'Marc Pfister' viram 'marc pfister'."""
    return " ".join(sorted(tokens(s)))


def is_initial(tok: str) -> bool:
    return len(tok) == 1


def similarity(a: str, b: str) -> float:
    """0..1. Pensado para nome completo x nome completo, nome com inicial ou só sobrenome.

    1.00  mesmos tokens (em qualquer ordem)
    0.90  um nome contém o outro inteiro ('Giulia Zardini Lacedelli' x 'Zardini Lacedelli')
          desde que o menor tenha sobrenome com 2+ tokens ou haja só partículas sobrando
    0.88  inicial compatível + mesmo sobrenome ('Y. Schwaller' x 'Yannick Schwaller')
    0.75  só o sobrenome bate ('Schwaller' x 'Yannick Schwaller')
    ~0.8  erro de digitação (difflib >= 0.9 sobre as chaves)
    """
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    if sorted(ta) == sorted(tb):
        return 1.0
    # nomes asiáticos: ordem trocada e partes unidas ou com hífen ('Gim Eun-ji' x 'Eunji Gim')
    if len(ta) <= 4 and len(tb) <= 4 and _joined(ta) & _joined(tb):
        return 0.97
    # apelido ou forma curta do primeiro nome, com o resto igual ('Chris Plys' x 'Christopher Plys')
    if len(ta) == len(tb) >= 2:
        diff = [(x, y) for x, y in zip(sorted(ta, key=lambda t: t in tb), sorted(tb, key=lambda t: t in ta)) if x != y]
        rest_a, rest_b = [t for t in ta if t in tb], [t for t in tb if t in ta]
        if len(diff) == 1 and len(rest_a) == len(ta) - 1 and len(rest_b) == len(tb) - 1:
            x, y = diff[0]
            if min(len(x), len(y)) >= 3 and (x.startswith(y) or y.startswith(x) or _NICK.get(x) == y or _NICK.get(y) == x):
                return 0.9
    sa = [t for t in ta if t not in _PARTICLES]
    sb = [t for t in tb if t not in _PARTICLES]
    if sorted(sa) == sorted(sb):
        return 0.98

    full_a = [t for t in sa if not is_initial(t)]
    full_b = [t for t in sb if not is_initial(t)]
    ini_a = [t for t in sa if is_initial(t)]
    ini_b = [t for t in sb if is_initial(t)]

    small, big = (full_a, full_b) if len(full_a) <= len(full_b) else (full_b, full_a)
    small_ini, big_full = (ini_a, full_b) if len(full_a) <= len(full_b) else (ini_b, full_a)
    if small and set(small) <= set(big):
        leftover = [t for t in big if t not in small]
        if small_ini:
            # 'Y Schwaller' x 'Yannick Schwaller': as iniciais precisam bater com os tokens que sobram
            if all(any(l.startswith(i) for l in leftover) for i in small_ini):
                return 0.88
            return 0.2  # inicial diferente: provavelmente outra pessoa (Xenia x Yannick)
        if len(small) >= 2:
            return 0.9
        return 0.75

    r = difflib.SequenceMatcher(None, " ".join(sorted(sa)), " ".join(sorted(sb))).ratio()
    if r >= 0.9:
        return round(0.8 * r, 3)
    return round(r * 0.5, 3)


def _joined(toks: list[str]) -> set[str]:
    """Todas as ordens dos tokens, coladas: 'eun ji gim' -> {'eunjigim', 'gimeunji', ...}."""
    from itertools import permutations
    return {"".join(p) for p in permutations(toks)}
