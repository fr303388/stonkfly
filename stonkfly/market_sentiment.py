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
    "trade deal", "貿易協議", "ceasefire", "停火", "peace talks", "和平談判",
    "dovish", "鴿派", "soft landing", "軟著陸", "jobs growth", "就業成長",
    "tax cut", "減稅", "infrastructure", "基礎建設", "diplomacy", "外交",
    "summit", "峰會", "agreement", "協議", "stable", "穩定",
]
NEGATIVE_KEYWORDS = [
    "sec lawsuit", "sec 訴訟", "ban", "禁止", "hack", "駭客", "exploit",
    "漏洞", "rate hike", "升息", "recession", "衰退", "inflation", "通膨",
    "war", "戰爭", "sanction", "制裁", "crash", "崩盤", "dump", "拋售",
    "fraud", "詐欺", "bankruptcy", "破產", "crackdown", "打壓",
    "china ban", "中國禁止", "fed hawkish", "鷹派",
    "tariff", "關稅", "trade war", "貿易戰", "conflict", "衝突",
    "military", "軍事", "missile", "飛彈", "invasion", "入侵",
    "coup", "政變", "protest", "抗議", "riot", "暴動",
    "default", "違約", "debt crisis", "債務危機", "stagflation", "停滯性通膨",
    "unemployment", "失業", "layoff", "裁員", "geopolitical", "地緣政治",
    "tension", "緊張", "threat", "威脅", "embargo", "禁運",
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



def _translate_to_zh(text: str, timeout: int = 5) -> str:
    """使用 MyMemory 免費 API 翻譯成繁體中文"""
    try:
        import urllib.parse
        encoded = urllib.parse.quote(text[:100])
        url = f"https://api.mymemory.translated.net/get?q={encoded}&langpair=en|zh-TW"
        req = urllib.request.Request(url, headers={"User-Agent": "stonkfly/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        translated = data.get("responseData", {}).get("translatedText", "")
        if translated and translated != text:
            return translated
    except Exception:
        pass
    return text
def _fetch_rss(url: str, timeout: int = 8) -> list:
    """抓取並解析 RSS feed，返回標題列表"""
    import xml.etree.ElementTree as ET
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 stonkfly/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
        root = ET.fromstring(content)
        items = []
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            pub = item.findtext("pubDate", "").strip()
            desc = item.findtext("description", "").strip()[:200]
            if title:
                items.append({"title": title, "url": link, "pub": pub, "desc": desc})
        return items
    except Exception:
        return []


def fetch_news_sentiment() -> dict:
    """抓取加密貨幣+宏觀政治新聞並計算情緒分數
    新聞源：Cointelegraph, CoinDesk（加密）+ BBC Business, CNBC（宏觀）
    """
    rss_feeds = [
        ("https://cointelegraph.com/rss", "加密"),
        ("https://www.coindesk.com/arc/outboundfeeds/rss/", "加密"),
        ("http://feeds.bbci.co.uk/news/business/rss.xml", "宏觀"),
        ("https://www.cnbc.com/id/100003114/device/rss/rss.html", "宏觀"),
        ("https://feeds.a.dj.com/rss/RSSWorldNews.xml", "宏觀"),
    ]
    all_items = []
    for feed_url, category in rss_feeds:
        items = _fetch_rss(feed_url)
        for item in items[:6]:  # 每個來源取前6則，確保宏觀新聞不被擠掉
            item["category"] = category
            all_items.append(item)
    headlines = []
    pos_hits = 0
    neg_hits = 0
    for item in all_items:
        title = item["title"]
        desc = item.get("desc", "")
        category = item.get("category", "宏觀")
        text_lower = (title + " " + desc).lower()
        score = 0
        for kw in POSITIVE_KEYWORDS:
            if kw.lower() in text_lower:
                score += 1
                pos_hits += 1
        for kw in NEGATIVE_KEYWORDS:
            if kw.lower() in text_lower:
                score -= 1
                neg_hits += 1
        if score > 0:
            tag = "看漲"
        elif score < 0:
            tag = "看跌"
        else:
            tag = "中性"
        time_str = ""
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(item["pub"])
            time_str = dt.astimezone(UTC8).strftime("%H:%M")
        except Exception:
            pass
        title_zh = _translate_to_zh(title[:80])
        headlines.append({
            "title": title[:80], "title_zh": title_zh, "tag": tag,
            "score": score, "url": item["url"], "time": time_str,
            "category": category,
        })
    headlines.sort(key=lambda x: x.get("time", ""), reverse=True)
    total = pos_hits + neg_hits
    news_score = (pos_hits - neg_hits) / total if total > 0 else 0.0
    return {"score": round(max(-1,min(1,news_score)),3), "positive_hits": pos_hits, "negative_hits": neg_hits, "source": "RSS", "headlines": headlines[:10]}


def compute_fly_emotion(neural: dict | None = None, pnl: float = 0.0) -> dict:
    """計算果蠅當前情緒狀態
    基於獎勵/厭惡放電比例、大腦活躍度、持倉盈虧
    """
    if not neural:
        return {"emotion": "平靜", "score": 0.0, "detail": "觀察中"}

    reward = neural.get("reward_spikes", 0)
    aversive = neural.get("aversive_spikes", 0)
    total = reward + aversive
    ratio = (reward - aversive) / total if total > 0 else 0.0

    # 結合盈虧
    pnl_factor = 0.0
    if pnl > 50:
        pnl_factor = 0.3
    elif pnl > 0:
        pnl_factor = 0.1
    elif pnl < -50:
        pnl_factor = -0.3
    elif pnl < 0:
        pnl_factor = -0.1

    score = ratio * 0.7 + pnl_factor * 0.3
    score = max(-1.0, min(1.0, score))

    if score > 0.4:
        emotion = "興奮"
        detail = f"獎勵放電強 ({reward}Hz)，預期獲利"
    elif score > 0.15:
        emotion = "期待"
        detail = f"獎勵略高 ({reward}/{aversive})，看好走勢"
    elif score > -0.15:
        emotion = "平靜"
        detail = f"獎勵/厭惡平衡 ({reward}/{aversive})，冷靜觀察"
    elif score > -0.4:
        emotion = "焦慮"
        detail = f"厭惡放電增 ({aversive}Hz)，擔心風險"
    else:
        emotion = "恐懼"
        detail = f"厭惡主導 ({aversive}Hz)，強烈避險"

    return {
        "emotion": emotion,
        "score": round(score, 3),
        "reward_hz": reward,
        "aversive_hz": aversive,
        "detail": detail,
    }


def compute_sentiment(fng: dict, news: dict, neural: dict | None = None, pnl: float = 0.0) -> dict:
    """綜合計算市場情緒分數
    返回: {score, label, fng_value, fng_class, news_score, buy_threshold, headlines, fly_emotion}
    """
    # FNG 轉換為 -1~+1：0=極度恐懼(-1), 50=中性(0), 100=極度貪婪(+1)
    fng_score = (fng.get("value", 50) - 50) / 50.0

    # 新聞情緒
    news_score = news.get("score", 0.0)

    # 加權：FNG 60% + 新聞 40%
    combined = fng_score * 0.6 + news_score * 0.4
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
        buy_threshold = base_threshold + abs(combined) * 15
    else:
        buy_threshold = base_threshold + combined * 10
    buy_threshold = min(90, max(50, buy_threshold))

    # 果蠅情緒
    fly_emotion = compute_fly_emotion(neural, pnl)

    return {
        "score": round(combined, 3),
        "label": label,
        "fng_value": fng.get("value", 50),
        "fng_class": fng.get("classification", "Neutral"),
        "news_score": round(news_score, 3),
        "news_positive": news.get("positive_hits", 0),
        "news_negative": news.get("negative_hits", 0),
        "headlines": news.get("headlines", []),
        "fly_emotion": fly_emotion,
        "buy_threshold": round(buy_threshold, 1),
        "updated": datetime.now(UTC8).strftime("%Y-%m-%d %H:%M:%S"),
    }


def _notify_new_news(news: dict, old_first_title: str = ""):
    """有新的看漲/看跌新聞時發送Telegram通知"""
    try:
        headlines = news.get("headlines", [])
        if not headlines:
            return
        first = headlines[0]
        first_title = first.get("title", "")
        if not first_title or first_title == old_first_title:
            return
        tag = first.get("tag", "中性")
        if tag not in ("看漲", "看跌"):
            return
        from stonkfly.telegram_notify import send_telegram
        emoji = "🟢" if tag == "看漲" else "🔴"
        title_zh = first.get("title_zh") or first.get("title", "")
        url = first.get("url", "")
        msg = f"{emoji} <b>市場新聞 {tag}</b>\n{title_zh}\n\n<a href='{url}'>閱讀原文</a>"
        send_telegram(msg)
    except Exception:
        pass


def get_sentiment(force_refresh: bool = False, neural: dict | None = None, pnl: float = 0.0) -> dict:
    """取得市場情緒（含快取）
    neural: 神經活動數據（用於計算果蠅情緒）
    pnl: 當前持倉盈虧
    """
    # 檢查快取（新聞部分快取1小時，果蠅情緒每次即時計算）
    cached_news = None
    old_first_title = ""
    if not force_refresh and CACHE_FILE.exists():
        try:
            cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if time.time() - cache.get("fetched_at", 0) < CACHE_TTL:
                cached_news = cache.get("news_data")
            # 記錄舊的第一則新聞標題（用於偵測新新聞）
            old_news = cache.get("news_data", {})
            old_headlines = old_news.get("headlines", []) if isinstance(old_news, dict) else []
            if old_headlines:
                old_first_title = old_headlines[0].get("title", "")
        except Exception:
            pass

    # 抓取新資料（新聞用快取，FNG每次抓）
    fng = fetch_fear_greed()
    if cached_news:
        news = cached_news
    else:
        news = fetch_news_sentiment()
        # 有新的看漲/看跌新聞時發送Telegram通知
        _notify_new_news(news, old_first_title)
        # 寫入新聞快取
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(
                json.dumps({"fetched_at": time.time(), "news_data": news}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    result = compute_sentiment(fng, news, neural, pnl)
    return result


if __name__ == "__main__":
    s = get_sentiment(force_refresh=True)
    print(json.dumps(s, ensure_ascii=False, indent=2))
