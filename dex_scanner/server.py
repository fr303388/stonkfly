"""迷因幣雷達 - 含模擬交易"""
import requests, time, json
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, send_file

app = Flask(__name__)
UTC8 = timezone(timedelta(hours=8))
CACHE = {"data": None, "ts": 0}
PORTFOLIO_FILE = r'C:\Users\ANGEL\Doubao\chats\2026-09-12\new-chat\dex_scanner\portfolio.json'
REC_FILE = r'C:\Users\ANGEL\Doubao\chats\2026-09-12\new-chat\dex_scanner\rec_tracker.json'

def load_portfolio():
    try:
        with open(PORTFOLIO_FILE, "r") as f:
            return json.load(f)
    except:
        return {"positions": [], "started": None, "total_invested": 0}

def save_portfolio(p):
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)

IMG_CACHE = {}
def fetch_image(url):
    if url in IMG_CACHE: return IMG_CACHE[url]
    try:
        pair_addr = url.rstrip("/").split("/")[-1]
        print(f"[IMG] fetching {pair_addr}", flush=True)
        r = requests.get(f"https://api.dexscreener.com/latest/dex/pairs/solana/{pair_addr}", timeout=8)
        pairs = r.json().get("pairs",[])
        if pairs:
            img = (pairs[0].get("info",{}) or {}).get("imageUrl","")
            print(f"[IMG] got: {img[:60]}", flush=True)
            IMG_CACHE[url] = img
            return img
        print("[IMG] no pairs", flush=True)
    except Exception as e:
        print(f"[IMG] error: {e}", flush=True)
    IMG_CACHE[url] = ""
    return ""

def score_token(t):
    score = 0; reasons = []
    h1, h24 = t.get("change_1h",0), t.get("change_24h",0)
    vol, liq, br = t.get("volume_24h",0), t.get("liquidity",0), t.get("buy_ratio",50)
    if h1 > 30: score += 2; reasons.append("1h強勢")
    elif h1 > 10: score += 1; reasons.append("1h上漲")
    elif h1 < -10: score -= 2; reasons.append("1h暴跌")
    elif h1 < -30: score -= 3; reasons.append("1h崩盤")
    if 10 < h24 <= 50: score += 2; reasons.append("健康上漲")
    elif 50 < h24 <= 150: score += 1; reasons.append("強勢噴發")
    elif h24 > 200: score -= 1; reasons.append("高位追風險")
    elif h24 < -30: score -= 3; reasons.append("死亡螺旋")
    elif h24 < -50: score -= 5; reasons.append("已崩盤")
    if vol > 200000: score += 1.5; reasons.append("大量")
    elif vol > 50000: score += 0.5
    if liq > 30000: score += 1; reasons.append("流動性足")
    elif liq < 5000: score -= 1
    if br > 70: score += 1.5; reasons.append("買盤極強")
    elif br < 40: score -= 1.5; reasons.append("賣壓大")
    rating = "🔥強推薦" if score>=4 else "✅可關注" if score>=2 else "⚪觀望" if score>=0 else "⚠️危險" if score>=-2 else "❌避開"
    return round(score,1), rating, reasons

