"""
Monitor watchdog - restarts monitor_pro.py and simulation if they crash or stall.
- Monitors monitor_pro.py on port 8767
- Monitors latest.json update time; if no update for 6 minutes, force restart simulation
- Tracks restart count and writes to stats file for UI display
"""
import subprocess
import sys
import time
import json
import os
import signal
from pathlib import Path

ROOT = Path(__file__).parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
MONITOR = ROOT / "monitor_pro.py"
RUN_CONTINUOUS = ROOT / "run_continuous.py"
LATEST_JSON = ROOT / "runs" / "paper" / "latest.json"
STATS_FILE = ROOT / "runs" / "paper" / "watchdog_stats.json"
STALL_THRESHOLD = 360  # 6 minutes in seconds
CHECK_INTERVAL = 30  # check every 30 seconds


def write_stats(restart_count, stall_restart_count, uptime_start):
    try:
        stats = {
            "restart_count": restart_count,
            "stall_restart_count": stall_restart_count,
            "first_start": uptime_start,
            "last_restart": time.time(),
            "status": "running",
        }
        STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATS_FILE, "w") as f:
            json.dump(stats, f, indent=2)
    except Exception:
        pass


def kill_stonkfly_processes():
    """Kill all stonkfly python processes except this watchdog."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # Use taskkill to kill all stonkfly-related python processes
        result = subprocess.run(
            ["wmic", "process", "where",
             "name='python.exe' and (commandline like '%stonkfly%' or commandline like '%run_continuous%' or commandline like '%monitor_pro%')",
             "get", "processid"],
            capture_output=True, text=True
        )
        pids = []
        for line in result.stdout.strip().split('\n')[1:]:
            line = line.strip()
            if line and line.isdigit():
                pid = int(line)
                if pid != os.getpid():
                    pids.append(pid)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"  已停止進程 PID {pid}")
            except Exception:
                pass
        time.sleep(3)
        # Force kill any remaining
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
        # Clean lock file
        lock_file = ROOT / "runs" / "paper" / "worker.lock"
        if lock_file.exists():
            try:
                lock_file.unlink()
            except Exception:
                pass
    except Exception as e:
        print(f"  清理進程異常: {e}")


def is_simulation_stalled():
    """Check if latest.json hasn't been updated for STALL_THRESHOLD seconds."""
    if not LATEST_JSON.exists():
        return False  # simulation may be starting up
    mtime = LATEST_JSON.stat().st_mtime
    elapsed = time.time() - mtime
    return elapsed > STALL_THRESHOLD


print("=" * 60)
print("  看門狗啟動 (監控伺服器 + 模擬活躍度)")
print(f"  模擬停滯閾值: {STALL_THRESHOLD}秒 ({STALL_THRESHOLD//60}分鐘)")
print("  當機自動重啟，按 Ctrl+C 停止")
print("=" * 60)

restart_count = 0
stall_restart_count = 0
uptime_start = time.time()
write_stats(restart_count, stall_restart_count, uptime_start)

# Start monitor in background
monitor_proc = subprocess.Popen([str(PYTHON), str(MONITOR)], cwd=str(ROOT))
print(f"[啟動] monitor_pro.py PID={monitor_proc.pid}")

# Start simulation in background
sim_proc = subprocess.Popen([str(PYTHON), str(RUN_CONTINUOUS)], cwd=str(ROOT))
print(f"[啟動] run_continuous.py PID={sim_proc.pid}")

last_stall_check = time.time()

while True:
    try:
        time.sleep(CHECK_INTERVAL)

        # Check if monitor is alive
        if monitor_proc.poll() is not None:
            restart_count += 1
            print(f"[當機] monitor_pro.py 已退出，重啟中...")
            monitor_proc = subprocess.Popen([str(PYTHON), str(MONITOR)], cwd=str(ROOT))
            write_stats(restart_count, stall_restart_count, uptime_start)

        # Check if simulation is alive
        if sim_proc.poll() is not None:
            restart_count += 1
            print(f"[當機] run_continuous.py 已退出，重啟中...")
            sim_proc = subprocess.Popen([str(PYTHON), str(RUN_CONTINUOUS)], cwd=str(ROOT))
            write_stats(restart_count, stall_restart_count, uptime_start)

        # Check for stall every CHECK_INTERVAL
        if time.time() - last_stall_check >= CHECK_INTERVAL:
            last_stall_check = time.time()
            if is_simulation_stalled():
                stall_restart_count += 1
                elapsed = time.time() - LATEST_JSON.stat().st_mtime
                print(f"[停滯] latest.json已{elapsed:.0f}秒未更新，強制睡眠重啟...")
                # Kill everything and restart
                kill_stonkfly_processes()
                time.sleep(3)
                monitor_proc = subprocess.Popen([str(PYTHON), str(MONITOR)], cwd=str(ROOT))
                sim_proc = subprocess.Popen([str(PYTHON), str(RUN_CONTINUOUS)], cwd=str(ROOT))
                write_stats(restart_count, stall_restart_count, uptime_start)
                print(f"[恢復] 已強制重啟，累計停滯重啟{stall_restart_count}次")

    except KeyboardInterrupt:
        print("\n[停止] 看門狗已停止")
        try:
            stats = json.loads(STATS_FILE.read_text())
            stats["status"] = "stopped"
            STATS_FILE.write_text(json.dumps(stats, indent=2))
        except Exception:
            pass
        # Kill child processes
        try:
            monitor_proc.terminate()
            sim_proc.terminate()
        except Exception:
            pass
        sys.exit(0)
    except Exception as e:
        print(f"[異常] {e}")
        time.sleep(5)
