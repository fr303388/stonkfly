"""Position-sizing strategies that layer on top of neural BUY/SELL/HOLD decisions.

The fly brain decides direction; these strategies decide HOW MUCH to trade.
Strategy state (multiplier, streak) is encoded into the visual input so the
fly can learn to associate position-sizing context with outcomes.

Strategies:
  none          - fixed base size (default)
  martingale    - double after loss, reset to base after win
  anti_martingale - double after win, reset after loss
  kelly         - fraction of bankroll based on win rate and payoff
"""

import math
from dataclasses import dataclass, field


@dataclass
class StrategyState:
    name: str = "none"
    base_budget: float = 10.0  # USD base order size
    multiplier: float = 1.0
    streak: int = 0  # positive = win streak, negative = loss streak
    wins: int = 0
    losses: int = 0
    max_multiplier: float = 8.0  # cap to prevent ruin
    drawdown_threshold: float = 0.06  # martingale: add position after -6% drawdown
    history: list = field(default_factory=list)  # recent P&L deltas

    def reset(self):
        self.multiplier = 1.0
        self.streak = 0

    def record_trade(self, pnl_delta: float):
        """Record a completed trade outcome and update strategy state."""
        won = pnl_delta > 0
        if won:
            self.wins += 1
            self.streak = max(1, self.streak + 1) if self.streak >= 0 else 1
        else:
            self.losses += 1
            self.streak = min(-1, self.streak - 1) if self.streak <= 0 else -1

        self.history.append(pnl_delta)
        if len(self.history) > 50:
            self.history.pop(0)

        if self.name == "martingale":
            if won:
                self.multiplier = 1.0
            else:
                self.multiplier = min(self.multiplier * 2, self.max_multiplier)
        elif self.name == "anti_martingale":
            if won:
                self.multiplier = min(self.multiplier * 2, self.max_multiplier)
            else:
                self.multiplier = 1.0
        elif self.name == "kelly":
            self._update_kelly()
        # none: multiplier stays 1.0

    def _update_kelly(self):
        """Kelly fraction: f* = (bp - q) / b where b=payoff, p=win rate, q=loss rate."""
        total = self.wins + self.losses
        if total < 5:
            self.multiplier = 0.5  # conservative until enough data
            return
        p = self.wins / total
        q = 1.0 - p
        # Estimate payoff ratio from history
        wins = [x for x in self.history if x > 0]
        losses = [abs(x) for x in self.history if x < 0]
        avg_win = sum(wins) / len(wins) if wins else 1.0
        avg_loss = sum(losses) / len(losses) if losses else 1.0
        b = avg_win / max(avg_loss, 0.001)
        kelly = (b * p - q) / b if b > 0 else 0.0
        # Half-Kelly for safety, scaled to base budget
        self.multiplier = max(0.1, min(kelly * 0.5, self.max_multiplier))

    def update_from_position(self, unrealized_pnl_pct: float):
        """Update multiplier based on current position drawdown (for dip-buying martingale).
        
        unrealized_pnl_pct: positive = profit, negative = loss
        Martingale: increase position size at each -6% drawdown tier.
        """
        if self.name != "martingale":
            return
        if unrealized_pnl_pct >= 0:
            self.multiplier = 1.0  # profitable or flat: reset
            return
        # Each 6% drawdown tier increases multiplier
        loss = abs(unrealized_pnl_pct)
        tier = int(loss / self.drawdown_threshold)
        self.multiplier = min(2.0 ** tier, self.max_multiplier)

    def budget(self, cash: float) -> float:
        """Return the order budget in USD for this tick."""
        if self.name == "none":
            return self.base_budget
        return min(self.base_budget * self.multiplier, cash * 0.95)

    def to_dict(self):
        return {
            "name": self.name,
            "multiplier": round(self.multiplier, 4),
            "streak": self.streak,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.wins / max(1, self.wins + self.losses), 4),
            "budget_usd": round(self.base_budget * self.multiplier, 2),
            "drawdown_threshold": self.drawdown_threshold,
        }
