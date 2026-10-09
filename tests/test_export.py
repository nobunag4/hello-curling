import unittest

from hc.export import category


class CategoryTest(unittest.TestCase):
    # precisa bater com gameCats() em site/index.html
    def test_category(self):
        self.assertEqual(category("Men", "European Curling Championships"), "m")
        self.assertEqual(category("Women", "World Junior Curling Championships"), "jw")
        self.assertEqual(category("Mixed Doubles", "World Mixed Doubles Qualification Event"), "md")
        self.assertEqual(category("Mixed", "World Wheelchair Curling Championships"), "wcx")
        self.assertEqual(category("Mixed Doubles", "World Wheelchair Mixed Doubles Curling Championship"), "wcmd")
        self.assertEqual(category("Men", "World Senior Curling Championships"), "sm")
        self.assertIsNone(category(None, "Olympic Games"))


if __name__ == "__main__":
    unittest.main()
