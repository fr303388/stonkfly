"""纏論無腦交易模組 - 跟著5分K線買賣標記自動交易，使用獨立虛擬帳戶
全開模式：RSI門檻50、分型預判、冷卻5分鐘、無趨勢過濾
"""

import json
import time
from pathlib import Path
from decimal import Decimal as D


class ChanNoBrainTrader:
    """基於纏論買賣信號的無腦交易器，使用獨立帳戶不影響果蠅交易"""

    def __init__(self, state_path: Path, initial_cash: float = 10000.0):
        self.state_path = Path(state_path)
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.position = 0.0  # BTC數量
        self.avg_entry = 0.0
        self.trades = []  # 交易記錄
        self.last_signal_time = 0  # 避免重複交易
        self.cooldown_seconds = 300  # 交易冷卻時間5分鐘（全開模式）
        self.last_buy_signal_index = -1  # 最後處理的買入信號index
        self.last_sell_signal_index = -1  # 最後處理的賣出信號index
        self.tick_count = 0  # 啟動後的tick計數
        self.startup_protection_ticks = 5  # 重開後前5個tick不交易，先觀察
        self.stop_loss_pct = 0.03  # 止損比例3%
        self.stop_loss_price = 0.0  # 止損價格
        self.take_profit_pct = 0.05  # 止盈比例5%
        self.take_profit_price = 0.0  # 止盈價格
        self.load()

    def load(self):
        """從文件載入狀態"""
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
        """保存狀態到文件"""
        data = {
            "cash": self.cash,
            "position": self.position,
            "avg_entry": self.avg_entry,
            "trades": self.trades[-100:],  # 只保留最近100筆
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
        """計算已實現盈虧"""
        total = 0.0
        for t in self.trades:
            if t.get("side") == "SELL":
                total += float(t.get("pnl", 0))
        return total

    def _calc_unrealized_pnl(self):
        """計算未實現盈虧（需要當前價格，這裡返回0，由調用者更新）"""
        return 0.0

    def _calc_rsi(self, klines, period=14):
        """計算RSI指標"""
        if len(klines) < period + 1:
            return 50.0  # 數據不足時返回中性值
        closes = [float(k.get("c", 0)) for k in klines[-(period + 1):]]
        gains = []
        losses = []
        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _calc_trend(self, klines):
        """判斷趨勢：使用短期均線和長期均線"""
        if len(klines) < 20:
            return "neutral"
        closes = [float(k.get("c", 0)) for k in klines]
        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20
        if ma5 > ma20 * 1.001:
            return "uptrend"
        elif ma5 < ma20 * 0.999:
            return "downtrend"
        else:
            return "neutral"

    def process_signal(self, czsc_data: dict, current_price: float):
        """
        處理纏論信號，執行無腦交易（優化版）

        Args:
            czsc_data: 纏論分析數據，包含fractals（分型）和klines（K線數據）
            current_price: 當前價格
        """
        now = time.time()
        self.tick_count += 1
        self.save()

        # 啟動保護：重開後前N個tick不交易，先觀察市場
        if self.tick_count <= self.startup_protection_ticks:
            return {"action": "STARTUP_PROTECT", "reason": f"啟動觀察中({self.tick_count}/{self.startup_protection_ticks})，先看後動"}

        # 計算RSI和趨勢
        klines = czsc_data.get("klines", [])
        rsi = self._calc_rsi(klines)
        trend = self._calc_trend(klines)

        # ===== 止損/止盈檢查（優先級最高）=====
        if self.position > 0:
            # 止損
            if self.stop_loss_price > 0 and current_price <= self.stop_loss_price:
                sell_qty = self.position
                sell_amount = sell_qty * current_price
                pnl = (current_price - self.avg_entry) * sell_qty
                self.cash += sell_amount
                self.position = 0
                self.avg_entry = 0.0
                self.stop_loss_price = 0.0
                self.take_profit_price = 0.0
                self.last_signal_time = now
                trade = {
                    "time": now,
                    "side": "SELL",
                    "price": current_price,
                    "qty": sell_qty,
                    "amount": sell_amount,
                    "signal": "止損賣出",
                    "signal_index": -1,
                    "pnl": pnl,
                    "rsi": round(rsi, 1),
                    "trend": trend,
                }
                self.trades.append(trade)
                self.save()
                return {"action": "STOP_LOSS", "price": current_price, "pnl": pnl, "signal": "止損賣出"}

            # 止盈
            if self.take_profit_price > 0 and current_price >= self.take_profit_price:
                sell_qty = self.position
                sell_amount = sell_qty * current_price
                pnl = (current_price - self.avg_entry) * sell_qty
                self.cash += sell_amount
                self.position = 0
                self.avg_entry = 0.0
                self.stop_loss_price = 0.0
                self.take_profit_price = 0.0
                self.last_signal_time = now
                trade = {
                    "time": now,
                    "side": "SELL",
                    "price": current_price,
                    "qty": sell_qty,
                    "amount": sell_amount,
                    "signal": "止盈賣出",
                    "signal_index": -1,
                    "pnl": pnl,
                    "rsi": round(rsi, 1),
                    "trend": trend,
                }
                self.trades.append(trade)
                self.save()
                return {"action": "TAKE_PROFIT", "price": current_price, "pnl": pnl, "signal": "止盈賣出"}

        # 冷卻期檢查
        if now - self.last_signal_time < self.cooldown_seconds:
            return {"action": "COOLDOWN", "reason": f"冷卻中({int(self.cooldown_seconds - (now - self.last_signal_time))}s)"}

        fractals = czsc_data.get("fractals", [])

        # 只使用已確認的分型，不使用預測分型（減少假信號）
        if not fractals:
            if self.position > 0:
                unrealized = (current_price - self.avg_entry) * self.position
                return {"action": "HOLD", "reason": f"持有中，等待頂分型，RSI{rsi:.0f}，未實現{unrealized:+.2f}"}
            else:
                return {"action": "WAIT", "reason": f"等待底分型，RSI{rsi:.0f}，趨勢{trend}"}

        latest_fractal = fractals[-1]
        latest_type = latest_fractal.get("type", "")
        latest_index = latest_fractal.get("index", -1)

        # 全開模式：分型預判，允許未確認分型（第2根K線就進場）
        # 不再等待第3根K線確認，提前進場搶價格
        _fractal_confirmed = True
        if len(klines) > 0 and latest_index >= len(klines) - 1:
            _fractal_confirmed = False  # 標記為預判分型

        # 無持倉且最新是底分型 → 買入（加入RSI和趨勢過濾）
        if self.position <= 0 and latest_type == "bottom":
            # 避免重複處理同一個信號
            if latest_index == self.last_buy_signal_index:
                return {"action": "WAIT", "reason": "已處理過此底分型，等待下一個"}

            # RSI過濾：只在RSI較低時買入（超賣區）
            if rsi > 50:
                return {"action": "WAIT", "reason": f"底分型但RSI{rsi:.0f}偏高，不買入（全開模式門檻50）"}

            # 全開模式：不做趨勢過濾，下跌趨勢也可以買入（接飛刀模式）

            buy_amount = min(self.cash * 0.95, self.cash)  # 用95%現金買入
            if buy_amount > 10 and current_price > 0:
                qty = buy_amount / current_price
                self.position = qty
                self.avg_entry = current_price
                self.cash -= buy_amount
                self.last_signal_time = now
                self.last_buy_signal_index = latest_index
                # 設置止損和止盈
                self.stop_loss_price = current_price * (1 - self.stop_loss_pct)
                self.take_profit_price = current_price * (1 + self.take_profit_pct)
                trade = {
                    "time": now,
                    "side": "BUY",
                    "price": current_price,
                    "qty": qty,
                    "amount": buy_amount,
                    "signal": "底分型買入",
                    "signal_index": latest_index,
                    "pnl": 0,
                    "rsi": round(rsi, 1),
                    "trend": trend,
                    "stop_loss": round(self.stop_loss_price, 2),
                    "take_profit": round(self.take_profit_price, 2),
                }
                self.trades.append(trade)
                self.save()
                _predict_tag = " [預判]" if not _fractal_confirmed else ""
                return {"action": "BUY", "price": current_price, "qty": qty, "signal": f"底分型買入(RSI{rsi:.0f}){_predict_tag}", "stop_loss": self.stop_loss_price, "take_profit": self.take_profit_price}

        # 有持倉且最新是頂分型 → 賣出（加入RSI過濾）
        if self.position > 0 and latest_type == "top":
            # 避免重複處理同一個信號
            if latest_index == self.last_sell_signal_index:
                unrealized = (current_price - self.avg_entry) * self.position
                return {"action": "HOLD", "reason": f"已處理過此頂分型，等待下一個，未實現{unrealized:+.2f}"}

            # RSI過濾：只在RSI較高時賣出（超買區）
            if rsi < 50:
                unrealized = (current_price - self.avg_entry) * self.position
                return {"action": "HOLD", "reason": f"頂分型但RSI{rsi:.0f}偏低，不賣出（全開模式門檻50），未實現{unrealized:+.2f}"}

            sell_qty = self.position
            sell_amount = sell_qty * current_price
            pnl = (current_price - self.avg_entry) * sell_qty
            self.cash += sell_amount
            self.position = 0
            self.avg_entry = 0.0
            self.stop_loss_price = 0.0
            self.take_profit_price = 0.0
            self.last_signal_time = now
            self.last_sell_signal_index = latest_index
            trade = {
                "time": now,
                "side": "SELL",
                "price": current_price,
                "qty": sell_qty,
                "amount": sell_amount,
                "signal": "頂分型賣出",
                "signal_index": latest_index,
                "pnl": pnl,
                "rsi": round(rsi, 1),
                "trend": trend,
            }
            self.trades.append(trade)
            self.save()
            _predict_tag = " [預判]" if not _fractal_confirmed else ""
            return {"action": "SELL", "price": current_price, "pnl": pnl, "signal": f"頂分型賣出(RSI{rsi:.0f}){_predict_tag}"}

        # 最新分型與持倉狀態不匹配
        if self.position > 0:
            unrealized = (current_price - self.avg_entry) * self.position
            return {"action": "HOLD", "reason": f"持有中，最新是底分型，等待頂分型，RSI{rsi:.0f}，未實現{unrealized:+.2f}"}
        else:
            return {"action": "WAIT", "reason": f"最新是頂分型，等待底分型，RSI{rsi:.0f}，趨勢{trend}"}

    def get_status(self, current_price: float = 0):
        """獲取當前狀態"""
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
