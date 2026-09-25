"""分型機器人看門狗 - 檢查 last_check_time 是否超過10分鐘，卡住就重啟"""
import requests, time, subprocess, os, sys, signal

STONKFLY_DIR = r"C:\Users\ANGEL\Doubao\chats\2026-09-12\new-chat\stonkfly"
PYTHON = os.path.join(STONKFLY_DIR, ".venv", "Scripts", "python.exe")
API_URL = "http://127.0.0.1:8767/api/fractal_bot/summary"
STALE_SECONDS = 600  # 10分鐘沒更新就重啟

def check():
    try:
        r = requests.get(API_URL, timeout=10)
        d = r.json()
        bots = d.get("bots", [])
        if not bots:
            print("[fractal_watch] 無bot資料，重啟", flush=True)
            return restart()
        
        now = time.time()
        for bot in bots:
            last = bot.get("last_check_time", 0)
            symbol = bot.get("symbol", "?")
            age = now - last
            print(f"[fractal_watch] {symbol}: 最後更新 {age:.0f}秒前", flush=True)
            if age > STALE_SECONDS:
                print(f"[fractal_watch] {symbol} 卡住了！重啟中...", flush=True)
                return restart()
        
        print("[fractal_watch] 所有bot正常", flush=True)
        return True
    except Exception as e:
        print(f"[fractal_watch] API無回應: {e}，重啟", flush=True)
        return restart()

def restart():
    # 殺掉舊的 fractal bot 進程
    try:
        result = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "ProcessId,CommandLine"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.split("\n"):
            if "fractal_multi_bot" in line:
                parts = line.strip().split()
                pid = int(parts[-1])
                print(f"[fractal_watch] 殺掉舊進程 PID={pid}", flush=True)
                try:
                    os.kill(pid, signal.SIGTERM)
                except:
                    pass
    except Exception as e:
        print(f"[fractal_watch] 殺進程失敗: {e}", flush=True)
    
    time.sleep(3)
    
    # 重新啟動
    subprocess.Popen(
        [PYTHON, "-m", "stonkfly.fractal_multi_bot"],
        cwd=STONKFLY_DIR,
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    print("[fractal_watch] 已重啟分型機器人", flush=True)
    time.sleep(15)
    
    # 驗證
    try:
        r = requests.get(API_URL, timeout=15)
        d = r.json()
        bots = d.get("bots", [])
        for bot in bots:
            age = time.time() - bot.get("last_check_time", 0)
            if age < 120:
                print(f"[fractal_watch] {bot.get('symbol')} 恢復正常 ({age:.0f}秒前)", flush=True)
            else:
                print(f"[fractal_watch] {bot.get('symbol')} 仍舊 ({age:.0f}秒前)", flush=True)
    except:
        print("[fractal_watch] 重啟後API仍無回應", flush=True)
    
    return True

if __name__ == "__main__":
    while True:
        check()
        time.sleep(120)  # 每2分鐘檢查一次
