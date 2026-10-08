"""Calendário automático: leitura da página principal e dos resumos do placar oficial (páginas reais salvas)."""
import unittest
from datetime import date
from pathlib import Path

from hc.sources import curlit

FIX = Path(__file__).parent / "fixtures"
read = lambda n: (FIX / n).read_text(encoding="utf-8")


class TestCurlit(unittest.TestCase):
    def test_index(self):
        cs = {c["slug"]: c for c in curlit.parse_index(read("curlit_index.html"))}
        ecc = cs["ecc"]
        self.assertEqual(ecc["section"], "upcoming")
        self.assertEqual((ecc["start"], ecc["end"]), (date(2026, 10, 27), date(2026, 11, 1)))
        self.assertEqual(ecc["place"], "Ostrava, Czechia")
        self.assertEqual(cs["wmdqe26"]["section"], "current")

    def test_timezones(self):
        self.assertEqual(curlit.tz_for("Ostrava, Czechia"), "Europe/Prague")
        self.assertEqual(curlit.tz_for("Lafayette, CO, USA"), "America/Denver")
        self.assertEqual(curlit.tz_for("Saint John, NB"), "America/Moncton")
        self.assertEqual(curlit.tz_for("Calgary, Canada"), "America/Edmonton")
        self.assertIsNone(curlit.tz_for("Somewhere, Canada"))  # sem adivinhar fuso em país com vários

    def test_span_across_year(self):
        self.assertEqual(curlit._span("Dec 28 - Jan 3, 2027"), (date(2026, 12, 28), date(2027, 1, 3)))

    def test_sessions_ecc(self):
        ss = curlit.parse_sessions(read("curlit_ecc_men.html"), date(2026, 10, 27), "Europe/Prague")
        s2 = ss[0]
        self.assertEqual((s2["key"], s2["t"]), (2, "2026-10-28T07:30Z"))  # 8:30 em Ostrava (horário de inverno, UTC+1)
        self.assertEqual([(g["a"], g["b"]) for g in s2["games"]], [("AUT", "BEL"), ("ITA", "GER"), ("SWE", "NOR"), ("SCO", "NED")])
        self.assertEqual([s["key"] for s in ss[-2:]], ["sf", "fin"])

    def test_sessions_with_groups(self):
        ss = curlit.parse_sessions(read("curlit_wcqm.html"), date(2026, 11, 8), "Europe/London")
        self.assertEqual((ss[0]["key"], ss[0]["group"]), (1, "A"))
        self.assertEqual((ss[1]["key"], ss[1]["group"]), (1, "B"))
        self.assertEqual(ss[-1]["key"], "po")
        ww = curlit.parse_sessions(read("curlit_wwhbcc.html"), date(2026, 11, 23), "Europe/Helsinki")
        self.assertEqual((ww[0]["key"], ww[0]["group"]), (1, "A"))
        self.assertEqual(len(ww[0]["games"]), 3)

    def test_groups(self):
        gs = curlit.parse_groups(read("curlit_wcqm.html"))
        self.assertEqual([g["group"] for g in gs], ["A", "B"])
        self.assertIn("NOR", gs[0]["teams"])
        self.assertEqual(len(gs[0]["teams"]), 8)

    def test_meta(self):
        meta = curlit.parse_meta(read("curlit_ecc_men.html"))
        self.assertEqual([(e["event_id"], e["title"]) for e in meta["events"]], [(1, "Men"), (2, "Women")])
        self.assertEqual(curlit.parse_api_keys(read("curlit_gamecenter_ecc.html")), {"season": "2627", "comp": "ECC"})

    def test_site_id(self):
        self.assertEqual(curlit.site_id("ecc", date(2026, 10, 27)), "ecc26")
        self.assertEqual(curlit.site_id("wmdqe26", date(2026, 10, 2)), "wmdqe26")


if __name__ == "__main__":
    unittest.main()
