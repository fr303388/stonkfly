"""纏論無腦交易模組 - 跟著5分K線買賣標記自動交易，使用獨立虛擬帳戶
優化版：只交易確認分型、趨勢過濾、不賠錢割肉、拉長冷卻
"""

import json
import time
from pathlib import Path
from decimal import Decimal as D


class ChanNoBrainTrader:
    """基於纏論買賣信號的無腦交易器，使用獨立帳戶不影響果蠅交易"""

    def __init__(self, state_path: Path, initial_cash: float = 100.0):
        self.state_path = Path(state_path)
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.position = 0.0
        self.avg_entry = 0.0
        self.trades = []
        self.last_signal_time = 0
        self.cooldown_seconds = 300  # 5分鐘冷卻（5分K線）
        self.last_buy_signal_index = -1
        self.last_sell_signal_index = -1
        self.tick_count = 0
        self.startup_protection_ticks = 5
        self.stop_loss_pct = 0.05  # 5%止損
        self.stop_loss_price = 0.0
        self.take_profit_pct = 0.03  # 3%止盈
        self.take_profit_price = 0.0
        self.load()

    def load(self):
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                self.cash = data.get("cash", self.initial_cash)
                self.position = data.get("position", 0.0)
                self.avg_entry = data.get("avg_entry", 0.0)
                self.trades = data.get("trades", [])
                self.last_signal_time = data.get("last_signal_time", 0)
                self.last_buy_signal_index = data.get("last_buy_signal_index", -1)
                self.last_sell_signal_index = data.get("last_sell_signal_index", -1)
                self.tick_count = data.get("tick_count", 0)
                self.stop_loss_price = data.get("stop_loss_price", 0.0)
                self.take_profit_price = data.get("take_profit_price", 0.0)
            except Exception:
                pass

    def save(self):
        data = {
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "position": self.position,
            "avg_entry": self.avg_entry,
            "trades": self.trades[-100:],
            "last_signal_time": self.last_signal_time,
            "last_buy_signal_index": self.last_buy_signal_index,
            "last_sell_signal_index": self.last_sell_signal_index,
            "tick_count": self.tick_count,
            "total_trades": len(self.trades),
            "realized_pnl": self._calc_realized_pnl(),
            "unrealized_pnl": self._calc_unrealized_pnl(),
            "equity": self.cash + self.position * (self.avg_entry if self.avg_entry > 0 else 0),
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
        }
        self.state_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _calc_realized_pnl(self):
        total = 0.0
        for t in self.trades:
            if t.get("side") == "SELL":
                total += float(t.get("pnl", 0))
        return total

    def _calc_unrealized_pnl(self):
        return 0.0

    def _calc_rsi(self, klines, period=14):
        if len(klines) < period + 1:
            return 50.0
        closes = [float(k.get("c", 0)) for k in klines[-(period + 1):]]
        gains, losses = [], []
        for i in range(1, len(closes)):
            ch = closes[i] - closes[i - 1]
            gains.append(ch if ch > 0 else 0)
            losses.append(abs(ch) if ch < 0 else 0)
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        return 100 - 100 / (1 + avg_gain / avg_loss)

    def _calc_trend(self, klines):
        if len(klines) < 20:
            return "neutral"
        closes = [float(k.get("c", 0)) for k in klines]
        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20
        if ma5 > ma20 * 1.002:
            return "uptrend"
        elif ma5 < ma20 * 0.998:
            return "downtrend"
        return "neutral"

    def _calc_percentile(self, klines):
        if len(klines) < 20:
            return 50.0
        closes = [float(k.get("c", 0)) for k in klines[-100:]]
        cur = closes[-1]
        rng = max(closes) - min(closes) or 1.0
        return max(0, min(100, (cur - min(closes)) / rng * 100))

    def process_signal(self, czsc_data: dict, current_price: float):
        now = time.time()
        self.tick_count += 1
        self.save()

        if self.tick_count <= self.startup_protection_ticks:
            return {"action": "STARTUP_PROTECT", "reason": f"觀察中({self.tick_count}/{self.startup_protection_ticks})"}

        klines = czsc_data.get("klines", [])
        rsi = self._calc_rsi(klines)
        trend = self._calc_trend(klines)
        percentile = self._calc_percentile(klines)

        # ===== 止損/止盈優先 =====
        if self.position > 0:
            if self.stop_loss_price > 0 and current_price <= self.stop_loss_price:
                self._sell(current_price, "止損", rsi, trend, -1)
                return {"action": "STOP_LOSS", "price": current_price, "signal": "止損賣出"}
            if self.take_profit_price > 0 and current_price >= self.take_profit_price:
                self._sell(current_price, "止盈", rsi, trend, -1)
                return {"action": "TAKE_PROFIT", "price": current_price, "signal": "止盈賣出"}

        # 冷卻
        if now - self.last_signal_time < self.cooldown_seconds:
            remain = int(self.cooldown_seconds - (now - self.last_signal_time))
            return {"action": "COOLDOWN", "reason": f"冷卻{remain}s"}

        fractals = czsc_data.get("fractals", [])
        if not fractals:
            if self.position > 0:
                unrealized = (current_price - self.avg_entry) * self.position
                return {"action": "HOLD", "reason": f"持有中 RSI{rsi:.0f} 未實現{unrealized:+.2f}"}
            return {"action": "WAIT", "reason": f"等待底分型 RSI{rsi:.0f} {trend}"}

        latest_fractal = fractals[-1]
        ftype = latest_fractal.get("type", "")
        findex = latest_fractal.get("index", -1)
        fconfirmed = latest_fractal.get("confirmed", True)  # 是否確認

        # ===== 買入：只在確認底分型 + RSI<40 + 不是下跌趨勢 =====
        if self.position <= 0 and ftype == "bottom" and fconfirmed:
            if findex == self.last_buy_signal_index:
                return {"action": "WAIT", "reason": "已處理此底分型"}
            # RSI過濾：只在超賣區域買
            if rsi > 45:
                return {"action": "WAIT", "reason": f"RSI{rsi:.0f}>45 等超賣"}
            # 下跌趨勢不接刀
            if trend == "downtrend" and percentile > 30:
                return {"action": "WAIT", "reason": f"下跌趨勢{trend} 百分位{percentile:.0f}%"}

            buy_amount = min(self.cash * 0.95, self.cash)
            if buy_amount > 10 and current_price > 0:
                qty = buy_amount / current_price
                self.position = qty
                self.avg_entry = current_price
                self.cash -= buy_amount
                self.last_signal_time = now
                self.last_buy_signal_index = findex
                self.stop_loss_price = current_price * (1 - self.stop_loss_pct)
                self.take_profit_price = current_price * (1 + self.take_profit_pct)
                self.trades.append({
                    "time": now, "side": "BUY", "price": current_price,
                    "qty": qty, "amount": buy_amount, "signal": "確認底分型買入",
                    "signal_index": findex, "pnl": 0, "rsi": round(rsi, 1), "trend": trend,
                    "stop_loss": round(self.stop_loss_price, 2),
                    "take_profit": round(self.take_profit_price, 2),
                })
                self.save()
                return {"action": "BUY", "price": current_price, "qty": qty,
                        "signal": f"底分型買入 RSI{rsi:.0f} {trend}"}

        # ===== 賣出：只在確認頂分型 + 有賺錢 =====
        if self.position > 0 and ftype == "top" and fconfirmed:
            if findex == self.last_sell_signal_index:
                return {"action": "HOLD", "reason": "已處理此頂分型"}
            unrealized = (current_price - self.avg_entry) * self.position
            # 虧損時不因頂分型賣出（交給止損）
            if unrealized < 0:
                return {"action": "HOLD", "reason": f"頂分型但虧損{unrealized:+.2f} 等反彈/止損"}

            self._sell(current_price, "頂分型賣出", rsi, trend, findex)
            return {"action": "SELL", "price": current_price, "pnl": unrealized,
                    "signal": f"頂分型賣出 RSI{rsi:.0f} 盈虧{unrealized:+.2f}"}

        if self.position > 0:
            unrealized = (current_price - self.avg_entry) * self.position
            return {"action": "HOLD", "reason": f"持有 RSI{rsi:.0f} 未實現{unrealized:+.2f}"}
        return {"action": "WAIT", "reason": f"等待底分型 RSI{rsi:.0f} {trend}"}

    def _sell(self, price, signal, rsi, trend, findex):
        sell_qty = self.position
        sell_amount = sell_qty * price
        pnl = (price - self.avg_entry) * sell_qty
        self.cash += sell_amount
        self.position = 0
        self.avg_entry = 0.0
        self.stop_loss_price = 0.0
        self.take_profit_price = 0.0
        self.last_signal_time = time.time()
        self.last_sell_signal_index = findex
        self.trades.append({
            "time": time.time(), "side": "SELL", "price": price,
            "qty": sell_qty, "amount": sell_amount, "signal": signal,
            "signal_index": findex, "pnl": pnl, "rsi": round(rsi, 1), "trend": trend,
        })
        self.save()

    def get_status(self, current_price: float = 0):
        unrealized = (current_price - self.avg_entry) * self.position if self.position > 0 and current_price > 0 else 0
        equity = self.cash + self.position * current_price if current_price > 0 else self.cash
        return {
            "cash": round(self.cash, 2),
            "position": round(self.position, 6),
            "avg_entry": round(self.avg_entry, 2),
            "current_price": round(current_price, 2),
            "unrealized_pnl": round(unrealized, 2),
            "realized_pnl": round(self._calc_realized_pnl(), 2),
            "equity": round(equity, 2),
            "total_trades": len(self.trades),
            "recent_trades": self.trades[-5:],
            "has_position": self.position > 0,
            "stop_loss_price": round(self.stop_loss_price, 2),
            "take_profit_price": round(self.take_profit_price, 2),
        }
