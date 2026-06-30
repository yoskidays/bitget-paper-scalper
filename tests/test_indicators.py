import unittest

from bot.indicators import atr, ema, rsi
from bot.models import Candle


class IndicatorTests(unittest.TestCase):
    def test_ema_tracks_uptrend(self):
        values = [float(x) for x in range(1, 31)]
        result = ema(values, 10)
        self.assertEqual(len(result), len(values))
        self.assertGreater(result[-1], result[-5])
        self.assertLess(result[-1], values[-1])

    def test_rsi_uptrend_is_high(self):
        values = [100 + x * 0.5 for x in range(40)]
        result = rsi(values, 14)
        self.assertIsNotNone(result[-1])
        self.assertGreater(result[-1], 70)

    def test_atr_positive(self):
        candles = [
            Candle(i * 300000, 100+i, 102+i, 99+i, 101+i, 10, 1000)
            for i in range(30)
        ]
        result = atr(candles, 14)
        self.assertGreater(result[-1], 0)


if __name__ == "__main__":
    unittest.main()
