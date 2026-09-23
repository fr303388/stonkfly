"""Single-worker run loop. Default execution is paper; live must be explicit."""

import argparse
import dataclasses
import gc
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

import numpy as np
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from .config import D, Settings


def _acquire_worker_lock(path):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        handle = kernel32.CreateFileW(
            str(path),
            0x80000000 | 0x40000000,  # GENERIC_READ | GENERIC_WRITE
            0,  # No sharing: only one worker may own this file.
            None,
            4,  # OPEN_ALWAYS
            0x80,  # FILE_ATTRIBUTE_NORMAL
            None,
        )
        if handle == wintypes.HANDLE(-1).value:
            error = ctypes.get_last_error()
            if error in (32, 33):  # ERROR_SHARING_VIOLATION/LOCK_VIOLATION
                raise BlockingIOError(error, "Worker lock is already held")
            raise ctypes.WinError(error)
        return handle

    import fcntl

    lock = path.open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        lock.close()
        raise
    return lock


def _release_worker_lock(lock):
    if os.name == "nt":
        import ctypes

        ctypes.WinDLL("kernel32").CloseHandle(lock)
    else:
        lock.close()


def main():
    p = argparse.ArgumentParser(prog="stonkfly")
    sub = p.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--reuse-doomfly", type=Path)
    sub.add_parser("verify")
    run = sub.add_parser("run")
    run.add_argument("--live", action="store_true")
    run.add_argument(
        "--exchange",
        choices=["binance", "coinbase"],
        default="coinbase",
        help="Exchange for live trading (default: coinbase)",
    )
    run.add_argument(
        "--preflight-only",
        action="store_true",
        help="Read-only exchange checks; never submit an order",
    )
    run.add_argument(
        "--resume-reviewed",
        action="store_true",
        help="After manual review, clear a transient halt only after successful reconciliation",
    )
    run.add_argument(
        "--fixture",
        action="store_true",
        help="Synthetic offline market input; paper only",
    )
    run.add_argument("--steps", type=int, default=0, help="0 keeps running")
    run.add_argument(
        "--fast",
        action="store_true",
        help="Skip waiting in paper mode; execution cooldown still applies",
    )
    run.add_argument(
        "--frozen",
        action="store_true",
        help="Freeze all memory efficacies for a control run",
    )
    run.add_argument("--out", type=Path)
    run.add_argument(
        "--products",
        nargs="+",
        default=["BTC-USDC"],
        choices=["BTC-USDT", "ETH-USDT", "BNB-USDT", "SOL-USDT", "ZEC-USDT", "ADA-USDT", "AVAX-USDT", "DOT-USDT", "LINK-USDT", "LTC-USDT", "NEAR-USDT", "ATOM-USDT", "ARB-USDT", "OP-USDT", "INJ-USDT", "SUI-USDT", "SEI-USDT", "DOGE-USDT", "SHIB-USDT", "PEPE-USDT", "WIF-USDT", "FLOKI-USDT", "BONK-USDT"],
    )
    run.add_argument("--neural-ms", type=float, default=500)
    run.add_argument("--hz432", action="store_true", help="Enable 432Hz oscillatory stimulation to KC mushroom body neurons")
    run.add_argument("--hz432-current", type=float, default=5.0, help="432Hz stimulation current amplitude (default 5.0)")
    run.add_argument("--strategy", choices=["BTC-USDT", "ETH-USDT", "BNB-USDT", "SOL-USDT", "ZEC-USDT", "ADA-USDT", "AVAX-USDT", "DOT-USDT", "LINK-USDT", "LTC-USDT", "NEAR-USDT", "ATOM-USDT", "ARB-USDT", "OP-USDT", "INJ-USDT", "SUI-USDT", "SEI-USDT", "DOGE-USDT", "SHIB-USDT", "PEPE-USDT", "WIF-USDT", "FLOKI-USDT", "BONK-USDT"], default="none",
                     help="Position sizing strategy: none (fixed), martingale (double after loss), anti_martingale (double after win), kelly")
    run.add_argument(
        "--take-profit",
        type=float,
        default=0.0,
        help="Take-profit percent; when equity rises by this %% from initial capital, force SELL and reward PAM11 (0 disables)",
    )
    run.add_argument("--chan-auto", action="store_true",
                     help="[測試版] 純纏論15分K線自動交易模式")
    status = sub.add_parser("status")
    status.add_argument("--out", type=Path, default=Path("runs/paper"))
    a = p.parse_args()
    from dotenv import load_dotenv

    # Never search parent projects for unrelated account credentials.
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    if a.command in ("prepare", "verify"):
        from .data import prepare, verify

        if a.command == "prepare":
            prepare(a.reuse_doomfly)
        else:
            print(json.dumps(verify()))
        return
    if a.command == "status":
        import sqlite3

        db = sqlite3.connect(f"file:{a.out / 'ledger.sqlite'}?mode=ro", uri=True)
        meta = {k: json.loads(v) for k, v in db.execute("SELECT key,value FROM meta")}
        print(
            json.dumps(
                {
                    k: meta.get(k)
                    for k in [
                        "mode",
                        "tick",
                        "cash",
                        "positions",
                        "initial_cash",
                        "anchor",
                        "halted",
                    ]
                },
                indent=2,
            )
        )
        return
    if a.live and (a.fixture or a.fast):
        p.error("Live mode forbids fixtures and fast replay")
    if a.steps < 0:
        p.error("steps cannot be negative")
    settings = Settings(
        products=tuple(a.products),
        learning=not a.frozen,
        neural_ms=a.neural_ms,
        hz432=getattr(a, "hz432", False),
        hz432_current=getattr(a, "hz432_current", 5.0),
        pulse_ms=min(200, a.neural_ms),
    )
    out = a.out or Path("runs/live" if a.live else "runs/paper")
    out.mkdir(parents=True, exist_ok=True)
    try:
        lock = _acquire_worker_lock(out / "worker.lock")
    except BlockingIOError:
        raise SystemExit("A worker already owns this run directory")
    from .broker import BinanceBroker, CoinbaseBroker, PaperBroker
    from .ledger import Ledger

    ledger = Ledger(out / "ledger.sqlite", settings, "live" if a.live else "paper")

    # Recover tick counter from events.jsonl to avoid duplicate tick numbers after restart
    try:
        events_file = out / "events.jsonl"
        if events_file.exists() and events_file.stat().st_size > 100:
            max_tick = 0
            with open(events_file, "r", encoding="utf-8") as _ef:
                for _line in _ef:
                    _line = _line.strip()
                    if _line:
                        try:
                            _ev = json.loads(_line)
                            _t = _ev.get("tick", 0)
                            if isinstance(_t, (int, float)) and _t > max_tick:
                                max_tick = int(_t)
                        except json.JSONDecodeError:
                            continue
            current_tick = ledger.get("tick") or 0
            if max_tick > current_tick:
                ledger.put("tick", max_tick)
                print(f"[恢復] tick從{current_tick}恢復到{max_tick}（從交易記錄）", file=sys.stderr, flush=True)
    except Exception as _e:
        print(f"[恢復] tick恢復失敗: {_e}", file=sys.stderr, flush=True)

    try:
        if a.live:
            if a.exchange == "binance":
                broker = BinanceBroker.from_env(settings, ledger)
            else:
                broker = CoinbaseBroker.from_env(settings, ledger)
        else:
            broker = PaperBroker(settings, ledger)
        result = broker.preflight()
        print(json.dumps(result), flush=True)
        if a.resume_reviewed:
            if (out / "STOP").exists() or ledger.pending():
                raise RuntimeError(
                    "Remove STOP only after review; unresolved orders cannot resume"
                )
            reason = ledger.get("halted")
            if reason and ("Loss stop" in reason or "fee exceeded" in reason):
                raise RuntimeError("A financial stop cannot be cleared by this flag")
            ledger.put("halted", None)
        if a.preflight_only:
            return
        from .data import verify

        verified = verify()
        from PIL import Image

        from .actions import StonkflyActions
        from .display import market_frame, compute_macd, compute_rsi
        from .czsc_skills import analyze_czsc, get_czsc_observation
        from .chan_learning import ChanLearner
        from .chan_practical import ChanPracticalLearner
        from .chan_no_brain_trader import ChanNoBrainTrader
        from .czsc_chart import extract_czsc_structures
        from .advanced_learning import AdvancedBrain, TradeReview
        from .trade_reason import generate_buy_reason, generate_sell_reason
        from .market import BinanceMarket, CoinbaseMarket, FixtureMarket
        from .neural.controller import FlyController
        from .reinforcement import reinforcement
        from .risk import Guard, Veto
        from .strategy import StrategyState

        if a.fixture:
            market = FixtureMarket(settings.products)
        elif a.exchange == "binance":
            market = BinanceMarket(settings.products)
        else:
            market = CoinbaseMarket(settings.products)
        previous = ledger.get("observation")
        if previous:
            market.history = previous["market_history"]
            if a.fixture:
                market.tick = previous["fixture_tick"]
        controller = FlyController(settings)
        cp = ledger.get("checkpoint")
        if cp:
            path = out / cp["file"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != cp["sha256"]:
                raise RuntimeError("Checkpoint integrity mismatch")
            controller.restore(path)
        provenance = {
            "settings": dataclasses.asdict(settings),
            "dataset": verified,
            "circuit": controller.brain.circuit["report"],
            "vision": controller.brain.visual_report,
            "mode": broker.mode,
            "feed": "fixture" if a.fixture else "coinbase-public",
            "decoder": "DNp20 mean R-L: buy/sell; DNpe017 spike gate; otherwise hold. Engineered fixed mapping.",
            "learning_validated": False,
            "pain_receptors_modeled": False,
            "timing": "Each observation advances configured neural_ms regardless of wall-market time; no claim of real-time fly physiology.",
            "source_sha256": {
                str(path.relative_to(Path(__file__).parent)): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in Path(__file__).parent.rglob("*")
                if path.suffix in (".py", ".cpp")
            },
        }
        signature = hashlib.sha256(
            json.dumps(provenance, sort_keys=True).encode()
        ).hexdigest()
        if ledger.get("provenance_sha256") not in (None, signature):
            raise RuntimeError(
                "Run source/protocol changed; use a separate paper run or explicitly review migration"
            )
        ledger.put("provenance_sha256", signature)
        (out / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
        guard = Guard(settings, ledger, out / "STOP")
        strategy = StrategyState(name=getattr(a, "strategy", "none"), base_budget=100.0)
        chan_strategy = None
        chan_observations = 0  # 果蠅觀察纏論交易次數
        chan_imitation_correct = 0  # 果蠅自然決策與纏論一致次數
        if getattr(a, "chan_auto", False):
            from .chan_strategy import ChanAutoStrategy
            chan_strategy = ChanAutoStrategy(symbol=settings.products[0].replace("-","") if settings.products else "BTCUSDT", cooldown_seconds=60)
            # Sync strategy position with ledger on startup
            try:
                _product = settings.products[0] if settings.products else None
                if _product:
                    _pos = float(ledger.positions.get(_product, 0) or 0)
                    if _pos > 0.0001:
                        _init_cash = float(ledger.get("initial_cash") or 0)
                        _cash = float(ledger.get("cash") or 0)
                        _cash_spent = _init_cash - _cash
                        _avg_price = _cash_spent / _pos if _pos > 0 else None
                        if _avg_price and _avg_price > 0:
                            chan_strategy.update_position("LONG", _avg_price)
            except Exception:
                pass
            print("[纏論自動交易] 測試版已啟用，果蠅將觀察學習纏論決策", flush=True)
        chan_learner = ChanLearner(save_path=out / "chan_knowledge.json")
        practical_learner = ChanPracticalLearner(
            knowledge_path=out / "chan_knowledge.json",
            practical_path=out / "chan_practical.json"
        )
        advanced_brain = AdvancedBrain(run_dir=out)
        from .chanlun_web_learner import get_web_learner
        web_learner = get_web_learner()
        web_learner.save_path = out / "chanlun_web_learning.json"
        web_learner.state = web_learner._load_state()
        _web_study_counter = 0
        no_brain_trader = ChanNoBrainTrader(out / "no_brain_state.json", initial_cash=0)
        # 共用果蠅帳戶現金
        def _shared_cash():
            try:
                return float(broker.state().get("cash", settings.capital))
            except Exception:
                return settings.capital
        no_brain_trader.cash_provider = _shared_cash
        provider = StonkflyActions(guard, broker)
        action = provider.get_actions()[0]
        count = 0
        # RSI+CZSC trading + cooldown state
        avg_entry_price = 0.0
        trade_cooldown = 0
        last_trade_time = 0.0
        last_trade_side = None  # 記錄上次交易類型，用於區分買賣冷卻時間
        last_buy_time = 0.0
        MIN_HOLD_SECONDS = 180
        COOLDOWN_SECONDS = 40
        # 全局持久化神經模擬 executor（不使用 with，避免 shutdown 阻塞）
        _neural_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="neural-sim")
        while not a.steps or count < a.steps:
            started = time.monotonic()
            # Release unused memory before each tick - prevents gradual slowdown
            gc.collect()
            # Step-based sleep: every 25 steps, sleep & reorganize IN-PROCESS (no exit)
            if count >= 25:
                print(f"[睡眠] 已執行 {count} 步，睡眠整理大腦（進程內完成，不退出）", file=sys.stderr, flush=True)
                # Save brain checkpoint before sleep
                try:
                    _sleep_slot = ledger.get("tick") % 2
                    _sleep_ckpt = out / f"brain-{_sleep_slot}.npz"
                    controller.save(_sleep_ckpt)
                except Exception as _save_err:
                    print(f"[睡眠] 檢查點保存跳過: {_save_err}", file=sys.stderr, flush=True)
                try:
                    (out / "SLEEP").write_text(json.dumps({
                        "tick": ledger.get("tick"),
                        "steps": count,
                        "time": time.time(),
                    }))
                except Exception:
                    pass
                gc.collect()
                # Brain consolidation during sleep: prune weak synapses
                try:
                    if hasattr(controller, 'brain') and hasattr(controller.brain, 'consolidate'):
                        controller.brain.consolidate(prune_threshold=0.01)
                        print("[睡眠] 大腦記憶鞏固完成，弱化突觸已修剪", file=sys.stderr, flush=True)
                except Exception as _e:
                    print(f"[睡眠] 記憶鞏固跳過: {_e}", file=sys.stderr, flush=True)
                # 重置計數器，繼續循環（不退出進程）
                count = 0
                gc.collect()
                print("[睡眠] 整理完成，繼續運行", file=sys.stderr, flush=True)
            stop_requested = (out / "STOP").exists()
            halted = ledger.get("halted")
            if stop_requested or halted:
                reason = "STOP file exists" if stop_requested else f"run is halted: {halted}"
                print(f"Run stopped before tick: {reason}", file=sys.stderr, flush=True)
                break
            broker.reconcile()
            broker.verify_balances()
            quotes = market.snapshot()
            guard.check(quotes, time.time())
            market.record(quotes)
            product = settings.products[ledger.get("tick") % len(settings.products)]
            q = quotes[product]
            equity = ledger.equity(quotes)
            # Position info (moved early for chan strategy)
            pos_qty = float(ledger.positions.get(product, 0))
            current_price = float(q.bid)
            has_position = pos_qty > 0.0001
            # [測試版] 純纏論15分K線自動交易 + 果蠅觀察學習
            chan_result = None
            fly_natural_side = "HOLD"  # 果蠅自然決策（observe之後才知道，先預設）
            if chan_strategy is not None:
                chan_result = chan_strategy.analyze(interval="15m")
                chan_sig = chan_result.get("signal", "HOLD")
                chan_reason = chan_result.get("reason", "")
                if chan_sig == "BUY" and not has_position:
                    chan_strategy.mark_traded()
                    chan_observations += 1
                elif chan_sig == "SELL" and has_position:
                    chan_strategy.mark_traded()
                    chan_observations += 1
            kind, delta = reinforcement(
                equity, ledger.get("anchor"), settings.reward_deadband
            )
            # Take-profit: equity >= initial*(1+tp%) forces SELL + PAM11 reward
            take_profit_hit = False
            if a.take_profit and a.take_profit > 0:
                _init_cap = D(ledger.get("initial_cash"))
                _tp_thresh = _init_cap * (1 + D(a.take_profit) / D(100))
                _has_pos = any(D(_v) > 0 for _v in ledger.positions.values())
                if equity >= _tp_thresh and _has_pos:
                    take_profit_hit = True
                    kind = "reward"
                    delta = equity - D(ledger.get("anchor"))
            # [觀察學習] 纏論交易時用reward刺激，讓果蠅學習該決策模式
            if chan_strategy is not None and chan_result is not None and chan_result.get("signal") in ("BUY", "SELL"):
                kind = "reward"
            macd = compute_macd(market.history[product])
            rsi = compute_rsi(market.history[product])
            rsi_latest = float(rsi[-1]) if len(rsi) and not np.isnan(rsi[-1]) else None
            # CZSC 缠论 analysis - fruit fly learns technical analysis skills
            czsc_analysis = analyze_czsc(market.history[product])

            # 無腦交易：基於纏論5分K線買賣標記自動交易（獨立帳戶）
            try:
                # 從幣安API獲取5分K線數據
                import urllib.request as _ur
                _nb_symbol = product.replace("-", "") if product else "BTCUSDT"
                _nb_url = "https://api.binance.com/api/v3/klines?symbol=" + _nb_symbol + "&interval=5m&limit=200"
                _nb_req = _ur.Request(_nb_url, headers={"User-Agent": "Mozilla/5.0"})
                with _ur.urlopen(_nb_req, timeout=10) as _nb_resp:
                    _nb_raw = json.loads(_nb_resp.read().decode("utf-8"))
                _klines_for_nb = [{"t": k[0], "o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4]), "v": float(k[5])} for k in _nb_raw]
                _czsc_struct = extract_czsc_structures(_klines_for_nb, freq="5m")
                _czsc_struct["klines"] = _klines_for_nb  # 傳入K線數據用於預測分型
                _current_price = float(q.bid) if q and hasattr(q, 'bid') else 0.0
                _nb_result = no_brain_trader.process_signal(_czsc_struct, _current_price)
                _nb_status = no_brain_trader.get_status(_current_price)
            except Exception as _nb_err:
                _nb_result = {"action": "ERROR", "reason": str(_nb_err)}
                _current_price = float(q.bid) if q and hasattr(q, 'bid') else 0.0
                _nb_status = no_brain_trader.get_status(_current_price)
            czsc_obs = get_czsc_observation(market.history[product])
            # Price percentile: teach fly to buy at lows, sell at highs
            _prices = np.asarray(market.history[product][-100:], dtype=float)
            if len(_prices) > 10:
                _p_high, _p_low = float(np.max(_prices)), float(np.min(_prices))
                _p_range = _p_high - _p_low or 1.0
                price_percentile = max(0, min(100, (float(q.bid) - _p_low) / _p_range * 100))
            else:
                price_percentile = 50.0

            # === 震盪盤識別 + ATR計算 ===
            _is_ranging = False
            _atr_pct = 1.5  # 預設1.5%波動
            try:
                _recent_prices = np.asarray(market.history[product][-20:], dtype=float)
                if len(_recent_prices) >= 10:
                    _h = float(np.max(_recent_prices))
                    _l = float(np.min(_recent_prices))
                    _avg = float(np.mean(_recent_prices))
                    _volatility = (_h - _l) / _avg * 100 if _avg > 0 else 100
                    _is_ranging = _volatility < 1.0
                    # ATR近似：最近20根的平均真實波幅百分比
                    _diffs = np.abs(np.diff(_recent_prices))
                    _atr_pct = float(np.mean(_diffs) / _avg * 100) if _avg > 0 else 1.5
                    if _atr_pct < 0.3: _atr_pct = 0.3  # 最低0.3%
            except Exception:
                pass
            # === 趨勢過濾器：EMA20/EMA60判斷下跌趨勢 ===
            _is_downtrend = False
            try:
                _hist_prices = np.asarray(market.history[product][-60:], dtype=float)
                if len(_hist_prices) >= 20:
                    # EMA計算
                    def _ema(arr, period):
                        k = 2 / (period + 1)
                        e = arr[0]
                        for v in arr[1:]:
                            e = v * k + e * (1 - k)
                        return e
                    _ema20 = _ema(_hist_prices[-20:], 20) if len(_hist_prices) >= 20 else _hist_prices[-1]
                    _ema60 = _ema(_hist_prices, 60) if len(_hist_prices) >= 60 else _ema(_hist_prices[-20:], 20)
                    _cur_price = float(q.bid)
                    # 下跌趨勢：EMA20 < EMA60 且 價格在EMA20下方
                    _is_downtrend = (_ema20 < _ema60) and (_cur_price < _ema20)
            except Exception:
                pass

            frame = market_frame(product, market.history[product], q.bid, q.ask, macd=macd, strategy=strategy.to_dict(), czsc=czsc_obs)
            # 神經模擬超時機制：超過60秒自動跳過，避免無限循環卡住整個交易循環
            # 使用全局持久化 executor，不使用 with 語句（避免 shutdown(wait=True) 阻塞）
            _neural_timeout = 60  # 秒
            _neural_start = time.time()
            try:
                _neural_future = _neural_executor.submit(controller.observe, frame, kind, czsc=czsc_analysis)
                neural = _neural_future.result(timeout=_neural_timeout)
            except FuturesTimeoutError:
                _neural_elapsed = time.time() - _neural_start
                print(f"[超時] 神經模擬超過{_neural_timeout}s（已用{_neural_elapsed:.1f}s），跳過本次模擬，使用HOLD默認值", file=sys.stderr, flush=True)
                # 取消未完成的 future（儘管無法強制中斷執行緒，但可以阻止回調）
                try:
                    _neural_future.cancel()
                except Exception:
                    pass
                neural = {
                    "side": "HOLD",
                    "left_hz": 0.0,
                    "right_hz": 0.0,
                    "difference_hz": 0.0,
                    "gate_spikes": 0,
                    "kc_spikes": 0,
                    "total_spikes": 0,
                    "compute_seconds": _neural_elapsed,
                    "decision_note": f"神經模擬超時{_neural_elapsed:.0f}s，跳過",
                    "rsi": 50,
                    "price_percentile": 50,
                    "avg_entry": None,
                    "position": 0,
                    "cash": 0,
                    "pnl": 0,
                    "unrealized_pnl": 0,
                }
            except Exception as _neural_err:
                print(f"[錯誤] 神經模擬異常: {_neural_err}", file=sys.stderr, flush=True)
                neural = {
                    "side": "HOLD", "left_hz": 0.0, "right_hz": 0.0, "difference_hz": 0.0,
                    "gate_spikes": 0, "kc_spikes": 0, "total_spikes": 0,
                    "compute_seconds": 0, "decision_note": f"神經模擬錯誤: {str(_neural_err)[:30]}",
                    "rsi": 50, "price_percentile": 50, "avg_entry": None,
                    "position": 0, "cash": 0, "pnl": 0, "unrealized_pnl": 0,
                }
            # Compute time guard: if neural simulation exceeds 30s, flag for optimization
            _compute_sec = neural.get("compute_seconds", 0)
            if _compute_sec > 30:
                print(f"[警告] 神經模擬耗時{_compute_sec:.1f}s，建議睡眠整理", file=sys.stderr, flush=True)
            # 進階學習：果蠅在每個tick都進行進階知識學習
            try:
                _neural_activity = float(neural.get("total_spikes", 0)) / 1000.0 if neural.get("total_spikes", 0) > 0 else 0.5
                advanced_brain.study(neural_activity=min(1.0, max(0.1, _neural_activity)))
            except Exception as _adv_err:
                pass
            # [果蠅參考纏論指標自主決策] 果蠅參考纏論數據後自己判斷買賣
            # 全局冷卻：賣出後15分鐘內不再買入（避免追高），買入後5分鐘內不再交易
            if last_trade_side == "SELL":
                _global_cooldown = 300  # 賣出後5分鐘冷卻（避免追高但不錯過機會）
            else:
                _global_cooldown = 0  # 買入後不全局冷卻（加倉由_add_cooldown控制）
            _time_since_trade = time.time() - last_trade_time if last_trade_time > 0 else 9999
            _in_cooldown = _time_since_trade < _global_cooldown

            # 加倉限制：已有持倉時，需比均價低6%才能加倉(購買後不追高)，最多加倉2次
            # 下跌趨勢中禁止馬丁格爾加倉，只做短線反彈
            _max_add_count = 2  # 最多加倉2次，避免無限攤平
            _add_position_threshold = 0.06  # 需跌6%才能加倉
            _can_add_position = not _is_downtrend  # 下跌趨勢禁止加倉
            if has_position and pos_qty > 0 and not _is_downtrend:
                if add_count >= _max_add_count:
                    _can_add_position = False
                elif avg_entry_price > 0 and current_price > avg_entry_price * (1 - _add_position_threshold):
                    _can_add_position = False

            if chan_strategy is not None and chan_result is not None:
                fly_natural_side = neural.get("side", "HOLD")
                chan_sig = chan_result.get("signal", "HOLD")
                # 下跌趨勢：只在RSI<30超賣時考慮小倉反彈，且TP改為3%
                if _is_downtrend and chan_sig == "BUY" and rsi_latest > 30:
                    chan_sig = "HOLD"  # RSI不夠低，不接飛刀
                chan_reason = chan_result.get("reason", "")
                fly_gate = neural.get("gate_spikes", 0)
                fly_diff = abs(neural.get("right_hz", 0) - neural.get("left_hz", 0))
                # 纏論指標細節
                chan_rsi = chan_result.get("rsi", 0)
                chan_trend = chan_result.get("trend", "?")
                chan_bull = chan_result.get("bull_score", 0)
                chan_bear = chan_result.get("bear_score", 0)
                chan_pivot = chan_result.get("in_pivot", False)
                chan_div = chan_result.get("divergence", "")
                chan_conf = chan_result.get("confidence", 0)
                chan_czsc = chan_result.get("czsc_signal", "")
                chan_strokes = chan_result.get("strokes", 0)
                chan_pivots = chan_result.get("pivots", 0)
                # === 學習成果接入交易決策 ===
                # 纏論理論學習偏見：掌握度越高，對纏論訊號信任度越高
                _learn_bias = chan_learner.get_trading_bias()
                _buy_conf = _learn_bias.get("buy_confidence", 0)
                _sell_conf = _learn_bias.get("sell_confidence", 0)
                _overall_knowledge = _learn_bias.get("overall", 0)
                # 實戰學習器評估目前市場狀態
                _practical_signal = practical_learner.evaluate_signal(
                    czsc_obs, has_position, current_price, avg_entry_price
                ) if hasattr(practical_learner, 'evaluate_signal') else {"signal": "HOLD", "confidence": 0, "reason": ""}
                _prac_sig = _practical_signal.get("signal", "HOLD")
                _prac_conf = _practical_signal.get("confidence", 0)
                _prac_reason = _practical_signal.get("reason", "")

                # 果蠅參考纏論建議再下單：不能自己無腦下單
                # 基礎買入：雙方共識 或 纏論主導(果蠅不反對)
                want_buy = (fly_natural_side == "BUY" and chan_sig == "BUY") or (chan_sig == "BUY" and fly_natural_side == "HOLD")
                # 基礎賣出：雙方共識 或 纏論主導(果蠅不反對)
                want_sell = (fly_natural_side == "SELL" and chan_sig == "SELL") or (chan_sig == "SELL" and fly_natural_side == "HOLD")

                # 學習加成：實戰學習器高信心買入(>60)且果蠅不反對 → 也可買入
                if _prac_sig == "BUY" and _prac_conf > 60 and fly_natural_side != "SELL" and not has_position:
                    want_buy = True
                # 學習加成：實戰學習器高信心賣出(>60)且果蠅不反對 → 也可賣出
                if _prac_sig == "SELL" and _prac_conf > 60 and fly_natural_side != "BUY" and has_position:
                    want_sell = True
                # 知識不足時(<30)更保守：需要果蠅+纏論共識才買
                if _overall_knowledge < 30 and not (fly_natural_side == "BUY" and chan_sig == "BUY"):
                    want_buy = False

                # 建構纏論指標摘要
                chan_summary = f"RSI{chan_rsi:.0f} 多空{chan_bull}/{chan_bear} 趨勢{chan_trend}"
                if chan_pivot:
                    chan_summary += " 中樞內"
                if chan_div:
                    chan_summary += f" {chan_div}"
                if chan_czsc:
                    chan_summary += f" {chan_czsc}"

                # TP3止盈：價格達到TP3(均價+1.5%)立即賣出，不等纏論
                _tp3_pct = 0.03 if _is_downtrend else 0.015  # 下跌趨勢反彈3%就跑
                _tp3_price = avg_entry_price * (1 + _tp3_pct) if avg_entry_price > 0 else 0
                if has_position and _tp3_price > 0 and current_price >= _tp3_price:
                    neural["side"] = "SELL"
                    neural["fly_side"] = fly_natural_side
                    neural["chan_side"] = chan_sig
                    _pnl_pct = (current_price - avg_entry_price) / avg_entry_price * 100
                    neural["decision_note"] = f"[TP3止盈] 均價${avg_entry_price:.2f} 現價${current_price:.2f} 達到TP3(${_tp3_price:.2f})，全數出清，盈虧{_pnl_pct:+.3f}%"
                # 纏論賣出模式：有持倉時，纏論指示SELL就全數出清
                elif has_position and chan_sig == "SELL":
                    # 纏論指示賣出，全數出清
                    neural["side"] = "SELL"
                    neural["fly_side"] = fly_natural_side
                    neural["chan_side"] = "SELL"
                    _pnl_pct = (current_price - avg_entry_price) / avg_entry_price * 100 if avg_entry_price > 0 else 0
                    if _prac_sig == "SELL" and _prac_conf > 60 and chan_sig != "SELL":
                        decision_tag = "[實戰學習主導賣出]"
                        decision_reason = f"實戰學習器高信心({_prac_conf:.0f}%)觸發:{_prac_reason}，賣出信心{_sell_conf:.0f}%，全數出清，盈虧{_pnl_pct:+.3f}%"
                    elif fly_natural_side == "SELL":
                        decision_tag = "[果蠅+纏論共識賣出]"
                        decision_reason = f"果蠅與纏論同時指示賣出，{chan_summary}，賣出信心{_sell_conf:.0f}%，全數出清，盈虧{_pnl_pct:+.3f}%"
                    else:
                        decision_tag = "[纏論主導賣出]"
                        decision_reason = f"纏論指標觸發賣出:{chan_summary} 信心{chan_conf:.0f}%，果蠅建議{fly_natural_side}，賣出信心{_sell_conf:.0f}%，跟隨纏論全數出清，盈虧{_pnl_pct:+.3f}%"
                    neural["decision_note"] = f"{decision_tag} {decision_reason}"
                    chan_observations += 1
                elif has_position:
                    # 已有持倉，纏論未說賣出，繼續持有
                    neural["side"] = "HOLD"
                    neural["fly_side"] = fly_natural_side
                    neural["chan_side"] = chan_sig
                    _current_pct = (current_price - avg_entry_price) / avg_entry_price * 100 if avg_entry_price > 0 else 0
                    _learn_note = f" 知識{_overall_knowledge:.0f}% 實戰:{_prac_sig}({_prac_conf:.0f}%)" if _prac_sig != "HOLD" else f" 知識{_overall_knowledge:.0f}%"
                    neural["decision_note"] = f"[持有中] 均價${avg_entry_price:.2f} 現價${current_price:.2f} ({_current_pct:+.3f}%) | 等待賣出訊號 | 果蠅:{fly_natural_side} 纏論:{chan_sig}{_learn_note}"
                elif want_buy and not _in_cooldown:
                    # 無持倉，正常買入
                    if _prac_sig == "BUY" and _prac_conf > 60 and chan_sig != "BUY":
                        decision_tag = "[實戰學習主導買入]"
                        decision_reason = f"實戰學習器高信心({_prac_conf:.0f}%)觸發:{_prac_reason}，理論知識{_overall_knowledge:.0f}%，果蠅{fly_natural_side}不反對，跟隨入場"
                    elif fly_natural_side == "BUY" and chan_sig == "BUY":
                        chan_imitation_correct += 1
                        decision_tag = "[果蠅+纏論共識]"
                        decision_reason = f"果蠅參考纏論指標({chan_summary})後同意買入，閘門{fly_gate} 左右腦差{fly_diff:.1f}Hz，理論知識{_overall_knowledge:.0f}% 買入信心{_buy_conf:.0f}%，雙方共識入場"
                    else:
                        decision_tag = "[纏論主導買入]"
                        decision_reason = f"纏論指標觸發買入:{chan_summary} 信心{chan_conf:.0f}%，果蠅不反對({fly_natural_side})，理論知識{_overall_knowledge:.0f}% 買入信心{_buy_conf:.0f}%，跟隨入場"
                    neural["side"] = "BUY"
                    neural["fly_side"] = fly_natural_side
                    neural["chan_side"] = chan_sig
                    neural["decision_note"] = f"{decision_tag} {decision_reason}"
                    chan_observations += 1
                else:
                    # 無持倉且未觸發買入，觀察
                    neural["side"] = "HOLD"
                    neural["fly_side"] = fly_natural_side
                    neural["chan_side"] = chan_sig
                    _cooldown_note = ""
                    if _in_cooldown:
                        _cooldown_note = f" 冷卻中({int(_global_cooldown - _time_since_trade)}s)"
                    neural["decision_note"] = f"[觀察等待買點] 果蠅:{fly_natural_side} 纏論:{chan_sig} | {chan_summary} | 模仿率{(chan_imitation_correct/chan_observations*100) if chan_observations else 0:.0f}%{_cooldown_note}"
            neural_side = neural.get("side", "HOLD")
            if take_profit_hit:
                neural["side"] = "SELL"
                neural["take_profit"] = True
                neural["take_profit_pct"] = a.take_profit
            # Checkpoint + accounting anchor are committed before any trade.
            # Two slots keep the last committed snapshot safe during a crash.
            slot = ledger.get("tick") % 2
            checkpoint = out / f"brain-{slot}.npz"
            controller.save(checkpoint)
            checkpoint_info = {
                "file": checkpoint.name,
                "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            }
            macd_latest = {
                "dif": float(macd["dif"][-1]) if len(macd["dif"]) and not np.isnan(macd["dif"][-1]) else None,
                "dea": float(macd["dea"][-1]) if len(macd["dea"]) and not np.isnan(macd["dea"][-1]) else None,
                "hist": float(macd["hist"][-1]) if len(macd["hist"]) and not np.isnan(macd["hist"][-1]) else None,
            }


            observation = {
                "neural": neural,
                "product": product,
                "quote": q.json(),
                "pnl_delta_usdc": str(delta),
                "market_history": market.history,
                "fixture_tick": getattr(market, "tick", None),
                "macd": macd_latest,
                "rsi": rsi_latest,
                "czsc": czsc_analysis,
                "price_percentile": price_percentile,
                "chan_auto": chan_result,
                "chan_observations": chan_observations,
                "chan_imitation_rate": (chan_imitation_correct / chan_observations * 100) if chan_observations > 0 else 0,
            }
            # Periodically compact SQLite WAL to prevent growth
            if count > 0 and count % 100 == 0:
                try:
                    ledger.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception:
                    pass

            ledger.commit_tick(equity, checkpoint_info, observation)
            order = {"status": "HOLD"}
            neural_left = neural.get("left_hz", 0)
            neural_right = neural.get("right_hz", 0)
            neural_gate = neural.get("gate_spikes", 0)
            # 併合模式：果蠅只跟隨纏論決策，跳過所有獨立賣出邏輯
            neural["side"] = neural.get("side", "HOLD")  # 保持纏論決策
            rsi_val = rsi_latest

            # 跳過所有獨立賣出邏輯（700-980行），直接到執行階段
            # 只保留 trailing peak 追蹤用於無腦
            if has_position and avg_entry_price > 0:
                if trailing_peak is None:
                    trailing_peak = current_price
                trailing_peak = max(trailing_peak, current_price)
            else:
                trailing_peak = None
            tp_stage = 0  # 重置TP階段，由無腦處理止盈

            # [併合模式] 跳過獨立賣出邏輯，只跟隨纏論決策
            # Unlimited capital mode: no cash check, fixed 0.1 BTC per buy
            # 啟動保護：前10個tick只觀察不交易，讓果蠅先熟悉市場
            FLY_STARTUP_TICKS = 10
            if count < FLY_STARTUP_TICKS and neural["side"] != "HOLD":
                order = {"status": "HOLD", "reason": f"啟動觀察中({count+1}/{FLY_STARTUP_TICKS})，先看後動"}
                neural["side"] = "HOLD"
            elif neural["side"] != "HOLD":
                try:
                    # Neural integration can be slow; use a fresh execution book.
                    fresh = market.snapshot()
                    latest = fresh[product]
                    if abs(latest.bid - q.bid) / q.bid > D(settings.slippage):
                        raise Veto("Price moved beyond neural observation tolerance")
                    provider.quotes = fresh
                    # Use batch_size for buy quantity if available, default 1.0 BTC
                    fixed_btc = neural.get("batch_size", 1.0)
                    if neural["side"] == "BUY":
                        guard.strategy_budget = fixed_btc * current_price * 1.01  # 1% buffer for exact fill
                    else:
                        _sell_pct = neural.get("sell_pct", 1.0)
                        _pos_qty = float(ledger.positions.get(product, 0))
                        if _pos_qty > 0:
                            guard.strategy_budget = _pos_qty * _sell_pct * current_price * 1.01  # sell all position with 1% buffer
                        else:
                            guard.strategy_budget = 0
                    order = action.invoke({"product": product, "side": neural["side"]})
                    guard.strategy_budget = None
                except Veto as e:
                    order = {"status": "VETO", "reason": str(e)}
            # Record trade outcome for strategy learning
            if order.get("status") in ("FILLED", "SETTLED"):
                strategy.record_trade(float(delta))
                last_trade_time = time.time()  # 40-second cooldown after each trade
                last_trade_side = neural.get("side", None)  # 記錄交易類型用於冷卻
                exec_side = neural.get("side", order.get("side", ""))
                if exec_side == "BUY":
                    last_buy_time = time.time()
                    tp_stage = 0  # track buy time for min hold
                    if has_position:
                        add_count += 1  # 加倉次數+1
                    else:
                        add_count = 0  # 新倉重置計數
                if exec_side == "SELL":
                    add_count = 0  # 賣出後重置加倉計數
                # After sell, reset grid reference to current price
                if exec_side == "SELL":
                    grid_ref_price = current_price
                # Sync position to chan strategy for take-profit/stop-loss
                if chan_strategy is not None:
                    _exec_qty = float(order.get("base", 0))
                    _exec_price = float(order.get("quote", 0)) / _exec_qty if _exec_qty > 0 else current_price
                    if exec_side == "BUY":
                        chan_strategy.update_position("LONG", _exec_price)
                    elif exec_side == "SELL":
                        chan_strategy.update_position(None)
                exec_qty = float(order.get("base", 0))
                exec_price = float(order.get("quote", 0)) / exec_qty if exec_qty > 0 else current_price
                if exec_side == "BUY" and exec_qty > 0:
                    if avg_entry_price == 0 or pos_qty == 0:
                        avg_entry_price = exec_price
                    else:
                        total_cost = avg_entry_price * pos_qty + exec_price * exec_qty
                        avg_entry_price = total_cost / (pos_qty + exec_qty)
                elif exec_side == "SELL":
                    new_qty = pos_qty - exec_qty
                    if new_qty <= 0.0001:
                        avg_entry_price = 0.0
            add_count = 0  # 加倉次數計數
            # Add TP levels and avg entry to neural for UI display
            _tp_disp_pct = 0.03 if _is_downtrend else 0.015
            neural["tp1"] = round(avg_entry_price * (1 + _tp_disp_pct*0.33), 2) if avg_entry_price > 0 else None
            neural["tp2"] = round(avg_entry_price * (1 + _tp_disp_pct*0.66), 2) if avg_entry_price > 0 else None
            neural["tp3"] = round(avg_entry_price * (1 + _tp_disp_pct), 2) if avg_entry_price > 0 else None
            neural["trend"] = "下跌" if _is_downtrend else "震盪/上漲" 
            neural["avg_entry"] = round(avg_entry_price, 2) if avg_entry_price > 0 else None
            neural["atr_pct"] = round(_atr_pct, 2)
            neural["regime"] = "震盪盤" if _is_ranging else "趨勢盤"

            row = {
                "tick": ledger.get("tick"),
                "wall_time": time.time(),
                "product": product,
                "mode": broker.mode,
                "quote": q.json(),
                "equity_usdc": str(equity),
                "pnl_delta_usdc": str(delta),
                "neural": neural,
                "execution": order,
                "macd": macd_latest,
                "rsi": rsi_latest,
                "czsc": czsc_analysis,
                "price_percentile": price_percentile,
                "cooldown_remaining": 20.0,
                "hold_remaining": 0,
                "chan_learning": chan_learner.get_knowledge_summary(),
                "chan_bias": chan_learner.get_trading_bias(),
                "chan_practical": practical_learner.get_summary(),
                "chan_web": {
                    "total_articles": web_learner.state.get("total_articles_studied", 0),
                    "concepts": web_learner.state.get("concepts_learned", {}),
                    "last_article": web_learner.state.get("current_article_title", ""),
                },
                "advanced_learning": advanced_brain.get_status(),
                "web_learning": web_learner.get_status(),
                "strategy": strategy.to_dict(),
                "no_brain": _nb_status,
                "no_brain_action": _nb_result,
            }
            # Only record actual FILLED trades, not unexecuted BUY/SELL decisions
            _is_trade = order.get("status") in ("FILLED", "SETTLED")
            if _is_trade:
                with (out / "events.jsonl").open("a") as f:
                    f.write(json.dumps(row, allow_nan=False) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            Image.fromarray(frame).save(out / "latest-input.png")
            (out / "latest.json").write_text(json.dumps(row, indent=2) + "\n")
            try:
                print(
                    json.dumps(
                        {
                            "tick": row["tick"],
                            "side": neural["side"],
                            "execution": order["status"],
                            "equity": str(equity),
                            "stimulus": kind,
                            "plastic_edges_changed": neural["memory"]["changed_edges"],
                        }
                    ),
                    flush=True,
                )
            except OSError:
                pass  # hidden window has no stdout
            count += 1
            # Per-step cooldown: 20 seconds, fly studies theory + practical
            if not a.steps or count < a.steps:
                cooldown_end = time.time() + 20
                study_concept = chan_learner.start_study()
                practical_learner.start_practice()
                market_for_practice = {
                    "rsi": rsi_val,
                    "czsc": czsc_analysis,
                    "price": float(q.bid),
                }
                # 每3步學習一篇chanlun.com文章
                _web_study_counter += 1
                _web_study_result = None
                if _web_study_counter >= 3:
                    _web_study_counter = 0
                    try:
                        _web_study_result = web_learner.study_random()
                        # 將網路學習成果注入chan_learner知識庫
                        if _web_study_result and _web_study_result.get("success"):
                            _web_concepts = _web_study_result.get("concepts", {})
                            # 映射web概念到chan_learner概念並提升掌握度
                            _concept_map = {
                                "fractal": "fractal", "stroke": "stroke",
                                "pivot": "pivot", "divergence": "divergence",
                                "buy_point": "buy_point", "sell_point": "sell_point",
                            }
                            for _web_key, _chan_key in _concept_map.items():
                                if _web_key in _web_concepts and _chan_key in chan_learner.concepts:
                                    _mentions = _web_concepts[_web_key]
                                    _boost = min(2.0, _mentions * 0.2)
                                    _c = chan_learner.concepts[_chan_key]
                                    _c.level = min(100, _c.level + _boost)
                            chan_learner.save()
                    except Exception as _web_err:
                        print(f"[纏論網路學習] 錯誤: {_web_err}", flush=True)
                while time.time() < cooldown_end and not (out / "STOP").exists():
                    neural_activity = min(1.0, 0.5 + (neural.get("total_spikes", 100000) / 500000) * 0.3)
                    chan_learner.study_step(neural_activity=neural_activity)
                    practical_learner.practice_with_market(market_for_practice)
                    time.sleep(2)
                chan_learner.stop_study()
                practical_learner.stop_practice()
    except KeyboardInterrupt:
        print("Stopped; run state preserved.", flush=True)
    except Exception as e:
        # Never print SDK exception text: it may contain account/request details.
        if not ledger.get("halted"):
            ledger.halt(type(e).__name__)
        frames = traceback.extract_tb(e.__traceback__)
        origin = frames[-1] if frames else None
        internal = origin and Path(origin.filename).is_relative_to(
            Path(__file__).parent
        )
        diagnostic = {
            "type": type(e).__name__,
            "reason": str(e)
            if internal
            else "External dependency error; review connection and account state.",
            "locations": [
                f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in frames
            ],
        }
        (out / "error.json").write_text(json.dumps(diagnostic, indent=2) + "\n")
        print(
            f"Stopped safely: {type(e).__name__}. Inspect local state and reconcile before restarting.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    finally:
        ledger.close()
        _release_worker_lock(lock)


if __name__ == "__main__":
    main()
