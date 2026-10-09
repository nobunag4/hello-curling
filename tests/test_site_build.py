import unittest

from hc.site_build import _absolute, _nation_pt, slugify


class SiteBuildTest(unittest.TestCase):
    def test_slugify(self):
        # precisa bater com o slugify da página (site/index.html)
        self.assertEqual(slugify("Stefania Constantini"), "stefania-constantini")
        self.assertEqual(slugify("Rasmus Wranå"), "rasmus-wrana")
        self.assertEqual(slugify("Łukasz Ølsen-Jæger"), "lukasz-olsen-jaeger")
        self.assertEqual(slugify("  O'Neil, Jr. "), "o-neil-jr")

    def test_absolute(self):
        s = 'fetch("data/index.json"); `data/nation/${c}.json`; src="img/logo-96.png" href="#top" "metadata/x"'
        self.assertEqual(_absolute(s), 'fetch("/data/index.json"); `/data/nation/${c}.json`; src="/img/logo-96.png" href="#top" "metadata/x"')

    def test_nation_pt(self):
        src = 'const NATION_PT = {\n  BRA:"Brasil", ITA:"Itália",\n};'
        self.assertEqual(_nation_pt(src), {"BRA": "Brasil", "ITA": "Itália"})


if __name__ == "__main__":
    unittest.main()
