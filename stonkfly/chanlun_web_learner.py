"""
纏論網路學習模組
從 chanlun.com 抓取《教你炒股票》108課和精讀文章，提取纏論概念，加入果蠅學習知識庫
"""
import urllib.request
import re
import json
import time
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class ChanlunWebLearner:
    """從 chanlun.com 學習纏論知識"""

    BASE_URL = "https://chanlun.com"
    LESSON_URL_TEMPLATE = "/posts/ke-{:03d}"
    JINGDU_URL_TEMPLATE = "/posts/jingdu-{:03d}"
    TOTAL_LESSONS = 108
    TOTAL_JINGDU = 100

    # 纏論關鍵詞映射，用於從文章中提取概念
    CONCEPT_KEYWORDS = {
        "fractal": ["分型", "顶分型", "底分型", "顶底"],
        "stroke": ["笔", "向上笔", "向下笔", "一笔"],
        "segment": ["线段", "线段破坏", "特征序列"],
        "pivot": ["中枢", "震荡", "中枢震荡", "中枢扩展"],
        "divergence": ["背驰", "顶背驰", "底背驰", "盘整背驰"],
        "buy_point": ["买点", "一买", "二买", "三买", "第一类买点", "第二类买点", "第三类买点"],
        "sell_point": ["卖点", "一卖", "二卖", "三卖", "第一类卖点", "第二类卖点", "第三类卖点"],
        "level": ["级别", "走势级别", "递归"],
        "trend": ["趋势", "上涨", "下跌", "盘整"],
        "rsi_divergence": ["RSI", "相对强弱", "超买", "超卖"],
        "macd_cross": ["MACD", "金叉", "死叉", "零轴"],
        "volume_price": ["成交量", "量价", "放量", "缩量"],
        "support": ["支撑", "支撑位", "低点"],
        "resistance": ["压力", "压力位", "阻力", "高点"],
        "stop_loss": ["止损", "停损", "割肉"],
        "take_profit": ["止盈", "停利", "获利了结"],
        "position_size": ["仓位", "仓位管理", "加减仓"],
        "discipline": ["纪律", "执行", "心态"],
    }

    def __init__(self, save_path: Optional[Path] = None):
        self.save_path = save_path or Path("runs/paper/chanlun_web_learning.json")
        self.state = self._load_state()

    def _load_state(self) -> Dict:
        """加載學習狀態"""
        if self.save_path.exists():
            try:
                with open(self.save_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "current_lesson": 1,
            "current_jingdu": 1,
            "studied_lessons": [],
            "studied_jingdu": [],
            "total_articles_studied": 0,
            "concepts_learned": {},
            "last_study_time": 0,
            "current_article_title": "",
            "current_article_url": "",
            "study_log": [],
        }

    def _save_state(self):
        """保存學習狀態"""
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.save_path, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def _fetch_article(self, url_path: str) -> Optional[Dict]:
        """抓取文章內容"""
        url = f"{self.BASE_URL}{url_path}"
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode('utf-8', errors='ignore')

            # 提取標題
            title_match = re.search(r'<title>([^<]+)</title>', html)
            title = title_match.group(1).strip() if title_match else "未知標題"

            # 提取文章內容
            content_match = re.search(r'<article[^>]*>(.*?)</article>', html, re.DOTALL)
            if not content_match:
                return None

            content_html = content_match.group(1)
            # 移除HTML標籤
            text = re.sub(r'<[^>]+>', ' ', content_html)
            text = re.sub(r'\s+', ' ', text).strip()

            return {
                "title": title,
                "url": url,
                "content": text,
                "length": len(text),
            }
        except Exception as e:
            print(f"抓取文章失敗 {url}: {e}")
            return None

    def _extract_concepts(self, content: str) -> Dict[str, int]:
        """從文章內容中提取纏論概念及其出現次數"""
        concepts = {}
        for concept, keywords in self.CONCEPT_KEYWORDS.items():
            count = 0
            for keyword in keywords:
                count += content.count(keyword)
            if count > 0:
                concepts[concept] = count
        return concepts

    def _summarize_article(self, content: str, max_length: int = 300) -> str:
        """生成文章摘要（取前幾句）"""
        # 移除標題和元信息
        sentences = re.split(r'[。！？]', content)
        summary_parts = []
        current_length = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10:
                continue
            # 跳過元信息
            if any(skip in sentence for skip in ['免费', '入门', '原文核心引用', '白话翻译', '出处']):
                continue
            summary_parts.append(sentence)
            current_length += len(sentence)
            if current_length >= max_length:
                break

        return '。'.join(summary_parts) + '。' if summary_parts else content[:max_length]

    def study_next_lesson(self) -> Dict:
        """學習下一篇課程"""
        lesson_num = self.state["current_lesson"]
        if lesson_num > self.TOTAL_LESSONS:
            # 循環學習
            lesson_num = 1
            self.state["studied_lessons"] = []

        url_path = self.LESSON_URL_TEMPLATE.format(lesson_num)
        article = self._fetch_article(url_path)

        if not article:
            # 跳過失敗的文章
            self.state["current_lesson"] = lesson_num + 1
            self._save_state()
            return {"success": False, "error": "抓取失敗", "lesson": lesson_num}

        # 提取概念
        concepts = self._extract_concepts(article["content"])
        summary = self._summarize_article(article["content"])

        # 更新學習狀態
        self.state["current_lesson"] = lesson_num + 1
        self.state["studied_lessons"].append(lesson_num)
        self.state["total_articles_studied"] += 1
        self.state["last_study_time"] = time.time()
        self.state["current_article_title"] = article["title"]
        self.state["current_article_url"] = article["url"]

        # 更新概念學習次數
        for concept, count in concepts.items():
            if concept not in self.state["concepts_learned"]:
                self.state["concepts_learned"][concept] = {"count": 0, "mentions": 0}
            self.state["concepts_learned"][concept]["count"] += 1
            self.state["concepts_learned"][concept]["mentions"] += count

        # 記錄學習日誌
        self.state["study_log"].append({
            "time": time.time(),
            "type": "lesson",
            "number": lesson_num,
            "title": article["title"],
            "concepts": concepts,
            "summary": summary[:200],
        })
        # 只保留最近50條記錄
        self.state["study_log"] = self.state["study_log"][-50:]

        self._save_state()

        return {
            "success": True,
            "type": "lesson",
            "number": lesson_num,
            "title": article["title"],
            "url": article["url"],
            "concepts": concepts,
            "summary": summary,
            "content_length": article["length"],
        }

    def study_next_jingdu(self) -> Dict:
        """學習下一篇精讀"""
        jingdu_num = self.state["current_jingdu"]
        if jingdu_num > self.TOTAL_JINGDU:
            jingdu_num = 1
            self.state["studied_jingdu"] = []

        url_path = self.JINGDU_URL_TEMPLATE.format(jingdu_num)
        article = self._fetch_article(url_path)

        if not article:
            self.state["current_jingdu"] = jingdu_num + 1
            self._save_state()
            return {"success": False, "error": "抓取失敗", "jingdu": jingdu_num}

        concepts = self._extract_concepts(article["content"])
        summary = self._summarize_article(article["content"])

        self.state["current_jingdu"] = jingdu_num + 1
        self.state["studied_jingdu"].append(jingdu_num)
        self.state["total_articles_studied"] += 1
        self.state["last_study_time"] = time.time()
        self.state["current_article_title"] = article["title"]
        self.state["current_article_url"] = article["url"]

        for concept, count in concepts.items():
            if concept not in self.state["concepts_learned"]:
                self.state["concepts_learned"][concept] = {"count": 0, "mentions": 0}
            self.state["concepts_learned"][concept]["count"] += 1
            self.state["concepts_learned"][concept]["mentions"] += count

        self.state["study_log"].append({
            "time": time.time(),
            "type": "jingdu",
            "number": jingdu_num,
            "title": article["title"],
            "concepts": concepts,
            "summary": summary[:200],
        })
        self.state["study_log"] = self.state["study_log"][-50:]

        self._save_state()

        return {
            "success": True,
            "type": "jingdu",
            "number": jingdu_num,
            "title": article["title"],
            "url": article["url"],
            "concepts": concepts,
            "summary": summary,
            "content_length": article["length"],
        }

    def study_random(self) -> Dict:
        """隨機學習一篇文章（課程或精讀）"""
        if random.random() < 0.5:
            return self.study_next_lesson()
        else:
            return self.study_next_jingdu()

    def get_status(self) -> Dict:
        """獲取學習狀態"""
        return {
            "current_lesson": self.state["current_lesson"],
            "current_jingdu": self.state["current_jingdu"],
            "total_lessons": self.TOTAL_LESSONS,
            "total_jingdu": self.TOTAL_JINGDU,
            "studied_lessons_count": len(self.state["studied_lessons"]),
            "studied_jingdu_count": len(self.state["studied_jingdu"]),
            "total_articles_studied": self.state["total_articles_studied"],
            "concepts_learned": self.state["concepts_learned"],
            "current_article_title": self.state["current_article_title"],
            "current_article_url": self.state["current_article_url"],
            "last_study_time": self.state["last_study_time"],
            "recent_studies": self.state["study_log"][-5:],
            "lesson_progress": (len(self.state["studied_lessons"]) / self.TOTAL_LESSONS) * 100,
            "jingdu_progress": (len(self.state["studied_jingdu"]) / self.TOTAL_JINGDU) * 100,
        }


# 全局實例
_web_learner = None

def get_web_learner() -> ChanlunWebLearner:
    """獲取全局學習器實例"""
    global _web_learner
    if _web_learner is None:
        _web_learner = ChanlunWebLearner()
    return _web_learner
