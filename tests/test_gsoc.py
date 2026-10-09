"""Grand Slam: leitura do feed de jogos (Co-op Tour Challenge 2025, já encerrado, salvo do site oficial)."""
import unittest
from datetime import date
from pathlib import Path

from hc.sources import gsoc

FEED = (Path(__file__).parent / "fixtures" / "gsoc_feed_tch2025.json").read_text(encoding="utf-8")


class TestGsoc(unittest.TestCase):
    def test_final(self):
        ms = gsoc.parse_feed(FEED)
        final = next(m for m in ms if m["stage"] == "fin" and m["div"] == "w")
        self.assertEqual((final["a"], final["b"], final["sa"], final["sb"]), ("Tirinzoni", "Homan", 2, 8))
        self.assertEqual(final["ends"][:2], [[0, 4], [1, 0]])
        self.assertEqual(final["hammer"], "a")
        self.assertEqual(final["state"], "done")

    def test_build_groups_draws(self):
        ms = gsoc.parse_feed(FEED)
        slam = {"site_id": "gsoc-inv", "tour_id": "tch_2025", "series_name": "CO-OP Tour Challenge", "city": "Nisku, AB",
                "start": date(2025, 10, 14), "end": date(2025, 10, 19)}
        ev = gsoc.build(slam, ms, {"Homan": "CAN"})
        self.assertEqual(ev["teams"], {"Homan": "CAN"})
        self.assertTrue(all(isinstance(d["key"], int) or d["key"] in ("tb", "qf", "sf", "fin", "po") for d in ev["draws"]))
        self.assertEqual(sum(len(d["games"]) for d in ev["draws"]), sum(m["real"] for m in ms))
        self.assertEqual(ev["draws"], sorted(ev["draws"], key=lambda d: d["t"]))

    def test_names(self):
        self.assertEqual(gsoc._name("Hoesli"), "Hösli")
        self.assertFalse(gsoc._real("Men's Final: TBD"))



class HistoryTest(unittest.TestCase):
    def test_roles_skip_throws_fourth_unless_team_has_a_fourth(self):
        from hc.sources.gsoc import roles
        normal = [{"position_name": "SKIP"}, {"position_name": "THIRD"}, {"position_name": "SECOND"}, {"position_name": "LEAD"}]
        self.assertEqual([(r, s) for _, r, s in roles(normal)], [("fourth", True), ("third", False), ("second", False), ("lead", False)])
        swapped = [{"position_name": "FOURTH"}, {"position_name": "SKIP"}, {"position_name": "SECOND"}, {"position_name": "LEAD"}]
        self.assertEqual([(r, s) for _, r, s in roles(swapped)][:2], [("fourth", False), ("third", True)])

    def test_finished_slams(self):
        from datetime import date
        from hc.sources.gsoc import finished_slams
        series = [
            {"league_type_name": "Grand Slam of Curling", "tour_id": "tch_2025", "start_date": "10/14/2025", "end_date": "10/19/2025", "match_count": 82, "completed_matches": 82},
            {"league_type_name": "Grand Slam of Curling", "tour_id": "wol_2025", "start_date": "02/04/2026", "end_date": "02/22/2026", "match_count": 147, "completed_matches": 147},
            {"league_type_name": "Grand Slam of Curling", "tour_id": "tch_2026", "start_date": "10/13/2026", "end_date": "10/18/2026", "match_count": 80, "completed_matches": 0},
            {"league_type_name": "Testing", "tour_id": "tesc_2025", "start_date": "09/01/2025", "end_date": "09/05/2025", "match_count": 44, "completed_matches": 44},
        ]
        self.assertEqual([s["tour_id"] for s in finished_slams(series, date(2026, 10, 9))], ["tch_2025"])

    def test_local_time(self):
        from hc.ingest_gsoc import _local
        self.assertEqual(_local("2025-10-14T14:00-00:00", "-06:00"), "2025-10-14 08:00:00")
        self.assertEqual(_local("2025-10-14T23:30-00:00", "+01:00"), "2025-10-15 00:30:00")


if __name__ == "__main__":
    unittest.main()
