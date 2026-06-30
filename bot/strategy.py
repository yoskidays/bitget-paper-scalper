from __future__ import annotations

from dataclasses import dataclass

from .indicators import atr, bearish_engulfing, bullish_engulfing, candle_body_ratio, ema, rsi, sma
from .models import Candle, Signal, Ticker


@dataclass(slots=True)
class AnalysisInput:
    ticker: Ticker
    candles_1h: list[Candle]
    candles_15m: list[Candle]
    candles_5m: list[Candle]
    previous_open_interest: float | None


class PullbackMomentumStrategy:
    """Multi-timeframe trend/pullback/momentum scoring strategy."""

    def __init__(self, config: dict) -> None:
        self.config = config

    @staticmethod
    def _closed(candles: list[Candle], count: int = 220) -> list[Candle]:
        # REST may include the current updating candle. Removing the newest candle is conservative.
        if len(candles) > 2:
            candles = candles[:-1]
        return candles[-count:]

    def analyze(self, data: AnalysisInput) -> Signal | None:
        h1 = self._closed(data.candles_1h, 240)
        m15 = self._closed(data.candles_15m, 220)
        m5 = self._closed(data.candles_5m, 220)
        if len(h1) < 205 or len(m15) < 60 or len(m5) < 60:
            return None

        c1 = [x.close for x in h1]
        c15 = [x.close for x in m15]
        c5 = [x.close for x in m5]
        v5 = [x.base_volume for x in m5]

        ema50_h = ema(c1, 50)
        ema200_h = ema(c1, 200)
        ema20_15 = ema(c15, 20)
        ema50_15 = ema(c15, 50)
        ema9_5 = ema(c5, 9)
        ema20_5 = ema(c5, 20)
        rsi5 = rsi(c5, 14)
        atr5 = atr(m5, 14)
        vol_sma = sma(v5, 20)

        last_h = h1[-1]
        last_15 = m15[-1]
        prev_5, last_5 = m5[-2], m5[-1]
        current_atr = atr5[-1]
        current_rsi = rsi5[-1]
        current_vol_avg = vol_sma[-1]
        if not current_atr or current_atr <= 0 or current_rsi is None or not current_vol_avg:
            return None

        long_bias = (
            last_h.close > ema50_h[-1] > ema200_h[-1]
            and ema50_h[-1] > ema50_h[-4]
        )
        short_bias = (
            last_h.close < ema50_h[-1] < ema200_h[-1]
            and ema50_h[-1] < ema50_h[-4]
        )
        if not long_bias and not short_bias:
            return None

        direction = "LONG" if long_bias else "SHORT"
        score = 0.0
        reasons: list[str] = []

        # 1H trend: 30 points
        trend_separation = abs(ema50_h[-1] - ema200_h[-1]) / last_h.close
        score += 22.0
        if trend_separation >= 0.005:
            score += 5.0
        if (direction == "LONG" and c1[-1] > c1[-4]) or (direction == "SHORT" and c1[-1] < c1[-4]):
            score += 3.0
        reasons.append(f"Tren 1H {direction.lower()} terkonfirmasi")

        # 15M pullback/context: 24 points
        distance_to_ema20 = abs(last_15.close - ema20_15[-1])
        atr15_values = atr(m15, 14)
        atr15 = atr15_values[-1] or max(last_15.close * 0.005, 1e-9)
        near_pullback = distance_to_ema20 <= atr15 * 0.8
        aligned_15 = (
            direction == "LONG" and last_15.close >= ema50_15[-1]
        ) or (
            direction == "SHORT" and last_15.close <= ema50_15[-1]
        )
        if aligned_15:
            score += 12.0
            reasons.append("Struktur 15M searah tren")
        if near_pullback:
            score += 8.0
            reasons.append("Harga 15M dekat area pullback EMA20")
        if (direction == "LONG" and ema20_15[-1] > ema50_15[-1]) or (direction == "SHORT" and ema20_15[-1] < ema50_15[-1]):
            score += 4.0

        # 5M trigger: 28 points
        body_ok = candle_body_ratio(last_5) >= 0.45
        if direction == "LONG":
            trigger_candle = last_5.close > last_5.open
            ema_trigger = last_5.close > ema9_5[-1] > ema20_5[-1]
            structure_break = last_5.close > max(x.high for x in m5[-5:-1])
            engulf = bullish_engulfing(prev_5, last_5)
            rsi_ok = 50.0 <= current_rsi <= 72.0
        else:
            trigger_candle = last_5.close < last_5.open
            ema_trigger = last_5.close < ema9_5[-1] < ema20_5[-1]
            structure_break = last_5.close < min(x.low for x in m5[-5:-1])
            engulf = bearish_engulfing(prev_5, last_5)
            rsi_ok = 28.0 <= current_rsi <= 50.0

        if trigger_candle and body_ok:
            score += 7.0
            reasons.append("Candle pemicu 5M kuat")
        if ema_trigger:
            score += 7.0
            reasons.append("EMA 5M searah")
        if structure_break:
            score += 8.0
            reasons.append("Break struktur minor 5M")
        elif engulf:
            score += 6.0
            reasons.append("Engulfing 5M")
        if rsi_ok:
            score += 6.0
            reasons.append(f"RSI 5M mendukung ({current_rsi:.1f})")

        # Volume, OI, funding and execution quality: 18 points
        volume_ratio = last_5.base_volume / current_vol_avg if current_vol_avg else 0.0
        if volume_ratio >= 1.25:
            score += 6.0
            reasons.append(f"Volume 5M {volume_ratio:.2f}x rata-rata")
        elif volume_ratio >= 1.0:
            score += 3.0

        if data.previous_open_interest and data.ticker.open_interest > 0:
            oi_change = (data.ticker.open_interest - data.previous_open_interest) / data.previous_open_interest
            if oi_change > 0.001:
                score += 4.0
                reasons.append("Open interest meningkat")
            elif oi_change < -0.01:
                score -= 3.0

        funding = data.ticker.funding_rate
        if abs(funding) <= 0.0005:
            score += 3.0
        elif (direction == "LONG" and funding > 0.001) or (direction == "SHORT" and funding < -0.001):
            score -= 5.0
            reasons.append("Funding terlalu padat melawan kualitas entry")

        if data.ticker.spread_bps <= 2.0:
            score += 5.0
        elif data.ticker.spread_bps <= self.config["max_spread_bps"]:
            score += 2.0

        current_price = data.ticker.mid or last_5.close
        raw_stop_pct = current_atr * self.config["atr_stop_multiplier"] / current_price
        stop_pct = min(self.config["max_stop_pct"], max(self.config["min_stop_pct"], raw_stop_pct))

        return Signal(
            symbol=data.ticker.symbol,
            direction=direction,
            score=round(max(0.0, min(100.0, score)), 2),
            reference_price=current_price,
            stop_distance_pct=stop_pct,
            atr=current_atr,
            spread_bps=data.ticker.spread_bps,
            volume_24h=data.ticker.usdt_volume,
            funding_rate=funding,
            open_interest=data.ticker.open_interest,
            reasons=reasons,
        )
