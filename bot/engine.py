from __future__ import annotations

import math
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .api import BitgetPublicClient
from .config import load_config
from .models import AccountState, ContractInfo, Position, Signal, Ticker, utc_now_iso
from .reporting import build_html_report, calculate_metrics
from .storage import Storage
from .strategy import AnalysisInput, PullbackMomentumStrategy
from .websocket_feed import BitgetTickerStream, LiveTicker

EventCallback = Callable[[str, dict], None]


class PaperTradingEngine:
    def __init__(self, callback: EventCallback | None = None) -> None:
        self.config = load_config()
        self.storage = Storage()
        self.state = self.storage.load_state(self.config["starting_equity"])
        self.client = BitgetPublicClient(
            self.config["api_base_url"],
            self.config["product_type"],
            self.config["request_timeout_seconds"],
        )
        self.strategy = PullbackMomentumStrategy(self.config)
        self.callback = callback or (lambda _event, _payload: None)
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.contracts: dict[str, ContractInfo] = {}
        self.latest_tickers: dict[str, Ticker] = {}
        self.last_candidates: list[Signal] = []
        self._cycle_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self.live_ticker: LiveTicker | None = None
        self.ws_connected = False
        self.ws_symbol: str | None = None
        self._last_live_emit = 0.0
        self.stream = BitgetTickerStream(
            self.config["websocket_url"],
            self.config["product_type"],
            self._on_live_tick,
            self._on_ws_status,
            self.config["websocket_heartbeat_seconds"],
        ) if self.config.get("websocket_enabled", True) else None

    def emit(self, event: str, **payload) -> None:
        try:
            self.callback(event, payload)
        except Exception:
            self.storage.logger.exception("UI callback gagal")

    @property
    def is_running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self) -> None:
        if self.is_running:
            return
        self.stop_event.clear()
        if self.stream:
            self.stream.start()
            if self.state.open_position:
                self.stream.set_symbol(self.state.open_position.symbol)
        self.thread = threading.Thread(target=self._loop, name="paper-scalper", daemon=True)
        self.thread.start()
        self.emit("status", text="BOT BERJALAN • SCAN 1M")

    def stop(self) -> None:
        self.stop_event.set()
        if self.stream:
            self.stream.stop()
        self.emit("status", text="BOT DIHENTIKAN")

    def scan_now_async(self) -> None:
        if self._cycle_lock.locked():
            self.emit("log", text="Scan masih berjalan.")
            return
        threading.Thread(target=self.run_cycle, name="manual-scan", daemon=True).start()

    def _loop(self) -> None:
        interval = self.config["scan_interval_minutes"] * 60.0
        next_run = time.monotonic()
        while not self.stop_event.is_set():
            self.run_cycle()
            next_run += interval
            delay = next_run - time.monotonic()
            if delay < 0:
                # If a scan took longer than its cadence, resume immediately and
                # reset the clock rather than accumulating increasing drift.
                next_run = time.monotonic()
                delay = 0.0
            self.stop_event.wait(delay)

    def _refresh_day_guard(self) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        if self.state.day_anchor != today:
            self.state.day_anchor = today
            self.state.day_start_balance = self.state.balance
            self.state.stopped_for_daily_loss = False

    def _update_drawdown(self, marked_equity: float | None = None) -> None:
        equity = marked_equity if marked_equity is not None else self.state.balance
        self.state.peak_equity = max(self.state.peak_equity, equity)
        if self.state.peak_equity > 0:
            drawdown = max(0.0, (self.state.peak_equity - equity) / self.state.peak_equity * 100.0)
            self.state.max_drawdown_pct = max(self.state.max_drawdown_pct, drawdown)

    def _check_daily_loss(self) -> None:
        if self.state.day_start_balance <= 0:
            return
        loss_pct = (self.state.day_start_balance - self.state.balance) / self.state.day_start_balance * 100.0
        self.state.stopped_for_daily_loss = loss_pct >= self.config["daily_loss_limit_pct"]

    def run_cycle(self) -> None:
        if not self._cycle_lock.acquire(blocking=False):
            return
        try:
            self._refresh_day_guard()
            self.emit("log", text="Mengambil live market data Bitget...")
            tickers = self.client.get_tickers()
            self.latest_tickers = {item.symbol: item for item in tickers}
            if not self.contracts:
                self.contracts = self.client.get_contracts()

            if self.state.open_position:
                self._manage_position()

            self._check_daily_loss()
            if not self.state.open_position and not self.state.stopped_for_daily_loss:
                self._scan_and_maybe_open(tickers)
            elif self.state.stopped_for_daily_loss:
                self.emit("log", text="Batas loss harian tercapai; entry baru dihentikan sampai hari UTC berikutnya.")

            self.state.last_scan_at = utc_now_iso()
            self.storage.save_state(self.state)
            self.emit("state", state=self.snapshot())
        except Exception as exc:
            self.storage.logger.exception("Siklus bot gagal")
            self.emit("error", text=f"Scan gagal: {exc}")
        finally:
            self._cycle_lock.release()

    def _eligible_tickers(self, tickers: list[Ticker]) -> list[Ticker]:
        allowed = set(self.config.get("crypto_symbols") or [])
        result = []
        for ticker in tickers:
            contract = self.contracts.get(ticker.symbol)
            if allowed and ticker.symbol not in allowed:
                continue
            if contract and contract.status.lower() != "normal":
                continue
            if ticker.last <= 0 or ticker.bid <= 0 or ticker.ask <= 0:
                continue
            if ticker.usdt_volume < self.config["min_usdt_volume_24h"]:
                continue
            if ticker.spread_bps > self.config["max_spread_bps"]:
                continue
            if abs(ticker.change_24h * 100.0) > self.config["max_abs_change_24h_pct"]:
                continue
            result.append(ticker)
        result.sort(key=lambda x: x.usdt_volume, reverse=True)
        return result[: self.config["max_pairs_to_analyze"]]

    def _scan_and_maybe_open(self, tickers: list[Ticker]) -> None:
        eligible = self._eligible_tickers(tickers)
        if not eligible:
            self.emit("log", text="Tidak ada pair yang lolos filter likuiditas/spread.")
            self.state.empty_scan_count += 1
            return

        signals: list[Signal] = []
        for index, ticker in enumerate(eligible, start=1):
            if self.stop_event.is_set():
                return
            self.emit("progress", current=index, total=len(eligible), symbol=ticker.symbol)
            try:
                data = AnalysisInput(
                    ticker=ticker,
                    candles_1h=self.client.get_candles(ticker.symbol, "1H", 240),
                    candles_15m=self.client.get_candles(ticker.symbol, "15m", 220),
                    candles_5m=self.client.get_candles(ticker.symbol, "5m", 220),
                    candles_1m=self.client.get_candles(ticker.symbol, "1m", 180),
                    previous_open_interest=self.state.oi_snapshots.get(ticker.symbol),
                )
                signal = self.strategy.analyze(data)
                self.state.oi_snapshots[ticker.symbol] = ticker.open_interest
                if signal:
                    signals.append(signal)
            except Exception as exc:
                self.storage.logger.warning("Analisis %s gagal: %s", ticker.symbol, exc)

        signals.sort(key=lambda item: (item.score, item.volume_24h), reverse=True)
        self.last_candidates = signals[:10]
        self.emit("candidates", items=[self._signal_dict(item) for item in self.last_candidates])

        qualifying = [item for item in signals if item.score >= self.config["min_signal_score"]]
        chosen: Signal | None = qualifying[0] if qualifying else None
        if chosen:
            self.state.empty_scan_count = 0
            self._open_position(chosen, fallback=False)
            return

        self.state.empty_scan_count += 1
        self.emit("log", text=f"Belum ada sinyal normal ≥ {self.config['min_signal_score']:.0f}. Empty scan: {self.state.empty_scan_count}.")
        fallback_due = (
            self.config["fallback_enabled"]
            and self.state.empty_scan_count >= self.config["fallback_after_empty_scans"]
            and signals
            and signals[0].score >= self.config["fallback_min_score"]
        )
        if fallback_due:
            chosen = signals[0]
            chosen.setup_type = "fallback"
            self.state.empty_scan_count = 0
            self._open_position(chosen, fallback=True)

    def _round_qty(self, qty: float, contract: ContractInfo | None) -> float:
        if not contract:
            return math.floor(qty * 1_000_000) / 1_000_000
        step = contract.size_multiplier if contract.size_multiplier > 0 else 10 ** (-contract.volume_place)
        rounded = math.floor(qty / step) * step
        return round(rounded, contract.volume_place)

    def _open_position(self, signal: Signal, fallback: bool) -> None:
        ticker = self.latest_tickers[signal.symbol]
        contract = self.contracts.get(signal.symbol)
        fee_rate = contract.taker_fee_rate if contract else self.config["default_taker_fee_rate"]
        risk_pct = self.config["fallback_risk_pct"] if fallback else self.config["risk_per_trade_pct"]
        leverage = self.config["fallback_leverage"] if fallback else self.config["max_leverage"]
        if contract:
            leverage = min(leverage, contract.max_leverage)

        reference = ticker.mid
        slip = self.config["slippage_bps"] / 10_000.0
        if signal.direction == "LONG":
            entry = ticker.ask * (1.0 + slip)
            stop = entry * (1.0 - signal.stop_distance_pct)
            risk_per_unit = entry - stop
            tp1 = entry + risk_per_unit * self.config["tp1_r"]
            tp2 = entry + risk_per_unit * self.config["tp2_r"]
        else:
            entry = ticker.bid * (1.0 - slip)
            stop = entry * (1.0 + signal.stop_distance_pct)
            risk_per_unit = stop - entry
            tp1 = entry - risk_per_unit * self.config["tp1_r"]
            tp2 = entry - risk_per_unit * self.config["tp2_r"]

        risk_usdt = self.state.balance * risk_pct / 100.0
        qty_by_risk = risk_usdt / max(risk_per_unit, 1e-12)
        max_notional = self.state.balance * leverage
        qty_by_leverage = max_notional / entry
        qty = self._round_qty(min(qty_by_risk, qty_by_leverage), contract)
        notional = qty * entry
        min_usdt = contract.min_trade_usdt if contract else 5.0
        min_qty = contract.min_trade_num if contract else 0.0
        if qty <= 0 or qty < min_qty or notional < min_usdt:
            self.emit("log", text=f"{signal.symbol} dilewati: ukuran posisi di bawah minimum kontrak.")
            return

        entry_fee = notional * fee_rate
        slippage_cost = abs(entry - reference) * qty
        self.state.balance -= entry_fee
        position = Position(
            symbol=signal.symbol,
            direction=signal.direction,
            setup_type="fallback" if fallback else "normal",
            opened_at=utc_now_iso(),
            entry_reference=reference,
            entry_price=entry,
            initial_qty=qty,
            remaining_qty=qty,
            leverage=leverage,
            stop_price=stop,
            initial_stop_price=stop,
            tp1_price=tp1,
            tp2_price=tp2,
            tp1_fraction=self.config["tp1_fraction"],
            fee_rate=fee_rate,
            entry_fee=entry_fee,
            slippage_cost=slippage_cost,
            score=signal.score,
            reasons=signal.reasons,
            last_checked_candle_ts=int(time.time() * 1000),
        )
        with self._state_lock:
            self.state.open_position = position
        if self.stream:
            self.stream.set_symbol(position.symbol)
        self._update_drawdown()
        self.storage.logger.info("OPEN PAPER %s %s qty=%s entry=%s", position.symbol, position.direction, qty, entry)
        self.emit("trade_open", position=position.to_dict())

    def _manage_position(self) -> None:
        with self._state_lock:
            position = self.state.open_position
            if not position:
                return
            ticker = self.latest_tickers.get(position.symbol)
            if not ticker:
                ticker_rows = self.client.get_tickers()
                self.latest_tickers = {item.symbol: item for item in ticker_rows}
                ticker = self.latest_tickers.get(position.symbol)
            if not ticker:
                return

            # WebSocket handles SL/TP continuously. REST 1M candles are retained as
            # a fallback when the live feed is disconnected.
            ws_live = bool(self.stream and self.stream.is_live_for(position.symbol))
            if not ws_live:
                candles = self.client.get_candles(position.symbol, "1m", 120)
                if len(candles) > 2:
                    candles = candles[:-1]
                new_candles = [c for c in candles if c.timestamp > position.last_checked_candle_ts]
                if not new_candles:
                    new_candles = candles[-1:]
                for candle in new_candles:
                    position.last_checked_candle_ts = max(position.last_checked_candle_ts, candle.timestamp)
                    if self._process_candle(position, candle):
                        break

            if self.state.open_position:
                opened = datetime.fromisoformat(position.opened_at)
                age_minutes = (datetime.now(timezone.utc) - opened).total_seconds() / 60.0
                if age_minutes >= self.config["max_hold_minutes"]:
                    exit_reference = ticker.bid if position.direction == "LONG" else ticker.ask
                    self._close_all(position, exit_reference, "time_stop")
                else:
                    if self.live_ticker and self.live_ticker.symbol == position.symbol:
                        mark = (self.live_ticker.executable_long_exit if position.direction == "LONG"
                                else self.live_ticker.executable_short_exit)
                    else:
                        mark = ticker.bid if position.direction == "LONG" else ticker.ask
                    unrealized = self._gross_pnl(position.direction, position.entry_price, mark, position.remaining_qty)
                    self._update_drawdown(self.state.balance + unrealized)

    def _process_candle(self, position: Position, candle) -> bool:
        # Conservative intrabar assumption: if stop and target are both touched, stop is processed first.
        if position.direction == "LONG":
            if candle.low <= position.stop_price:
                self._close_all(position, position.stop_price, "stop_loss" if not position.tp1_hit else "breakeven_stop")
                return True
            if not position.tp1_hit and candle.high >= position.tp1_price:
                self._take_partial(position, position.tp1_price)
            if self.state.open_position and candle.high >= position.tp2_price:
                self._close_all(position, position.tp2_price, "take_profit_2")
                return True
        else:
            if candle.high >= position.stop_price:
                self._close_all(position, position.stop_price, "stop_loss" if not position.tp1_hit else "breakeven_stop")
                return True
            if not position.tp1_hit and candle.low <= position.tp1_price:
                self._take_partial(position, position.tp1_price)
            if self.state.open_position and candle.low <= position.tp2_price:
                self._close_all(position, position.tp2_price, "take_profit_2")
                return True
        return False

    @staticmethod
    def _gross_pnl(direction: str, entry: float, exit_price: float, qty: float) -> float:
        multiplier = 1.0 if direction == "LONG" else -1.0
        return (exit_price - entry) * qty * multiplier

    def _take_partial(self, position: Position, target_price: float) -> None:
        qty = min(position.remaining_qty, position.initial_qty * position.tp1_fraction)
        if qty <= 0:
            return
        gross = self._gross_pnl(position.direction, position.entry_price, target_price, qty)
        exit_fee = target_price * qty * position.fee_rate
        self.state.balance += gross - exit_fee
        position.remaining_qty -= qty
        position.realized_gross_pnl += gross
        position.realized_exit_fees += exit_fee
        position.tp1_hit = True
        position.stop_price = position.entry_price
        self.storage.logger.info("PARTIAL PAPER %s gross=%s", position.symbol, gross)
        self.emit("trade_update", text=f"{position.symbol} TP1; SL dipindah ke breakeven.")

    def _close_all(self, position: Position, raw_exit_price: float, reason: str) -> None:
        ticker = self.latest_tickers.get(position.symbol)
        slip = self.config["slippage_bps"] / 10_000.0
        if reason.startswith("take_profit") or reason in {"time_stop", "manual_close"}:
            if position.direction == "LONG":
                exit_price = raw_exit_price * (1.0 - slip)
            else:
                exit_price = raw_exit_price * (1.0 + slip)
        else:
            if position.direction == "LONG":
                exit_price = raw_exit_price * (1.0 - slip)
            else:
                exit_price = raw_exit_price * (1.0 + slip)

        qty = position.remaining_qty
        gross = self._gross_pnl(position.direction, position.entry_price, exit_price, qty)
        exit_fee = abs(exit_price * qty) * position.fee_rate
        exit_slippage = abs(exit_price - raw_exit_price) * qty
        self.state.balance += gross - exit_fee
        total_gross = position.realized_gross_pnl + gross
        total_fees = position.entry_fee + position.realized_exit_fees + exit_fee
        total_slippage = position.slippage_cost + exit_slippage
        net = total_gross - total_fees
        self._update_drawdown()

        trade = {
            "trade_id": uuid.uuid4().hex[:12],
            "symbol": position.symbol,
            "direction": position.direction,
            "setup_type": position.setup_type,
            "opened_at": position.opened_at,
            "closed_at": utc_now_iso(),
            "entry_price": f"{position.entry_price:.12g}",
            "exit_price": f"{exit_price:.12g}",
            "initial_qty": f"{position.initial_qty:.12g}",
            "leverage": f"{position.leverage:.2f}",
            "score": f"{position.score:.2f}",
            "gross_pnl": f"{total_gross:.8f}",
            "fees": f"{total_fees:.8f}",
            "slippage_estimate": f"{total_slippage:.8f}",
            "net_pnl": f"{net:.8f}",
            "return_on_starting_equity_pct": f"{net / self.state.starting_equity * 100.0:.6f}",
            "exit_reason": reason,
            "tp1_hit": str(position.tp1_hit),
            "balance_after": f"{self.state.balance:.8f}",
            "reasons": " | ".join(position.reasons),
        }
        self.storage.append_trade(trade)
        self.storage.logger.info("CLOSE PAPER %s reason=%s net=%s", position.symbol, reason, net)
        self.state.open_position = None
        if self.stream:
            self.stream.set_symbol(None)
        self._check_daily_loss()
        self.emit("trade_close", trade=trade)

    def _on_ws_status(self, event: str, payload: dict) -> None:
        if event == "connected":
            self.ws_connected = True
            self.emit("ws_status", connected=True, symbol=payload.get("symbol"), text="WS TERHUBUNG")
        elif event == "subscribed":
            self.ws_connected = True
            self.ws_symbol = payload.get("symbol")
            self.emit("ws_status", connected=True, symbol=self.ws_symbol, text=f"WS LIVE {self.ws_symbol or ''}".strip())
        elif event in {"disconnected", "reconnecting"}:
            self.ws_connected = False
            self.ws_symbol = None
            text = "WS RECONNECT" if event == "reconnecting" else "WS TERPUTUS"
            self.emit("ws_status", connected=False, symbol=None, text=text)
        elif event == "unsubscribed":
            self.ws_symbol = None
            self.emit("ws_status", connected=self.ws_connected, symbol=None, text="WS SIAGA")
        elif event == "error":
            self.emit("error", text=f"WebSocket: {payload.get('text', 'unknown error')}")

    def _on_live_tick(self, live: LiveTicker) -> None:
        self.live_ticker = live
        now = time.monotonic()
        with self._state_lock:
            position = self.state.open_position
            if not position or position.symbol != live.symbol or self.stop_event.is_set():
                return

            executable = (live.executable_long_exit if position.direction == "LONG"
                          else live.executable_short_exit)
            if executable <= 0:
                return

            closed = False
            if position.direction == "LONG":
                if executable <= position.stop_price:
                    self._close_all(position, executable, "stop_loss" if not position.tp1_hit else "breakeven_stop")
                    closed = True
                else:
                    if not position.tp1_hit and executable >= position.tp1_price:
                        self._take_partial(position, position.tp1_price)
                        self.storage.save_state(self.state)
                    if self.state.open_position and executable >= position.tp2_price:
                        self._close_all(position, position.tp2_price, "take_profit_2")
                        closed = True
            else:
                if executable >= position.stop_price:
                    self._close_all(position, executable, "stop_loss" if not position.tp1_hit else "breakeven_stop")
                    closed = True
                else:
                    if not position.tp1_hit and executable <= position.tp1_price:
                        self._take_partial(position, position.tp1_price)
                        self.storage.save_state(self.state)
                    if self.state.open_position and executable <= position.tp2_price:
                        self._close_all(position, position.tp2_price, "take_profit_2")
                        closed = True

            if not closed and self.state.open_position:
                unrealized = self._gross_pnl(position.direction, position.entry_price, executable, position.remaining_qty)
                self._update_drawdown(self.state.balance + unrealized)

            throttle = self.config.get("live_ui_throttle_seconds", 1.0)
            if closed or now - self._last_live_emit >= throttle:
                self._last_live_emit = now
                self.storage.save_state(self.state)
                self.emit(
                    "live_tick",
                    symbol=live.symbol,
                    price=live.last,
                    bid=live.bid,
                    ask=live.ask,
                    timestamp_ms=live.timestamp_ms,
                )
                self.emit("state", state=self.snapshot())

    def close_position_async(self) -> None:
        def task() -> None:
            with self._cycle_lock:
                position = self.state.open_position
                if not position:
                    return
                tickers = self.client.get_tickers()
                self.latest_tickers = {item.symbol: item for item in tickers}
                ticker = self.latest_tickers.get(position.symbol)
                if ticker:
                    reference = ticker.bid if position.direction == "LONG" else ticker.ask
                    self._close_all(position, reference, "manual_close")
                    self.storage.save_state(self.state)
                    self.emit("state", state=self.snapshot())
        threading.Thread(target=task, daemon=True).start()

    def snapshot(self) -> dict:
        trades = self.storage.read_trades()
        metrics = calculate_metrics(
            trades,
            self.state.starting_equity,
            self.state.balance,
            self.state.max_drawdown_pct,
        )
        return {
            "running": self.is_running,
            "balance": self.state.balance,
            "starting_equity": self.state.starting_equity,
            "open_position": self.state.open_position.to_dict() if self.state.open_position else None,
            "last_scan_at": self.state.last_scan_at,
            "daily_stop": self.state.stopped_for_daily_loss,
            "websocket_enabled": bool(self.stream),
            "websocket_connected": self.ws_connected,
            "websocket_symbol": self.ws_symbol,
            "live_price": self.live_ticker.last if self.live_ticker else None,
            "live_price_ts": self.live_ticker.timestamp_ms if self.live_ticker else None,
            "metrics": metrics,
        }

    def make_report(self) -> Path:
        trades = self.storage.read_trades()
        metrics = calculate_metrics(trades, self.state.starting_equity, self.state.balance, self.state.max_drawdown_pct)
        if self.state.open_position:
            p = self.state.open_position
            open_text = f"{p.symbol} {p.direction} @ {p.entry_price:.8g}"
        else:
            open_text = "Tidak ada"
        return build_html_report(trades, metrics, open_text)

    @staticmethod
    def _signal_dict(signal: Signal) -> dict:
        return {
            "symbol": signal.symbol,
            "direction": signal.direction,
            "score": signal.score,
            "price": signal.reference_price,
            "spread_bps": signal.spread_bps,
            "volume": signal.volume_24h,
            "funding": signal.funding_rate,
            "reasons": "; ".join(signal.reasons[:4]),
        }
