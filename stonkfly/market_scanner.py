"""
市場掃描器：偵測強勢幣和埋伏幣
- 強勢幣：已經在噴的貨幣（順勢跟進）
- 埋伏幣：整理完畢準備噴發的貨幣（提前佈局）
每15分鐘掃描一次，快取結果
"""
import json
import time
import urllib.request
from pathlib import Path
from datetime import datetime, timezone, timedelta

UTC8 = timezone(timedelta(hours=8))
SCAN_INTERVAL = 900  # 15分鐘掃描一次
MIN_24H_VOLUME = 5_000_000  # 最低24小時成交量500萬USDT
TOP_N = 20  # 每個排行榜取前20名

CACHE_FILE = Path(__file__).parent.parent / "runs" / "paper" / "market_scan_cache.json"


def _fetch(url: str, timeout: int = 10) -> dict:
    """發送HTTP GET請求"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}


def fetch_24h_ticker() -> list:
    """獲取所有USDT交易對的24小時數據"""
    url = "https://api.binance.com/api/v3/ticker/24hr"
    data = _fetch(url)
    if not data:
        return []
    # 只保留USDT交易對，且排除槓桿代幣和穩定幣
    exclude_keywords = ["UP", "DOWN", "BULL", "BEAR", "USDC", "TUSD", "USDP", "FDUSD", "DAI", "BUSD"]
    result = []
    for item in data:
        symbol = item.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue
        if any(kw in symbol for kw in exclude_keywords):
            continue
        try:
            volume_usdt = float(item.get("quoteVolume", 0))
            if volume_usdt < MIN_24H_VOLUME:
                continue
            result.append({
                "symbol": symbol,
                "price": float(item.get("lastPrice", 0)),
                "change_24h": float(item.get("priceChangePercent", 0)),
                "volume_24h": volume_usdt,
                "high_24h": float(item.get("highPrice", 0)),
                "low_24h": float(item.get("lowPrice", 0)),
            })
        except (ValueError, TypeError):
            continue
    return result


def fetch_klines(symbol: str, interval: str = "15m", limit: int = 100) -> list:
    """抓取K線數據"""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    data = _fetch(url)
    if not data:
        return []
    return [{"time": k[0] / 1000, "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in data]


def calc_rsi(klines: list, period: int = 14) -> float:
    """計算RSI"""
    if len(klines) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(klines)):
        change = klines[i]["close"] - klines[i-1]["close"]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def detect_trend(klines: list) -> str:
    """趨勢判斷"""
    if len(klines) < 25:
        return "neutral"
    short_ma = sum(k["close"] for k in klines[-5:]) / 5
    long_ma = sum(k["close"] for k in klines[-20:]) / 20
    if short_ma > long_ma * 1.005:
        return "uptrend"
    elif short_ma < long_ma * 0.995:
        return "downtrend"
    return "neutral"


def calc_bollinger_bandwidth(klines: list, period: int = 20) -> float:
    """計算布林帶寬度（相對於價格的百分比）"""
    if len(klines) < period:
        return 0
    closes = [k["close"] for k in klines[-period:]]
    ma = sum(closes) / period
    variance = sum((c - ma) ** 2 for c in closes) / period
    std = variance ** 0.5
    return (std * 2 / ma) * 100 if ma > 0 else 0


def calc_strong_score(ticker: dict, klines: list, btc_change: float) -> tuple:
    """
    計算強勢分數（0-100）
    回傳 (分數, 細節dict)
    """
    score = 0
    details = {}

    # 1. 24h漲幅超越BTC (+20)
    relative_gain = ticker["change_24h"] - btc_change
    if relative_gain > 5:
        score += 20
        details["relative_gain"] = f"+{relative_gain:.1f}%"
    elif relative_gain > 2:
        score += 12
        details["relative_gain"] = f"+{relative_gain:.1f}%"
    elif relative_gain > 0:
        score += 5
        details["relative_gain"] = f"+{relative_gain:.1f}%"
    else:
        details["relative_gain"] = f"{relative_gain:.1f}%"

    # 2. 多時間框上漲趨勢 (+20)
    trend_15m = detect_trend(klines)
    klines_1h = fetch_klines(ticker["symbol"], "1h", 50)
    trend_1h = detect_trend(klines_1h) if klines_1h else "neutral"
    trend_score = 0
    if trend_15m == "uptrend":
        trend_score += 10
    if trend_1h == "uptrend":
        trend_score += 10
    score += trend_score
    details["trend"] = f"15m:{trend_15m} 1h:{trend_1h}"

    # 3. 成交量放大 (+15)
    if len(klines) >= 30:
        avg_vol_20 = sum(k["volume"] for k in klines[-20:]) / 20
        recent_vol = sum(k["volume"] for k in klines[-4:]) / 4
        vol_ratio = recent_vol / avg_vol_20 if avg_vol_20 > 0 else 0
        if vol_ratio > 2:
            score += 15
        elif vol_ratio > 1.5:
            score += 10
        elif vol_ratio > 1.2:
            score += 5
        details["volume_ratio"] = f"{vol_ratio:.1f}x"
    else:
        details["volume_ratio"] = "N/A"

    # 4. 創24h新高 (+15)
    if ticker["price"] >= ticker["high_24h"] * 0.995:
        score += 15
        details["near_high"] = "接近新高"
    elif ticker["price"] >= ticker["high_24h"] * 0.97:
        score += 8
        details["near_high"] = "接近新高"
    else:
        details["near_high"] = "否"

    # 5. RSI在50-70（強勢但未超買）(+15)
    rsi = calc_rsi(klines)
    if 50 <= rsi <= 70:
        score += 15
        details["rsi"] = f"{rsi:.0f}"
    elif 45 <= rsi < 50:
        score += 8
        details["rsi"] = f"{rsi:.0f}"
    elif 70 < rsi <= 80:
        score += 5
        details["rsi"] = f"{rsi:.0f}"
    else:
        details["rsi"] = f"{rsi:.0f}"

    # 6. 均線多頭排列 (+15)
    if len(klines) >= 20:
        ma5 = sum(k["close"] for k in klines[-5:]) / 5
        ma10 = sum(k["close"] for k in klines[-10:]) / 10
        ma20 = sum(k["close"] for k in klines[-20:]) / 20
        if ma5 > ma10 > ma20:
            score += 15
            details["ma_alignment"] = "多頭排列"
        elif ma5 > ma10:
            score += 7
            details["ma_alignment"] = "短期多頭"
        else:
            details["ma_alignment"] = "否"
    else:
        details["ma_alignment"] = "N/A"

    return score, details


def calc_potential_score(ticker: dict, klines: list) -> tuple:
    """
    計算埋伏分數（0-100）- 整理完畢準備噴發
    回傳 (分數, 細節dict)
    """
    score = 0
    details = {}

    if len(klines) < 30:
        return 0, {"error": "數據不足"}

    # 1. 橫盤整理（最近50根振幅<8%）(+20)
    recent_50 = klines[-50:] if len(klines) >= 50 else klines
    high_50 = max(k["high"] for k in recent_50)
    low_50 = min(k["low"] for k in recent_50)
    amplitude = (high_50 - low_50) / low_50 * 100 if low_50 > 0 else 100
    if amplitude < 5:
        score += 20
        details["amplitude"] = f"{amplitude:.1f}%"
    elif amplitude < 8:
        score += 12
        details["amplitude"] = f"{amplitude:.1f}%"
    elif amplitude < 12:
        score += 5
        details["amplitude"] = f"{amplitude:.1f}%"
    else:
        details["amplitude"] = f"{amplitude:.1f}%"

    # 2. 量能萎縮（最近10根成交量<20根平均的0.7倍）(+20)
    avg_vol_20 = sum(k["volume"] for k in klines[-20:]) / 20
    avg_vol_10 = sum(k["volume"] for k in klines[-10:]) / 10
    vol_shrink = avg_vol_10 / avg_vol_20 if avg_vol_20 > 0 else 1
    if vol_shrink < 0.5:
        score += 20
        details["volume_shrink"] = f"{vol_shrink:.1f}x"
    elif vol_shrink < 0.7:
        score += 15
        details["volume_shrink"] = f"{vol_shrink:.1f}x"
    elif vol_shrink < 0.85:
        score += 8
        details["volume_shrink"] = f"{vol_shrink:.1f}x"
    else:
        details["volume_shrink"] = f"{vol_shrink:.1f}x"

    # 3. 突放巨量但價格未大漲（莊家吸籌）(+20)
    accumulation = False
    for i in range(-5, -1):
        if abs(i) > len(klines):
            continue
        k = klines[i]
        vol_ratio = k["volume"] / avg_vol_20 if avg_vol_20 > 0 else 0
        price_change = abs(k["close"] - k["open"]) / k["open"] * 100 if k["open"] > 0 else 0
        if vol_ratio > 2.5 and price_change < 3:
            accumulation = True
            break
    if accumulation:
        score += 20
        details["accumulation"] = "有吸籌跡象"
    else:
        details["accumulation"] = "否"

    # 4. 布林帶收斂 (+15)
    current_bw = calc_bollinger_bandwidth(klines)
    # 比較歷史布林帶寬度
    historical_bw = []
    for i in range(-40, -20):
        if abs(i) <= len(klines):
            sub = klines[:len(klines) + i]
            bw = calc_bollinger_bandwidth(sub)
            if bw > 0:
                historical_bw.append(bw)
    if historical_bw and current_bw > 0:
        avg_hist_bw = sum(historical_bw) / len(historical_bw)
        bw_ratio = current_bw / avg_hist_bw
        if bw_ratio < 0.6:
            score += 15
            details["bollinger"] = f"收斂{bw_ratio:.1f}x"
        elif bw_ratio < 0.8:
            score += 8
            details["bollinger"] = f"收斂{bw_ratio:.1f}x"
        else:
            details["bollinger"] = f"{bw_ratio:.1f}x"
    else:
        details["bollinger"] = "N/A"

    # 5. RSI從低位回升（30-50之間）(+15)
    rsi = calc_rsi(klines)
    if 35 <= rsi <= 50:
        score += 15
        details["rsi"] = f"{rsi:.0f}"
    elif 30 <= rsi < 35:
        score += 10
        details["rsi"] = f"{rsi:.0f}"
    elif 50 < rsi <= 55:
        score += 8
        details["rsi"] = f"{rsi:.0f}"
    else:
        details["rsi"] = f"{rsi:.0f}"

    # 6. 底部背馳（價格創新低但RSI未創新低）(+10)
    if len(klines) >= 30:
        # 找最近兩個低點
        lows = []
        for i in range(2, len(klines) - 2):
            if klines[i]["low"] < klines[i-1]["low"] and klines[i]["low"] < klines[i+1]["low"]:
                lows.append((i, klines[i]["low"]))
        if len(lows) >= 2:
            last_low_idx, last_low_price = lows[-1]
            prev_low_idx, prev_low_price = lows[-2]
            if last_low_price < prev_low_price:
                # 計算兩個低點的RSI
                rsi_at_last = calc_rsi(klines[:last_low_idx + 1])
                rsi_at_prev = calc_rsi(klines[:prev_low_idx + 1])
                if rsi_at_last > rsi_at_prev:
                    score += 10
                    details["divergence"] = "底部背馳"
                else:
                    details["divergence"] = "否"
            else:
                details["divergence"] = "價格未創新低"
        else:
            details["divergence"] = "低點不足"
    else:
        details["divergence"] = "N/A"

    return score, details


def scan_market() -> dict:
    """掃描整個市場，回傳強勢幣和埋伏幣排行榜"""
    # 檢查快取
    if CACHE_FILE.exists():
        try:
            cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if time.time() - cache.get("scanned_at", 0) < SCAN_INTERVAL:
                return cache
        except Exception:
            pass

    print(f"[市場掃描] 開始掃描...")
    tickers = fetch_24h_ticker()
    if not tickers:
        print("[市場掃描] 獲取24h數據失敗")
        return {"strong": [], "potential": [], "scanned_at": time.time(), "error": "獲取數據失敗"}

    # 獲取BTC的24h漲幅作為基準
    btc_change = 0
    for t in tickers:
        if t["symbol"] == "BTCUSDT":
            btc_change = t["change_24h"]
            break

    # 按24h成交量排序，取前80名進行深度分析
    tickers_sorted = sorted(tickers, key=lambda x: x["volume_24h"], reverse=True)[:80]

    strong_list = []
    potential_list = []

    for i, ticker in enumerate(tickers_sorted):
        symbol = ticker["symbol"]
        klines = fetch_klines(symbol, "15m", 100)
        if len(klines) < 30:
            continue

        # 強勢分數
        strong_score, strong_details = calc_strong_score(ticker, klines, btc_change)
        if strong_score >= 50:
            strong_list.append({
                "symbol": symbol,
                "price": ticker["price"],
                "change_24h": ticker["change_24h"],
                "volume_24h": ticker["volume_24h"],
                "score": strong_score,
                "details": strong_details,
            })

        # 埋伏分數（只對24h漲幅在-5%到+10%之間的幣種計算，排除已經在噴的）
        if -5 <= ticker["change_24h"] <= 10:
            potential_score, potential_details = calc_potential_score(ticker, klines)
            if potential_score >= 50:
                potential_list.append({
                    "symbol": symbol,
                    "price": ticker["price"],
                    "change_24h": ticker["change_24h"],
                    "volume_24h": ticker["volume_24h"],
                    "score": potential_score,
                    "details": potential_details,
                })

        if (i + 1) % 20 == 0:
            print(f"[市場掃描] 已掃描 {i+1}/{len(tickers_sorted)}")

    # 排序並取前N名
    strong_list = sorted(strong_list, key=lambda x: x["score"], reverse=True)[:TOP_N]
    potential_list = sorted(potential_list, key=lambda x: x["score"], reverse=True)[:TOP_N]

    result = {
        "strong": strong_list,
        "potential": potential_list,
        "scanned_at": time.time(),
        "scanned_count": len(tickers_sorted),
        "btc_change_24h": btc_change,
    }

    # 儲存快取
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    print(f"[市場掃描] 完成：強勢幣{len(strong_list)}個，埋伏幣{len(potential_list)}個")
    return result


def get_scan_result() -> dict:
    """取得掃描結果（優先使用快取）"""
    if CACHE_FILE.exists():
        try:
            cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            return cache
        except Exception:
            pass
    return scan_market()


if __name__ == "__main__":
    print("市場掃描器啟動")
    result = scan_market()
    print(f"\n🔥 強勢幣 TOP 10:")
    for item in result["strong"][:10]:
        print(f"  {item['symbol']}: {item['score']}分 | 24h {item['change_24h']:+.1f}% | {item['details']}")
    print(f"\n💎 埋伏幣 TOP 10:")
    for item in result["potential"][:10]:
        print(f"  {item['symbol']}: {item['score']}分 | 24h {item['change_24h']:+.1f}% | {item['details']}")
