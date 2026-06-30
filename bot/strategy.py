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
    candles_1m: list[Candle]
    previous_open_interest: float | None


class PullbackMomentumStrategy:
    """1H bias + 15M context + 5M alignment + closed 1M execution trigger."""

    def __init__(self, config: dict) -> None:
        self.config = config

    @staticmethod
    def _closed(candles: list[Candle], count: int) -> list[Candle]:
        # Bitget REST can include the still-forming candle. Excluding the newest
        # candle prevents entries based on an intrabar signal that later disappears.
        if len(candles) > 2:
            candles = candles[:-1]
        return candles[-count:]

    def analyze(self, data: AnalysisInput) -> Signal | None:
        h1 = self._closed(data.candles_1h, 240)
        m15 = self._closed(data.candles_15m, 220)
        m5 = self._closed(data.candles_5m, 220)
        m1 = self._closed(data.candles_1m, 180)
        if len(h1) < 205 or len(m15) < 60 or len(m5) < 60 or len(m1) < 60:
            return None

        c1h = [x.close for x in h1]
        c15 = [x.close for x in m15]
        c5 = [x.close for x in m5]
        c1 = [x.close for x in m1]
        v1 = [x.base_volume for x in m1]

        ema50_h = ema(c1h, 50)
        ema200_h = ema(c1h, 200)
        ema20_15 = ema(c15, 20)
        ema50_15 = ema(c15, 50)
        ema9_5 = ema(c5, 9)
        ema20_5 = ema(c5, 20)
        ema9_1 = ema(c1, 9)
        ema20_1 = ema(c1, 20)
        rsi1 = rsi(c1, 14)
        atr1 = atr(m1, 14)
        atr5_values = atr(m5, 14)
        vol_sma1 = sma(v1, 20)

        last_h = h1[-1]
        last_15 = m15[-1]
        last_5 = m5[-1]
        prev_1, last_1 = m1[-2], m1[-1]
        current_atr1 = atr1[-1]
        current_atr5 = atr5_values[-1]
        current_rsi1 = rsi1[-1]
        current_vol_avg1 = vol_sma1[-1]
        if (
            not current_atr1
            or current_atr1 <= 0
            or not current_atr5
            or current_atr5 <= 0
            or current_rsi1 is None
            or not current_vol_avg1
        ):
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

        # 1H directional bias: 25 points.
        trend_separation = abs(ema50_h[-1] - ema200_h[-1]) / max(last_h.close, 1e-12)
        score += 18.0
        if trend_separation >= 0.005:
            score += 4.0
        if (direction == "LONG" and c1h[-1] > c1h[-4]) or (direction == "SHORT" and c1h[-1] < c1h[-4]):
            score += 3.0
        reasons.append(f"Tren 1H {direction.lower()} terkonfirmasi")

        # 15M pullback/context: 20 points.
        atr15_values = atr(m15, 14)
        current_atr15 = atr15_values[-1] or max(last_15.close * 0.005, 1e-9)
        distance_to_ema20 = abs(last_15.close - ema20_15[-1])
        near_pullback = distance_to_ema20 <= current_atr15 * 0.9
        aligned_15 = (
            direction == "LONG" and last_15.close >= ema50_15[-1]
        ) or (
            direction == "SHORT" and last_15.close <= ema50_15[-1]
        )
        if aligned_15:
            score += 10.0
            reasons.append("Struktur 15M searah tren")
        if near_pullback:
            score += 6.0
            reasons.append("Harga 15M dekat area pullback")
        if (direction == "LONG" and ema20_15[-1] > ema50_15[-1]) or (direction == "SHORT" and ema20_15[-1] < ema50_15[-1]):
            score += 4.0

        # 5M alignment: 20 points. This avoids treating every 1M impulse as a setup.
        if direction == "LONG":
            aligned_5 = last_5.close > ema9_5[-1] > ema20_5[-1]
            momentum_5 = last_5.close >= m5[-2].close
            not_extended_5 = (last_5.close - ema20_5[-1]) <= current_atr5 * 1.5
        else:
            aligned_5 = last_5.close < ema9_5[-1] < ema20_5[-1]
            momentum_5 = last_5.close <= m5[-2].close
            not_extended_5 = (ema20_5[-1] - last_5.close) <= current_atr5 * 1.5
        if aligned_5:
            score += 10.0
            reasons.append("EMA 5M searah")
        if momentum_5:
            score += 5.0
        if not_extended_5:
            score += 5.0
        else:
            score -= 6.0
            reasons.append("Harga 5M terlalu jauh dari mean")

        # Closed 1M execution trigger: 23 points.
        body_ok = candle_body_ratio(last_1) >= 0.42
        recent_high = max(x.high for x in m1[-6:-1])
        recent_low = min(x.low for x in m1[-6:-1])
        if direction == "LONG":
            trigger_candle = last_1.close > last_1.open
            ema_trigger = last_1.close > ema9_1[-1] > ema20_1[-1]
            structure_break = last_1.close > recent_high
            engulf = bullish_engulfing(prev_1, last_1)
            rsi_ok = 52.0 <= current_rsi1 <= 74.0
        else:
            trigger_candle = last_1.close < last_1.open
            ema_trigger = last_1.close < ema9_1[-1] < ema20_1[-1]
            structure_break = last_1.close < recent_low
            engulf = bearish_engulfing(prev_1, last_1)
            rsi_ok = 26.0 <= current_rsi1 <= 48.0

        if trigger_candle and body_ok:
            score += 5.0
            reasons.append("Candle pemicu 1M kuat")
        if ema_trigger:
            score += 5.0
            reasons.append("EMA 1M searah")
        if structure_break:
            score += 8.0
            reasons.append("Break struktur minor 1M")
        elif engulf:
            score += 5.0
            reasons.append("Engulfing 1M")
        if rsi_ok:
            score += 5.0
            reasons.append(f"RSI 1M mendukung ({current_rsi1:.1f})")

        # Volume, OI, funding and execution quality: 17 points.
        volume_ratio = last_1.base_volume / current_vol_avg1 if current_vol_avg1 else 0.0
        if volume_ratio >= 1.5:
            score += 6.0
            reasons.append(f"Volume 1M {volume_ratio:.2f}x rata-rata")
        elif volume_ratio >= 1.1:
            score += 3.0

        if data.previous_open_interest and data.ticker.open_interest > 0:
            oi_change = (data.ticker.open_interest - data.previous_open_interest) / data.previous_open_interest
            if oi_change > 0.001:
                score += 3.0
                reasons.append("Open interest meningkat")
            elif oi_change < -0.01:
                score -= 3.0

        funding = data.ticker.funding_rate
        if abs(funding) <= 0.0005:
            score += 3.0
        elif (direction == "LONG" and funding > 0.001) or (direction == "SHORT" and funding < -0.001):
            score -= 5.0
            reasons.append("Funding terlalu padat")

        if data.ticker.spread_bps <= 2.0:
            score += 5.0
        elif data.ticker.spread_bps <= self.config["max_spread_bps"]:
            score += 2.0

        execution_ready = ema_trigger and (
            structure_break
            or engulf
            or (trigger_candle and body_ok and volume_ratio >= 1.1)
        )
        if not execution_ready:
            # Keep the pair visible as a candidate, but prevent both normal and
            # fallback entry until a closed 1M candle provides a real trigger.
            score = min(score, self.config["fallback_min_score"] - 1.0)
            reasons.append("Trigger eksekusi 1M belum lengkap")

        current_price = data.ticker.mid or last_1.close
        # Blend 1M and 5M ATR so the stop is responsive but not unrealistically tight.
        blended_atr = max(current_atr1 * 2.0, current_atr5 * 0.45)
        raw_stop_pct = blended_atr * self.config["atr_stop_multiplier"] / current_price
        stop_pct = min(self.config["max_stop_pct"], max(self.config["min_stop_pct"], raw_stop_pct))

        return Signal(
            symbol=data.ticker.symbol,
            direction=direction,
            score=round(max(0.0, min(100.0, score)), 2),
            reference_price=current_price,
            stop_distance_pct=stop_pct,
            atr=blended_atr,
            spread_bps=data.ticker.spread_bps,
            volume_24h=data.ticker.usdt_volume,
            funding_rate=funding,
            open_interest=data.ticker.open_interest,
            reasons=reasons,
        )
