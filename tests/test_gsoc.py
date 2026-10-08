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


if __name__ == "__main__":
    unittest.main()
