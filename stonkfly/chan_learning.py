"""
果蠅纏論學習模組
在冷卻/持有期間，讓果蠅大腦學習纏論知識理論
- 分型辨識（頂分型/底分型）
- 筆的構成（向上筆/向下筆）
- 中樞識別（震盪區間）
- 背離判斷（價格與動能背離）
- 買賣點識別（一買/二買/三買）
"""
import random
import time
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass
class ChanConcept:
    """纏論概念學習進度"""
    name: str
    name_zh: str
    description: str
    level: float = 0.0  # 0-100 掌握度
    study_count: int = 0
    correct_count: int = 0
    last_studied: float = 0.0

    @property
    def accuracy(self) -> float:
        if self.study_count == 0:
            return 0.0
        return (self.correct_count / self.study_count) * 100

    def study(self, success: bool):
        self.study_count += 1
        if success:
            self.correct_count += 1
            # 學習曲線：每次成功提升掌握度，遞減邊際效益
            gain = max(0.5, 5.0 * (1 - self.level / 100))
            self.level = min(100, self.level + gain)
        else:
            # 失敗小幅下降
            self.level = max(0, self.level - 0.5)
        self.last_studied = time.time()


class ChanLearner:
    """果蠅纏論學習器"""

    CONCEPTS = [
        ("fractal", "分型", "辨識K線頂分型與底分型，三根K線的最高/最低結構"),
        ("stroke", "筆", "連接相鄰分型的線段，向上筆與向下筆的構成"),
        ("pivot", "中樞", "至少三筆重疊形成的震盪區間，多空交戰地帶"),
        ("divergence", "背離", "價格創新高/低但動能未跟隨，趨勢衰竭訊號"),
        ("buy_point", "買點", "一買（背離後）、二買（回踩不破）、三買（突破中樞）"),
        ("sell_point", "賣點", "一賣（頂背離）、二賣（反彈不過）、三賣（跌破中樞）"),
    ]

    def __init__(self, save_path: Optional[Path] = None):
        self.save_path = save_path
        self.concepts: Dict[str, ChanConcept] = {}
        for key, name, desc in self.CONCEPTS:
            self.concepts[key] = ChanConcept(name=key, name_zh=name, description=desc)
        self.total_study_time = 0.0
        self.current_concept: Optional[str] = None
        self.study_start_time: float = 0.0
        self.is_studying = False
        self._load()

    def _load(self):
        """載入學習進度"""
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
        """儲存學習進度"""
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

    def start_study(self) -> str:
        """開始一個學習階段，回傳目前學習的概念名稱"""
        # 優先學習掌握度最低的概念
        sorted_concepts = sorted(self.concepts.values(), key=lambda c: c.level)
        concept = sorted_concepts[0]
        self.current_concept = concept.name
        self.study_start_time = time.time()
        self._last_study_time = time.time()
        self.is_studying = True
        return concept.name_zh

    def study_step(self, neural_activity: float = 0.5) -> Dict:
        """
        執行一次學習步驟
        neural_activity: 神經活躍度 0-1，越高表示大腦越專注
        回傳學習結果
        """
        if not self.is_studying or not self.current_concept:
            return {"status": "idle"}

        concept = self.concepts[self.current_concept]
        # 學習成功率與神經活躍度、掌握度相關
        # 掌握度越高，越容易成功（強化學習）
        base_success = 0.3 + (concept.level / 100) * 0.5
        focus_bonus = neural_activity * 0.2
        success_rate = min(0.95, base_success + focus_bonus)
        success = random.random() < success_rate

        concept.study(success)
        elapsed = time.time() - self.study_start_time
        # Track actual elapsed study time (2 seconds per step in cooldown)
        if not hasattr(self, '_last_study_time') or self._last_study_time == 0:
            self._last_study_time = time.time()
        self.total_study_time += time.time() - self._last_study_time
        self._last_study_time = time.time()

        result = {
            "status": "studying",
            "concept": concept.name_zh,
            "concept_key": concept.name,
            "description": concept.description,
            "level": concept.level,
            "accuracy": concept.accuracy,
            "study_count": concept.study_count,
            "success": success,
            "elapsed": elapsed,
        }

        # 每學習5次更換概念（避免只學一個）
        if concept.study_count % 5 == 0:
            self.current_concept = None
            self.is_studying = False

        self.save()
        return result

    def stop_study(self) -> Dict:
        """停止學習，回傳總結"""
        if self.is_studying and self.current_concept:
            concept = self.concepts[self.current_concept]
            elapsed = time.time() - self.study_start_time
            summary = {
                "concept": concept.name_zh,
                "level": concept.level,
                "study_count": concept.study_count,
                "elapsed": elapsed,
            }
        else:
            summary = {"concept": None, "level": 0, "study_count": 0, "elapsed": 0}
        self.is_studying = False
        self.current_concept = None
        return summary

    def get_knowledge_summary(self) -> Dict:
        """取得整體知識總結"""
        levels = [c.level for c in self.concepts.values()]
        avg_level = sum(levels) / len(levels) if levels else 0
        mastered = sum(1 for c in self.concepts.values() if c.level >= 80)
        learning = sum(1 for c in self.concepts.values() if 30 <= c.level < 80)
        beginner = sum(1 for c in self.concepts.values() if c.level < 30)

        return {
            "avg_level": avg_level,
            "mastered": mastered,
            "learning": learning,
            "beginner": beginner,
            "total_concepts": len(self.concepts),
            "total_study_time": self.total_study_time,
            "is_studying": self.is_studying,
            "current_concept": self.concepts[self.current_concept].name_zh if self.current_concept else None,
            "concepts": [
                {
                    "key": c.name,
                    "name": c.name_zh,
                    "level": c.level,
                    "accuracy": c.accuracy,
                    "study_count": c.study_count,
                }
                for c in self.concepts.values()
            ],
        }

    def get_trading_bias(self) -> Dict:
        """
        根據學習進度給予交易偏見（知識影響決策）
        掌握度越高，對纏論訊號的信任度越高
        """
        fractal_level = self.concepts["fractal"].level
        pivot_level = self.concepts["pivot"].level
        divergence_level = self.concepts["divergence"].level
        buy_level = self.concepts["buy_point"].level
        sell_level = self.concepts["sell_point"].level

        # 對買入訊號的信心（買點+背離+分型）
        buy_confidence = (buy_level + divergence_level + fractal_level) / 3
        # 對賣出訊號的信心（賣點+背離+分型）
        sell_confidence = (sell_level + divergence_level + fractal_level) / 3
        # 對中樞震盪的辨識能力
        pivot_awareness = pivot_level

        return {
            "buy_confidence": buy_confidence,
            "sell_confidence": sell_confidence,
            "pivot_awareness": pivot_awareness,
            "overall": (buy_confidence + sell_confidence + pivot_awareness) / 3,
        }
