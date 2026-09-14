"""Render observations into an RGB chart; never reads future prices or P&L."""

import numpy as np
from PIL import Image, ImageDraw


def compute_macd(prices, fast=12, slow=26, signal=9):
    """Compute MACD indicator from price series."""
    prices = np.asarray(prices, dtype=float)
    n = len(prices)
    if n < slow + signal:
        return {
            "dif": np.full(n, np.nan),
            "dea": np.full(n, np.nan),
            "hist": np.full(n, np.nan),
        }

    def ema(arr, period):
        alpha = 2.0 / (period + 1)
        out = np.empty_like(arr)
        out[0] = arr[0]
        for i in range(1, len(arr)):
            out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
        return out

    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)
    dif = ema_fast - ema_slow
    dea = ema(dif, signal)
    hist = 2 * (dif - dea)
    return {"dif": dif, "dea": dea, "hist": hist}




def compute_rsi(prices, period=14):
    """Compute RSI (Relative Strength Index) from price series.
    Returns array of RSI values 0-100."""
    prices = np.asarray(prices, dtype=float)
    n = len(prices)
    if n < period + 1:
        return np.full(n, np.nan)
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    rsi = np.full(n, np.nan)
    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100.0 - (100.0 / (1.0 + rs))
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))
    return rsi

