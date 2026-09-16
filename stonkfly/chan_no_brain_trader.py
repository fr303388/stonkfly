"""纏論無腦交易模組 - 跟著15分K線買賣標記自動交易，使用獨立虛擬帳戶"""

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
        self.cooldown_seconds = 60  # 交易冷卻時間
        self.last_buy_signal_index = -1  # 最後處理的買入信號index
        self.last_sell_signal_index = -1  # 最後處理的賣出信號index
        self.tick_count = 0  # 啟動後的tick計數
        self.startup_protection_ticks = 10  # 重開後前10個tick不交易，先觀察
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

    def process_signal(self, czsc_data: dict, current_price: float):
        """
        處理纏論信號，執行無腦交易

        Args:
            czsc_data: 纏論分析數據，包含fractals（分型）和klines（K線數據，用於預測分型）
            current_price: 當前價格
        """
        now = time.time()
        self.tick_count += 1
        self.save()

        # 啟動保護：重開後前N個tick不交易，先觀察市場
        if self.tick_count <= self.startup_protection_ticks:
            return {"action": "STARTUP_PROTECT", "reason": f"啟動觀察中({self.tick_count}/{self.startup_protection_ticks})，先看後動"}

        # 冷卻期檢查
        if now - self.last_signal_time < self.cooldown_seconds:
            return {"action": "COOLDOWN", "reason": f"冷卻中({int(self.cooldown_seconds - (now - self.last_signal_time))}s)"}

        fractals = czsc_data.get("fractals", [])
        klines = czsc_data.get("klines", [])

        # 預測分型：檢查最後3根K線是否正在形成分型，提前進場
        predicted_type = None
        if len(klines) >= 3:
            k1 = klines[-3]
            k2 = klines[-2]
            k3 = klines[-1]
            # 預測底分型：k2低點 < k1低點 且 k3低點 > k2低點（當前K線還在形成中）
            if k2.get("l", 0) < k1.get("l", 0) and k3.get("l", 0) > k2.get("l", 0):
                predicted_type = "bottom"
            # 預測頂分型：k2高點 > k1高點 且 k3高點 < k2高點（當前K線還在形成中）
            elif k2.get("h", 0) > k1.get("h", 0) and k3.get("h", 0) < k2.get("h", 0):
                predicted_type = "top"

        # 優先使用預測分型，如果沒有則使用已確認的最新分型
        if predicted_type:
            latest_type = predicted_type
            latest_index = len(klines) - 2  # 預測分型的中心點是倒數第2根
        elif fractals:
            latest_fractal = fractals[-1]
            latest_type = latest_fractal.get("type", "")
            latest_index = latest_fractal.get("index", -1)
        else:
            return {"action": "WAIT", "reason": "無分型信號"}

        # 無持倉且最新是底分型 → 買入
        if self.position <= 0 and latest_type == "bottom":
            buy_amount = min(self.cash * 0.95, self.cash)  # 用95%現金買入
            if buy_amount > 10 and current_price > 0:
                qty = buy_amount / current_price
                self.position = qty
                self.avg_entry = current_price
                self.cash -= buy_amount
                self.last_signal_time = now
                self.last_buy_signal_index = latest_index
                trade = {
                    "time": now,
                    "side": "BUY",
                    "price": current_price,
                    "qty": qty,
                    "amount": buy_amount,
                    "signal": "底分型買入",
                    "signal_index": latest_index,
                    "pnl": 0,
                }
                self.trades.append(trade)
                self.save()
                return {"action": "BUY", "price": current_price, "qty": qty, "signal": "底分型買入"}

        # 有持倉且最新是頂分型 → 賣出
        if self.position > 0 and latest_type == "top":
            sell_qty = self.position
            sell_amount = sell_qty * current_price
            pnl = (current_price - self.avg_entry) * sell_qty
            self.cash += sell_amount
            self.position = 0
            self.avg_entry = 0.0
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
            }
            self.trades.append(trade)
            self.save()
            return {"action": "SELL", "price": current_price, "pnl": pnl, "signal": "頂分型賣出"}

        # 最新分型與持倉狀態不匹配（有持倉但出現底分型，或無持倉但出現頂分型）
        if self.position > 0:
            unrealized = (current_price - self.avg_entry) * self.position
            return {"action": "HOLD", "reason": f"持有中，最新是底分型，等待頂分型，未實現盈虧{unrealized:+.2f}"}
        else:
            return {"action": "WAIT", "reason": "最新是頂分型，等待底分型"}

        # 沒有信號或不滿足條件
        if self.position > 0:
            unrealized = (current_price - self.avg_entry) * self.position
            return {"action": "HOLD", "reason": f"持有中，等待賣出信號，未實現盈虧{unrealized:+.2f}"}
        else:
            return {"action": "WAIT", "reason": "等待買入信號"}

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
        }
