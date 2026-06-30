import unittest

from bot.engine import PaperTradingEngine


class EngineMathTests(unittest.TestCase):
    def test_long_pnl(self):
        self.assertAlmostEqual(PaperTradingEngine._gross_pnl("LONG", 100, 101, 2), 2)

    def test_short_pnl(self):
        self.assertAlmostEqual(PaperTradingEngine._gross_pnl("SHORT", 100, 98, 3), 6)


if __name__ == "__main__":
    unittest.main()
