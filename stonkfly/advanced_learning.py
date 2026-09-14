"""
進階學習系統 - 果蠅交易大腦強化
整合：擴充知識庫、交易回顧、市場狀態偵測、多時間框共振
"""
import json
import time
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple
import math


# ============================================================
# 1. 擴充知識庫 - 多領域學習
# ============================================================
@dataclass
class KnowledgeConcept:
    name: str
    name_zh: str
    description: str
    level: float = 0.0
    study_count: int = 0
    correct_count: int = 0

    @property
    def accuracy(self) -> float:
        if self.study_count == 0:
            return 0.0
        return (self.correct_count / self.study_count) * 100

    def study(self, success: bool):
        self.study_count += 1
        if success:
            self.correct_count += 1
            gain = max(0.3, 3.0 * (1 - self.level / 100))
            self.level = min(100, self.level + gain)
        else:
            self.level = max(0, self.level - 0.3)


class KnowledgeBase:
    """多領域知識庫"""

    DOMAINS = {
        "chan": {
            "name_zh": "纏論",
            "concepts": [
                ("fractal", "分型", "辨識K線頂分型與底分型"),
                ("stroke", "筆", "連接相鄰分型的線段"),
                ("pivot", "中樞", "三筆重疊形成的震盪區間"),
                ("divergence", "背馳", "價格創新但動能未跟隨"),
                ("buy_point", "買點", "一買二買三買的辨識"),
                ("sell_point", "賣點", "一賣二賣三賣的辨識"),
            ]
        },
        "indicator": {
            "name_zh": "指標",
            "concepts": [
                ("rsi_divergence", "RSI背馳", "價格與RSI指標背離"),
                ("macd_cross", "MACD交叉", "快慢線交叉與零軸位置"),
                ("volume_price", "量價關係", "漲量縮/跌量增的解讀"),
                ("bollinger", "布林通道", "通道寬度與價格位置"),
            ]
        },
        "structure": {
            "name_zh": "結構",
            "concepts": [
                ("support", "支撐位", "歷史低點與密集成交區"),
                ("resistance", "壓力位", "歷史高點與套牢區"),
                ("trend_line", "趨勢線", "高低點連線的斜率"),
                ("gap", "缺口", "跳空缺口的類型與意義"),
            ]
        },
        "risk": {
            "name_zh": "風控",
            "concepts": [
                ("position_size", "倉位管理", "依勝率調控單筆倉位"),
                ("stop_loss", "停損紀律", "結構破位即停損"),
                ("take_profit", "停利策略", "移動停利與分批獲利"),
                ("drawdown", "回撤控制", "最大回撤與恢復時間"),
            ]
        },
        "psychology": {
            "name_zh": "心理",
            "concepts": [
                ("fomo", "FOMO控制", "避免追高殺低的情緒"),
                ("patience", "耐心等待", "不到訊號不動手"),
                ("conviction", "信心管理", "獲利加碼與虧損減碼"),
            ]
        }
    }

    def __init__(self, save_path: Optional[Path] = None):
        self.save_path = save_path
        self.concepts: Dict[str, KnowledgeConcept] = {}
        self.domain_progress: Dict[str, float] = {}
        self.total_study_time = 0.0
        self._init_concepts()
        self._load()

    def _init_concepts(self):
        for domain, info in self.DOMAINS.items():
            for key, name, desc in info["concepts"]:
                full_key = f"{domain}.{key}"
                self.concepts[full_key] = KnowledgeConcept(
                    name=full_key, name_zh=f"{info['name_zh']}·{name}", description=desc
                )

    def _load(self):
        if self.save_path and self.save_path.exists():
            try:
                data = json.loads(self.save_path.read_text(encoding="utf-8"))
                for key, cdata in data.get("concepts", {}).items():
                    if key in self.concepts:
                        c = self.concepts[key]
                        c.level = cdata.get("level", 0)
                        c.study_count = cdata.get("study_count", 0)
                        c.correct_count = cdata.get("correct_count", 0)
                self.total_study_time = data.get("total_study_time", 0)
            except Exception:
                pass

    def save(self):
        if self.save_path:
            try:
                self.save_path.parent.mkdir(parents=True, exist_ok=True)
                data = {
                    "concepts": {k: asdict(v) for k, v in self.concepts.items()},
                    "total_study_time": self.total_study_time,
                    "saved_at": time.time(),
                }
                self.save_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

    def get_weakest_concept(self) -> Optional[KnowledgeConcept]:
        if not self.concepts:
            return None
        return min(self.concepts.values(), key=lambda c: c.level)

    def study_step(self, neural_activity: float = 0.5) -> Dict:
        concept = self.get_weakest_concept()
        if not concept:
            return {"status": "no_concepts"}
        success = neural_activity > 0.4
        concept.study(success)
        self.total_study_time += 1.0
        self.save()
        return {
            "concept": concept.name_zh,
            "level": concept.level,
            "success": success,
            "accuracy": concept.accuracy,
        }

    def get_domain_progress(self) -> Dict[str, float]:
        progress = {}
        for domain, info in self.DOMAINS.items():
            domain_concepts = [self.concepts[f"{domain}.{k}"] for k, _, _ in info["concepts"] if f"{domain}.{k}" in self.concepts]
            if domain_concepts:
                progress[info["name_zh"]] = sum(c.level for c in domain_concepts) / len(domain_concepts)
        return progress

    def get_overall_level(self) -> float:
        if not self.concepts:
            return 0
        return sum(c.level for c in self.concepts.values()) / len(self.concepts)

    def get_knowledge_summary(self) -> Dict:
        return {
            "overall": self.get_overall_level(),
            "domains": self.get_domain_progress(),
            "total_concepts": len(self.concepts),
            "mastered": sum(1 for c in self.concepts.values() if c.level >= 80),
            "study_time_min": self.total_study_time / 60,
        }


