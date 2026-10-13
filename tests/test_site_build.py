import unittest

from hc.site_build import SHEET_BODY, SHEET_CLOSED, _absolute, _ld_json, _nation_pt, _page, _pre, _types_pt, slugify


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

    def test_types_pt(self):
        src = 'const PT_TYPES = {\n  1: "Mundial", 2: "Europeu",\n  40: "Qualificatório do Mundial",\n};'
        self.assertEqual(_types_pt(src), {1: "Mundial", 2: "Europeu", 40: "Qualificatório do Mundial"})

    def test_page_with_pre(self):
        # a ficha vem aberta e escrita; sem ficha, a página fica igual à inicial
        shell = f'{SHEET_CLOSED}<div class="sheet-panel">{SHEET_BODY}</div></div>'
        page = _page(shell, title="T", desc="D", path="/atleta/1-x/", css="a.css", pre=_pre("<h1>X</h1>"), ld=[{"name": "</script>"}])
        self.assertIn('<div class="sheet" id="sheet"><div class="sheet-panel"><div id="sheet-body"><article class="pre"><h1>X</h1></article></div>', page)
        self.assertIn('<body style="overflow:hidden">', page)
        self.assertIn('{"name":"<\\/script>"}', page)
        self.assertNotIn("</script>\"", page)
        plain = _page(shell, title="T", desc="D", path="/", css="a.css")
        self.assertIn(SHEET_CLOSED, plain)
        self.assertIn("<body>", plain)

    def test_ld_json(self):
        self.assertEqual(_ld_json({"a": "Wranå</x>"}), '{"a":"Wranå<\\/x>"}')


if __name__ == "__main__":
    unittest.main()
