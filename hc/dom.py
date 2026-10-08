"""Árvore HTML mínima sobre html.parser, só com a biblioteca padrão.

Tolera HTML malformado: tags órfãs de fechamento são ignoradas e tags abertas
sem fechamento são fechadas quando o pai fecha.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
SKIP = {"script", "style", "svg", "noscript"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict | None = None, parent: "Node | None" = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list[Node | str] = []
        self.parent = parent

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def iter(self):
        for c in self.children:
            if isinstance(c, Node):
                yield c
                yield from c.iter()

    def find_all(self, tag: str | None = None, cls: str | None = None, **attrs) -> list["Node"]:
        out = []
        for n in self.iter():
            if tag and n.tag != tag:
                continue
            if cls and cls not in n.classes:
                continue
            if any(n.attrs.get(k) != v for k, v in attrs.items()):
                continue
            out.append(n)
        return out

    def find(self, tag: str | None = None, cls: str | None = None, **attrs) -> "Node | None":
        r = self.find_all(tag, cls, **attrs)
        return r[0] if r else None

    def element_children(self) -> list["Node"]:
        return [c for c in self.children if isinstance(c, Node)]

    def text(self) -> str:
        parts = []
        for c in self.children:
            parts.append(c if isinstance(c, str) else c.text())
        return clean(" ".join(parts))

    def __repr__(self):
        return f"<{self.tag} {self.attrs.get('class', '')}>"


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s).replace("\xa0", " ")).strip()


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.cur = self.root
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if self.skip_depth:
            if tag in SKIP:
                self.skip_depth += 1
            return
        if tag in SKIP:
            self.skip_depth = 1
            return
        node = Node(tag, {k: (v or "") for k, v in attrs}, self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        if self.skip_depth or tag in SKIP:
            return
        self.cur.children.append(Node(tag, {k: (v or "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        if self.skip_depth:
            if tag in SKIP:
                self.skip_depth -= 1
            return
        if tag in VOID:
            return
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is self.root:
            return  # fechamento órfão
        self.cur = n.parent

    def handle_data(self, data):
        if not self.skip_depth and data:
            self.cur.children.append(data)


def parse(markup: str) -> Node:
    b = _Builder()
    b.feed(markup)
    b.close()
    return b.root