# ============================================================
# 2. 交易回顧強化學習
# ============================================================
@dataclass
class TradeReview:
    trade_id: int
    side: str
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    hold_time: float
    reason: str
    regime: str
    rsi_at_entry: float
    lesson: str = ""
    strategy_tag: str = ""


class TradeReviewer:
    """從實際交易結果中學習"""

    def __init__(self, save_path: Optional[Path] = None):
        self.save_path = save_path
        self.reviews: List[TradeReview] = []
        self.strategy_stats: Dict[str, Dict] = {}  # {tag: {wins, losses, total_pnl, count}}
        self.regime_stats: Dict[str, Dict] = {}
        self.total_reviews = 0
        self._load()

    def _load(self):
        if self.save_path and self.save_path.exists():
            try:
                data = json.loads(self.save_path.read_text(encoding="utf-8"))
                self.strategy_stats = data.get("strategy_stats", {})
                self.regime_stats = data.get("regime_stats", {})
                self.total_reviews = data.get("total_reviews", 0)
                self.reviews = [TradeReview(**r) for r in data.get("reviews", [])[-100:]]
            except Exception:
                pass

    def save(self):
        if self.save_path:
            try:
                self.save_path.parent.mkdir(parents=True, exist_ok=True)
                data = {
                    "strategy_stats": self.strategy_stats,
                    "regime_stats": self.regime_stats,
                    "total_reviews": self.total_reviews,
                    "reviews": [asdict(r) for r in self.reviews[-50:]],
                    "saved_at": time.time(),
                }
                self.save_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

    def review_trade(self, review: TradeReview):
        """回顧一筆交易，更新策略統計"""
        self.reviews.append(review)
        self.total_reviews += 1

        # Strategy stats
        tag = review.strategy_tag or "default"
        if tag not in self.strategy_stats:
            self.strategy_stats[tag] = {"wins": 0, "losses": 0, "total_pnl": 0, "count": 0}
        stat = self.strategy_stats[tag]
        stat["count"] += 1
        stat["total_pnl"] += review.pnl
        if review.pnl > 0:
            stat["wins"] += 1
        else:
            stat["losses"] += 1

        # Regime stats
        regime = review.regime or "unknown"
        if regime not in self.regime_stats:
            self.regime_stats[regime] = {"wins": 0, "losses": 0, "total_pnl": 0, "count": 0}
        rstat = self.regime_stats[regime]
        rstat["count"] += 1
        rstat["total_pnl"] += review.pnl
        if review.pnl > 0:
            rstat["wins"] += 1
        else:
            rstat["losses"] += 1

        self.save()

    def get_strategy_win_rate(self, tag: str) -> float:
        stat = self.strategy_stats.get(tag, {})
        total = stat.get("wins", 0) + stat.get("losses", 0)
        if total == 0:
            return 50.0
        return stat.get("wins", 0) / total * 100

    def get_best_strategies(self, top_n: int = 3) -> List[Tuple[str, float]]:
        """返回勝率最高的策略"""
        scored = []
        for tag, stat in self.strategy_stats.items():
            total = stat.get("wins", 0) + stat.get("losses", 0)
            if total >= 3:
                wr = stat.get("wins", 0) / total * 100
                scored.append((tag, wr, stat.get("total_pnl", 0)))
        scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
        return [(tag, wr) for tag, wr, _ in scored[:top_n]]

    def get_worst_strategies(self, top_n: int = 3) -> List[Tuple[str, float]]:
        """返回勝率最低的策略（應該避免）"""
        scored = []
        for tag, stat in self.strategy_stats.items():
            total = stat.get("wins", 0) + stat.get("losses", 0)
            if total >= 3:
                wr = stat.get("wins", 0) / total * 100
                scored.append((tag, wr, stat.get("total_pnl", 0)))
        scored.sort(key=lambda x: (x[1], x[2]))
        return [(tag, wr) for tag, wr, _ in scored[:top_n]]

    def get_regime_performance(self) -> Dict[str, Dict]:
        return self.regime_stats

    def get_lessons(self) -> List[str]:
        """從歷史交易中提取教訓"""
        lessons = []
        if self.total_reviews < 5:
            return ["交易樣本不足，繼續累積經驗"]

        # Find best/worst strategies
        best = self.get_best_strategies(1)
        worst = self.get_worst_strategies(1)
        if best:
            lessons.append(f"勝率最高策略：{best[0][0]} ({best[0][1]:.0f}%)")
        if worst and worst[0][1] < 50:
            lessons.append(f"應避免策略：{worst[0][0]} ({worst[0][1]:.0f}%)")

        # Regime analysis
        for regime, stat in self.regime_stats.items():
            total = stat.get("wins", 0) + stat.get("losses", 0)
            if total >= 3:
                wr = stat.get("wins", 0) / total * 100
                if wr > 60:
                    lessons.append(f"{regime}市勝率{wr:.0f}%，適合積極操作")
                elif wr < 40:
                    lessons.append(f"{regime}市勝率{wr:.0f}%，應保守觀望")

        return lessons[:5]


