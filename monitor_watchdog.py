"""
Monitor watchdog - restarts monitor_pro.py if it crashes.
Tracks restart count and writes to stats file for UI display.
"""
import subprocess
import sys
import time
import json
from pathlib import Path

ROOT = Path(__file__).parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
MONITOR = ROOT / "monitor_pro.py"
STATS_FILE = ROOT / "runs" / "paper" / "watchdog_stats.json"

def write_stats(crash_count, uptime_start):
    try:
        stats = {
            "restart_count": crash_count,
            "first_start": uptime_start,
            "last_restart": time.time(),
            "status": "running",
        }
        STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATS_FILE, "w") as f:
            json.dump(stats, f, indent=2)
    except Exception:
        pass

print("=" * 60)
print("  監控伺服器看門狗啟動 (port 8767)")
print("  當機自動重啟，按 Ctrl+C 停止")
print("=" * 60)

crash_count = 0
uptime_start = time.time()
write_stats(crash_count, uptime_start)

while True:
    crash_count += 1
    print(f"\n[第 {crash_count} 次啟動] monitor_pro.py")
    write_stats(crash_count, uptime_start)
    try:
        result = subprocess.run(
            [str(PYTHON), str(MONITOR)],
            cwd=str(ROOT),
            capture_output=False,
        )
        print(f"[退出] code={result.returncode}，5秒後重啟...")
    except KeyboardInterrupt:
        print("\n[停止] 看門狗已停止")
        try:
            stats = json.loads(STATS_FILE.read_text())
            stats["status"] = "stopped"
            STATS_FILE.write_text(json.dumps(stats, indent=2))
        except Exception:
            pass
        sys.exit(0)
    except Exception as e:
        print(f"[異常] {e}，5秒後重啟...")
    write_stats(crash_count, uptime_start)
    time.sleep(5)
