import json
import unittest

from bot.websocket_feed import BitgetTickerStream


class WebSocketFeedTests(unittest.TestCase):
    def test_ticker_message_parsing(self):
        ticks = []
        statuses = []
        stream = BitgetTickerStream(
            "wss://example.test",
            "USDT-FUTURES",
            ticks.append,
            lambda event, payload: statuses.append((event, payload)),
        )
        payload = {
            "arg": {"instType": "USDT-FUTURES", "channel": "ticker", "instId": "BTCUSDT"},
            "data": [{
                "symbol": "BTCUSDT",
                "lastPr": "60000",
                "bidPr": "59999.5",
                "askPr": "60000.5",
                "markPrice": "60000.1",
                "ts": "1710000000000",
            }],
        }
        stream._on_message(None, json.dumps(payload))  # type: ignore[arg-type]
        self.assertEqual(len(ticks), 1)
        self.assertEqual(ticks[0].symbol, "BTCUSDT")
        self.assertEqual(ticks[0].executable_long_exit, 59999.5)
        self.assertEqual(ticks[0].executable_short_exit, 60000.5)

    def test_subscription_confirmation(self):
        statuses = []
        stream = BitgetTickerStream(
            "wss://example.test",
            "USDT-FUTURES",
            lambda _tick: None,
            lambda event, payload: statuses.append((event, payload)),
        )
        stream.set_symbol("SOLUSDT")
        stream._on_message(None, json.dumps({  # type: ignore[arg-type]
            "event": "subscribe",
            "arg": {"instType": "USDT-FUTURES", "channel": "ticker", "instId": "SOLUSDT"},
        }))
        self.assertEqual(statuses[-1][0], "subscribed")
        self.assertEqual(statuses[-1][1]["symbol"], "SOLUSDT")


if __name__ == "__main__":
    unittest.main()
