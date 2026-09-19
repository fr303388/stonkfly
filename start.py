"""一鍵啟動：停止→切換→清數據→啟動→驗證
用法: python start.py ZEC-USDT
     python start.py BTC-USDT
"""
import sys, os, time, subprocess, shutil, re
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# 交易對: (Binance symbol, 預估價格)
PAIRS = {
    "BTC-USDT":  ("BTCUSDT",  60000),
    "ETH-USDT":  ("ETHUSDT",  2500),
    "BNB-USDT":  ("BNBUSDT",  580),
    "SOL-USDT":  ("SOLUSDT",  150),
    "ZEC-USDT":  ("ZECUSDT",  1600),
    "ADA-USDT":  ("ADAUSDT",  0.5),
    "AVAX-USDT": ("AVAXUSDT", 35),
    "DOT-USDT":  ("DOTUSDT",  7),
    "LINK-USDT": ("LINKUSDT", 15),
    "LTC-USDT":  ("LTCUSDT",  70),
    "NEAR-USDT": ("NEARUSDT", 5),
    "ATOM-USDT": ("ATOMUSDT", 8),
    "ARB-USDT":  ("ARBUSDT",  1.2),
    "OP-USDT":   ("OPUSDT",   2.5),
    "INJ-USDT":  ("INJUSDT",  25),
    "SUI-USDT":  ("SUIUSDT",  1.5),
    "SEI-USDT":  ("SEIUSDT",  0.5),
    "DOGE-USDT": ("DOGEUSDT", 0.15),
    "SHIB-USDT": ("SHIBUSDT", 0.000025),
    "PEPE-USDT": ("PEPEUSDT", 0.000012),
    "WIF-USDT":  ("WIFUSDT",  2.5),
    "FLOKI-USDT":("FLOKIUSDT",0.0002),
    "BONK-USDT": ("BONKUSDT", 0.00003),
}

PY = str(ROOT / ".venv" / "Scripts" / "python.exe")

def read(p):
    return (ROOT / p).read_text(encoding="utf-8")

def write(p, c):
    (ROOT / p).write_text(c, encoding="utf-8")

def patch_cli(product, symbol):
    """安全地更新 cli.py：只改 --products 的 choices，不碰 --exchange"""
    c = read("stonkfly/cli.py")
    # 重建完整 choices 列表
    all_pairs = list(PAIRS.keys())
    choices_str = ", ".join(f'"{p}"' for p in all_pairs)
    # 只替換 --products 參數的 choices（通過上下文匹配）
    c = re.sub(
        r'(\s*"--products".*?choices=\[)[^\]]+(\])',
        lambda m: m.group(1) + choices_str + m.group(2),
        c, flags=re.DOTALL
    )
    # 更新 ChanAutoStrategy 和 no_brain 的 symbol
    c = re.sub(r'symbol="[A-Z]+USDT"', f'symbol="{symbol}"', c)
    c = re.sub(r'symbol=[A-Z]+USDT&interval=\w+m', f'symbol={symbol}&interval=5m', c)
    # 確保 --exchange choices 正確
    c = re.sub(
        r'("--exchange".*?choices=\[)[^\]]+(\])',
        lambda m: m.group(1) + '"binance", "coinbase"' + m.group(2),
        c, flags=re.DOTALL
    )
    write("stonkfly/cli.py", c)
    print("  ✓ cli.py")

def patch_config(product):
    c = read("stonkfly/config.py")
    allowlist = ", ".join(f'"{k}"' for k in PAIRS)
    c = re.sub(
        r'set\(self\.products\) <= set\(\([^)]+\)\)',
        f'set(self.products) <= set(({allowlist}))',
        c
    )
    write("stonkfly/config.py", c)
    print("  ✓ config.py")

def patch_market():
    c = read("stonkfly/market.py")
    sym_items = ", ".join(f'"{k}": "{v[0]}"' for k, v in PAIRS.items())
    base_items = ", ".join(f'"{k}": {v[1]}' for k, v in PAIRS.items())
    c = re.sub(r'self\._symbol_map = \{[^}]+\}', f'self._symbol_map = {{{sym_items}}}', c)
    c = re.sub(r'base = \{[^}]+\}', f'base = {{{base_items}}}', c)
    write("stonkfly/market.py", c)
    print("  ✓ market.py")

