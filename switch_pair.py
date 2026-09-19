"""一鍵切換交易對腳本
用法: python switch_pair.py ZEC-USDT
     python switch_pair.py BTC-USDT
"""
import sys, re, shutil
from pathlib import Path

ROOT = Path(__file__).parent

# 交易對對照表：產品名 → Binance symbol, 預估價格
PAIRS = {
    # 主流幣
    "BTC-USDT":  {"symbol": "BTCUSDT",  "price": 60000},
    "ETH-USDT":  {"symbol": "ETHUSDT",  "price": 2500},
    "BNB-USDT":  {"symbol": "BNBUSDT",  "price": 580},
    "SOL-USDT":  {"symbol": "SOLUSDT",  "price": 150},
    "ZEC-USDT":  {"symbol": "ZECUSDT",  "price": 1600},
    "ADA-USDT":  {"symbol": "ADAUSDT",  "price": 0.5},
    "AVAX-USDT": {"symbol": "AVAXUSDT", "price": 35},
    "DOT-USDT":  {"symbol": "DOTUSDT",  "price": 7},
    "LINK-USDT": {"symbol": "LINKUSDT", "price": 15},
    "LTC-USDT":  {"symbol": "LTCUSDT",  "price": 70},
    # 熱門山寨
    "NEAR-USDT": {"symbol": "NEARUSDT", "price": 5},
    "ATOM-USDT": {"symbol": "ATOMUSDT","price": 8},
    "ARB-USDT":  {"symbol": "ARBUSDT",  "price": 1.2},
    "OP-USDT":   {"symbol": "OPUSDT",   "price": 2.5},
    "INJ-USDT":  {"symbol": "INJUSDT",  "price": 25},
    "SUI-USDT":  {"symbol": "SUIUSDT",   "price": 1.5},
    "SEI-USDT":  {"symbol": "SEIUSDT",   "price": 0.5},
    # 迷因幣
    "DOGE-USDT": {"symbol": "DOGEUSDT", "price": 0.15},
    "SHIB-USDT": {"symbol": "SHIBUSDT", "price": 0.000025},
    "PEPE-USDT": {"symbol": "PEPEUSDT", "price": 0.000012},
    "WIF-USDT":  {"symbol": "WIFUSDT",  "price": 2.5},
    "FLOKI-USDT":{"symbol": "FLOKIUSDT","price": 0.0002},
    "BONK-USDT": {"symbol": "BONKUSDT", "price": 0.00003},
}

def read(p):
    return (ROOT / p).read_text(encoding="utf-8")

def write(p, c):
    (ROOT / p).write_text(c, encoding="utf-8")

def switch(product):
    if product not in PAIRS:
        print(f"未知交易對: {product}")
        print(f"可用: {', '.join(PAIRS.keys())}")
        return
    info = PAIRS[product]
    sym = info["symbol"]
    base = sym.replace("USDT", "").replace("USDC", "")  # BTC, ZEC, etc.
    print(f"切換到 {product} (Binance: {sym})")

    # 1. cli.py: choices, ChanAutoStrategy symbol, no_brain URL
    c = read("stonkfly/cli.py")
    c = re.sub(r'choices=\[[^\]]+\]', f'choices=["BTC-USDC","ETH-USDC","SOL-USDC","PEPE-USDT","BTC-USDT","BNB-USDT","ZEC-USDT"]', c)
    c = re.sub(r'symbol="[A-Z]+USDT"', f'symbol="{sym}"', c)
    c = re.sub(r'symbol=[A-Z]+USDT&interval=\w+m', f'symbol={sym}&interval=5m', c)
    write("stonkfly/cli.py", c)
    print("  ✓ cli.py")

    # 2. config.py: allowlist
    c = read("stonkfly/config.py")
    c = re.sub(r'set\(self\.products\) <= set\(\([^)]+\)\)',
               'set(self.products) <= set(("BTC-USDC","ETH-USDC","SOL-USDC","PEPE-USDT","BTC-USDT","BNB-USDT","ZEC-USDT"))', c)
    write("stonkfly/config.py", c)
    print("  ✓ config.py")

    # 3. market.py: symbol_map + base price
    c = read("stonkfly/market.py")
    # 更新 symbol_map
    c = re.sub(r'"BTC-USDT":\s*"BTCUSDT"[^}]*',
               f'"BTC-USDT": "BTCUSDT", "BNB-USDT": "BNBUSDT", "ETH-USDT": "ETHUSDT",\n            "SOL-USDT": "SOLUSDT", "BTC-USDC": "BTCUSDC", "ZEC-USDT": "ZECUSDT"', c)
    # 更新 base price dict
    c = re.sub(r'base\s*=\s*\{[^}]+\}',
               f'base = {{"BTC-USDC": 60000, "ETH-USDC": 2500, "SOL-USDC": 100, "PEPE-USDT": 0.000012, "BTC-USDT": 60000, "BNB-USDT": 580, "ZEC-USDT": 1600}}', c)
    write("stonkfly/market.py", c)
    print("  ✓ market.py")

    # 4. monitor_pro.py: all BTCUSDT → symbol
    c = read("monitor_pro.py")
    c = c.replace("BTCUSDT", sym)
    c = c.replace('"symbol": "BTC"', f'"symbol": "{base}"')
    write("monitor_pro.py", c)
    print("  ✓ monitor_pro.py")

    # 5. monitor_pro.html: BTC → base symbol text
    c = read("monitor_pro.html")
    c = re.sub(r'Binance \w+/USDT K 線', f'Binance {base}/USDT K 線', c)
    c = re.sub(r'訂單簿深度 · \w+/USDT', f'訂單簿深度 · {base}/USDT', c)
    c = re.sub(r'📦 \w+持倉', f'📦 {base}持倉', c)
    c = c.replace(f"'BTC $'", f"'{base} $'")
    c = c.replace("'BTC-USDT'", f"'{product}'")
    c = c.replace("+ ' BTC'", f"+ ' {base}'")
    c = c.replace("持倉 ... BTC", f"持倉 ... {base}")
    c = re.sub(r"toFixed\(\d\) \+ ' BTC", f"toFixed(4) + ' {base}", c)
    write("monitor_pro.html", c)
    print("  ✓ monitor_pro.html")

    # 6. no_brain trader: ChanAutoStrategy symbol already handled in cli.py
    #    initial_cash default already 100
    print("  ✓ no_brain trader (inherits from cli.py)")

    # 7. Clear pycache
    import shutil
    p = ROOT / "stonkfly" / "__pycache__"
    if p.exists():
        shutil.rmtree(p)
    print("  ✓ 清除 __pycache__")

    print(f"\n✅ 完成！啟動指令：")
    print(f"  python -m stonkfly.cli run --out runs/paper --products {product} --exchange binance --steps 1000 --hz432")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"用法: python switch_pair.py <交易對>")
        print(f"可用: {', '.join(PAIRS.keys())}")
        sys.exit(1)
    switch(sys.argv[1].upper())