# ============================================================
# 3. 市場狀態偵測
# ============================================================
class MarketRegimeDetector:
    """偵測市場狀態：趨勢/盤整/劇烈波動"""

    @staticmethod
    def detect(klines: List[Dict]) -> Dict:
        if len(klines) < 20:
            return {"regime": "unknown", "trend_strength": 0, "volatility": 0, "confidence": 0}

        closes = [float(k["c"]) for k in klines]
        highs = [float(k["h"]) for k in klines]
        lows = [float(k["l"]) for k in klines]
        volumes = [float(k.get("v", 0)) for k in klines]

        # Trend strength: linear regression slope normalized
        n = len(closes)
        x_mean = (n - 1) / 2
        y_mean = sum(closes) / n
        numerator = sum((i - x_mean) * (closes[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        slope = numerator / denominator if denominator != 0 else 0
        trend_strength = abs(slope) / y_mean * 10000 if y_mean != 0 else 0

        # Volatility: ATR-like
        tr_list = []
        for i in range(1, n):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1])
            )
            tr_list.append(tr)
        atr = sum(tr_list) / len(tr_list) if tr_list else 0
        volatility = atr / y_mean * 100 if y_mean != 0 else 0

        # ADX-like trend detection (simplified)
        price_range = max(highs[-20:]) - min(lows[-20:])
        body_sum = sum(abs(closes[i] - closes[i - 1]) for i in range(-20, 0))
        efficiency = price_range / body_sum if body_sum > 0 else 0

        # Classify
        if volatility > 1.5:
            regime = "劇烈波動"
        elif efficiency > 0.6 and trend_strength > 0.3:
            regime = "趨勢"
        elif efficiency < 0.3:
            regime = "盤整"
        else:
            regime = "過渡"

        trend_direction = "多頭" if slope > 0 else "空頭"

        return {
            "regime": regime,
            "trend_direction": trend_direction,
            "trend_strength": round(trend_strength, 2),
            "volatility": round(volatility, 3),
            "efficiency": round(efficiency, 2),
            "confidence": round(min(100, efficiency * 100 + (1 if regime != "unknown" else 0) * 20), 1),
        }

    @staticmethod
    def get_recommended_strategy(regime: str) -> str:
        strategies = {
            "趨勢": "趨勢跟隨·突破買入",
            "盤整": "區間操作·高拋低吸",
            "劇烈波動": "觀望為主·小倉試單",
            "過渡": "等待確認·輕倉佈局",
            "unknown": "觀察學習",
        }
        return strategies.get(regime, "觀察學習")


