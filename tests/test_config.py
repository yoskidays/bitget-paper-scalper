import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.config import DEFAULT_CONFIG, load_config


class ConfigTests(unittest.TestCase):
    def test_default_scan_interval_is_one_minute(self):
        self.assertEqual(DEFAULT_CONFIG["scan_interval_minutes"], 1)
        self.assertTrue(DEFAULT_CONFIG["websocket_enabled"])

    def test_legacy_ten_minute_config_is_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {"XDG_DATA_HOME": tmp, "LOCALAPPDATA": tmp},
                clear=False,
            ):
                app_dir = Path(tmp) / "BitgetPaperScalper"
                app_dir.mkdir(parents=True, exist_ok=True)
                config_file = app_dir / "config.json"
                config_file.write_text(
                    json.dumps({
                        "starting_equity": 50.0,
                        "scan_interval_minutes": 10,
                        "risk_per_trade_pct": 1.25,
                    }),
                    encoding="utf-8",
                )

                cfg = load_config()

                self.assertEqual(cfg["scan_interval_minutes"], 1)
                self.assertEqual(cfg["config_version"], 3)
                self.assertEqual(cfg["risk_per_trade_pct"], 1.25)
                self.assertTrue(cfg["websocket_enabled"])

    def test_v2_five_minute_config_is_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {"XDG_DATA_HOME": tmp, "LOCALAPPDATA": tmp},
                clear=False,
            ):
                app_dir = Path(tmp) / "BitgetPaperScalper"
                app_dir.mkdir(parents=True, exist_ok=True)
                (app_dir / "config.json").write_text(
                    json.dumps({
                        "config_version": 2,
                        "scan_interval_minutes": 5,
                        "risk_per_trade_pct": 0.75,
                    }),
                    encoding="utf-8",
                )

                cfg = load_config()

                self.assertEqual(cfg["scan_interval_minutes"], 1)
                self.assertEqual(cfg["risk_per_trade_pct"], 0.75)
                self.assertEqual(cfg["config_version"], 3)


if __name__ == "__main__":
    unittest.main()
