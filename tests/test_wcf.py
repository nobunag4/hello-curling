import unittest
from pathlib import Path

from hc.sources import wcf

F = Path(__file__).parent / "fixtures"


def read(name):
    return (F / name).read_text(encoding="utf-8")


class TestWcfParsers(unittest.TestCase):
    def test_type_list(self):
        rows = wcf.parse_type_list(read("wcf_type_34.html"))
        self.assertEqual({r["tid"] for r in rows}, {809, 810, 682, 683, 684})
        r = next(r for r in rows if r["tid"] == 809)
        self.assertEqual((r["year"], r["division"], r["country"], r["start"]), (2025, "Men", "SCO", "2025-10-07"))

    def test_details(self):
        d = wcf.parse_details(read("wcf_details_809.html"))
        self.assertEqual(d["title"], "Pre-Olympic Qualification Event 2025")
        self.assertEqual((d["city"], d["start"], d["end"]), ("Aberdeen", "2025-10-07", "2025-10-11"))
        self.assertEqual(len(d["entries"]), 7)
        top = d["entries"][0]
        self.assertEqual((top["rank"], top["code"], top["wins"], top["losses"]), (1, "PHI", 6, 0))
        den = d["lineups"]["Denmark"]["members"]
        skip = [m for m in den if m["skip"]]
        self.assertEqual([(m["name"], m["role"]) for m in skip], [("Jacob Schmidt", "third")])
        self.assertIn("coach", {m["role"] for m in den})

    def test_games(self):
        g = wcf.parse_games(read("wcf_games_809.html"))
        self.assertEqual(len(g), 23)
        first = g[0]
        self.assertEqual((first["draw"], first["when"], first["sheet"]), ("Draw #1", "2025-10-07 17:30:00", "A"))
        nz, aus = first["sides"]
        self.assertEqual((nz["name"], nz["total"], nz["hammer"], nz["ends"]), ("New Zealand", 8, True, [1, 1, 1, 4, 1, 0]))
        self.assertEqual(aus["total"], 1)
        self.assertEqual(sum(1 for p in nz["lineup"] if p["played"]), 4)
        # o site escreve '-' quando o time não marcou: deve virar 0
        tpe = next(s for x in g if x["draw"] == "Draw #2" for s in x["sides"] if s["name"] == "Chinese Taipei")
        self.assertEqual(tpe["total"], 0)
        self.assertTrue(all(len(x["sides"]) == 2 and all(s["total"] is not None for s in x["sides"]) for x in g))

    def test_person(self):
        p = wcf.parse_person(read("wcf_person_5654.html"))
        self.assertEqual(p, {"name": "Marc Pfister", "nations": ["SUI", "PHI"], "born": "1989-09-26", "gender": "M", "delivery": "right"})

    def test_roles(self):
        self.assertEqual(wcf.parse_role("Lead (Skip)"), ("lead", True))
        self.assertEqual(wcf.parse_role("Skip"), ("fourth", True))
        self.assertEqual(wcf.parse_role("Team Coach"), ("coach", False))
        self.assertEqual(wcf.parse_role("Female"), ("player", False))


if __name__ == "__main__":
    unittest.main()