def market_frame(product, history, bid, ask, macd=None, strategy=None, czsc=None):
    """Render market observation as 320x180 RGB frame.

    If strategy is provided, a position-sizing indicator is drawn in the header
    so the fly retina can see current multiplier, streak, and win rate.
    """
    im = Image.new("RGB", (320, 180), (235, 240, 249))
    d = ImageDraw.Draw(im)
    # Header
    d.rectangle((0, 0, 319, 27), fill=(19, 36, 71))
    d.text((9, 8), product, fill=(219, 229, 249))

    # Strategy indicator in header (right side)
    if strategy and strategy.get("name") != "none":
        mult = min(float(strategy.get("multiplier", 1.0)), 8.0)
        streak = int(strategy.get("streak", 0))
        # Multiplier bar: width proportional to multiplier (1x to 8x)
        bar_x = 160
        bar_w = int(140 * (mult / 8.0))
        bar_color = (34, 139, 34) if streak >= 0 else (197, 37, 78)
        d.rectangle((bar_x, 8, bar_x + 140, 18), fill=(60, 70, 100))
        d.rectangle((bar_x, 8, bar_x + max(2, bar_w), 18), fill=bar_color)
        # Streak dots
        dot_x = bar_x
        for i in range(abs(min(streak, 8))):
            color = (34, 197, 94) if streak > 0 else (239, 68, 68)
            d.ellipse((dot_x + i * 8, 20, dot_x + i * 8 + 4, 24), fill=color)

    # CZSC 缠论 skill indicator (bottom-left of header)
    if czsc:
        trend = czsc.get("trend", 0)
        in_zs = czsc.get("in_consolidation", 0)
        # Trend arrow: green up if bullish, red down if bearish
        if trend > 0.1:
            d.text((9, 14), "▲", fill=(34, 197, 94))  # bullish
        elif trend < -0.1:
            d.text((9, 14), "▼", fill=(239, 68, 68))  # bearish
        else:
            d.text((9, 14), "◆", fill=(200, 200, 100))  # neutral
        # Consolidation marker
        if in_zs:
            d.rectangle((20, 14, 28, 22), outline=(255, 200, 0), width=1)  # box = in pivot
        # Bullish/bearish mini bar (top-right corner)
        bull = int(czsc.get("signal_strength", 0.5) * 30)
        if trend >= 0:
            d.rectangle((280, 6, 310, 10), fill=(60, 70, 100))
            d.rectangle((280, 6, 280 + bull, 10), fill=(34, 197, 94))
        else:
            d.rectangle((280, 6, 310, 10), fill=(60, 70, 100))
            d.rectangle((280, 6, 280 + bull, 10), fill=(239, 68, 68))

    # Price chart area: y=32..130 (98px tall)
    price_top, price_bot = 32, 130
    for x in range(12, 310, 30):
        d.line((x, price_top, x, price_bot), fill=(200, 212, 233))
    for y in range(price_top + 4, price_bot, 24):
        d.line((10, y, 308, y), fill=(200, 212, 233))

    values = np.asarray(history[-100:], dtype=float)
    if len(values):
        span = max(float(np.ptp(values)), float(np.mean(values)) * 0.002)
        lo = float(values.min()) - span * 0.12
        span *= 1.24
        points = [
            (12 + i * 294 / max(1, len(values) - 1),
             price_bot - (v - lo) / span * (price_bot - price_top - 8))
            for i, v in enumerate(values)
        ]
        if len(points) > 1:
            for a, b in zip(points, points[1:]):
                d.line(
                    (*a, *b),
                    fill=(0, 101, 183) if b[1] <= a[1] else (197, 37, 78),
                    width=3,
                )
        for x, y in points:
            d.rectangle((x - 1, y - 1, x + 1, y + 1), fill=(27, 39, 81))

    # Price position indicator: teach fly to buy at lows, sell at highs
    if len(values) > 10:
        recent = values[-50:] if len(values) >= 50 else values
        r_high = float(np.max(recent))
        r_low = float(np.min(recent))
        r_range = r_high - r_low or 1.0
        current = float(values[-1])
        # Price percentile: 0 = lowest, 100 = highest
        percentile = (current - r_low) / r_range * 100
        percentile = max(0, min(100, percentile))

        # Draw support/resistance zones on price chart
        # Green zone (bottom 20%): buy area
        buy_zone_y = price_bot - (price_bot - price_top - 8) * 0.2
        d.rectangle((12, buy_zone_y, 308, price_bot - 4), fill=(34, 197, 94, 25))
        # Red zone (top 20%): sell area
        sell_zone_y = price_top + (price_bot - price_top - 8) * 0.2
        d.rectangle((12, price_top, 308, sell_zone_y), fill=(239, 68, 68, 25))

        # Mark local high and low points
        if len(values) >= 5:
            # Local high
            high_idx = int(np.argmax(recent))
            high_x = 12 + high_idx * 294 / max(1, len(recent) - 1)
            high_y = price_bot - (r_high - lo) / span * (price_bot - price_top - 8)
            d.text((high_x - 4, high_y - 12), "S", fill=(239, 68, 68))  # S = Sell zone
            # Local low
            low_idx = int(np.argmin(recent))
            low_x = 12 + low_idx * 294 / max(1, len(recent) - 1)
            low_y = price_bot - (r_low - lo) / span * (price_bot - price_top - 8)
            d.text((low_x - 4, low_y + 4), "B", fill=(34, 197, 94))  # B = Buy zone

        # Current price marker with percentile
        cur_y = price_bot - (current - lo) / span * (price_bot - price_top - 8)
        marker_color = (34, 197, 94) if percentile < 30 else (239, 68, 68) if percentile > 70 else (254, 211, 48)
        d.ellipse((304, cur_y - 4, 312, cur_y + 4), fill=marker_color)

        # Price percentile bar (right side of chart)
        bar_x, bar_y = 313, price_top
        bar_h = price_bot - price_top - 8
        d.rectangle((bar_x, bar_y, bar_x + 4, bar_y + bar_h), fill=(60, 70, 100))
        fill_h = int(bar_h * percentile / 100)
        d.rectangle((bar_x, bar_y + bar_h - fill_h, bar_x + 4, bar_y + bar_h), fill=marker_color)
        # Percentile text
        d.text((bar_x - 1, bar_y + bar_h + 2), f"{int(percentile)}", fill=marker_color)

    # MACD sub-chart: y=134..170 (36px tall)
    if macd is not None and len(macd.get("hist", [])):
        macd_top, macd_bot = 134, 170
        d.rectangle((0, macd_top - 2, 319, macd_top - 1), fill=(150, 160, 180))
        hist = np.asarray(macd["hist"][-100:], dtype=float)
        valid = hist[~np.isnan(hist)]
        if len(valid):
            hmax = max(abs(valid.max()), abs(valid.min()), 1e-9)
            mid = (macd_top + macd_bot) // 2
            bar_w = max(1, 294 // max(1, len(hist) - 1) - 1)
            for i, h in enumerate(hist):
                if np.isnan(h):
                    continue
                x = 12 + i * 294 / max(1, len(hist) - 1)
                if h >= 0:
                    y_top = mid - (h / hmax) * (mid - macd_top - 2)
                    d.rectangle((x - bar_w // 2, y_top, x + bar_w // 2, mid),
                                fill=(34, 139, 34))
                else:
                    y_bot = mid + (abs(h) / hmax) * (macd_bot - mid - 2)
                    d.rectangle((x - bar_w // 2, mid, x + bar_w // 2, y_bot),
                                fill=(197, 37, 78))
        dif = np.asarray(macd["dif"][-100:], dtype=float)
        dea = np.asarray(macd["dea"][-100:], dtype=float)
        all_vals = np.concatenate([dif[~np.isnan(dif)], dea[~np.isnan(dea)]])
        if len(all_vals):
            lo2, hi2 = all_vals.min(), all_vals.max()
            rng = max(hi2 - lo2, 1e-9)
            for arr, color in [(dif, (0, 101, 183)), (dea, (255, 140, 0))]:
                pts = []
                for i, v in enumerate(arr):
                    if np.isnan(v):
                        continue
                    x = 12 + i * 294 / max(1, len(arr) - 1)
                    y = macd_bot - 2 - (v - lo2) / rng * (macd_bot - macd_top - 4)
                    pts.append((x, y))
                if len(pts) > 1:
                    for a, b in zip(pts, pts[1:]):
                        d.line((*a, *b), fill=color, width=2)

    # Bid/Ask text
    d.text((9, 172), f"BID {bid}  ASK {ask}"[:50], fill=(28, 46, 82))
    return np.asarray(im, dtype=np.uint8)
