"""
純纏論自動交易策略（優化版）
使用15分K線的纏論結構 + RSI + 止損做買賣決策（止盈由纏論和果蠅決定）
更積極交易，避免長時間持有不動
"""
import time
import json
import urllib.request
from pathlib import Path


class ChanAutoStrategy:
    """純纏論指標自動交易（15分K線）- 優化版"""

    def __init__(self, symbol="BTCUSDT", cooldown_seconds=60):
        self.symbol = symbol
        self.cooldown_seconds = cooldown_seconds
        self.last_trade_time = 0
        self.last_signal = None
        self.signal_history = []
        self.entry_price = None  # 記錄買入價，用於止盈止損
        self.position_side = None  # "LONG" or None

    def fetch_klines(self, interval="15m", limit=200):
        """從幣安抓取K線"""
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

    def calc_rsi(self, klines, period=14):
        """計算RSI"""
        if len(klines) < period + 1:
            return 50
        closes = [k["c"] for k in klines]
        gains = []
        losses = []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i-1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def analyze(self, interval="15m"):
        """執行纏論分析，回傳交易訊號"""
        from .czsc_chart import extract_czsc_structures

        klines = self.fetch_klines(interval=interval)
        if len(klines) < 30:
            return {"signal": "HOLD", "reason": "K線數據不足", "czsc": None}

        czsc = extract_czsc_structures(klines, freq=interval)
        current_price = klines[-1]["c"]
        rsi = self.calc_rsi(klines)

        # 冷卻檢查
        if time.time() - self.last_trade_time < self.cooldown_seconds:
            remain = int(self.cooldown_seconds - (time.time() - self.last_trade_time))
            return {"signal": "HOLD", "reason": f"冷卻中({remain}s)", "czsc": czsc, "rsi": rsi}

        signal = "HOLD"
        reason = ""
        confidence = 0

        buy_signals = czsc.get("buy_signals", [])
        sell_signals = czsc.get("sell_signals", [])
        divergence = czsc.get("divergence")
        trend = czsc.get("trend", "unknown")
        in_pivot = czsc.get("in_pivot", False)
        last_stroke = czsc.get("last_stroke_direction", "unknown")
        bull_score = czsc.get("bullish_score", 50)
        bear_score = czsc.get("bearish_score", 50)

        # === 止損（優先級最高，止盈已取消，由纏論和果蠅決定賣出）===
        if self.position_side == "LONG" and self.entry_price:
            pnl_pct = (current_price - self.entry_price) / self.entry_price * 100
            if pnl_pct <= -3.0:
                return {
                    "signal": "SELL", "reason": f"止損 {pnl_pct:.2f}% (買入${self.entry_price:.2f})",
                    "confidence": 90, "price": current_price, "rsi": rsi,
                    "czsc": czsc, "trend": trend, "pnl_pct": pnl_pct,
                }

        # === 買入訊號（多條件確認）===
        buy_reasons = []

        # 1. 纏論買點
        for sig in buy_signals:
            if sig["type"] in ("一買", "二買", "三買"):
                buy_reasons.append(f"{sig['type']}")
                confidence += 30

        # 2. 底背馳
        if divergence == "底背馳":
            buy_reasons.append("底背馳")
            confidence += 25

        # 3. RSI超賣
        if rsi < 35:
            buy_reasons.append(f"RSI{rsi:.0f}超賣")
            confidence += 25

        # 4. 多頭分數明顯領先
        if bull_score >= bear_score + 15:
            buy_reasons.append(f"多頭{bull_score}/{bear_score}")
            confidence += 20

        # 5. 向下筆結束（可能反彈）
        if last_stroke == "down" and rsi < 45:
            buy_reasons.append("向下筆末段")
            confidence += 10

        # === 賣出訊號 ===
        sell_reasons = []

        # 1. 纏論賣點
        for sig in sell_signals:
            if sig["type"] in ("一賣", "二賣", "三賣"):
                sell_reasons.append(f"{sig['type']}")
                confidence += 30

        # 2. 頂背馳
        if divergence == "頂背馳":
            sell_reasons.append("頂背馳")
            confidence += 25

        # 3. RSI超買
        if rsi > 65:
            sell_reasons.append(f"RSI{rsi:.0f}超買")
            confidence += 25

        # 4. 空頭分數明顯領先
        if bear_score >= bull_score + 15:
            sell_reasons.append(f"空頭{bear_score}/{bull_score}")
            confidence += 20

        # 5. 向上筆結束（可能回落）
        if last_stroke == "up" and rsi > 55:
            sell_reasons.append("向上筆末段")
            confidence += 10

        # === 最終決策 ===
        if buy_reasons and confidence >= 40 and self.position_side is None:
            signal = "BUY"
            reason = " + ".join(buy_reasons)
        elif sell_reasons and confidence >= 40 and self.position_side == "LONG":
            signal = "SELL"
            reason = " + ".join(sell_reasons)
        elif buy_reasons and sell_reasons:
            # 多空衝突，看分數
            if bull_score > bear_score + 10 and self.position_side is None:
                signal = "BUY"
                reason = "多頭為主：" + " + ".join(buy_reasons)
            elif bear_score > bull_score + 10 and self.position_side == "LONG":
                signal = "SELL"
                reason = "空頭為主：" + " + ".join(sell_reasons)
            else:
                signal = "HOLD"
                reason = f"多空交戰 B{bull_score}/S{bear_score}"
        else:
            signal = "HOLD"
            if self.position_side == "LONG" and self.entry_price:
                pnl = (current_price - self.entry_price) / self.entry_price * 100
                reason = f"持有中 盈虧{pnl:+.2f}% RSI{rsi:.0f}"
            else:
                reason = f"觀望 RSI{rsi:.0f} 多空{bull_score}/{bear_score}"

        result = {
            "signal": signal,
            "reason": reason,
            "confidence": min(100, confidence),
            "price": current_price,
            "rsi": rsi,
            "trend": trend,
            "divergence": divergence,
            "in_pivot": in_pivot,
            "last_stroke": last_stroke,
            "czsc_signal": czsc.get("signal", ""),
            "bull_score": bull_score,
            "bear_score": bear_score,
            "fractals": len(czsc.get("fractals", [])),
            "strokes": len(czsc.get("strokes", [])),
            "pivots": len(czsc.get("pivots", [])),
            "buy_signals": [s["type"] for s in buy_signals],
            "sell_signals": [s["type"] for s in sell_signals],
            "position": self.position_side,
            "entry_price": self.entry_price,
        }

        # 記錄訊號歷史
        self.signal_history.append({
            "time": time.time(), "signal": signal, "reason": reason,
            "price": current_price, "rsi": rsi,
        })
        if len(self.signal_history) > 100:
            self.signal_history = self.signal_history[-100:]

        return result

    def mark_traded(self):
        """標記已交易，進入冷卻"""
        self.last_trade_time = time.time()

    def update_position(self, side, price=None):
        """由cli.py在成交後回報持倉狀態"""
        self.position_side = side
        if side == "LONG" and price:
            self.entry_price = price
        elif side is None:
            self.entry_price = None
