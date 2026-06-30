from __future__ import annotations

import threading
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import Candle, ContractInfo, Ticker


class BitgetPublicClient:
    """Read-only client for Bitget public futures market endpoints."""

    def __init__(self, base_url: str, product_type: str, timeout: int = 12) -> None:
        self.base_url = base_url.rstrip("/")
        self.product_type = product_type
        self.timeout = timeout
        self._local = threading.local()
        self._last_request = 0.0
        self._rate_lock = threading.Lock()

    def _session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            session = requests.Session()
            retry = Retry(
                total=3,
                connect=3,
                read=3,
                backoff_factor=0.5,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET"}),
            )
            session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10))
            session.headers.update({"User-Agent": "BitgetPaperScalper/1.0"})
            self._local.session = session
        return self._local.session

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        with self._rate_lock:
            elapsed = time.monotonic() - self._last_request
            if elapsed < 0.06:
                time.sleep(0.06 - elapsed)
            self._last_request = time.monotonic()
        response = self._session().get(
            f"{self.base_url}{path}", params=params, timeout=self.timeout
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != "00000":
            raise RuntimeError(f"Bitget API error {payload.get('code')}: {payload.get('msg')}")
        return payload.get("data")

    @staticmethod
    def _float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_tickers(self) -> list[Ticker]:
        rows = self._get("/api/v2/mix/market/tickers", {"productType": self.product_type})
        result: list[Ticker] = []
        for row in rows or []:
            result.append(Ticker(
                symbol=str(row.get("symbol", "")).upper(),
                last=self._float(row.get("lastPr")),
                bid=self._float(row.get("bidPr")),
                ask=self._float(row.get("askPr")),
                usdt_volume=self._float(row.get("usdtVolume") or row.get("quoteVolume")),
                change_24h=self._float(row.get("change24h")),
                funding_rate=self._float(row.get("fundingRate")),
                open_interest=self._float(row.get("holdingAmount")),
                mark_price=self._float(row.get("markPrice") or row.get("lastPr")),
            ))
        return result

    def get_contracts(self) -> dict[str, ContractInfo]:
        rows = self._get("/api/v2/mix/market/contracts", {"productType": self.product_type})
        result: dict[str, ContractInfo] = {}
        for row in rows or []:
            symbol = str(row.get("symbol", "")).upper()
            if not symbol:
                continue
            result[symbol] = ContractInfo(
                symbol=symbol,
                taker_fee_rate=self._float(row.get("takerFeeRate"), 0.0006),
                min_trade_usdt=self._float(row.get("minTradeUSDT"), 5.0),
                min_trade_num=self._float(row.get("minTradeNum"), 0.0),
                size_multiplier=self._float(row.get("sizeMultiplier"), 0.0),
                volume_place=int(self._float(row.get("volumePlace"), 6)),
                price_place=int(self._float(row.get("pricePlace"), 8)),
                max_leverage=self._float(row.get("maxLever"), 1.0),
                status=str(row.get("symbolStatus", "normal")),
            )
        return result

    def get_candles(self, symbol: str, granularity: str, limit: int = 250) -> list[Candle]:
        rows = self._get("/api/v2/mix/market/candles", {
            "symbol": symbol,
            "granularity": granularity,
            "limit": str(min(1000, max(20, limit))),
            "productType": self.product_type,
        })
        candles: list[Candle] = []
        for row in rows or []:
            if len(row) < 7:
                continue
            candles.append(Candle(
                timestamp=int(row[0]),
                open=self._float(row[1]),
                high=self._float(row[2]),
                low=self._float(row[3]),
                close=self._float(row[4]),
                base_volume=self._float(row[5]),
                quote_volume=self._float(row[6]),
            ))
        candles.sort(key=lambda item: item.timestamp)
        return candles
