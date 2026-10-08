import unittest

from hc import names


class TestNames(unittest.TestCase):
    def test_fold_and_key(self):
        self.assertEqual(names.fold("Mads Nørgaard"), "mads norgaard")
        self.assertEqual(names.fold("Wranå"), "wrana")
        self.assertEqual(names.key("PFISTER Marc"), names.key("Marc Pfister"))

    def test_display_fixes_caps(self):
        self.assertEqual(names.display("Florian KRAMLINGER"), "Florian Kramlinger")
        self.assertEqual(names.display("Anna HASSELBORG-SMITH"), "Anna Hasselborg-Smith")
        self.assertEqual(names.display("Stefania Constantini"), "Stefania Constantini")

    def test_same_tokens(self):
        self.assertEqual(names.similarity("Kramlinger Florian", "Florian KRAMLINGER"), 1.0)
        self.assertEqual(names.similarity("Mads Norgaard", "Mads Nørgaard"), 1.0)

    def test_initials_disambiguate(self):
        self.assertGreaterEqual(names.similarity("Y. Schwaller", "Yannick Schwaller"), 0.85)
        self.assertLess(names.similarity("X. Schwaller", "Yannick Schwaller"), 0.5)

    def test_compound_surname(self):
        self.assertGreaterEqual(names.similarity("Zardini Lacedelli", "Giulia Zardini Lacedelli"), 0.9)

    def test_surname_only_is_weak(self):
        s = names.similarity("Schwaller", "Yannick Schwaller")
        self.assertTrue(0.6 <= s < 0.9, s)

    def test_typo(self):
        self.assertGreaterEqual(names.similarity("Stefania Costantini", "Stefania Constantini"), 0.7)

    def test_different_people(self):
        self.assertLess(names.similarity("Anna Hasselborg", "Silvana Tirinzoni"), 0.5)


if __name__ == "__main__":
    unittest.main()
