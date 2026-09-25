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

# 翻譯快取（避免 API 速率限制導致新新聞變英文）
import os
_TRANSLATE_CACHE = {}
_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "runs", "paper", "translate_cache.json")
try:
    if os.path.exists(_CACHE_FILE):
        with open(_CACHE_FILE, "r", encoding="utf-8") as _cf:
            _TRANSLATE_CACHE = json.load(_cf)
except Exception:
    _TRANSLATE_CACHE = {}

def _save_translate_cache():
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        with open(_CACHE_FILE, "w", encoding="utf-8") as _cf:
            json.dump(_TRANSLATE_CACHE, _cf, ensure_ascii=False)
    except Exception:
        pass

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
    "收購", "併購", "增持", "買入", "超預期", "上揚", "飆升",
    "反彈", "新高", "看多", "利好", "增資", "擴張", "繁榮",
    "獲利", "盈利", "上漲", "成長", "突破", "樂觀", "信心",
    "合作", "聯盟", "戰略", "授權", "通過", "批准", "核准",
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
    "起訴", "訴訟", "指控", "出售", "賣出", "減持", "反對", "警告",
    "禁令", "限制", "下調", "衰退", "下跌", "暴跌", "拋售", "做空",
    "違規", "罰款", "調查", "調查", "查封", "凍結", "倒閉",
    "危機", "恐慌", "抛售", "下跌", "熊市", "利空", "下修",
    "虧損", "減損", "緊縮", "升息", "通脹", "通貨膨脹",
    "unemployment", "失業", "layoff", "裁員", "geopolitical", "地緣政治",
    "tension", "緊張", "threat", "威脅", "embargo", "禁運",
]

CACHE_FILE = Path(__file__).parent.parent / "runs" / "paper" / "sentiment_cache.json"
CACHE_TTL = 900  # 快取15分鐘


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