def patch_monitor(symbol, base):
    c = read("monitor_pro.py")
    c = c.replace("BTCUSDT", symbol).replace("BTCUSDT", symbol)
    c = re.sub(r'"symbol":\s*"[A-Z]+"', f'"symbol": "{base}"', c)
    write("monitor_pro.py", c)
    print("  ✓ monitor_pro.py")

def patch_html(base):
    c = read("monitor_pro.html")
    # 幣種名稱替換
    c = re.sub(r'Binance \w+/USDT K 線', f'Binance {base}/USDT K 線', c)
    c = re.sub(r'訂單簿深度 · \w+/USDT', f'訂單簿深度 · {base}/USDT', c)
    c = re.sub(r'📦 \w+持倉', f'📦 {base}持倉', c)
    # PnL: 讀所有持倉（不只BTC/BNB/PEPE）
    c = c.replace(
        "if (product.startsWith('BTC') || product.startsWith('BNB') || product.startsWith('PEPE')) btcAmount += parseFloat(amount) || 0;",
        "btcAmount += parseFloat(amount) || 0;"
    )
    # 持倉文字中的 BTC → base
    c = c.replace("' BTC ", f"' {base} ")
    c = re.sub(r"持倉 \.\.\. BTC", f"持倉 ... {base}", c)
    c = re.sub(r"toFixed\(\d\) \+ ' BTC", f"toFixed(4) + ' {base}", c)
    write("monitor_pro.html", c)
    print("  ✓ monitor_pro.html")

def main():
    product = sys.argv[1].upper() if len(sys.argv) > 1 else "BTC-USDT"
    if product not in PAIRS:
        print(f"未知: {product}")
        print(f"可用: {', '.join(PAIRS.keys())}")
        return
    symbol, price = PAIRS[product]
    base = symbol.replace("USDT", "")
    print(f"=== 一鍵啟動 {product} (Binance: {symbol}) ===\n")

    # 1. 停止所有 Python 進程
    print("[1/6] 停止舊進程...")
    subprocess.run("taskkill /F /IM python.exe", shell=True, capture_output=True)
    time.sleep(3)

    # 2. 打補丁
    print("[2/6] 更新代碼...")
    patch_cli(product, symbol)
    patch_config(product)
    patch_market()
    patch_monitor(symbol, base)
    patch_html(base)

    # 3. 清除 __pycache__
    print("[3/6] 清除緩存...")
    pyc = ROOT / "stonkfly" / "__pycache__"
    if pyc.exists():
        shutil.rmtree(pyc)

    # 4. 清除舊數據（全部清乾淨）
    print("[4/6] 清除舊數據...")
    paper = ROOT / "runs" / "paper"
    for f in paper.iterdir():
        if f.is_file():
            f.unlink()
    print("  ✓ runs/paper 已清空")

    # 5. 啟動
    print("[5/6] 啟動服務...")
    subprocess.Popen([PY, "monitor_pro.py"], cwd=str(ROOT), creationflags=0x08000000)
    time.sleep(3)
    subprocess.Popen(
        [PY, "-u", "-m", "stonkfly.cli", "run",
         "--out", "runs/paper", "--products", product,
         "--exchange", "binance", "--steps", "1000", "--hz432"],
        cwd=str(ROOT), creationflags=0x08000000
    )

    # 6. 等待就緒
    print("[6/6] 等待大腦載入...")
    for i in range(60):
        time.sleep(5)
        try:
            import urllib.request, json
            r = urllib.request.urlopen("http://127.0.0.1:8767/api/state", timeout=3)
            j = json.loads(r.read())
            if j.get("tick") and j.get("neural", {}).get("hz432"):
                print(f"  ✓ tick={j['tick']} hz432=ON price={j.get('quote',{}).get('bid','?')}")
                break
        except:
            pass
        if i % 6 == 5:
            print(f"  仍在載入... ({(i+1)*5}秒)")

    print(f"\n✅ 完成！打開 http://127.0.0.1:8767")
    print(f"   交易對: {product} | 初始: $100+$100 | 432Hz: ON")

if __name__ == "__main__":
    main()
