"""
多幣種分型交易機器人（模擬）
使用纏論分型訊號對 BTC ETH SOL ZEC ASTER DOGE WLD 進行模擬交易
只交易啟動後新形成的分型，加入RSI過濾和冷卻時間
買賣即時發送 Telegram 通知
"""
import os
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone, timedelta
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

UTC8 = timezone(timedelta(hours=8))

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "DOGEUSDT", "WLDUSDT", "ASTERUSDT", "ZECUSDT"]
INITIAL_CASH = 1000.0  # 每個幣種初始資金
STATE_FILE = Path(__file__).parent.parent / "runs" / "paper" / "fractal_multi_state.json"
CHECK_INTERVAL = 60  # 秒
COOLDOWN_AFTER_TRADE = 300  # 交易後冷卻5分鐘
TELEGRAM_NOTIFY_DEFAULT = os.environ.get("TELEGRAM_NOTIFY_FRACTAL", "true").lower() == "true"
RSI_OVERSOLD = 35  # RSI低於此值才考慮買入
RSI_OVERBOUGHT = 65  # RSI高於此值才考慮賣出
VOLUME_SURGE_RATIO = 1.2  # 成交量放大倍數（超過平均20%才算放量）
MULTI_TIMEFRAME_CONFIRM = True  # 多時間框共振確認
BTC_MARKET_FILTER = True  # BTC市場過濾器（BTC下跌時不買入）


def _load_env():
    """載入 .env 環境變數"""
    candidates = [
        Path(__file__).parent.parent / ".env",
        Path.cwd() / ".env",
    ]
    for env_path in candidates:
        if env_path.exists():
            try:
                for line in env_path.read_text(encoding="utf-8-sig").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, val = line.partition("=")
                        os.environ.setdefault(key.strip(), val.strip())
                break
            except Exception:
                pass


def fmt_price(price: float) -> str:
    """價格格式化：≥1000→0位，≥100→2位，≥1→4位，<1→6位"""
    if price >= 1000:
        return f"${price:,.0f}"
    elif price >= 100:
        return f"${price:,.2f}"
    elif price >= 1:
        return f"${price:,.4f}"
    else:
        return f"${price:,.8f}"


def send_telegram(message: str) -> bool:
    """發送 Telegram 訊息"""
    _load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    enabled = os.environ.get("TELEGRAM_ENABLED", "false").lower() == "true"
    if not enabled or not token or not chat_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true"
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