# 本地加密貨幣/金融詞典（API被限流時的備援翻譯）
_CRYPTO_DICT = {
    "bitcoin": "比特幣", "btc": "BTC", "ethereum": "以太坊", "eth": "ETH",
    "solana": "Solana", "sol": "SOL", "binance": "幣安", "coinbase": "Coinbase",
    "crypto": "加密貨幣", "cryptocurrency": "加密貨幣", "blockchain": "區塊鏈",
    "price": "價格", "surges": "飆漲", "surge": "飆漲", "soars": "飆漲", "soar": "飆漲",
    "jumps": "跳漲", "jump": "跳漲", "rises": "上漲", "rise": "上漲", "rallies": "反彈上漲",
    "rally": "反彈", "drops": "下跌", "drop": "下跌", "falls": "下跌", "fall": "下跌",
    "crashes": "崩跌", "crash": "崩跌", "plunges": "暴跌", "plunge": "暴跌",
    "tumbles": "重挫", "tumble": "重挫", "slides": "下滑", "slide": "下滑",
    "record": "創紀錄", "high": "高點", "low": "低點", "all-time": "歷史", "ath": "歷史新高",
    "market": "市場", "markets": "市場", "trading": "交易", "trade": "交易",
    "investor": "投資者", "investors": "投資者", "institution": "機構", "institutions": "機構",
    "adoption": "採用", "regulation": "監管", "regulator": "監管機構", "sec": "美國證監會",
    "etf": "ETF", "fund": "基金", "hedge": "對沖", "whale": "巨鯨", "whales": "巨鯨",
    "mining": "挖礦", "miner": "礦工", "miners": "礦工", "hashrate": "算力",
    "halving": "減半", "fork": "分叉", "upgrade": "升級", "update": "更新",
    "hack": "駭客攻擊", "hacked": "被駭", "exploit": "漏洞攻擊", "scam": "詐騙",
    "fraud": "詐欺", "lawsuit": "訴訟", "ban": "禁令", "banned": "被禁止",
    "approve": "批准", "approved": "已批准", "approval": "批准", "reject": "拒絕",
    "fed": "美聯準", "federal": "聯準會", "interest": "利率", "rate": "利率",
    "inflation": "通膨", "recession": "衰退", "economy": "經濟", "economic": "經濟的",
    "stablecoin": "穩定幣", "stablecoins": "穩定幣", "tether": "USDT", "usdt": "USDT",
    "defi": "DeFi", "nft": "NFT", "metaverse": "元宇宙", "web3": "Web3",
    "token": "代幣", "tokens": "代幣", "coin": "幣", "coins": "幣",
    "wallet": "錢包", "exchange": "交易所", "exchanges": "交易所",
    "volume": "交易量", "volatility": "波動", "bull": "多頭", "bullish": "看漲",
    "bear": "空頭", "bearish": "看跌", "outlook": "前景", "forecast": "預測",
    "prediction": "預測", "analysis": "分析", "analyst": "分析師", "analysts": "分析師",
    "report": "報告", "data": "數據", "index": "指數", "indicator": "指標",
    "buy": "買入", "sell": "賣出", "holding": "持有", "hold": "持有",
    "profit": "利潤", "loss": "虧損", "gain": "收益", "gains": "收益",
    "million": "百萬", "billion": "十億", "trillion": "兆", "percent": "%",
    "today": "今日", "tonight": "今晚", "weekly": "每週", "monthly": "每月",
    "global": "全球", "asia": "亞洲", "europe": "歐洲", "us": "美國", "china": "中國",
    "japan": "日本", "korea": "韓國", "russia": "俄羅斯", "uk": "英國",
    "bank": "銀行", "banks": "銀行", "credit": "信貸", "debt": "債務",
    "currency": "貨幣", "currencies": "貨幣", "dollar": "美元", "yuan": "人民幣",
    "yen": "日圓", "euro": "歐元", "pound": "英鎊",
    "oil": "石油", "gold": "黃金", "silver": "白銀", "stock": "股票", "stocks": "股票",
    "bond": "債券", "bonds": "債券", "asset": "資產", "assets": "資產",
    "portfolio": "投資組合", "strategy": "策略", "risk": "風險", "reward": "回報",
    "opportunity": "機會", "threat": "威脅", "challenge": "挑戰", "concern": "擔憂",
    "positive": "正面", "negative": "負面", "optimistic": "樂觀", "pessimistic": "悲觀",
    "uncertainty": "不確定性", "concerns": "擔憂", "worries": "擔憂", "fear": "恐懼",
    "greed": "貪婪", "sentiment": "情緒", "mood": "氛圍",
    "partnership": "合作", "collaboration": "合作", "deal": "交易", "agreement": "協議",
    "launch": "推出", "launches": "推出", "announce": "宣布", "announces": "宣布",
    "announcement": "公告", "release": "發布", "releases": "發布", "unveil": "揭曉",
    "introduce": "引入", "introduces": "引入", "roll": "推出", "rollout": "推出",
    "platform": "平台", "protocol": "協議", "network": "網路", "chain": "鏈",
    "layer": "層", "scaling": "擴容", "solution": "解決方案", "solutions": "解決方案",
    "smart": "智慧", "contract": "合約", "contracts": "合約", "decentralized": "去中心化",
    "centralized": "中心化", "consensus": "共識", "validator": "驗證者", "validators": "驗證者",
    "staking": "質押", "stake": "質押", "yield": "收益", "apy": "年化收益率",
    "liquidity": "流動性", "liquid": "流動性", "locked": "鎖定", "tvl": "總鎖倉量",
    "dao": "DAO", "governance": "治理", "vote": "投票", "voting": "投票",
    "airdrop": "空投", "airdrops": "空投", "ico": "ICO", "ido": "IDO", "ieo": "IEO",
    "listing": "上線", "list": "上線", "delist": "下架", "delisting": "下架",
    "withdraw": "提現", "withdrawal": "提現", "withdrawals": "提現", "deposit": "存款",
    "kyc": "KYC", "aml": "AML", "compliance": "合規", "audit": "審計", "audited": "已審計",
    "security": "安全", "breach": "安全漏洞", "vulnerability": "弱點", "bug": "bug",
    "patch": "修補", "fix": "修復", "issue": "問題", "issues": "問題",
    "outage": "停機", "downtime": "停機", "maintenance": "維護", "upgrade": "升級",
    "migration": "遷移", "transition": "轉換", "shift": "轉變", "change": "改變",
    "trend": "趨勢", "trends": "趨勢", "momentum": "動能", "breakout": "突破",
    "breakdown": "崩跌", "support": "支撐", "resistance": "阻力", "pattern": "形態",
    "chart": "圖表", "charts": "圖表", "technical": "技術", "fundamental": "基本面",
    "macro": "宏觀", "micro": "微觀", "sector": "板塊", "sectors": "板塊",
    "altcoin": "山寨幣", "altcoins": "山寨幣", "memecoin": "迷因幣", "memecoins": "迷因幣",
    "dogecoin": "狗狗幣", "doge": "DOGE", "shiba": "柴犬幣", "shib": "SHIB",
    "pepe": "PEPE", "xrp": "XRP", "ripple": "Ripple", "cardano": "卡爾達諾", "ada": "ADA",
    "avalanche": "Avalanche", "avax": "AVAX", "polkadot": "Polkadot", "dot": "DOT",
    "polygon": "Polygon", "matic": "MATIC", "chainlink": "Chainlink", "link": "LINK",
    "uniswap": "Uniswap", "uni": "UNI", "aave": "Aave", "compound": "Compound",
    "maker": "Maker", "mkr": "MKR", "sushi": "SushiSwap", "curve": "Curve",
    "lido": "Lido", "ldo": "LDO", "arbitrum": "Arbitrum", "arb": "ARB",
    "optimism": "Optimism", "op": "OP", "base": "Base", "zksync": "zkSync",
    "starknet": "StarkNet", "sui": "Sui", "aptos": "Aptos", "apt": "APT",
    "near": "NEAR", "ftm": "FTM", "fantom": "Fantom", "algo": "ALGO", "algorand": "Algorand",
    "hbar": "HBAR", "hedera": "Hedera", "qnt": "QNT", "quant": "Quant",
    "vet": "VET", "vechain": "VeChain", "xtz": "XTZ", "tezos": "Tezos",
    "atom": "ATOM", "cosmos": "Cosmos", "neo": "NEO", "eos": "EOS", "trx": "TRX", "tron": "Tron",
    "xec": "XEC", "bch": "BCH", "ltc": "LTC", "litecoin": "萊特幣", "dash": "DASH",
    "zec": "ZEC", "zcash": "Zcash", "xmr": "XMR", "monero": "門羅幣",
    "wld": "WLD", "worldcoin": "Worldcoin", "aster": "ASTER", "bnb": "BNB",
    "pengu": "PENGU", "bonk": "BONK", "wif": "WIF", "floki": "FLOKI",
    "ceo": "CEO", "founder": "創辦人", "cfo": "CFO", "cto": "CTO",
    "court": "法院", "trial": "審判", "verdict": "判決", "ruling": "裁決",
    "fine": "罰鍰", "penalty": "罰則", "settlement": "和解", "conviction": "定罪",
    "sentenced": "判刑", "prison": "監禁", "jail": "監禁", "arrest": "逮捕",
    "charged": "被起訴", "indicted": "被起訴", "investigation": "調查", "probe": "調查",
    "probe": "調查", "examines": "檢視", "explores": "探索", "considers": "考慮",
    "plans": "計畫", "plan": "計畫", "aims": "目標", "goal": "目標",
    "target": "目標", "targets": "目標", "focus": "聚焦", "focuses": "聚焦",
    "emphasizes": "強調", "stresses": "強調", "highlights": "強調", "notes": "指出",
    "says": "表示", "said": "表示", "claims": "聲稱", "argues": "主張",
    "believes": "認為", "thinks": "認為", "expects": "預期", "predicts": "預測",
    "warns": "警告", "caution": "警告", "urges": "呼籲", "calls": "呼籲",
    "demands": "要求", "requests": "請求", "proposes": "提議", "suggests": "建議",
    "recommends": "建議", "advises": "建議", "encourages": "鼓勵", "supports": "支持",
    "opposes": "反對", "criticizes": "批評", "praises": "讚揚", "welcomes": "歡迎",
    "response": "回應", "reaction": "反應", "impact": "影響", "effect": "影響",
    "consequence": "後果", "result": "結果", "results": "結果", "outcome": "結果",
    "benefit": "好處", "benefits": "好處", "advantage": "優勢", "advantages": "優勢",
    "disadvantage": "劣勢", "drawback": "缺點", "risk": "風險", "risks": "風險",
    "threat": "威脅", "threats": "威脅", "opportunity": "機會", "opportunities": "機會",
    "potential": "潛力", "possibility": "可能性", "probability": "機率", "likelihood": "可能性",
    "certainty": "確定性", "uncertain": "不確定", "unknown": "未知", "mystery": "謎團",
    "surprise": "驚喜", "shock": "震驚", "astonishing": "驚人的", "unexpected": "意外的",
    "unprecedented": "史無前例", "record-breaking": "破紀錄", "historic": "歷史性的",
    "milestone": "里程碑", "achievement": "成就", "success": "成功", "failure": "失敗",
    "breakthrough": "突破", "setback": "挫折", "recovery": "復甦", "rebound": "反彈",
    "correction": "修正", "consolidation": "盤整", "range-bound": "區間震盪",
    "sideways": "橫盤", "choppy": "震盪", "volatile": "波動劇烈", "stable": "穩定",
    "steady": "穩健", "strong": "強勁", "weak": "疲弱", "mixed": "分歧",
    "positive": "正向", "negative": "負向", "neutral": "中性", "cautious": "謹慎",
    "optimistic": "樂觀", "pessimistic": "悲觀", "bullish": "看多", "bearish": "看空",
    "hawkish": "鷹派", "dovish": "鴿派", "aggressive": "激進", "conservative": "保守",
}

