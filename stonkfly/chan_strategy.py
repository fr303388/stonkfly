"""
純纏論自動交易策略（測試版）
使用15分K線的纏論結構做買賣決策
- 買入：一買、底背馳、突破中樞回踩
- 賣出：一賣、頂背馳、跌破中樞
"""
import time
import json
import urllib.request
from pathlib import Path


class ChanAutoStrategy:
    """純纏論指標自動交易（15分K線）"""

    def __init__(self, symbol="BTCUSDT", cooldown_seconds=300):
        self.symbol = symbol
        self.cooldown_seconds = cooldown_seconds
        self.last_trade_time = 0
        self.last_signal = None
        self.signal_history = []

    def fetch_klines(self, interval="15m", limit=200):
        """從幣安抓取15分K線"""
        url = f"https://api.binance.com/api/v3/klines?symbol={self.symbol}&interval={interval}&limit={limit}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
            klines = []
            for k in data:
                klines.append({
                    "t": k[0], "o": float(k[1]), "h": float(k[2]),
                    "l": float(k[3]), "c": float(k[4]), "v": float(k[5]),
                })
            return klines
        except Exception as e:
            print(f"[纏論策略] 抓K線失敗: {e}")
            return []

    def analyze(self, interval="15m"):
        """執行纏論分析，回傳交易訊號"""
        from .czsc_chart import extract_czsc_structures

        klines = self.fetch_klines(interval=interval)
        if len(klines) < 30:
            return {"signal": "HOLD", "reason": "K線數據不足", "czsc": None}

        czsc = extract_czsc_structures(klines, freq=interval)

        # 冷卻檢查
        if time.time() - self.last_trade_time < self.cooldown_seconds:
            return {"signal": "HOLD", "reason": f"冷卻中({int(self.cooldown_seconds - (time.time() - self.last_trade_time))}s)", "czsc": czsc}

        signal = "HOLD"
        reason = ""
        confidence = 0

        buy_signals = czsc.get("buy_signals", [])
        sell_signals = czsc.get("sell_signals", [])
        divergence = czsc.get("divergence")
        trend = czsc.get("trend", "unknown")
        in_pivot = czsc.get("in_pivot", False)
        last_stroke = czsc.get("last_stroke_direction", "unknown")
        current_price = klines[-1]["c"] if klines else 0

        # === 買入訊號 ===
        buy_reasons = []

        # 1. 一買：向下筆在中樞下沿結束 + 價格回升
        for sig in buy_signals:
            if sig["type"] == "一買":
                buy_reasons.append(f"一買@{sig['price']:.2f}")
                confidence += 40

        # 2. 底背馳：下降趨勢中動力衰減
        if divergence == "底背馳" and last_stroke == "down":
            buy_reasons.append("底背馳")
            confidence += 30

        # 3. 突破中樞後回踩不破
        if not in_pivot and trend == "上升" and last_stroke == "down":
            pivots = czsc.get("pivots", [])
            if pivots:
                last_zs = pivots[-1]
                if current_price > last_zs["high"] * 0.99:
                    buy_reasons.append("突破回踩")
                    confidence += 20

        # === 賣出訊號 ===
        sell_reasons = []

        # 1. 一賣：向上筆在中樞上沿結束 + 價格回落
        for sig in sell_signals:
            if sig["type"] == "一賣":
                sell_reasons.append(f"一賣@{sig['price']:.2f}")
                confidence += 40

        # 2. 頂背馳：上升趨勢中動力衰減
        if divergence == "頂背馳" and last_stroke == "up":
            sell_reasons.append("頂背馳")
            confidence += 30

        # 3. 跌破中樞
        if not in_pivot and trend == "下降" and last_stroke == "down":
            pivots = czsc.get("pivots", [])
            if pivots:
                last_zs = pivots[-1]
                if current_price < last_zs["low"] * 1.01:
                    sell_reasons.append("跌破中樞")
                    confidence += 20

        # === 最終決策 ===
        if buy_reasons and not sell_reasons and confidence >= 40:
            signal = "BUY"
            reason = " + ".join(buy_reasons)
        elif sell_reasons and not buy_reasons and confidence >= 40:
            signal = "SELL"
            reason = " + ".join(sell_reasons)
        elif buy_reasons and sell_reasons:
            # 多空訊號衝突，看趨勢
            if trend == "上升":
                signal = "BUY"
                reason = "多頭趨勢：" + " + ".join(buy_reasons)
            elif trend == "下降":
                signal = "SELL"
                reason = "空頭趨勢：" + " + ".join(sell_reasons)
            else:
                signal = "HOLD"
                reason = "多空訊號衝突，盤整觀望"
        else:
            signal = "HOLD"
            if divergence:
                reason = f"觀望（{divergence}）"
            elif in_pivot:
                reason = "觀望（中樞震盪）"
            else:
                reason = f"觀望（{trend}，筆{last_stroke}）"

        result = {
            "signal": signal,
            "reason": reason,
            "confidence": min(100, confidence),
            "price": current_price,
            "trend": trend,
            "divergence": divergence,
            "in_pivot": in_pivot,
            "last_stroke": last_stroke,
            "czsc_signal": czsc.get("signal", ""),
            "fractals": len(czsc.get("fractals", [])),
            "strokes": len(czsc.get("strokes", [])),
            "pivots": len(czsc.get("pivots", [])),
            "buy_signals": [s["type"] for s in buy_signals],
            "sell_signals": [s["type"] for s in sell_signals],
        }

        # 記錄訊號歷史
        self.signal_history.append({
            "time": time.time(),
            "signal": signal,
            "reason": reason,
            "price": current_price,
        })
        if len(self.signal_history) > 100:
            self.signal_history = self.signal_history[-100:]

        return result

    def mark_traded(self):
        """標記已交易，進入冷卻"""
        self.last_trade_time = time.time()
