import unittest

from bot.api import BitgetPublicClient


class FakeClient(BitgetPublicClient):
    def _get(self, path, params):
        if path.endswith('/tickers'):
            return [{
                'symbol': 'BTCUSDT', 'lastPr': '60000', 'bidPr': '59999', 'askPr': '60001',
                'usdtVolume': '1000000000', 'change24h': '0.02', 'fundingRate': '0.0001',
                'holdingAmount': '12345', 'markPrice': '60000.5'
            }]
        if path.endswith('/contracts'):
            return [{
                'symbol': 'BTCUSDT', 'takerFeeRate': '0.0006', 'minTradeUSDT': '5',
                'minTradeNum': '0.001', 'sizeMultiplier': '0.001', 'volumePlace': '3',
                'pricePlace': '1', 'maxLever': '125', 'symbolStatus': 'normal'
            }]
        if path.endswith('/candles'):
            return [['1000', '10', '11', '9', '10.5', '100', '1050']]
        return []


class ApiParsingTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient('https://example.test', 'USDT-FUTURES')

    def test_ticker_parsing(self):
        ticker = self.client.get_tickers()[0]
        self.assertEqual(ticker.symbol, 'BTCUSDT')
        self.assertAlmostEqual(ticker.spread_bps, 0.3333333333, places=5)
        self.assertEqual(ticker.usdt_volume, 1_000_000_000)

    def test_contract_parsing(self):
        contract = self.client.get_contracts()['BTCUSDT']
        self.assertEqual(contract.volume_place, 3)
        self.assertEqual(contract.min_trade_usdt, 5)

    def test_candle_parsing(self):
        candle = self.client.get_candles('BTCUSDT', '5m')[0]
        self.assertEqual(candle.close, 10.5)
        self.assertEqual(candle.quote_volume, 1050)


if __name__ == '__main__':
    unittest.main()
