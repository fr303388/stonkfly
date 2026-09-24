"""
市場情緒與時事嗅覺模組
- 加密貨幣恐慌貪婪指數 (Fear & Greed Index)
- 財經新聞關鍵字計分
- 輸出情緒分數，用於調整果蠅買賣門檻
"""
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone, timedelta

UTC8 = timezone(timedelta(hours=8))

# 恐慌貪婪指數 API（免費，無需 key）
FNG_API = "https://api.alternative.me/fng/?limit=2"

# 新聞關鍵字計分（正面/負面）
POSITIVE_KEYWORDS = [
    "etf approved", "etf 通過", "rate cut", "降息", "bull market", "牛市",
    "institutional adoption", "機構採用", "partnership", "合作", "upgrade",
    "升級", "mainstream", "主流", "regulation clear", "監管明確",
    "stimulus", "刺激", "economic growth", "經濟成長", "halving", "減半",
]
NEGATIVE_KEYWORDS = [
    "sec lawsuit", "sec 訴訟", "ban", "禁止", "hack", "駭客", "exploit",
    "漏洞", "rate hike", "升息", "recession", "衰退", "inflation", "通膨",
    "war", "戰爭", "sanction", "制裁", "crash", "崩盤", "dump", "拋售",
    "fraud", "詐欺", "bankruptcy", "破產", "crackdown", "打壓",
    "china ban", "中國禁止", "fed hawkish", "鷹派",
]

CACHE_FILE = Path(__file__).parent.parent / "runs" / "paper" / "sentiment_cache.json"
CACHE_TTL = 3600  # 快取1小時


def _fetch_json(url: str, timeout: int = 10) -> dict | None:
    """安全抓取 JSON"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "stonkfly/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def fetch_fear_greed() -> dict:
    """抓取恐慌貪婪指數
    返回: {value: 0-100, classification: 'Extreme Fear'/'Fear'/'Neutral'/'Greed'/'Extreme Greed'}
    """
    data = _fetch_json(FNG_API)
    if data and "data" in data and len(data["data"]) > 0:
        item = data["data"][0]
        return {
            "value": int(item["value"]),
            "classification": item["value_classification"],
            "timestamp": int(item["timestamp"]),
        }
    return {"value": 50, "classification": "Neutral", "timestamp": 0}


def fetch_news_sentiment() -> dict:
    """簡易新聞情緒（用免費 RSS 或公開 API）
    目前使用 CryptoPanic 公開資料，若失敗返回中性
    """
    # 使用 CoinGecko 狀態頁面的簡易替代：直接返回中性，後續可擴充
    return {
        "score": 0.0,
        "positive_hits": 0,
        "negative_hits": 0,
        "source": "disabled",
    }


def compute_sentiment(fng: dict, news: dict) -> dict:
    """綜合計算市場情緒分數
    返回: {score: -1~+1, label: '恐懼'/'中性'/'貪婪', fng_value, fng_class, adjusted_buy_threshold}
    """
    # FNG 轉換為 -1~+1：0=極度恐懼(-1), 50=中性(0), 100=極度貪婪(+1)
    fng_score = (fng.get("value", 50) - 50) / 50.0

    # 新聞情緒（目前為0，後續擴充）
    news_score = news.get("score", 0.0)

    # 加權：FNG 70% + 新聞 30%
    combined = fng_score * 0.7 + news_score * 0.3
    combined = max(-1.0, min(1.0, combined))

    # 標籤
    if combined < -0.3:
        label = "恐懼"
    elif combined > 0.3:
        label = "貪婪"
    else:
        label = "中性"

    # 調整買入門檻：
    # 恐懼時(-1)：買入信心門檻提高到 80%（更保守）
    # 中性時(0)：門檻 65%
    # 貪婪時(+1)：門檻提高到 75%（避免追高）
    base_threshold = 65
    if combined < 0:
        # 恐懼：越恐懼越保守
        buy_threshold = base_threshold + abs(combined) * 15
    else:
        # 貪婪：越貪婪越小心追高
        buy_threshold = base_threshold + combined * 10
    buy_threshold = min(90, max(50, buy_threshold))

    return {
        "score": round(combined, 3),
        "label": label,
        "fng_value": fng.get("value", 50),
        "fng_class": fng.get("classification", "Neutral"),
        "news_score": round(news_score, 3),
        "buy_threshold": round(buy_threshold, 1),
        "updated": datetime.now(UTC8).strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_sentiment(force_refresh: bool = False) -> dict:
    """取得市場情緒（含快取）"""
    # 檢查快取
    if not force_refresh and CACHE_FILE.exists():
        try:
            cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if time.time() - cache.get("fetched_at", 0) < CACHE_TTL:
                return cache["data"]
        except Exception:
            pass

    # 抓取新資料
    fng = fetch_fear_greed()
    news = fetch_news_sentiment()
    result = compute_sentiment(fng, news)

    # 寫入快取
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(
            json.dumps({"fetched_at": time.time(), "data": result}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

    return result


if __name__ == "__main__":
    s = get_sentiment(force_refresh=True)
    print(json.dumps(s, ensure_ascii=False, indent=2))
