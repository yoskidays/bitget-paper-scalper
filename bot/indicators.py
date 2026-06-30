from __future__ import annotations

from math import isfinite
from typing import Iterable

from .models import Candle


def ema(values: list[float], period: int) -> list[float]:
    if period <= 0 or not values:
        return []
    alpha = 2.0 / (period + 1.0)
    output = [float(values[0])]
    for value in values[1:]:
        output.append(alpha * float(value) + (1.0 - alpha) * output[-1])
    return output


def sma(values: list[float], period: int) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    output: list[float | None] = []
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= period:
            running -= values[index - period]
        output.append(running / period if index >= period - 1 else None)
    return output


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    if len(values) < 2:
        return [None] * len(values)
    gains = [0.0]
    losses = [0.0]
    for previous, current in zip(values, values[1:]):
        delta = current - previous
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    output: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return output

    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    output[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    for index in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[index]) / period
        avg_loss = (avg_loss * (period - 1) + losses[index]) / period
        output[index] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return output


def true_ranges(candles: list[Candle]) -> list[float]:
    if not candles:
        return []
    output = [candles[0].high - candles[0].low]
    for previous, current in zip(candles, candles[1:]):
        output.append(max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        ))
    return output


def atr(candles: list[Candle], period: int = 14) -> list[float | None]:
    ranges = true_ranges(candles)
    output: list[float | None] = [None] * len(ranges)
    if len(ranges) < period:
        return output
    current = sum(ranges[:period]) / period
    output[period - 1] = current
    for index in range(period, len(ranges)):
        current = (current * (period - 1) + ranges[index]) / period
        output[index] = current
    return output


def percentile_rank(values: Iterable[float], value: float) -> float:
    cleaned = sorted(v for v in values if isfinite(v))
    if not cleaned:
        return 0.0
    count = sum(1 for item in cleaned if item <= value)
    return count / len(cleaned)


def candle_body_ratio(candle: Candle) -> float:
    candle_range = max(candle.high - candle.low, 1e-12)
    return abs(candle.close - candle.open) / candle_range


def bullish_engulfing(previous: Candle, current: Candle) -> bool:
    return (
        previous.close < previous.open
        and current.close > current.open
        and current.open <= previous.close
        and current.close >= previous.open
    )


def bearish_engulfing(previous: Candle, current: Candle) -> bool:
    return (
        previous.close > previous.open
        and current.close < current.open
        and current.open >= previous.close
        and current.close <= previous.open
    )