def fetch_meme_coins():
    if CACHE["data"] and time.time() - CACHE["ts"] < 15:
        return CACHE["data"]
    all_tokens = []
    try:
        r = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=10)
        for prof in r.json():
            chain, addr = prof.get("chainId",""), prof.get("tokenAddress","")
            if not addr or chain not in ("solana","base"): continue
            try:
                pr = requests.get(f"https://api.dexscreener.com/token-pairs/v1/{chain}/{addr}", timeout=8)
                for p in pr.json():
                    if p.get("baseToken",{}).get("address","").lower() != addr.lower(): continue
                    base = p.get("baseToken",{}).get("symbol","?")
                    name = p.get("baseToken",{}).get("name","")
                    try: price=float(p.get("priceUsd",0) or 0)
                    except: price=0
                    try: h24=float(p.get("priceChange",{}).get("h24",0) or 0)
                    except: h24=0
                    try: h1=float(p.get("priceChange",{}).get("h1",0) or 0)
                    except: h1=0
                    try: vol=float(p.get("volume",{}).get("h24",0) or 0)
                    except: vol=0
                    try: liq=float(p.get("liquidity",{}).get("usd",0) or 0)
                    except: liq=0
                    try: buys=p.get("txns",{}).get("h24",{}).get("buys",0)
                    except: buys=0
                    try: sells=p.get("txns",{}).get("h24",{}).get("sells",0)
                    except: sells=0
                    if liq < 2000: continue
                    br = round(buys/(buys+sells)*100) if (buys+sells)>0 else 50
                    t = {"symbol":f"{base}/SOL","name":name,"price":price,"change_1h":round(h1,1),"change_24h":round(h24,1),"volume_24h":round(vol),"liquidity":round(liq),"chain":chain,"url":p.get("url",""),"buy_ratio":br,"address":addr,"image":(p.get("info",{}) or {}).get("imageUrl","")}
                    sc, rating, reasons = score_token(t)
                    t["score"], t["rating"], t["reasons"] = sc, rating, reasons
                    all_tokens.append(t)
                    break
            except: pass
    except: pass
    all_tokens.sort(key=lambda x: x["score"], reverse=True)
    
    # 模擬組合：本金$1000，每筆$100，停利+50% / 停損-50%
    pf = load_portfolio()
    pf.setdefault("trades", [])
    pf.setdefault("capital", 1000)
    if not pf["positions"] and all_tokens:
        now = datetime.now(UTC8).strftime("%Y-%m-%d %H:%M")
        pf["started"] = now
        pf["total_invested"] = 0
        for t in all_tokens[:3]:
            pf["positions"].append({
                "symbol": t["symbol"],
                "buy_price": t["price"],
                "buy_time": now,
                "invested": 100,
                "shares": 100 / t["price"] if t["price"] > 0 else 0,
                "url": t["url"],
                "buy_score": t["score"],
                "address": t.get("address",""),
                "chain": t.get("chain",""),
                "image": t.get("image","")
            })
            pf["total_invested"] += 100
        save_portfolio(pf)
    
    # 計算即時盈虧
    for pos in pf["positions"]:
        current = next((t for t in all_tokens if t["symbol"] == pos["symbol"]), None)
        if current:
            pos["current_price"] = current["price"]
            if current.get("image"): pos["image"] = current["image"]
        elif pos.get("address") and pos.get("chain"):
            # 持倉幣已不在最新列表，直接查詢價格
            try:
                pr = requests.get(f"https://api.dexscreener.com/token-pairs/v1/{pos['chain']}/{pos['address']}", timeout=5)
                pairs = pr.json()
                if pairs:
                    best = max(pairs, key=lambda p: float(p.get("liquidity",{}).get("usd",0) or 0))
                    pos["current_price"] = float(best.get("priceUsd",0) or 0)
                    img = (best.get("info",{}) or {}).get("imageUrl","")
                    if img: pos["image"] = img
            except:
                pos["current_price"] = pos.get("current_price", pos["buy_price"])
        else:
            try:
                pair_addr = pos.get("url","").rstrip("/").split("/")[-1]
                pr = requests.get(f"https://api.dexscreener.com/latest/dex/pairs/solana/{pair_addr}", timeout=5)
                pairs = pr.json().get("pairs",[])
                if pairs:
                    pos["current_price"] = float(pairs[0].get("priceUsd",0) or 0)
                    img = (pairs[0].get("info",{}) or {}).get("imageUrl","")
                    if img: pos["image"] = img
            except:
                pos["current_price"] = pos.get("current_price", pos["buy_price"])
        pos["current_value"] = pos["shares"] * pos["current_price"]
        pos["pnl"] = pos["current_value"] - pos["invested"]
        pos["pnl_pct"] = round((pos["pnl"] / pos["invested"]) * 100, 1)
        if not pos.get("image") and pos.get("url"):
            pos["image"] = fetch_image(pos["url"])
            print(f"[IMG] {pos['symbol']} -> {pos['image'][:60]}", flush=True)
    
    # 停利+50% / 停損-50%
    TAKE_PROFIT_PCT = 50.0
    STOP_LOSS_PCT = -50.0
    kept = []
    now_str = datetime.now(UTC8).strftime("%Y-%m-%d %H:%M")
    for pos in pf["positions"]:
        sell_reason = None
        if pos["pnl_pct"] >= TAKE_PROFIT_PCT:
            sell_reason = f"停利+{pos['pnl_pct']}%"
        elif pos["pnl_pct"] <= STOP_LOSS_PCT:
            sell_reason = f"停損{pos['pnl_pct']}%"
        if sell_reason:
            pf["trades"].append({
                "time": now_str, "symbol": pos["symbol"],
                "action": "SELL", "buy_price": pos["buy_price"],
                "sell_price": pos["current_price"], "pnl": round(pos["pnl"],2),
                "pnl_pct": pos["pnl_pct"], "reason": sell_reason
            })
            print(f"[SELL] {pos['symbol']} {sell_reason} 盈餘${round(pos['pnl'],2)}", flush=True)
        else:
            kept.append(pos)
    
    # 主動追蹤：新推薦幣(score>=4)出現時自動買入$100，最多10倉（$1000本金）
    held_syms = [p["symbol"] for p in kept]
    fresh = [t for t in all_tokens if t["symbol"] not in held_syms and t["score"] >= 4]
    for t in fresh:
        if len(kept) >= 10: break
        now2 = datetime.now(UTC8).strftime("%Y-%m-%d %H:%M")
        kept.append({
            "symbol": t["symbol"], "buy_price": t["price"], "buy_time": now2,
            "invested": 100, "shares": 100/t["price"] if t["price"]>0 else 0,
            "url": t["url"], "buy_score": t["score"],
            "address": t.get("address",""), "chain": t.get("chain",""),
            "image": t.get("image","")
        })
        pf["trades"].append({
            "time": now2, "symbol": t["symbol"],
            "action": "BUY", "buy_price": t["price"],
            "sell_price": 0, "pnl": 0, "pnl_pct": 0,
            "reason": f"推薦score={t['score']}"
        })
        pf["total_invested"] += 100
        print(f"[NEW] 買入 {t['symbol']} @ ${t['price']} score={t['score']}", flush=True)

    pf["positions"] = kept
    save_portfolio(pf)
    
    pf["total_value"] = sum(p.get("current_value", p["invested"]) for p in pf["positions"])
    pf["total_invested"] = sum(p["invested"] for p in pf["positions"])
    pf["total_pnl"] = pf["total_value"] - pf["total_invested"]
    pf["total_pnl_pct"] = round((pf["total_pnl"] / pf["total_invested"]) * 100, 1) if pf["total_invested"] > 0 else 0
    # 從$1000本金開始的總盈虧（含已實現）
    realized = sum(t.get("pnl", 0) for t in pf.get("trades", []) if t.get("action") == "SELL")
    cash_left = pf.get("capital", 1000) - pf["total_invested"] + realized
    pf["cash_left"] = round(cash_left, 2)
    pf["realized_pnl"] = round(realized, 2)
    pf["total_equity"] = round(pf["total_value"] + cash_left, 2)
    pf["all_time_pnl"] = round(pf["total_equity"] - pf.get("capital", 1000), 2)
    pf["all_time_pnl_pct"] = round((pf["all_time_pnl"] / pf.get("capital", 1000)) * 100, 1)
    
    # 潛力股：剛剛起步、買盤進入但還沒噴發
    holdings = [p["symbol"] for p in pf["positions"]]
    potential = [
        t for t in all_tokens
        if t["symbol"] not in holdings
        and t["liquidity"] > 3000
        and t["buy_ratio"] >= 50
        and -20 < t["change_1h"] < 20
        and -20 < t["change_24h"] < 50
        and t["volume_24h"] > 5000
    ]
    potential.sort(key=lambda x: x["buy_ratio"], reverse=True)
    
    # Telegram 新幣通知 - 從 stonkfly .env 讀取
    TOKEN, CHAT_ID = "", ""
    try:
        envf = open(r"C:\Users\ANGEL\Doubao\chats\2026-09-12\new-chat\stonkfly\.env", encoding="utf-8").read()
        for line in envf.splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="): TOKEN = line.split("=",1)[1].strip()
            if line.startswith("TELEGRAM_CHAT_ID="): CHAT_ID = line.split("=",1)[1].strip()
    except: pass
    SEEN_FILE = r'C:\Users\ANGEL\Doubao\chats\2026-09-12\new-chat\dex_scanner\seen_coins.json'
    try:
        with open(SEEN_FILE, "r") as f: seen = set(json.load(f))
    except: seen = set()
    
    hot_tokens = [t for t in all_tokens if t["score"] >= 4]
    new_coins = []
    for t in hot_tokens + potential:
        if t["symbol"] not in seen:
            new_coins.append(t)
            seen.add(t["symbol"])
    
    if new_coins and TOKEN and CHAT_ID:
        for t in new_coins[:3]:
            is_hot = t["score"] >= 4
            emoji = "🔥" if is_hot else "🌱"
            p_str = f"${t['price']:.8f}" if t['price'] < 0.01 else f"${t['price']:.4f}"
            msg = f"{emoji} 新幣警報\n\n幣種: {t['symbol']}\n名稱: {t['name']}\n價格: {p_str}\n1h: {t['change_1h']:+.1f}%\n24h: {t['change_24h']:+.1f}%\n買盤: {t['buy_ratio']}%\n流動性: ${t['liquidity']:,.0f}\n\n{t['url']}"
            try:
                requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                    data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
            except: pass
    
    try:
        with open(SEEN_FILE, "w") as f: json.dump(list(seen), f)
    except: pass
    
    trending = []
    try:
        tr = requests.get("https://api.coingecko.com/api/v3/search/trending", timeout=8)
        for c in tr.json().get("coins", [])[:10]:
            trending.append({"rank": c["item"]["score"]+1, "name": c["item"]["name"], "symbol": c["item"]["symbol"].upper(), "price_btc": c["item"].get("price_btc",0), "thumb": c["item"].get("thumb","")})
    except: pass
    # 補充持倉圖片
    for pos in pf["positions"]:
        if not pos.get("image") and pos.get("url"):
            pos["image"] = fetch_image(pos["url"])

    # 即時推薦追蹤：新推薦出現時模擬買入$100
    try:
        with open(REC_FILE, "r") as rf: rec_tracker = json.load(rf)
    except: rec_tracker = {}
    rec_symbols = {t["symbol"]: t for t in all_tokens if t["score"] >= 4}
    for sym, t in rec_symbols.items():
        if sym not in rec_tracker:
            rec_tracker[sym] = {"buy_price": t["price"], "buy_time": datetime.now(UTC8).strftime("%H:%M"), "image": t.get("image",""), "url": t["url"]}
        rec_tracker[sym]["current_price"] = t["price"]
        rec_tracker[sym]["pnl"] = round((t["price"] - rec_tracker[sym]["buy_price"]) / rec_tracker[sym]["buy_price"] * 100, 1) if rec_tracker[sym]["buy_price"] > 0 else 0
    # 清理超過1小時沒出現的
    now_ts = time.time()
    rec_tracker = {k:v for k,v in rec_tracker.items() if k in rec_symbols}
    with open(REC_FILE, "w") as rf: json.dump(rec_tracker, rf, ensure_ascii=False)

    result = {"scanned_at": datetime.now(UTC8).strftime("%H:%M:%S"), "total": len(all_tokens), "tokens": all_tokens[:25], "portfolio": pf, "potential": potential[:8], "trending": trending, "rec_tracker": rec_tracker}
    CACHE["data"] = result; CACHE["ts"] = time.time()
    return result

@app.route("/api/dex")
def api_dex(): return jsonify(fetch_meme_coins())

@app.route("/testimg")
def testimg():
    url = "https://dexscreener.com/solana/8l39ujshgnzckrtwqfdqfzf1iv8ypwgfkaskvrkegypc"
    return jsonify({"result": fetch_image(url)})
@app.route("/alert.mp3")
def alert(): return send_file("alert.mp3")
@app.route("/")
def index(): return send_file("dashboard.html")
if __name__ == "__main__":
    print("迷因幣雷達: http://127.0.0.1:8770")
    app.run(host="127.0.0.1", port=8770, debug=False)
