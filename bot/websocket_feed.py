from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Callable

import websocket


@dataclass(slots=True)
class LiveTicker:
    symbol: str
    last: float
    bid: float
    ask: float
    mark_price: float
    timestamp_ms: int

    @property
    def executable_long_exit(self) -> float:
        return self.bid if self.bid > 0 else self.last

    @property
    def executable_short_exit(self) -> float:
        return self.ask if self.ask > 0 else self.last


TickCallback = Callable[[LiveTicker], None]
StatusCallback = Callable[[str, dict], None]


class BitgetTickerStream:
    """Public Bitget ticker WebSocket with reconnect and text ping/pong heartbeat.

    The connection never authenticates and never sends private/order messages. It can
    dynamically subscribe to one active-position symbol, which keeps resource use low.
    """

    def __init__(
        self,
        url: str,
        product_type: str,
        on_tick: TickCallback,
        on_status: StatusCallback | None = None,
        heartbeat_seconds: int = 25,
    ) -> None:
        self.url = url
        self.product_type = product_type
        self.on_tick = on_tick
        self.on_status = on_status or (lambda _event, _payload: None)
        self.heartbeat_seconds = max(10, heartbeat_seconds)

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._ws: websocket.WebSocketApp | None = None
        self._connected = False
        self._desired_symbol: str | None = None
        self._subscribed_symbol: str | None = None
        self._last_pong_monotonic = 0.0
        self._connected_since_monotonic = 0.0

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    @property
    def desired_symbol(self) -> str | None:
        with self._lock:
            return self._desired_symbol

    def is_live_for(self, symbol: str) -> bool:
        with self._lock:
            return self._connected and self._subscribed_symbol == symbol.upper()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, name="bitget-public-ws", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            ws = self._ws
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        with self._lock:
            self._connected = False
            self._subscribed_symbol = None
        self.on_status("disconnected", {"reason": "stopped"})

    def set_symbol(self, symbol: str | None) -> None:
        normalized = symbol.upper() if symbol else None
        with self._lock:
            old_desired = self._desired_symbol
            self._desired_symbol = normalized
            connected = self._connected
            ws = self._ws
            old_subscribed = self._subscribed_symbol

        if not connected or not ws:
            return
        try:
            if old_subscribed and old_subscribed != normalized:
                self._send_subscription(ws, "unsubscribe", old_subscribed)
                with self._lock:
                    self._subscribed_symbol = None
            if normalized and normalized != old_subscribed:
                self._send_subscription(ws, "subscribe", normalized)
            elif normalized is None and old_desired:
                with self._lock:
                    self._subscribed_symbol = None
        except Exception as exc:
            self.on_status("error", {"text": f"Gagal mengganti subscription WebSocket: {exc}"})

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                app = websocket.WebSocketApp(
                    self.url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                with self._lock:
                    self._ws = app
                app.run_forever(skip_utf8_validation=True)
            except Exception as exc:
                self.on_status("error", {"text": f"WebSocket gagal: {exc}"})
            finally:
                with self._lock:
                    connected_for = (time.monotonic() - self._connected_since_monotonic
                                     if self._connected_since_monotonic else 0.0)
                    self._connected = False
                    self._subscribed_symbol = None
                    self._ws = None
                if connected_for >= 10.0:
                    backoff = 1.0
            if self._stop_event.wait(backoff):
                break
            self.on_status("reconnecting", {"delay_seconds": backoff})
            backoff = min(30.0, backoff * 2.0)

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        with self._lock:
            self._connected = True
            self._last_pong_monotonic = time.monotonic()
            self._connected_since_monotonic = self._last_pong_monotonic
            desired = self._desired_symbol
        self.on_status("connected", {"symbol": desired})
        if desired:
            self._send_subscription(ws, "subscribe", desired)
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(ws,),
            name="bitget-ws-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _on_close(self, _ws: websocket.WebSocketApp, status_code, message) -> None:
        with self._lock:
            self._connected = False
            self._subscribed_symbol = None
        if not self._stop_event.is_set():
            self.on_status(
                "disconnected",
                {"reason": f"code={status_code}, message={message or '-'}"},
            )

    def _on_error(self, _ws: websocket.WebSocketApp, error) -> None:
        if not self._stop_event.is_set():
            self.on_status("error", {"text": str(error)})

    def _heartbeat_loop(self, ws: websocket.WebSocketApp) -> None:
        while not self._stop_event.wait(self.heartbeat_seconds):
            with self._lock:
                if ws is not self._ws or not self._connected:
                    return
                last_pong = self._last_pong_monotonic
            if last_pong and time.monotonic() - last_pong > self.heartbeat_seconds * 3:
                self.on_status("error", {"text": "WebSocket pong timeout; reconnect."})
                try:
                    ws.close()
                except Exception:
                    pass
                return
            try:
                ws.send("ping")
            except Exception:
                try:
                    ws.close()
                except Exception:
                    pass
                return

    def _on_message(self, ws: websocket.WebSocketApp, raw_message: str) -> None:
        if raw_message == "pong":
            with self._lock:
                self._last_pong_monotonic = time.monotonic()
            return
        try:
            payload = json.loads(raw_message)
        except (TypeError, json.JSONDecodeError):
            return

        event = payload.get("event")
        arg = payload.get("arg") or {}
        if event == "subscribe":
            symbol = str(arg.get("instId", "")).upper() or None
            with self._lock:
                desired = self._desired_symbol
                self._subscribed_symbol = symbol
            if symbol and symbol != desired:
                try:
                    self._send_subscription(ws, "unsubscribe", symbol)
                except Exception:
                    pass
                return
            self.on_status("subscribed", {"symbol": symbol})
            return
        if event == "unsubscribe":
            symbol = str(arg.get("instId", "")).upper() or None
            with self._lock:
                if self._subscribed_symbol == symbol:
                    self._subscribed_symbol = None
            self.on_status("unsubscribed", {"symbol": symbol})
            return
        if event == "error" or payload.get("code"):
            self.on_status(
                "error",
                {"text": f"Bitget WS {payload.get('code', '')}: {payload.get('msg', 'unknown error')}"},
            )
            return

        if arg.get("channel") != "ticker":
            return
        rows = payload.get("data") or []
        for row in rows:
            try:
                ticker = LiveTicker(
                    symbol=str(row.get("symbol") or row.get("instId") or arg.get("instId") or "").upper(),
                    last=float(row.get("lastPr") or 0.0),
                    bid=float(row.get("bidPr") or 0.0),
                    ask=float(row.get("askPr") or 0.0),
                    mark_price=float(row.get("markPrice") or row.get("lastPr") or 0.0),
                    timestamp_ms=int(row.get("ts") or payload.get("ts") or int(time.time() * 1000)),
                )
            except (TypeError, ValueError):
                continue
            if ticker.symbol and ticker.last > 0:
                self.on_tick(ticker)

    def _send_subscription(self, ws: websocket.WebSocketApp, operation: str, symbol: str) -> None:
        message = {
            "op": operation,
            "args": [
                {
                    "instType": self.product_type,
                    "channel": "ticker",
                    "instId": symbol,
                }
            ],
        }
        ws.send(json.dumps(message, separators=(",", ":")))
