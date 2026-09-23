"""Extended CZSC structure extraction for K-line chart overlay."""

import numpy as np
from datetime import datetime, timedelta

try:
    from czsc import CZSC, Freq, RawBar
    CZSC_AVAILABLE = True
except ImportError:
    CZSC_AVAILABLE = False


def klines_to_bars(klines, freq="15分钟"):
    """Convert Binance klines (OHLCV) to czsc RawBar list.

    Args:
        klines: list of dicts with t, o, h, l, c, v
        freq: czsc frequency

    Returns:
        list of RawBar objects
    """
    if not CZSC_AVAILABLE or len(klines) < 10:
        return []

    bars = []
    freq_map = {"1m": Freq.F1, "5m": Freq.F5, "15m": Freq.F15, "30m": Freq.F30, "60m": Freq.F60}
    czsc_freq = freq_map.get(freq, Freq.F15)

    for i, k in enumerate(klines):
        dt = datetime.fromtimestamp(k["t"] / 1000)
        bars.append(RawBar(
            symbol="BNB-USDT",
            id=i,
            freq=czsc_freq,
            dt=dt,
            open=float(k["o"]),
            high=float(k["h"]),
            low=float(k["l"]),
            close=float(k["c"]),
            vol=float(k.get("v", 1000)),
            amount=float(k["c"]) * float(k.get("v", 1000)),
        ))
    return bars


