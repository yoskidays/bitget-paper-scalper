from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Direction = Literal["LONG", "SHORT"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    base_volume: float
    quote_volume: float


@dataclass(slots=True)
class Ticker:
    symbol: str
    last: float
    bid: float
    ask: float
    usdt_volume: float
    change_24h: float
    funding_rate: float
    open_interest: float
    mark_price: float

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.last

    @property
    def spread_bps(self) -> float:
        mid = self.mid
        if mid <= 0 or self.ask <= 0 or self.bid <= 0:
            return float("inf")
        return (self.ask - self.bid) / mid * 10_000.0


@dataclass(slots=True)
class ContractInfo:
    symbol: str
    taker_fee_rate: float
    min_trade_usdt: float
    min_trade_num: float
    size_multiplier: float
    volume_place: int
    price_place: int
    max_leverage: float
    status: str


@dataclass(slots=True)
class Signal:
    symbol: str
    direction: Direction
    score: float
    reference_price: float
    stop_distance_pct: float
    atr: float
    spread_bps: float
    volume_24h: float
    funding_rate: float
    open_interest: float
    reasons: list[str] = field(default_factory=list)
    setup_type: str = "normal"


@dataclass(slots=True)
class Position:
    symbol: str
    direction: Direction
    setup_type: str
    opened_at: str
    entry_reference: float
    entry_price: float
    initial_qty: float
    remaining_qty: float
    leverage: float
    stop_price: float
    initial_stop_price: float
    tp1_price: float
    tp2_price: float
    tp1_fraction: float
    fee_rate: float
    entry_fee: float
    slippage_cost: float
    score: float
    reasons: list[str]
    tp1_hit: bool = False
    realized_gross_pnl: float = 0.0
    realized_exit_fees: float = 0.0
    last_checked_candle_ts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Position":
        return cls(**value)


@dataclass(slots=True)
class AccountState:
    starting_equity: float
    balance: float
    peak_equity: float
    max_drawdown_pct: float = 0.0
    open_position: Position | None = None
    empty_scan_count: int = 0
    last_scan_at: str | None = None
    day_anchor: str = ""
    day_start_balance: float = 0.0
    stopped_for_daily_loss: bool = False
    oi_snapshots: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["open_position"] = self.open_position.to_dict() if self.open_position else None
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AccountState":
        copy = dict(value)
        if copy.get("open_position"):
            copy["open_position"] = Position.from_dict(copy["open_position"])
        return cls(**copy)
