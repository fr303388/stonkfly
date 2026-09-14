"""CZSC (缠论) skills for stonkfly fruit fly brain.

Converts price history into Chan Theory signals:
- 分型 (Fractal): top/bottom reversal points
- 笔 (Stroke): trends between fractals
- 中枢 (Pivot/Consolidation): price consolidation zones
- Signal summary for neural observation
"""

import numpy as np
from datetime import datetime, timedelta

try:
    from czsc import CZSC, Freq, RawBar
    CZSC_AVAILABLE = True
except ImportError:
    CZSC_AVAILABLE = False


def prices_to_bars(prices, freq="15分钟"):
    """Convert stonkfly price history (list of float prices) to czsc RawBar list.

    Args:
        prices: list of float prices (closing prices)
        freq: czsc frequency string

    Returns:
        list of RawBar objects
    """
    if not CZSC_AVAILABLE or len(prices) < 10:
        return []

    bars = []
    base_time = datetime(2024, 1, 1, 9, 30)
    # Determine minutes per bar based on freq
    minutes_map = {"1分钟": 1, "5分钟": 5, "15分钟": 15, "30分钟": 30, "60分钟": 60, "日线": 240}
    minutes = minutes_map.get(freq, 15)

    for i, price in enumerate(prices):
        dt = base_time + timedelta(minutes=i * minutes)
        # Create OHLC from close prices (use close as all OHLC for simplicity)
        # In real usage, we'd have actual OHLC data
        bars.append(RawBar(
            symbol="BNB-USDT",
            id=i,
            freq=Freq.F15 if freq == "15分钟" else Freq.F30,
            dt=dt,
            open=float(price),
            high=float(price) * 1.001,
            low=float(price) * 0.999,
            close=float(price),
            vol=1000.0,
            amount=float(price) * 1000,
        ))
    return bars


def analyze_czsc(prices, freq="15分钟"):
    """Run CZSC analysis on price history and return key signals.

    Returns:
        dict with:
        - bi_count: number of strokes (笔)
        - zs_count: number of pivots (中枢)
        - fx_count: number of fractals (分型)
        - last_bi_direction: direction of last stroke (up/down)
        - last_bi_pct: percentage change of last stroke
        - in_zs: whether currently in a pivot zone
        - zs_high/zs_low: current pivot boundaries
        - signal: human-readable signal summary
        - bullish_score: 0-100 bullish signal strength
        - bearish_score: 0-100 bearish signal strength
    """
    if not CZSC_AVAILABLE or len(prices) < 30:
        return {
            "bi_count": 0, "zs_count": 0, "fx_count": 0,
            "last_bi_direction": "unknown", "last_bi_pct": 0,
            "in_zs": False, "zs_high": None, "zs_low": None,
            "signal": "數據不足", "bullish_score": 50, "bearish_score": 50,
        }

    bars = prices_to_bars(prices, freq)
    if len(bars) < 10:
        return {"signal": "數據不足", "bullish_score": 50, "bearish_score": 50}

    try:
        czsc_obj = CZSC(bars)
    except Exception as e:
        return {"signal": f"分析錯誤: {e}", "bullish_score": 50, "bearish_score": 50}

    bi_list = czsc_obj.bi_list or []
    zs_list = czsc_obj.zs_list or []
    fx_list = czsc_obj.fx_list or []

    result = {
        "bi_count": len(bi_list),
        "zs_count": len(zs_list),
        "fx_count": len(fx_list),
        "last_bi_direction": "unknown",
        "last_bi_pct": 0,
        "in_zs": False,
        "zs_high": None,
        "zs_low": None,
        "signal": "",
        "bullish_score": 50,
        "bearish_score": 50,
    }

    # Last stroke direction and magnitude
    if bi_list:
        last_bi = bi_list[-1]
        direction = getattr(last_bi, 'direction', None)
        if direction:
            dir_str = str(direction)
            result["last_bi_direction"] = "up" if "up" in dir_str.lower() or "多" in dir_str else "down"
        # Calculate stroke percentage
        try:
            high = float(getattr(last_bi, 'high', 0))
            low = float(getattr(last_bi, 'low', 0))
            if low > 0:
                result["last_bi_pct"] = (high - low) / low * 100
        except (TypeError, ValueError):
            pass

    # Current pivot zone
    if zs_list:
        last_zs = zs_list[-1]
        try:
            result["zs_high"] = float(getattr(last_zs, 'zg', 0) or getattr(last_zs, 'high', 0))
            result["zs_low"] = float(getattr(last_zs, 'zd', 0) or getattr(last_zs, 'low', 0))
            current_price = prices[-1]
            if result["zs_low"] and result["zs_high"]:
                result["in_zs"] = result["zs_low"] <= current_price <= result["zs_high"]
        except (TypeError, ValueError):
            pass

    # Compute bullish/bearish scores
    bullish = 50
    bearish = 50

    # Stroke direction
    if result["last_bi_direction"] == "up":
        bullish += 15
        bearish -= 10
    elif result["last_bi_direction"] == "down":
        bearish += 15
        bullish -= 10

    # Pivot breakout
    if result["in_zs"]:
        bullish += 5
        bearish += 5  # consolidation = neutral
    elif result["zs_high"] and prices[-1] > result["zs_high"]:
        bullish += 20  # breakout above pivot
        bearish -= 15
    elif result["zs_low"] and prices[-1] < result["zs_low"]:
        bearish += 20  # breakdown below pivot
        bullish -= 15

    # Stroke magnitude (larger moves = stronger signal)
    if result["last_bi_pct"] > 3:
        if result["last_bi_direction"] == "up":
            bullish += 10
        else:
            bearish += 10

    result["bullish_score"] = max(0, min(100, bullish))
    result["bearish_score"] = max(0, min(100, bearish))

    # Human-readable signal
    signals = []
    if result["last_bi_direction"] == "up":
        signals.append(f"筆向上 ({result['last_bi_pct']:.1f}%)")
    elif result["last_bi_direction"] == "down":
        signals.append(f"筆向下 ({result['last_bi_pct']:.1f}%)")
    if result["in_zs"]:
        signals.append("中樞震盪")
    elif result["zs_high"] and prices[-1] > result["zs_high"]:
        signals.append("突破中樞")
    elif result["zs_low"] and prices[-1] < result["zs_low"]:
        signals.append("跌破中樞")
    signals.append(f"多空 {result['bullish_score']:.0f}/{result['bearish_score']:.0f}")
    result["signal"] = " · ".join(signals) if signals else "纏論分析中"

    return result


def get_czsc_observation(prices):
    """Get a compact observation dict for the fruit fly brain.

    Returns normalized values suitable for neural stimulation:
    - trend: -1 (bearish) to 1 (bullish)
    - volatility: 0-1 normalized stroke magnitude
    - in_consolidation: 0 or 1
    - signal_strength: 0-1
    """
    analysis = analyze_czsc(prices)
    trend = (analysis["bullish_score"] - analysis["bearish_score"]) / 100.0
    volatility = min(1.0, analysis["last_bi_pct"] / 10.0)
    return {
        "trend": round(trend, 3),
        "volatility": round(volatility, 3),
        "in_consolidation": 1 if analysis["in_zs"] else 0,
        "signal_strength": round(max(analysis["bullish_score"], analysis["bearish_score"]) / 100.0, 3),
        "detail": analysis,
    }