def extract_czsc_structures(klines, freq="15m"):
    """Extract CZSC structures with chart coordinates.

    Returns:
        dict with:
        - fractals: list of {index, price, type: 'top'|'bottom'}
        - strokes: list of {start_index, start_price, end_index, end_price, direction}
        - pivots: list of {start_index, end_index, high, low}
        - last_stroke_direction: 'up'|'down'|'unknown'
        - in_pivot: bool
        - signal: str
    """
    if not CZSC_AVAILABLE or len(klines) < 30:
        return {"fractals": [], "strokes": [], "pivots": [], "signal": "數據不足"}

    bars = klines_to_bars(klines, freq)
    if len(bars) < 10:
        return {"fractals": [], "strokes": [], "pivots": [], "signal": "數據不足"}

    try:
        czsc_obj = CZSC(bars)
    except Exception as e:
        return {"fractals": [], "strokes": [], "pivots": [], "signal": f"分析錯誤: {e}"}

    result = {
        "fractals": [],
        "strokes": [],
        "pivots": [],
        "last_stroke_direction": "unknown",
        "in_pivot": False,
        "signal": "",
        "trend": "unknown",
        "pivot_range": None,
        "current_stroke": None,
        "buy_signals": [],
        "sell_signals": [],
        "suggestion": "觀望",
        "divergence": None,
    }

    # Extract fractals (分型)
    fx_list = czsc_obj.fx_list or []
    for fx in fx_list:
        try:
            fx_type = "top" if "顶" in str(getattr(fx, 'mark', '')) or "高" in str(getattr(fx, 'mark', '')) else "bottom"
            # Try to get price and bar index
            fx_price = float(getattr(fx, 'fx', 0) or getattr(fx, 'price', 0))
            # Get the bar index from the fractal's dt or id
            bar_id = getattr(fx, 'id', None)
            if bar_id is None:
                # Try to find by dt
                fx_dt = getattr(fx, 'dt', None)
                if fx_dt:
                    for i, b in enumerate(bars):
                        if b.dt == fx_dt:
                            bar_id = i
                            break
            if bar_id is None:
                bar_id = getattr(fx, 'bar_index', 0)
            result["fractals"].append({
                "index": int(bar_id) if bar_id is not None else 0,
                "price": fx_price,
                "type": fx_type,
            })
        except (TypeError, ValueError, AttributeError):
            continue

    # Extract strokes (笔)
    bi_list = czsc_obj.bi_list or []
    for bi in bi_list:
        try:
            # 方向判斷：CZSC Direction enum 的字串是「向上」「向下」
            dir_val = getattr(bi, 'direction', None)
            dir_str = str(dir_val)
            if '上' in dir_str or 'up' in dir_str.lower() or '多' in dir_str:
                direction = "up"
            elif '下' in dir_str or 'down' in dir_str.lower() or '空' in dir_str:
                direction = "down"
            else:
                direction = "down"
            sdt = getattr(bi, 'sdt', None)
            edt = getattr(bi, 'edt', None)
            s_price = float(getattr(bi, 'low', 0) if direction == "up" else getattr(bi, 'high', 0))
            e_price = float(getattr(bi, 'high', 0) if direction == "up" else getattr(bi, 'low', 0))

            # Find bar indices by datetime
            s_idx = 0
            e_idx = len(bars) - 1
            for i, b in enumerate(bars):
                if sdt and b.dt == sdt:
                    s_idx = i
                if edt and b.dt == edt:
                    e_idx = i

            result["strokes"].append({
                "start_index": s_idx,
                "start_price": s_price,
                "end_index": e_idx,
                "end_price": e_price,
                "direction": direction,
            })
        except (TypeError, ValueError, AttributeError):
            continue

    if result["strokes"]:
        result["last_stroke_direction"] = result["strokes"][-1]["direction"]

    # Extract pivots (中枢)
    zs_list = czsc_obj.zs_list or []
    for zs in zs_list:
        try:
            zg = float(getattr(zs, 'zg', 0) or getattr(zs, 'high', 0))
            zd = float(getattr(zs, 'zd', 0) or getattr(zs, 'low', 0))
            sdt = getattr(zs, 'sdt', None)
            edt = getattr(zs, 'edt', None)
            s_idx = 0
            e_idx = len(bars) - 1
            for i, b in enumerate(bars):
                if sdt and b.dt == sdt:
                    s_idx = i
                if edt and b.dt == edt:
                    e_idx = i
            result["pivots"].append({
                "start_index": s_idx,
                "end_index": e_idx,
                "high": zg,
                "low": zd,
            })
        except (TypeError, ValueError, AttributeError):
            continue

    # Check if current price is in a pivot
    if result["pivots"] and klines:
        last_zs = result["pivots"][-1]
        current_price = klines[-1]["c"]
        result["in_pivot"] = last_zs["low"] <= current_price <= last_zs["high"]

    # Current stroke info
    if result["strokes"]:
        last_bi = result["strokes"][-1]
        result["current_stroke"] = {
            "direction": last_bi["direction"],
            "start_price": last_bi["start_price"],
            "end_price": last_bi["end_price"],
            "change_pct": ((last_bi["end_price"] - last_bi["start_price"]) / last_bi["start_price"] * 100) if last_bi["start_price"] else 0,
        }

    # Pivot range
    if result["pivots"]:
        last_zs = result["pivots"][-1]
        result["pivot_range"] = {"high": last_zs["high"], "low": last_zs["low"], "mid": (last_zs["high"] + last_zs["low"]) / 2}

    # Trend classification
    if len(result["strokes"]) >= 3:
        recent = result["strokes"][-3:]
        up_count = sum(1 for s in recent if s["direction"] == "up")
        if up_count >= 2:
            result["trend"] = "上升"
        elif up_count <= 1:
            result["trend"] = "下降"
        else:
            result["trend"] = "盤整"
    elif result["in_pivot"]:
        result["trend"] = "盤整"

    # Divergence detection (simple: compare stroke magnitudes)
    if len(result["strokes"]) >= 4 and klines:
        same_dir = [s for s in result["strokes"][-4:] if s["direction"] == result["last_stroke_direction"]]
        if len(same_dir) >= 2:
            mag1 = abs(same_dir[-2]["end_price"] - same_dir[-2]["start_price"])
            mag2 = abs(same_dir[-1]["end_price"] - same_dir[-1]["start_price"])
            if mag2 < mag1 * 0.7:
                result["divergence"] = "頂背馳" if result["last_stroke_direction"] == "up" else "底背馳"

    # Buy/Sell signal detection (chan theory rules)
    current_price = klines[-1]["c"] if klines else 0
    if result["pivots"] and result["strokes"]:
        last_zs = result["pivots"][-1]
        last_bi = result["strokes"][-1]
        # Buy signal: downward stroke ends near pivot low + price starts rising
        if last_bi["direction"] == "down" and last_bi["end_price"] <= last_zs["low"] * 1.02:
            if current_price > last_bi["end_price"]:
                sig_idx = min(last_bi["end_index"], len(klines) - 1)
                result["buy_signals"].append({"index": sig_idx, "price": last_bi["end_price"], "type": "一買"})
        # Sell signal: upward stroke ends near pivot high + price starts falling
        if last_bi["direction"] == "up" and last_bi["end_price"] >= last_zs["high"] * 0.98:
            if current_price < last_bi["end_price"]:
                sig_idx = min(last_bi["end_index"], len(klines) - 1)
                result["sell_signals"].append({"index": sig_idx, "price": last_bi["end_price"], "type": "一賣"})
        # Breakout buy: price breaks above pivot
        if not result["in_pivot"] and current_price > last_zs["high"] and result["last_stroke_direction"] == "up":
            result["buy_signals"].append({"index": len(klines) - 1, "price": current_price, "type": "突破買"})
        # Breakdown sell: price breaks below pivot
        if not result["in_pivot"] and current_price < last_zs["low"] and result["last_stroke_direction"] == "down":
            result["sell_signals"].append({"index": len(klines) - 1, "price": current_price, "type": "跌破賣"})

    # Trading suggestion
    if result["buy_signals"] and not result["sell_signals"]:
        result["suggestion"] = "買入"
    elif result["sell_signals"] and not result["buy_signals"]:
        result["suggestion"] = "賣出"
    elif result["divergence"]:
        result["suggestion"] = "警戒(" + result["divergence"] + ")"
    elif result["in_pivot"]:
        result["suggestion"] = "觀望(中樞震盪)"
    else:
        result["suggestion"] = "觀望"

    # Professional signal summary
    parts = []
    if result["trend"] != "unknown":
        parts.append("趨勢:" + result["trend"])
    if result["last_stroke_direction"] == "up":
        parts.append("筆向上")
    elif result["last_stroke_direction"] == "down":
        parts.append("筆向下")
    if result["in_pivot"]:
        parts.append("中樞震盪")
    elif result["pivots"] and klines:
        last_zs = result["pivots"][-1]
        if klines[-1]["c"] > last_zs["high"]:
            parts.append("突破中樞")
        elif klines[-1]["c"] < last_zs["low"]:
            parts.append("跌破中樞")
    if result["divergence"]:
        parts.append(result["divergence"])
    if result["buy_signals"]:
        parts.append("買點:" + ",".join(s["type"] for s in result["buy_signals"]))
    if result["sell_signals"]:
        parts.append("賣點:" + ",".join(s["type"] for s in result["sell_signals"]))
    parts.append(f"{len(result['fractals'])}分型 {len(result['strokes'])}筆 {len(result['pivots'])}中樞")
    result["signal"] = " · ".join(parts) if parts else "纏論分析中"

    return result
