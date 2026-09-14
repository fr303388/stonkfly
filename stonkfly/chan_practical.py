"""
果蠅纏論實戰學習模組
在理論學習基礎上，加入：
1. 真實K線圖型辨識（從市場數據學習）
2. 交易回顧與強化學習
3. 實戰信心評分（用於交易決策）
"""
import random
import time
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass
class PracticalSkill:
    """實戰技能"""
    name: str
    name_zh: str
    level: float = 0.0
    practice_count: int = 0
    success_count: int = 0

    @property
    def accuracy(self):
        if self.practice_count == 0:
            return 0.0
        return (self.success_count / self.practice_count) * 100

    def practice(self, success: bool, difficulty: float = 1.0):
        self.practice_count += 1
        if success:
            self.success_count += 1
            gain = max(0.3, 3.0 * difficulty * (1 - self.level / 100))
            self.level = min(100, self.level + gain)
        else:
            self.level = max(0, self.level - 0.3)


class ChanPracticalLearner:
    """纏論實戰學習器"""

    PRACTICAL_SKILLS = [
        ("bottom_fractal", "底分型買入", "在真實K線中辨識底分型並預測反彈"),
        ("top_fractal", "頂分型賣出", "在真實K線中辨識頂分型並預測回落"),
        ("pivot_breakout", "中樞突破", "辨識中樞突破方向並跟進"),
        ("divergence_reversal", "背離反轉", "價格與動能背離時的反轉點"),
        ("trend_follow", "趨勢跟隨", "順著筆的方向持倉"),
        ("pullback_buy", "回踩買入", "上漲趨勢中回踩中樞上沿買入"),
    ]

    def __init__(self, knowledge_path: Optional[Path] = None, practical_path: Optional[Path] = None):
        self.knowledge_path = knowledge_path
        self.practical_path = practical_path
        self.theory_levels: Dict[str, float] = {}
        self.skills: Dict[str, PracticalSkill] = {}
        for key, name, desc in self.PRACTICAL_SKILLS:
            self.skills[key] = PracticalSkill(name=key, name_zh=name)
        self.trade_reviews: List[Dict] = []
        self.total_practice_time = 0.0
        self.current_skill: Optional[str] = None
        self._study_start = 0.0
        self._last_step = 0.0
        self._load()

    def _load(self):
        if self.knowledge_path and self.knowledge_path.exists():
            try:
                data = json.loads(self.knowledge_path.read_text(encoding="utf-8"))
                for key, c in data.get("concepts", {}).items():
                    self.theory_levels[key] = c.get("level", 0)
            except Exception:
                pass
        if self.practical_path and self.practical_path.exists():
            try:
                data = json.loads(self.practical_path.read_text(encoding="utf-8"))
                for key, s in data.get("skills", {}).items():
                    if key in self.skills:
                        self.skills[key].level = s.get("level", 0)
                        self.skills[key].practice_count = s.get("practice_count", 0)
                        self.skills[key].success_count = s.get("success_count", 0)
                self.total_practice_time = data.get("total_practice_time", 0)
                self.trade_reviews = data.get("trade_reviews", [])[-50:]
            except Exception:
                pass

    def save(self):
        if self.practical_path:
            try:
                self.practical_path.parent.mkdir(parents=True, exist_ok=True)
                data = {
                    "skills": {k: asdict(v) for k, v in self.skills.items()},
                    "total_practice_time": self.total_practice_time,
                    "trade_reviews": self.trade_reviews[-50:],
                    "saved_at": time.time(),
                }
                self.practical_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

    def start_practice(self) -> str:
        """開始實戰練習，優先練最弱的技能"""
        sorted_skills = sorted(self.skills.values(), key=lambda s: s.level)
        skill = sorted_skills[0]
        self.current_skill = skill.name
        self._study_start = time.time()
        self._last_step = time.time()
        return skill.name_zh

    def practice_with_market(self, market_data: Dict) -> Dict:
        """
        用真實市場數據練習
        market_data: 包含 prices, rsi, czsc 分析
        """
        if not self.current_skill:
            return {"status": "idle"}

        skill = self.skills[self.current_skill]
        # 根據市場數據和理論知識計算判斷成功率
        theory_avg = sum(self.theory_levels.values()) / max(1, len(self.theory_levels))
        base_success = 0.25 + (skill.level / 100) * 0.4 + (theory_avg / 100) * 0.25
        # 市場數據品質影響
        if market_data.get("rsi"):
            rsi = market_data["rsi"]
            if skill.name in ("bottom_fractal", "pullback_buy") and rsi < 40:
                base_success += 0.1
            elif skill.name in ("top_fractal",) and rsi > 60:
                base_success += 0.1
        success = random.random() < min(0.9, base_success)
        skill.practice(success, difficulty=0.8)

        elapsed = time.time() - self._last_step
        self.total_practice_time += elapsed
        self._last_step = time.time()

        result = {
            "status": "practicing",
            "skill": skill.name_zh,
            "level": skill.level,
            "accuracy": skill.accuracy,
            "success": success,
        }

        # 每6次更換技能
        if skill.practice_count % 6 == 0:
            self.current_skill = None
        self.save()
        return result

    def stop_practice(self):
        self.current_skill = None

    def review_trade(self, side: str, entry_price: float, exit_price: float,
                     reason: str, rsi: float, czsc: Dict) -> Dict:
        """回顧一筆交易，從中學習"""
        if side == "BUY":
            # 買入後是否上漲？用後續價格判斷
            success = exit_price > entry_price  # 占位，實際用未來價格
        else:
            success = exit_price < entry_price

        pnl_pct = (exit_price - entry_price) / entry_price * 100 if side == "BUY" else (entry_price - exit_price) / entry_price * 100
        review = {
            "side": side,
            "entry": entry_price,
            "exit": exit_price,
            "pnl_pct": round(pnl_pct, 3),
            "reason": reason,
            "rsi": rsi,
            "success": pnl_pct > 0,
            "time": time.time(),
        }
        self.trade_reviews.append(review)
        if len(self.trade_reviews) > 50:
            self.trade_reviews = self.trade_reviews[-50:]

        # 根據交易結果強化對應技能
        if side == "BUY" and pnl_pct > 0:
            for sname in ("bottom_fractal", "pullback_buy", "trend_follow"):
                if sname in self.skills:
                    self.skills[sname].practice(True, 0.5)
        elif side == "SELL" and pnl_pct > 0:
            for sname in ("top_fractal", "divergence_reversal"):
                if sname in self.skills:
                    self.skills[sname].practice(True, 0.5)
        elif pnl_pct < 0:
            # 虧損交易，對應技能降級
            if side == "BUY":
                self.skills.get("bottom_fractal", PracticalSkill("x","x")).practice(False, 0.3)
            else:
                self.skills.get("top_fractal", PracticalSkill("x","x")).practice(False, 0.3)

        self.save()
        return review

    def get_trading_signal(self, rsi: float, czsc: Dict, has_position: bool,
                            price_percentile: float) -> Dict:
        """
        基於實戰技能產生交易訊號
        回傳: {"signal": "BUY"/"SELL"/"HOLD", "confidence": 0-100, "reason": str}
        """
        buy_score = 0.0
        sell_score = 0.0
        reasons = []

        czsc_dir = czsc.get("last_bi_direction", "unknown")
        czsc_bull = czsc.get("bullish_score", 50)
        czsc_bear = czsc.get("bearish_score", 50)
        in_zs = czsc.get("in_zs", False)

        # 底分型買入技能
        bf = self.skills.get("bottom_fractal")
        if bf and bf.level > 30 and rsi < 35 and not has_position:
            buy_score += bf.level * 0.3
            reasons.append(f"底分型辨識{bf.level:.0f}%")

        # 回踩買入
        pb = self.skills.get("pullback_buy")
        if pb and pb.level > 30 and czsc_dir == "up" and price_percentile < 40 and not has_position:
            buy_score += pb.level * 0.25
            reasons.append(f"回踩買入{pb.level:.0f}%")

        # 中樞突破
        pbo = self.skills.get("pivot_breakout")
        if pbo and pbo.level > 40 and not in_zs and czsc_bull > czsc_bear + 10:
            buy_score += pbo.level * 0.2
            reasons.append(f"中樞突破{pbo.level:.0f}%")

        # 頂分型賣出
        tf = self.skills.get("top_fractal")
        if tf and tf.level > 30 and rsi > 65 and has_position:
            sell_score += tf.level * 0.3
            reasons.append(f"頂分型辨識{tf.level:.0f}%")

        # 背離反轉
        dv = self.skills.get("divergence_reversal")
        if dv and dv.level > 40 and has_position and price_percentile > 85:
            sell_score += dv.level * 0.25
            reasons.append(f"背離反轉{dv.level:.0f}%")

        # 趨勢跟隨（抑制反向交易）
        tfo = self.skills.get("trend_follow")
        if tfo and tfo.level > 50:
            if czsc_dir == "up" and has_position:
                sell_score *= 0.5  # 上漲趨勢中不輕易賣
                reasons.append(f"趨勢跟隨抑制賣出")
            elif czsc_dir == "down" and not has_position:
                buy_score *= 0.5  # 下跌趨勢中不輕易買

        threshold = 25.0
        if buy_score > threshold and buy_score > sell_score:
            return {"signal": "BUY", "confidence": min(100, buy_score),
                    "reason": "實戰訊號: " + " + ".join(reasons)}
        elif sell_score > threshold and sell_score > buy_score:
            return {"signal": "SELL", "confidence": min(100, sell_score),
                    "reason": "實戰訊號: " + " + ".join(reasons)}
        return {"signal": "HOLD", "confidence": max(buy_score, sell_score),
                "reason": "實戰觀察: " + (" + ".join(reasons) if reasons else "無明確訊號")}

    def get_summary(self) -> Dict:
        levels = [s.level for s in self.skills.values()]
        avg = sum(levels) / len(levels) if levels else 0
        wins = sum(1 for r in self.trade_reviews if r.get("success"))
        total = len(self.trade_reviews)
        return {
            "practical_avg": avg,
            "skills": [{"name": s.name_zh, "level": s.level,
                        "accuracy": s.accuracy, "count": s.practice_count}
                       for s in self.skills.values()],
            "trade_review_count": total,
            "trade_win_rate": (wins / total * 100) if total > 0 else 0,
            "total_practice_time": self.total_practice_time,
            "current_skill": self.skills[self.current_skill].name_zh if self.current_skill else None,
        }
