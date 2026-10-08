import unittest
from pathlib import Path

from hc.sources import live

F = Path(__file__).parent / "fixtures"


class TestLive(unittest.TestCase):
    def test_summary(self):
        s = live.parse_summary((F / "live_summary_wmdqe26.html").read_text(encoding="utf-8"), 2026, "America/Denver")
        self.assertEqual(s[0]["label"], "Session 1")
        self.assertEqual(s[0]["start_utc"], "2026-10-02T15:00:00+00:00")  # 9:00 no Colorado (UTC-6)
        self.assertEqual(s[0]["games"][0], {"a": "FRA", "b": "BEL", "sa": 12, "sb": 1})
        qf = next(x for x in s if x["label"] == "Quarter-finals")
        self.assertEqual(len(qf["games"]), 4)
        sf = next(x for x in s if x["label"] == "Semi-finals")
        self.assertEqual([(g["a"], g["b"]) for g in sf["games"]], [("FRA", "LAT"), ("USA", "POL")])

    def test_teams(self):
        t = live.parse_teams((F / "live_teams_wmdqe26.html").read_text(encoding="utf-8"))
        self.assertEqual(len(t), 26)
        self.assertIn({"team_id": 53, "country": "Brazil", "code": "BRA", "label": "Sumi / Vilela"}, t)

    def test_team_detail_mixed_doubles(self):
        m = live.parse_team_detail((F / "live_team_bra.html").read_text(encoding="utf-8"))
        self.assertEqual([(x["name"], x["gender"], x["function"]) for x in m],
                         [("Elen Naomi Sumi", "F", "player"), ("Sergio Mitsuo Vilela", "M", "player"), ("Arnaldo Yamashita", "M", "coach")])

    def test_split_name(self):
        self.assertEqual(live.split_name("ZARDINI LACEDELLI Giulia"), "Giulia Zardini Lacedelli")
        self.assertEqual(live.split_name("Anna Hasselborg"), "Anna Hasselborg")


if __name__ == "__main__":
    unittest.main()
