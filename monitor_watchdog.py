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
STALL_THRESHOLD = 120  # 2 minutes in seconds (faster response)
CHECK_INTERVAL = 15  # check every 15 seconds


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
    """Kill all stonkfly python processes except this watchdog using taskkill."""
    try:
        my_pid = os.getpid()
        # Use taskkill to force kill all python.exe that are NOT this watchdog
        # First get all python PIDs
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True
        )
        pids_to_kill = []
        for line in result.stdout.strip().split('\n'):
            if '"python.exe"' in line:
                parts = line.split('","')
                if len(parts) >= 2:
                    pid = int(parts[1].strip('"'))
                    if pid != my_pid:
                        pids_to_kill.append(pid)
        print(f"  找到 {len(pids_to_kill)} 個 Python 進程需要終止")
        # Force kill all
        for pid in pids_to_kill:
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                             capture_output=True, timeout=5)
            except Exception:
                pass
        time.sleep(5)
        # Verify all killed
        remaining = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True
        )
        remaining_count = 0
        for line in remaining.stdout.strip().split('\n'):
            if '"python.exe"' in line and str(my_pid) not in line:
                remaining_count += 1
        if remaining_count > 0:
            print(f"  警告: 仍有 {remaining_count} 個進程未終止，重試")
            time.sleep(3)
            for pid in pids_to_kill:
                try:
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                 capture_output=True, timeout=5)
                except Exception:
                    pass
        # Clean all lock files
        for lock_name in ["worker.lock", "watchdog.lock"]:
            lock_file = ROOT / "runs" / "paper" / lock_name
            if lock_file.exists():
                try:
                    lock_file.unlink()
                except Exception:
                    pass
        print("  進程清理完成")
    except Exception as e:
        print(f"  清理進程異常: {e}")


def is_simulation_stalled():
    """Check if latest.json hasn't been updated for STALL_THRESHOLD seconds."""
    if not LATEST_JSON.exists():
        return False  # simulation may be starting up
    mtime = LATEST_JSON.stat().st_mtime
    elapsed = time.time() - mtime
    return elapsed > STALL_THRESHOLD


# Single-instance lock: ensure only one watchdog runs at a time
LOCK_FILE = ROOT / "runs" / "paper" / "watchdog.lock"
try:
    if LOCK_FILE.exists():
        # Check if the locked process is still alive
        import ctypes
        locked_pid = int(LOCK_FILE.read_text().strip())
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(1, False, locked_pid)
        if handle:
            kernel32.CloseHandle(handle)
            print(f"[錯誤] 看門狗已在運行 (PID={locked_pid})，退出")
            sys.exit(1)
        else:
            # Old process is dead, remove stale lock
            LOCK_FILE.unlink()
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))
except Exception as e:
    print(f"[警告] 無法創建鎖文件: {e}")

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
        # Remove lock file
        try:
            if LOCK_FILE.exists():
                LOCK_FILE.unlink()
        except Exception:
            pass
        sys.exit(0)
    except Exception as e:
        print(f"[異常] {e}")
        time.sleep(5)
