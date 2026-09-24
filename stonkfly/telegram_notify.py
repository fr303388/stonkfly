"""Telegram 交易通知模組"""
import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

UTC8 = timezone(timedelta(hours=8))

_env_loaded = False

def _load_env():
    """從 .env 檔案載入環境變數（只執行一次）"""
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True
    # 嘗試多個可能的 .env 路徑
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

def _get_config():
    """從 .env 或環境變數讀取 Telegram 設定"""
    _load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    enabled = os.environ.get("TELEGRAM_ENABLED", "false").lower() == "true"
    return enabled, token, chat_id

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
    """發送 Telegram 訊息，回傳是否成功"""
    enabled, token, chat_id = _get_config()
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

def notify_trade(side: str, price: float, amount: float, qty: float,
                 reason: str, source: str = "果蠅", product: str = "BTC-USDT",
                 pnl: float = None, rsi: float = None) -> bool:
    """發送交易通知"""
    enabled, _, _ = _get_config()
    if not enabled:
        return False

    now = datetime.now(UTC8).strftime("%H:%M:%S")
    side_emoji = "🟢" if side == "BUY" else "🔴"
    side_text = "買入" if side == "BUY" else "賣出"

    lines = [
        f"{side_emoji} <b>{source} {side_text}</b>",
        f"⏰ {now} UTC+8",
        f"📊 {product.replace('-', '/')}",
        f"💰 價格: ${price:,.8f}".rstrip('0').rstrip('.') if price < 1 else f"💰 價格: ${price:,.2f}",
        f"💵 金額: ${amount:,.2f}",
        f"📦 數量: {qty:.6f}",
    ]
    if rsi is not None:
        lines.append(f"📉 RSI: {rsi:.1f}")
    if pnl is not None and pnl != 0:
        pnl_emoji = "📈" if pnl > 0 else "📉"
        lines.append(f"{pnl_emoji} 盈虧: {'+' if pnl > 0 else ''}${pnl:,.4f}")
    lines.append(f"📝 {reason}")

    return send_telegram("\n".join(lines))

def notify_system(message: str) -> bool:
    """發送系統通知（重啟、錯誤等）"""
    return send_telegram(f"⚙️ <b>系統通知</b>\n{message}")

def test_connection() -> dict:
    """測試 Telegram 連線，回傳結果"""
    enabled, token, chat_id = _get_config()
    if not enabled:
        return {"ok": False, "error": "Telegram 未啟用"}
    if not token:
        return {"ok": False, "error": "未設定 TELEGRAM_BOT_TOKEN"}
    if not chat_id:
        return {"ok": False, "error": "未設定 TELEGRAM_CHAT_ID"}
    ok = send_telegram("✅ StonkFly 通知測試成功！")
    return {"ok": ok, "error": None if ok else "發送失敗，請檢查 Token 和 Chat ID"}