def _local_translate(text: str) -> str:
    """使用本地詞典翻譯常見加密貨幣/金融術語"""
    if not text:
        return text
    result = text
    # 先處理多字詞（按長度降序避免部分匹配）
    for eng, zh in sorted(_CRYPTO_DICT.items(), key=lambda x: -len(x[0])):
        # 整詞匹配（大小寫不敏感）
        import re
        pattern = r"\b" + re.escape(eng) + r"\b"
        result = re.sub(pattern, zh, result, flags=re.IGNORECASE)
    return result

def _translate_to_zh(text: str, timeout: int = 5) -> str:
    """多策略翻譯：快取 → MyMemory → Google → 本地詞典"""
    if not text or not text.strip():
        return text
    cache_key = text[:80].strip()
    # 1. 快取
    if cache_key in _TRANSLATE_CACHE:
        return _TRANSLATE_CACHE[cache_key]
    # 2. 已是中文
    if any("\u4e00" <= ch <= "\u9fff" for ch in text[:20]):
        _TRANSLATE_CACHE[cache_key] = text
        return text
    # 3. 嘗試 MyMemory
    try:
        import urllib.parse
        encoded = urllib.parse.quote(text[:100])
        url = f"https://api.mymemory.translated.net/get?q={encoded}&langpair=en|zh-TW"
        req = urllib.request.Request(url, headers={"User-Agent": "stonkfly/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        translated = data.get("responseData", {}).get("translatedText", "")
        if translated and translated != text and len(translated) > 2:
            _TRANSLATE_CACHE[cache_key] = translated
            _save_translate_cache()
            return translated
    except Exception:
        pass
    # 4. 嘗試 Google 翻譯
    try:
        import urllib.parse
        encoded = urllib.parse.quote(text[:100])
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-TW&dt=t&q={encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        translated = "".join(seg[0] for seg in data[0] if seg[0])
        if translated and translated != text and len(translated) > 2:
            _TRANSLATE_CACHE[cache_key] = translated
            _save_translate_cache()
            return translated
    except Exception:
        pass
    # 5. 本地詞典翻譯（至少翻譯關鍵術語）
    local_result = _local_translate(text)
    if local_result != text:
        _TRANSLATE_CACHE[cache_key] = local_result
        _save_translate_cache()
        return local_result
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
            if not pub:
                # 沒有日期的RSS視為最新
                from datetime import datetime, timezone
                pub = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
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
        ("https://hk.investing.com/rss/news.rss", "宏觀"),
        ("https://www.investing.com/rss/news_25.rss", "加密"),
        ("http://feeds.bbci.co.uk/news/business/rss.xml", "宏觀"),
        ("https://www.cnbc.com/id/100003114/device/rss/rss.html", "宏觀"),
        ("https://feeds.a.dj.com/rss/RSSWorldNews.xml", "宏觀"),
    ]
    all_items = []
    for feed_url, category in rss_feeds:
        items = _fetch_rss(feed_url)
        for item in items[:8]:  # 每個來源取前8則
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
        sort_ts = 0
        try:
            from email.utils import parsedate_to_datetime
            pub_raw = item.get("pub", "")
            try:
                dt = parsedate_to_datetime(pub_raw)
            except Exception:
                from datetime import datetime
                dt = datetime.strptime(pub_raw, "%Y-%m-%d %H:%M:%S")
                from datetime import timezone, timedelta
                dt = dt.replace(tzinfo=timezone.utc)  # investing.com 時間是 UTC
            dt8 = dt.astimezone(UTC8)
            time_str = dt8.strftime("%m/%d %H:%M")
            sort_ts = dt8.timestamp()
        except Exception:
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone(timedelta(hours=8)))
            time_str = now.strftime("%m/%d %H:%M")
            sort_ts = now.timestamp()
        title_zh = _translate_to_zh(title[:80])
        headlines.append({
            "title": title[:80], "title_zh": title_zh, "tag": tag,
            "score": score, "url": item["url"], "time": time_str, "sort_ts": sort_ts,
            "category": category,
        })
    headlines.sort(key=lambda x: x.get("sort_ts", 0), reverse=True)
    total = pos_hits + neg_hits
    news_score = (pos_hits - neg_hits) / total if total > 0 else 0.0
    return {"score": round(max(-1,min(1,news_score)),3), "positive_hits": pos_hits, "negative_hits": neg_hits, "source": "RSS", "headlines": headlines[:15]}


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