# ============================================================
# 4. 多時間框共振分析
# ============================================================
class MultiTFAnalyzer:
    """多時間框訊號共振分析"""

    TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
    TF_WEIGHTS = {"1m": 0.1, "5m": 0.15, "15m": 0.2, "30m": 0.15, "1h": 0.2, "4h": 0.15, "1d": 0.05}

    @staticmethod
    def analyze(tf_signals: Dict[str, Dict]) -> Dict:
        """
        tf_signals: {tf: {direction: 'bullish'|'bearish'|'neutral', strength: 0-100, rsi: float}}
        """
        if not tf_signals:
            return {"resonance": 0, "direction": "neutral", "details": {}}

        bullish_score = 0
        bearish_score = 0
        total_weight = 0
        details = {}

        for tf, sig in tf_signals.items():
            weight = MultiTFAnalyzer.TF_WEIGHTS.get(tf, 0.1)
            direction = sig.get("direction", "neutral")
            strength = sig.get("strength", 50)
            total_weight += weight

            if direction == "bullish":
                bullish_score += weight * strength
            elif direction == "bearish":
                bearish_score += weight * strength

            details[tf] = {"direction": direction, "strength": strength}

        if total_weight == 0:
            return {"resonance": 0, "direction": "neutral", "details": details}

        net = (bullish_score - bearish_score) / total_weight
        resonance = abs(net)

        if net > 15:
            direction = "強烈多頭"
        elif net > 5:
            direction = "偏多"
        elif net < -15:
            direction = "強烈空頭"
        elif net < -5:
            direction = "偏空"
        else:
            direction = "中性"

        # Higher timeframe trend
        higher_tf_bullish = 0
        higher_tf_bearish = 0
        for tf in ["1h", "4h", "1d"]:
            if tf in tf_signals:
                if tf_signals[tf].get("direction") == "bullish":
                    higher_tf_bullish += 1
                elif tf_signals[tf].get("direction") == "bearish":
                    higher_tf_bearish += 1

        return {
            "resonance": round(resonance, 1),
            "direction": direction,
            "net_score": round(net, 1),
            "higher_tf_trend": "多頭" if higher_tf_bullish > higher_tf_bearish else "空頭" if higher_tf_bearish > higher_tf_bullish else "中性",
            "bullish_tfs": sum(1 for s in tf_signals.values() if s.get("direction") == "bullish"),
            "bearish_tfs": sum(1 for s in tf_signals.values() if s.get("direction") == "bearish"),
            "details": details,
        }

    @staticmethod
    def get_signal_from_klines(klines: List[Dict]) -> Dict:
        """從K線數據生成單一時間框訊號"""
        if len(klines) < 14:
            return {"direction": "neutral", "strength": 50, "rsi": 50}

        closes = [float(k["c"]) for k in klines]

        # Simple RSI
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [max(0, d) for d in deltas[-14:]]
        losses = [max(0, -d) for d in deltas[-14:]]
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss != 0 else 100

        # Trend: price vs 20-period MA
        ma20 = sum(closes[-20:]) / 20
        price = closes[-1]

        if rsi < 30 and price < ma20:
            direction = "bullish"
            strength = 70
        elif rsi > 70 and price > ma20:
            direction = "bearish"
            strength = 70
        elif price > ma20 and rsi > 50:
            direction = "bullish"
            strength = 55
        elif price < ma20 and rsi < 50:
            direction = "bearish"
            strength = 55
        else:
            direction = "neutral"
            strength = 50

        return {"direction": direction, "strength": strength, "rsi": round(rsi, 1)}


