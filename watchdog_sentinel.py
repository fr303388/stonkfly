"""第二層看門狗：哨兵"""
import subprocess, sys, os
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
WATCHDOG = str(ROOT / "monitor_watchdog.py")

# 用 PowerShell 檢查看門狗進程
result = subprocess.run(
    ["powershell", "-Command",
     "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'monitor_watchdog' } | Select-Object -ExpandProperty ProcessId"],
    capture_output=True, text=True
)

if not result.stdout.strip():
    # 看門狗掛了，重啟
    subprocess.Popen([PY, WATCHDOG], cwd=str(ROOT))
    print("[SENTINEL] watchdog was DEAD, restarted!")
else:
    print("[SENTINEL] watchdog alive, OK")
