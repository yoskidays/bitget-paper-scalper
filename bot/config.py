from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

APP_NAME = "BitgetPaperScalper"

DEFAULT_CONFIG: dict[str, Any] = {
    "config_version": 3,
    "starting_equity": 50.0,
    "scan_interval_minutes": 1,
    "risk_per_trade_pct": 1.0,
    "fallback_risk_pct": 0.25,
    "max_leverage": 5.0,
    "fallback_leverage": 2.0,
    "max_pairs_to_analyze": 15,
    "min_usdt_volume_24h": 10_000_000.0,
    "max_spread_bps": 8.0,
    "max_abs_change_24h_pct": 25.0,
    "min_signal_score": 68.0,
    "fallback_min_score": 52.0,
    "fallback_after_empty_scans": 6,
    "fallback_enabled": True,
    "tp1_r": 0.8,
    "tp2_r": 1.4,
    "tp1_fraction": 0.5,
    "atr_stop_multiplier": 1.2,
    "min_stop_pct": 0.0035,
    "max_stop_pct": 0.015,
    "max_hold_minutes": 60,
    "daily_loss_limit_pct": 3.0,
    "default_taker_fee_rate": 0.0006,
    "slippage_bps": 1.5,
    "request_timeout_seconds": 12,
    "api_base_url": "https://api.bitget.com",
    "websocket_enabled": True,
    "websocket_url": "wss://ws.bitget.com/v2/ws/public",
    "websocket_heartbeat_seconds": 25,
    "live_ui_throttle_seconds": 1.0,
    "product_type": "USDT-FUTURES",
    "dry_run_only": True,
    "auto_start_bot": True,
    "crypto_symbols": [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT",
        "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT",
        "TRXUSDT", "SUIUSDT", "TONUSDT", "APTUSDT", "ARBUSDT", "OPUSDT",
        "NEARUSDT", "ATOMUSDT", "FILUSDT", "ICPUSDT", "INJUSDT", "SEIUSDT",
        "TIAUSDT", "PEPEUSDT", "WIFUSDT", "BONKUSDT", "SHIBUSDT", "UNIUSDT",
        "AAVEUSDT", "ETCUSDT", "XLMUSDT", "ALGOUSDT", "VETUSDT", "RUNEUSDT",
        "FETUSDT", "TAOUSDT", "ENAUSDT", "JUPUSDT", "ONDOUSDT", "HBARUSDT",
        "KASUSDT", "POLUSDT", "CRVUSDT", "DYDXUSDT", "PENDLEUSDT", "RENDERUSDT",
        "GALAUSDT", "SANDUSDT", "MANAUSDT", "MKRUSDT", "LDOUSDT", "STXUSDT"
    ]
}


def data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return data_dir() / "config.json"


def _deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    cfg = _deep_merge(DEFAULT_CONFIG, config)
    cfg["config_version"] = 3
    cfg["starting_equity"] = max(1.0, float(cfg["starting_equity"]))
    cfg["scan_interval_minutes"] = max(1, int(cfg["scan_interval_minutes"]))
    cfg["websocket_enabled"] = bool(cfg.get("websocket_enabled", True))
    cfg["websocket_heartbeat_seconds"] = min(60, max(10, int(cfg.get("websocket_heartbeat_seconds", 25))))
    cfg["live_ui_throttle_seconds"] = min(5.0, max(0.25, float(cfg.get("live_ui_throttle_seconds", 1.0))))
    cfg["risk_per_trade_pct"] = min(5.0, max(0.1, float(cfg["risk_per_trade_pct"])))
    cfg["fallback_risk_pct"] = min(cfg["risk_per_trade_pct"], max(0.05, float(cfg["fallback_risk_pct"])))
    cfg["max_leverage"] = min(20.0, max(1.0, float(cfg["max_leverage"])))
    cfg["fallback_leverage"] = min(cfg["max_leverage"], max(1.0, float(cfg["fallback_leverage"])))
    cfg["max_pairs_to_analyze"] = min(50, max(3, int(cfg["max_pairs_to_analyze"])))
    cfg["min_signal_score"] = min(95.0, max(40.0, float(cfg["min_signal_score"])))
    cfg["fallback_min_score"] = min(cfg["min_signal_score"], max(30.0, float(cfg["fallback_min_score"])))
    cfg["tp1_r"] = max(0.4, float(cfg["tp1_r"]))
    cfg["tp2_r"] = max(cfg["tp1_r"] + 0.1, float(cfg["tp2_r"]))
    cfg["tp1_fraction"] = min(0.9, max(0.1, float(cfg["tp1_fraction"])))
    cfg["slippage_bps"] = max(0.0, float(cfg["slippage_bps"]))
    cfg["dry_run_only"] = True
    return cfg


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        save_config(DEFAULT_CONFIG)
        return deepcopy(DEFAULT_CONFIG)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        loaded = {}

    version = int(loaded.get("config_version", 1))

    # v1.0.1 migration: the original default moved from 10 to 5 minutes.
    if version < 2:
        if int(loaded.get("scan_interval_minutes", 10)) == 10:
            loaded["scan_interval_minutes"] = 5
        version = 2

    # v1.1.0 migration: REST screening moves to one minute and a public
    # WebSocket monitors an active virtual position between scans. Preserve
    # non-default custom intervals, but migrate the old 5/10-minute defaults.
    if version < 3:
        if int(loaded.get("scan_interval_minutes", 5)) in {5, 10}:
            loaded["scan_interval_minutes"] = 1
        loaded["websocket_enabled"] = bool(loaded.get("websocket_enabled", True))
        loaded["websocket_url"] = loaded.get("websocket_url", "wss://ws.bitget.com/v2/ws/public")
        loaded["websocket_heartbeat_seconds"] = int(loaded.get("websocket_heartbeat_seconds", 25))
        loaded["live_ui_throttle_seconds"] = float(loaded.get("live_ui_throttle_seconds", 1.0))
        loaded["config_version"] = 3

    cfg = validate_config(loaded)
    save_config(cfg)
    return cfg


def save_config(config: dict[str, Any]) -> None:
    cfg = validate_config(config)
    config_path().write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
