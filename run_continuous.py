"""
無限連續模擬：果蠅腦 24 小時不停交易
- 單次跑 10000 步（近乎無限）
- crash 後從大腦檢查點恢復，保留交易紀錄
- 學習成果跨 crash 保留
"""
import subprocess
import os
import sys
import time
import shutil
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
RUN_DIR = PROJECT_DIR / "runs" / "paper"
VENV_PYTHON = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
MINGW_PATH = r"C:\Program Files\WinLibs\mingw64\bin"
BACKUP_DIR = PROJECT_DIR / "runs" / "brain_backup"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

STEPS = 10000  # 近乎無限，crash 才重啟
RESTART_DELAY = 5


def backup_brain():
    for f in RUN_DIR.glob("brain-*.npz"):
        try:
            shutil.copy2(f, BACKUP_DIR / f.name)
        except Exception:
            pass


def restore_brain():
    for f in BACKUP_DIR.glob("brain-*.npz"):
        try:
            shutil.copy2(f, RUN_DIR / f.name)
        except Exception:
            pass


def run_batch(batch_num):
    print(f"\n{'='*60}")
    print(f"第 {batch_num} 次執行 (步數: {STEPS})")
    print(f"{'='*60}")

    env = os.environ.copy()
    env["PATH"] = MINGW_PATH + ";" + env.get("PATH", "")

    cmd = [
        str(VENV_PYTHON), "-m", "stonkfly", "run",
        "--fast", "--steps", str(STEPS),
        "--products", "BTC-USDT", "--exchange", "binance",
        "--neural-ms", "2000", "--hz432", "--strategy", "martingale",
        "--chan-auto",
    ]

    try:
        result = subprocess.run(
            cmd, cwd=str(PROJECT_DIR), env=env,
            capture_output=True, text=True, timeout=86400,  # 24小時上限
        )
        print(f"  結束代碼: {result.returncode}")
        lines = result.stdout.strip().split("\n")
        for line in lines[-3:]:
            print(f"  {line[:120]}")
        if result.returncode == 0:
            backup_brain()
            print("  [成功] 大腦已備份")
        elif result.returncode == 42:
            print("  [睡眠] 大腦超時睡眠，執行記憶整理...")
            backup_brain()
            # Write sleep stats for UI
            try:
                import json
                stats_file = RUN_DIR / "watchdog_stats.json"
                stats = {}
                if stats_file.exists():
                    stats = json.loads(stats_file.read_text())
                stats["sleep_count"] = stats.get("sleep_count", 0) + 1
                stats["last_sleep"] = time.time()
                stats_file.write_text(json.dumps(stats, indent=2))
            except Exception:
                pass
        return result.returncode
    except subprocess.TimeoutExpired:
        print("  [逾時 24h] 重啟")
        backup_brain()
        return -1
    except Exception as e:
        print(f"  [異常] {e}")
        return -1


def main():
    print("🪰 果蠅腦無限連續模擬啟動")
    print(f"每批 {STEPS} 步，crash 自動恢復，學習成果保留")
    print("按 Ctrl+C 停止\n")

    batch_num = 1
    first_run = True
    prev_exit_code = None
    try:
        while True:
            if first_run:
                # 檢查是否已有交易資料，有則保留（從中斷處恢復）
                has_existing_data = (RUN_DIR / "events.jsonl").exists() and (RUN_DIR / "events.jsonl").stat().st_size > 100
                if has_existing_data:
                    print("  [恢復] 偵測到既有交易資料，保留並接續執行")
                else:
                    # 首次執行：清除舊資料，從零開始
                    for pattern in ["ledger.sqlite", "events.jsonl", "latest.json"]:
                        f = RUN_DIR / pattern
                        if f.exists():
                            for _ in range(5):
                                try:
                                    f.unlink()
                                    break
                                except PermissionError:
                                    time.sleep(1)
                first_run = False
            else:
                # 從備份還原大腦
                restore_brain()
                if prev_exit_code == 42:
                    # 睡眠恢復：保留ledger（持倉、現金、權益接續）
                    print("  [睡眠恢復] 保留帳戶狀態，從睡眠前接續")
                else:
                    # crash 恢復：保留ledger（持倉、現金接續），避免資料遺失
                    print("  [崩潰恢復] 保留帳戶狀態，從中斷處接續")

            # 清理殘留鎖檔
            lock_file = RUN_DIR / "worker.lock"
            if lock_file.exists():
                try:
                    lock_file.unlink()
                except Exception:
                    pass
            # 清理睡眠訊號檔
            sleep_file = RUN_DIR / "SLEEP"
            if sleep_file.exists():
                try:
                    sleep_file.unlink()
                except Exception:
                    pass

            exit_code = run_batch(batch_num)
            prev_exit_code = exit_code

            if exit_code == 0:
                print("  模擬正常完成，準備下一輪...")
            elif exit_code == 42:
                print(f"  大腦睡眠整理完成，{RESTART_DELAY}s 後重新啟動（保留帳戶）...")
            else:
                print(f"  crash (code={exit_code})，{RESTART_DELAY}s 後從大腦檢查點恢復...")

            time.sleep(RESTART_DELAY)
            batch_num += 1

    except KeyboardInterrupt:
        print("\n\n使用者停止，果蠅休息了")
        backup_brain()
        sys.exit(0)


if __name__ == "__main__":
    main()