# ============================================================
# 整合入口
# ============================================================
class AdvancedBrain:
    """進階學習大腦 - 整合所有模組"""

    def __init__(self, run_dir: Path):
        self.knowledge = KnowledgeBase(save_path=run_dir / "advanced_knowledge.json")
        self.reviewer = TradeReviewer(save_path=run_dir / "trade_reviews.json")
        self.regime_detector = MarketRegimeDetector()
        self.multi_tf = MultiTFAnalyzer()
        self.current_regime = "unknown"
        self.multi_tf_result = None

    def study(self, neural_activity: float = 0.5) -> Dict:
        """學習步驟"""
        return self.knowledge.study_step(neural_activity)

    def analyze_market(self, klines: Dict[str, List[Dict]]) -> Dict:
        """完整市場分析"""
        result = {}

        # Market regime (use 15m as primary)
        if "15m" in klines:
            regime = self.regime_detector.detect(klines["15m"])
            self.current_regime = regime["regime"]
            result["regime"] = regime
            result["recommended_strategy"] = self.regime_detector.get_recommended_strategy(regime["regime"])

        # Multi-timeframe
        tf_signals = {}
        for tf, data in klines.items():
            if data:
                tf_signals[tf] = self.multi_tf.get_signal_from_klines(data)
        if tf_signals:
            self.multi_tf_result = self.multi_tf.analyze(tf_signals)
            result["multi_tf"] = self.multi_tf_result

        # Knowledge influence
        result["knowledge_level"] = self.knowledge.get_overall_level()
        result["lessons"] = self.reviewer.get_lessons()

        return result

    def get_decision_bias(self) -> Dict:
        """根據學習結果給予決策傾向"""
        bias = {"buy_bias": 0, "sell_bias": 0, "confidence": 50, "reason": ""}

        # Multi-TF resonance
        if self.multi_tf_result:
            if "多頭" in self.multi_tf_result.get("direction", ""):
                bias["buy_bias"] += self.multi_tf_result.get("resonance", 0) * 0.5
            elif "空頭" in self.multi_tf_result.get("direction", ""):
                bias["sell_bias"] += self.multi_tf_result.get("resonance", 0) * 0.5

        # Market regime
        if self.current_regime == "趨勢":
            bias["confidence"] += 10
        elif self.current_regime == "盤整":
            bias["confidence"] -= 5
        elif self.current_regime == "劇烈波動":
            bias["confidence"] -= 15

        # Strategy performance
        best = self.reviewer.get_best_strategies(1)
        if best:
            bias["confidence"] += (best[0][1] - 50) * 0.3
            bias["reason"] = f"歷史最佳策略勝率{best[0][1]:.0f}%"

        bias["confidence"] = max(0, min(100, bias["confidence"]))
        return bias

    def get_status(self) -> Dict:
        return {
            "knowledge": self.knowledge.get_knowledge_summary(),
            "trade_reviews": self.reviewer.total_reviews,
            "best_strategies": self.reviewer.get_best_strategies(3),
            "lessons": self.reviewer.get_lessons(),
            "current_regime": self.current_regime,
            "multi_tf": self.multi_tf_result,
        }