def fetch_klines(symbol: str, interval: str = "5m", limit: int = 100) -> list:
    """從幣安抓取K線"""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [{"time": k[0] / 1000, "open": float(k[1]), "high": float(k[2]),
                 "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in data]
    except Exception as e:
        print(f"[{symbol}] 抓取K線失敗: {e}")
        return []


def calc_rsi(klines: list, period: int = 14) -> float:
    """計算RSI"""
    if len(klines) < period + 1:
        return 50.0
    gains = []
    losses = []
    for i in range(1, len(klines)):
        change = klines[i]["close"] - klines[i-1]["close"]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def detect_trend(klines: list, period: int = 20) -> str:
    """簡單趨勢判斷：基於移動平均線"""
    if len(klines) < period + 5:
        return "neutral"
    # 短期均線 vs 長期均線
    short_ma = sum(k["close"] for k in klines[-5:]) / 5
    long_ma = sum(k["close"] for k in klines[-period:]) / period
    if short_ma > long_ma * 1.005:
        return "uptrend"
    elif short_ma < long_ma * 0.995:
        return "downtrend"
    return "neutral"


def calc_avg_volume(klines: list, period: int = 20) -> float:
    """計算最近period根K線的平均成交量"""
    if len(klines) < 5:
        return 0
    recent = klines[-min(period, len(klines)):]
    return sum(k["volume"] for k in recent) / len(recent)


def get_fractal_volume(fractal: dict, klines: list) -> float:
    """取得分型K線的成交量"""
    if not fractal or "index" not in fractal:
        return 0
    idx = fractal["index"]
    if 0 <= idx < len(klines):
        return klines[idx]["volume"]
    return 0


# BTC趨勢快取（避免每個幣種都重複抓取）
_btc_trend_cache = {"trend": "neutral", "timestamp": 0}

def get_btc_trend() -> str:
    """取得BTC趨勢（快取60秒）"""
    now = time.time()
    if now - _btc_trend_cache["timestamp"] < 60:
        return _btc_trend_cache["trend"]
    klines = fetch_klines("BTCUSDT", "5m", 50)
    if len(klines) < 20:
        _btc_trend_cache["trend"] = "neutral"
    else:
        _btc_trend_cache["trend"] = detect_trend(klines)
    _btc_trend_cache["timestamp"] = now
    return _btc_trend_cache["trend"]


def calc_percentile(klines: list, period: int = 50) -> float:
    """計算目前價格在最近period根K線中的百分位"""
    if len(klines) < 10:
        return 50.0
    recent = klines[-min(period, len(klines)):]
    prices = [k["close"] for k in recent]
    current = klines[-1]["close"]
    below = sum(1 for p in prices if p <= current)
    return below / len(prices) * 100


def detect_latest_fractal(klines: list) -> dict:
    """偵測最新的分型（只看倒數第3根，需要左右各一根確認）"""
    if len(klines) < 5:
        return None

    # 只檢查倒數第3根（需要i-1, i, i+1三根確認，i+2用於加強確認）
    i = len(klines) - 3  # 倒數第3根，已完成且有右邊確認

    # 頂分型：中間最高，左右都低
    is_top = (klines[i]["high"] > klines[i-1]["high"] and
              klines[i]["high"] > klines[i+1]["high"] and
              klines[i-1]["high"] > klines[i-2]["high"] and
              klines[i+1]["high"] > klines[i+2]["high"])

    # 底分型：中間最低，左右都高
    is_bottom = (klines[i]["low"] < klines[i-1]["low"] and
                 klines[i]["low"] < klines[i+1]["low"] and
                 klines[i-1]["low"] < klines[i-2]["low"] and
                 klines[i+1]["low"] < klines[i+2]["low"])

    if is_top:
        return {"type": "top", "price": klines[i]["high"], "time": klines[i]["time"], "index": i}
    if is_bottom:
        return {"type": "bottom", "price": klines[i]["low"], "time": klines[i]["time"], "index": i}
    return None


def load_state() -> dict:
    """載入多幣種狀態"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
            # 確保所有幣種都有狀態
            for sym in SYMBOLS:
                if sym not in state["symbols"]:
                    state["symbols"][sym] = {
                        "cash": INITIAL_CASH, "position": 0, "avg_entry": 0,
                        "trades": [], "last_fractal_time": 0, "realized_pnl": 0,
                        "last_trade_time": 0, "warmed_up": False,
                    }
                # 確保新欄位存在
                s = state["symbols"][sym]
                s.setdefault("last_trade_time", 0)
                s.setdefault("warmed_up", False)
                s.setdefault("last_check_time", 0)
                s.setdefault("current_rsi", 0)
                s.setdefault("current_price", 0)
                s.setdefault("latest_fractal", None)
                s.setdefault("last_action", "待機中")
                s.setdefault("activity_log", [])
                s.setdefault("notify_enabled", TELEGRAM_NOTIFY_DEFAULT)
            state.setdefault("notify_enabled", TELEGRAM_NOTIFY_DEFAULT)
            return state
        except Exception:
            pass
    # 初始化
    state = {"symbols": {}, "start_time": datetime.now(UTC8).timestamp(), "notify_enabled": TELEGRAM_NOTIFY_DEFAULT}
    for sym in SYMBOLS:
        state["symbols"][sym] = {
            "cash": INITIAL_CASH,
            "position": 0,
            "avg_entry": 0,
            "trades": [],
            "last_fractal_time": 0,
            "realized_pnl": 0,
            "last_trade_time": 0,
            "warmed_up": False,
            "last_check_time": 0,
            "current_rsi": 0,
            "current_price": 0,
            "last_candle_up": True,
            "recent_closes": [],
            "latest_fractal": None,
            "last_action": "待機中",
            "activity_log": [],
            "notify_enabled": TELEGRAM_NOTIFY_DEFAULT,
        }
    return state


def save_state(state: dict):
    """儲存狀態"""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def run_cycle():
    """執行一輪檢查"""
    state = load_state()
    now = datetime.now(UTC8)
    now_ts = now.timestamp()
    notify_enabled = state.get("notify_enabled", TELEGRAM_NOTIFY_DEFAULT)

    for sym in SYMBOLS:
        klines = fetch_klines(sym, "5m", 100)
        if len(klines) < 20:
            continue

        sym_state = state["symbols"][sym]
        current_price = klines[-1]["close"]
        rsi = calc_rsi(klines)
        sym_state["current_rsi"] = round(rsi, 1)
        sym_state["current_price"] = current_price
        sym_state["last_check_time"] = now_ts
        # 使用已收盤的最後一根K線判斷漲跌（klines[-2]，-1是正在形成的）
        if len(klines) >= 2:
            closed_candle = klines[-2]
            sym_state["last_candle_up"] = closed_candle["close"] >= closed_candle["open"]
        # 儲存最近20根收盤價用於迷你K線圖
        sym_state["recent_closes"] = [k["close"] for k in klines[-20:]]

        # 暖機：第一次執行只記錄最新分型時間，不交易
        if not sym_state["warmed_up"]:
            fractal = detect_latest_fractal(klines)
            if fractal:
                sym_state["last_fractal_time"] = fractal["time"]
            sym_state["warmed_up"] = True
            sym_state["last_action"] = f"暖機完成 RSI={rsi:.0f}"
            sym_state["activity_log"].append({"time": now_ts, "msg": f"暖機完成，RSI={rsi:.0f}"})
            if len(sym_state["activity_log"]) > 10:
                sym_state["activity_log"] = sym_state["activity_log"][-10:]
            print(f"[{sym}] 暖機完成，RSI={rsi:.1f}")
            continue

        # 冷卻檢查
        cooldown_left = COOLDOWN_AFTER_TRADE - (now_ts - sym_state["last_trade_time"])
        if cooldown_left > 0:
            sym_state["last_action"] = f"冷卻中 {int(cooldown_left)}s"
            continue

        # 偵測最新分型
        fractal = detect_latest_fractal(klines)
        sym_state["latest_fractal"] = fractal
        if not fractal:
            trend = detect_trend(klines)
            percentile = calc_percentile(klines)
            sym_state["last_action"] = f"觀察中 RSI={rsi:.0f} {trend} 百分位{percentile:.0f}%"
            continue

        # 避免重複交易同一根分型
        if fractal["time"] <= sym_state["last_fractal_time"]:
            trend = detect_trend(klines)
            sym_state["last_action"] = f"已處理{fractal['type']}分型 RSI={rsi:.0f} {trend}"
            continue

        # 確認分型是新形成的（分型K線時間在最近3根內）
        fractal_age = len(klines) - 1 - fractal["index"]
        if fractal_age > 3:
            trend = detect_trend(klines)
            sym_state["last_action"] = f"{fractal['type']}分型過舊({fractal_age}根) RSI={rsi:.0f} {trend}"
            continue

        sym_state["last_fractal_time"] = fractal["time"]

        # 底分型 → 買入（底分型 + RSI過濾 + 趨勢判斷 + 多時間框 + 成交量 + BTC過濾）
        if fractal["type"] == "bottom" and sym_state["position"] == 0:
            trend = detect_trend(klines)
            percentile = calc_percentile(klines)

            # === BTC市場過濾器：BTC下跌趨勢時不買入 ===
            if BTC_MARKET_FILTER:
                btc_trend = get_btc_trend()
                if btc_trend == "downtrend":
                    sym_state["last_action"] = f"BTC下跌趨勢 暫停買入"
                    sym_state["activity_log"].append({"time": now_ts, "msg": f"BTC下跌趨勢 暫停買入"})
                    if len(sym_state["activity_log"]) > 10:
                        sym_state["activity_log"] = sym_state["activity_log"][-10:]
                    continue

            # === 成交量確認：底分型需放量 ===
            avg_vol = calc_avg_volume(klines)
            fractal_vol = get_fractal_volume(fractal, klines)
            if avg_vol > 0 and fractal_vol < avg_vol * VOLUME_SURGE_RATIO:
                vol_ratio = fractal_vol / avg_vol if avg_vol > 0 else 0
                sym_state["last_action"] = f"底分型縮量({vol_ratio:.1f}x) 跳過"
                sym_state["activity_log"].append({"time": now_ts, "msg": f"底分型縮量({vol_ratio:.1f}x) 跳過"})
                if len(sym_state["activity_log"]) > 10:
                    sym_state["activity_log"] = sym_state["activity_log"][-10:]
                continue

            # === 多時間框共振：15分K需在低位 ===
            h15_confirm = True
            h15_rsi = 50
            if MULTI_TIMEFRAME_CONFIRM:
                klines_15m = fetch_klines(sym, "15m", 50)
                if len(klines_15m) >= 20:
                    h15_rsi = calc_rsi(klines_15m)
                    h15_trend = detect_trend(klines_15m)
                    # 15分K在低位（RSI<55）或上漲趨勢才確認
                    if h15_rsi > 55 and h15_trend != "uptrend":
                        h15_confirm = False
                if not h15_confirm:
                    sym_state["last_action"] = f"15分K RSI{h15_rsi:.0f}過高 跳過"
                    sym_state["activity_log"].append({"time": now_ts, "msg": f"15分K RSI{h15_rsi:.0f}過高 跳過"})
                    if len(sym_state["activity_log"]) > 10:
                        sym_state["activity_log"] = sym_state["activity_log"][-10:]
                    continue
            # 趨勢感知RSI過濾
            if trend == "uptrend":
                rsi_limit = 65  # 上漲趨勢回調即可買
            elif trend == "neutral":
                rsi_limit = 55  # 震盪中等要求
            else:
                rsi_limit = 40  # 下跌趨勢要超賣才買
            if rsi > rsi_limit:
                sym_state["last_action"] = f"底分型RSI{rsi:.0f}>{rsi_limit}({trend})"
                sym_state["activity_log"].append({"time": now_ts, "msg": f"底分型RSI={rsi:.0f}>{rsi_limit}({trend})"})
                if len(sym_state["activity_log"]) > 10:
                    sym_state["activity_log"] = sym_state["activity_log"][-10:]
                continue
            # 下跌趨勢：百分位<50%才考慮（避免追高）
            if trend == "downtrend" and percentile > 50:
                sym_state["last_action"] = f"下跌趨勢 百分位{percentile:.0f}%過高"
                sym_state["activity_log"].append({"time": now_ts, "msg": f"下跌趨勢百分位{percentile:.0f}%過高"})
                if len(sym_state["activity_log"]) > 10:
                    sym_state["activity_log"] = sym_state["activity_log"][-10:]
                continue
            buy_amount = min(sym_state["cash"], INITIAL_CASH * 0.5)
            if buy_amount > 10:
                qty = buy_amount / current_price
                sym_state["cash"] -= buy_amount
                sym_state["position"] = qty
                sym_state["avg_entry"] = current_price
                sym_state["last_trade_time"] = now_ts
                trade = {
                    "time": now_ts, "side": "BUY", "price": current_price,
                    "qty": qty, "amount": buy_amount,
                    "reason": f"底分型+RSI{rsi:.0f}+{trend}+放量{vol_ratio:.1f}x+15mRSI{h15_rsi:.0f}",
                    "pnl": 0,
                }
                sym_state["last_action"] = f"✅ 買入 ${current_price:.2f}"
                sym_state["activity_log"].append({"time": now_ts, "msg": f"買入 ${current_price:.2f} RSI={rsi:.0f}"})
                if len(sym_state["activity_log"]) > 10:
                    sym_state["activity_log"] = sym_state["activity_log"][-10:]
                sym_state["trades"].append(trade)
                msg = (f"🟢 <b>分型機器人 買入 [模擬]</b>\n"
                       f"⏰ {now.strftime('%H:%M:%S')} UTC+8\n"
                       f"📊 {sym.replace('USDT', '/USDT')}\n"
                       f"💰 價格: {fmt_price(current_price)}\n"
                       f"💵 金額: ${buy_amount:,.2f}\n"
                       f"📦 數量: {qty:.6f}\n"
                       f"📝 底分型 + RSI {rsi:.1f} + {trend}\n"
                       f"📊 放量 {vol_ratio:.1f}x | 15m RSI {h15_rsi:.0f}")
                if notify_enabled:
                    send_telegram(msg)
                print(f"[{sym}] 買入 @ ${current_price:.4f} RSI={rsi:.1f}")

        # 頂分型 → 賣出（頂分型 + RSI + 成交量確認）
        elif fractal["type"] == "top" and sym_state["position"] > 0:
            unrealized = (current_price - sym_state["avg_entry"]) * sym_state["position"]

            # === 成交量確認：頂分型需放量 ===
            avg_vol = calc_avg_volume(klines)
            fractal_vol = get_fractal_volume(fractal, klines)
            vol_ratio = fractal_vol / avg_vol if avg_vol > 0 else 0
            if avg_vol > 0 and fractal_vol < avg_vol * VOLUME_SURGE_RATIO:
                sym_state["last_action"] = f"頂分型縮量({vol_ratio:.1f}x) 續抱"
                sym_state["activity_log"].append({"time": now_ts, "msg": f"頂分型縮量({vol_ratio:.1f}x) 續抱"})
                if len(sym_state["activity_log"]) > 10:
                    sym_state["activity_log"] = sym_state["activity_log"][-10:]
                continue
            # 虧損時不因頂分型賣出
            if unrealized < 0:
                sym_state["last_action"] = f"頂分型但虧損{unrealized:+.1f}"
                sym_state["activity_log"].append({"time": now_ts, "msg": f"頂分型但虧損{unrealized:+.1f}"})
                if len(sym_state["activity_log"]) > 10:
                    sym_state["activity_log"] = sym_state["activity_log"][-10:]
                continue
            # RSI<45時不賣（可能還在漲）
            if rsi < 45:
                sym_state["last_action"] = f"頂分型RSI{rsi:.0f}<45續抱"
                sym_state["activity_log"].append({"time": now_ts, "msg": f"頂分型RSI{rsi:.0f}<45續抱"})
                if len(sym_state["activity_log"]) > 10:
                    sym_state["activity_log"] = sym_state["activity_log"][-10:]
                continue
            # 最小利潤0.3%才賣
            if current_price < sym_state["avg_entry"] * 1.003:
                sym_state["last_action"] = f"頂分型利潤<0.3%"
                sym_state["activity_log"].append({"time": now_ts, "msg": f"頂分型利潤<0.3%"})
                if len(sym_state["activity_log"]) > 10:
                    sym_state["activity_log"] = sym_state["activity_log"][-10:]
                continue
            sell_qty = sym_state["position"]
            sell_amount = sell_qty * current_price
            pnl = (current_price - sym_state["avg_entry"]) * sell_qty
            sym_state["cash"] += sell_amount
            sym_state["position"] = 0
            sym_state["realized_pnl"] += pnl
            sym_state["last_trade_time"] = now_ts
            trade = {
                "time": now_ts, "side": "SELL", "price": current_price,
                "qty": sell_qty, "amount": sell_amount,
                "reason": f"頂分型+RSI{rsi:.0f}",
                "pnl": pnl,
            }
            sym_state["last_action"] = f"✅ 賣出 ${current_price:.2f} {'+' if pnl>0 else ''}${pnl:.2f}"
            sym_state["activity_log"].append({"time": now_ts, "msg": f"賣出 ${current_price:.2f} PnL={'+' if pnl>0 else ''}${pnl:.2f}"})
            if len(sym_state["activity_log"]) > 10:
                sym_state["activity_log"] = sym_state["activity_log"][-10:]
            sym_state["trades"].append(trade)
            pnl_emoji = "📈" if pnl > 0 else "📉"
            msg = (f"🔴 <b>分型機器人 賣出 [模擬]</b>\n"
                   f"⏰ {now.strftime('%H:%M:%S')} UTC+8\n"
                   f"📊 {sym.replace('USDT', '/USDT')}\n"
                   f"💰 價格: {fmt_price(current_price)}\n"
                   f"💵 金額: ${sell_amount:,.2f}\n"
                   f"{pnl_emoji} 盈虧: {'+' if pnl > 0 else ''}${pnl:,.4f}\n"
                   f"📝 頂分型 + RSI {rsi:.1f} + 放量 {vol_ratio:.1f}x")
            if notify_enabled:
                send_telegram(msg)
            print(f"[{sym}] 賣出 @ ${current_price:.4f} PnL: ${pnl:.4f} RSI={rsi:.1f}")

    save_state(state)
    return state


def set_notification(enabled: bool) -> dict:
    """設定分型機器人是否發送Telegram通知"""
    state = load_state()
    state["notify_enabled"] = enabled
    save_state(state)
    if enabled:
        send_telegram("🔔 <b>分型機器人通知已開啟</b>\n買賣訊號將即時推播")
    else:
        send_telegram("🔕 <b>分型機器人通知已關閉</b>\n此為最後一則訊息")
    return {"notify_enabled": enabled}


def get_summary() -> dict:
    """取得所有幣種的摘要"""
    state = load_state()
    summary = []
    for sym, s in state["symbols"].items():
        sells = [t for t in s["trades"] if t["side"] == "SELL"]
        wins = sum(1 for t in sells if t["pnl"] > 0)
        losses = sum(1 for t in sells if t["pnl"] <= 0)
        win_rate = (wins / len(sells) * 100) if sells else 0
        summary.append({
            "symbol": sym,
            "cash": s["cash"],
            "position": s["position"],
            "avg_entry": s["avg_entry"],
            "realized_pnl": s["realized_pnl"],
            "total_trades": len(s["trades"]),
            "win_rate": win_rate,
            "has_position": s["position"] > 0,
            "warmed_up": s.get("warmed_up", False),
            "last_check_time": s.get("last_check_time", 0),
            "current_rsi": s.get("current_rsi", 0),
            "current_price": s.get("current_price", 0),
            "last_candle_up": s.get("last_candle_up", True),
            "recent_closes": s.get("recent_closes", []),
            "latest_fractal": s.get("latest_fractal"),
            "last_action": s.get("last_action", "待機中"),
            "activity_log": s.get("activity_log", [])[-5:],
            "notify_enabled": state.get("notify_enabled", TELEGRAM_NOTIFY_DEFAULT),
        })
    return {"bots": summary, "notify_enabled": state.get("notify_enabled", TELEGRAM_NOTIFY_DEFAULT), "updated": datetime.now(UTC8).timestamp()}


if __name__ == "__main__":
    print("分型機器人啟動（暖機模式），每60秒檢查一次，Telegram通知:", "開啟" if TELEGRAM_NOTIFY_DEFAULT else "關閉")
    print("規則：分型 + RSI過濾 + 多時間框共振 + 成交量確認 + BTC過濾 + 5分鐘冷卻")
    _init_state = load_state()
    if _init_state.get("notify_enabled", TELEGRAM_NOTIFY_DEFAULT):
        send_telegram("⚙️ <b>分型機器人啟動</b>\n模擬交易 7 個幣種\n暖機後只交易新分型 + RSI過濾")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"錯誤: {e}")
        time.sleep(CHECK_INTERVAL)
