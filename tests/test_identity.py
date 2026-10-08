"""Cenários reais de identidade, montados num banco em memória."""
import json
import unittest

from hc import db, identity, ingest


def lineup(*members):
    return [{"pid": pid, "name": n, "role": role, "skip": i == 0, "label": role.title()}
            for i, (pid, n, role) in enumerate(members)]


def add_event(con, tid, year, division, teams):
    """teams: {nome_time: (código, [membros])}"""
    details = {"title": f"Evento {tid}", "division": division, "start": f"{year}-11-01", "end": f"{year}-11-07",
               "entries": [{"rank": i + 1, "wins": 0, "losses": 0, "code": code, "name": name, "players": []}
                           for i, (name, (code, _)) in enumerate(teams.items())],
               "lineups": {name: {"code": code, "members": lineup(*ms)} for name, (code, ms) in teams.items()},
               "groups": {}}
    meta = {"tid": tid, "year": year, "type_id": 2, "division": division}
    ingest.ingest_wcf_event(con, meta, details, [])


class TestIdentity(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        c = self.con
        add_event(c, 1, 2023, "Men", {
            "Switzerland": ("SUI", [(100, "Yannick Schwaller", "fourth"), (101, "Benoit Schwarz-van Berkel", "third"),
                                    (102, "Sven Michel", "second"), (103, "Pablo Lachat-Couchepin", "lead")]),
        })
        add_event(c, 2, 2023, "Women", {
            "Switzerland": ("SUI", [(200, "Xenia Schwaller", "fourth"), (201, "Selina Gafner", "third"),
                                    (202, "Fabienne Rieder", "second"), (203, "Selina Rychiger", "lead")]),
            "Italy": ("ITA", [(300, "Stefania Constantini", "fourth"), (301, "Giulia ZARDINI LACEDELLI", "third"),
                              (302, "Elena Mathis", "second"), (303, "Angela Romei", "lead")]),
        })
        # mesma pessoa com dois códigos (dado antigo), e um homônimo de verdade
        add_event(c, 3, 2005, "Men", {"Norway": ("NOR", [(400, "Ole Hansen", "fourth")])})
        add_event(c, 4, 2010, "Men", {"Norway": ("NOR", [(401, "Ole Hansen", "fourth")])})
        add_event(c, 5, 2011, "Men", {"Denmark": ("DEN", [(402, "Ole Hansen", "fourth")])})
        c.execute("UPDATE person SET born='1980-01-01' WHERE wcf_id IN (400, 401)")
        c.execute("UPDATE person SET born='1990-05-05' WHERE wcf_id = 402")
        self.idx = identity.NameIndex(c)

    def tearDown(self):
        self.con.close()

    def pid(self, wcf_id):
        return self.con.execute("SELECT id FROM person WHERE wcf_id=?", (wcf_id,)).fetchone()[0]

    def test_anchor_keeps_one_person_per_code(self):
        a = identity.person_for_wcf(self.con, 300, "Stefania Constantini")
        b = identity.person_for_wcf(self.con, 300, "CONSTANTINI Stefania")
        self.assertEqual(a, b)
        self.assertEqual(self.con.execute("SELECT name FROM person WHERE wcf_id=301").fetchone()[0], "Giulia Zardini Lacedelli")

    def test_initial_picks_right_schwaller(self):
        y, conf = identity.resolve(self.con, "gsoc", "m:Y. Schwaller", "Y. Schwaller", gender="M", season="2026-27", index=self.idx)
        x, _ = identity.resolve(self.con, "gsoc", "w:X. Schwaller", "X. Schwaller", gender="F", season="2026-27", index=self.idx)
        self.assertEqual(y, self.pid(100))
        self.assertEqual(x, self.pid(200))

    def test_surname_only_with_gender(self):
        p, _ = identity.resolve(self.con, "gsoc", "w:Zardini Lacedelli", "Zardini Lacedelli", gender="F", season="2026-27", index=self.idx)
        self.assertEqual(p, self.pid(301))

    def test_teammates_resolve_ambiguity(self):
        # 'Schwaller' sozinho é ambíguo entre Yannick e Xenia, sem gênero
        p, _ = identity.resolve(self.con, "x", "k1", "Schwaller", index=self.idx)
        self.assertIsNone(p)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM review WHERE kind='person_link'").fetchone()[0], 1)
        # com os colegas de time, fica claro
        mates = {self.pid(101), self.pid(102)}
        p, _ = identity.resolve(self.con, "x", "k2", "Schwaller", teammates=mates, season="2024-25", index=self.idx)
        self.assertEqual(p, self.pid(100))

    def test_decision_is_remembered(self):
        p1, _ = identity.resolve(self.con, "gsoc", "w:Zardini Lacedelli", "Zardini Lacedelli", gender="F", index=self.idx)
        link = self.con.execute("SELECT method FROM link WHERE source='gsoc' AND key='w:Zardini Lacedelli'").fetchone()[0]
        self.assertEqual(link, "auto")
        p2, conf = identity.resolve(self.con, "gsoc", "w:Zardini Lacedelli", "qualquer coisa", index=self.idx)
        self.assertEqual(p1, p2)

    def test_duplicates_merge_only_with_birthdate(self):
        r = identity.find_wcf_duplicates(self.con)
        self.assertEqual(r["merged"], 1)  # 400 e 401: mesmo nome e nascimento
        a, b, c = self.pid(400), self.pid(401), self.pid(402)
        self.assertEqual(identity.live_id(self.con, b), a)
        self.assertEqual(identity.live_id(self.con, c), c)  # nascimento diferente: outra pessoa

    def test_same_event_never_merges(self):
        add_event(self.con, 6, 2012, "Men", {"A": ("SWE", [(500, "Erik Larsson", "fourth")]),
                                             "B": ("SWE", [(501, "Erik Larsson", "fourth")])})
        identity.find_wcf_duplicates(self.con)
        self.assertNotEqual(identity.live_id(self.con, self.pid(501)), self.pid(500))
        self.assertFalse(self.con.execute("SELECT COUNT(*) FROM review WHERE subject LIKE '%Erik%'").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
