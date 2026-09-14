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
        choices=["coinbase", "binance"],
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
        choices=["BTC-USDC", "ETH-USDC", "SOL-USDC", "PEPE-USDT", "BTC-USDT", "BNB-USDT"],
    )
    run.add_argument("--neural-ms", type=float, default=500)
    run.add_argument("--hz432", action="store_true", help="Enable 432Hz oscillatory stimulation to KC mushroom body neurons")
    run.add_argument("--hz432-current", type=float, default=5.0, help="432Hz stimulation current amplitude (default 5.0)")
    run.add_argument("--strategy", choices=["none", "martingale", "anti_martingale", "kelly"], default="none",
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
        strategy = StrategyState(name=getattr(a, "strategy", "none"), base_budget=10000000.0)
        chan_strategy = None
        chan_observations = 0  # 果蠅觀察纏論交易次數
        chan_imitation_correct = 0  # 果蠅自然決策與纏論一致次數
        if getattr(a, "chan_auto", False):
            from .chan_strategy import ChanAutoStrategy
            chan_strategy = ChanAutoStrategy(symbol="BTCUSDT", cooldown_seconds=60)
            print("[纏論自動交易] 測試版已啟用，果蠅將觀察學習纏論決策", flush=True)
        chan_learner = ChanLearner(save_path=out / "chan_knowledge.json")
        practical_learner = ChanPracticalLearner(
            knowledge_path=out / "chan_knowledge.json",
            practical_path=out / "chan_practical.json"
        )
        advanced_brain = AdvancedBrain(run_dir=out)
        provider = StonkflyActions(guard, broker)
        action = provider.get_actions()[0]
        count = 0
        # RSI+CZSC trading + cooldown state
        avg_entry_price = 0.0
        trade_cooldown = 0
        last_trade_time = 0.0
        last_buy_time = 0.0
        MIN_HOLD_SECONDS = 180
        COOLDOWN_SECONDS = 40
        while not a.steps or count < a.steps:
            started = time.monotonic()
            # Release unused memory before each tick - prevents gradual slowdown
            gc.collect()
            # Step-based sleep: every 25 steps, force sleep & reorganize
            if count >= 25:
                print(f"[睡眠] 已執行 {count} 步，強制睡眠整理大腦", file=sys.stderr, flush=True)
                # Save brain checkpoint before sleep
                _sleep_slot = ledger.get("tick") % 2
                _sleep_ckpt = out / f"brain-{_sleep_slot}.npz"
                controller.save(_sleep_ckpt)
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
                sys.exit(42)
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
            czsc_obs = get_czsc_observation(market.history[product])
            # Price percentile: teach fly to buy at lows, sell at highs
            _prices = np.asarray(market.history[product][-100:], dtype=float)
            if len(_prices) > 10:
                _p_high, _p_low = float(np.max(_prices)), float(np.min(_prices))
                _p_range = _p_high - _p_low or 1.0
                price_percentile = max(0, min(100, (float(q.bid) - _p_low) / _p_range * 100))
            else:
                price_percentile = 50.0
            frame = market_frame(product, market.history[product], q.bid, q.ask, macd=macd, strategy=strategy.to_dict(), czsc=czsc_obs)
            neural = controller.observe(frame, kind, czsc=czsc_analysis)
            # Compute time guard: if neural simulation exceeds 30s, flag for optimization
            _compute_sec = neural.get("compute_seconds", 0)
            if _compute_sec > 30:
                print(f"[警告] 神經模擬耗時{_compute_sec:.1f}s，建議睡眠整理", file=sys.stderr, flush=True)
            # [觀察學習] 纏論決策覆蓋果蠅自然決策，並記錄模仿準確率
            if chan_strategy is not None and chan_result is not None:
                fly_natural_side = neural.get("side", "HOLD")
                chan_sig = chan_result.get("signal", "HOLD")
                chan_reason = chan_result.get("reason", "")
                if chan_sig == "BUY" and not has_position:
                    if fly_natural_side == "BUY":
                        chan_imitation_correct += 1
                    neural["side"] = "BUY"
                    neural["decision_note"] = f"[纏論自動] {chan_reason} (信心{chan_result.get('confidence',0)}%)"
                elif chan_sig == "SELL" and has_position:
                    if fly_natural_side == "SELL":
                        chan_imitation_correct += 1
                    neural["side"] = "SELL"
                    neural["decision_note"] = f"[纏論自動] {chan_reason} (信心{chan_result.get('confidence',0)}%)"
                else:
                    neural["side"] = "HOLD"
                    neural["decision_note"] = f"[纏論自動] {chan_reason} (觀察{chan_observations}次 模仿率{(chan_imitation_correct/chan_observations*100) if chan_observations else 0:.0f}%)"
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
            # 儲存纏論決策（混合邏輯可能覆蓋，稍後恢復）
            chan_decision_side = neural.get("side", "HOLD")
            chan_decision_note = neural.get("decision_note", "")
            neural["side"] = "HOLD"
            neural["decision_note"] = "神經觀察中"

            rsi_val = rsi_latest
            czsc_dir = czsc_analysis.get("last_bi_direction", "unknown")
            czsc_bull = czsc_analysis.get("bullish_score", 50)
            czsc_bear = czsc_analysis.get("bearish_score", 50)
            czsc_in_zs = czsc_analysis.get("in_zs", False)
            rsi_neutral = rsi_val is not None and 35 < rsi_val < 65

            # CHAN THEORY LEARNING BIAS - knowledge influences trading
            chan_bias = chan_learner.get_trading_bias()
            buy_conf = chan_bias["buy_confidence"]    # 買點辨識信心 0-100
            sell_conf = chan_bias["sell_confidence"]  # 賣點辨識信心 0-100
            pivot_aware = chan_bias["pivot_awareness"] # 中樞辨識能力 0-100
            overall_know = chan_bias["overall"]       # 整體知識等級 0-100

            # PRIMARY: RSI oversold (<=30) + CZSC confirmation → BUY
            # Learning boost: if fly mastered buy points (>=50%), accept RSI<=35
            rsi_buy_thresh = 45 if buy_conf >= 50 else 40
            if rsi_val is not None and rsi_val <= rsi_buy_thresh and not has_position and trade_cooldown == 0:
                czsc_ok = czsc_bull > czsc_bear or czsc_dir == "up"
                # If learning is low (<20%), require stronger CZSC advantage
                if buy_conf < 20:
                    czsc_ok = czsc_bull > czsc_bear + 5
                if czsc_ok:
                    confirm_reason = "多頭壓倒" if czsc_bull > czsc_bear else ("最後一筆向上" if czsc_dir == "up" else "中樞震盪")
                    learn_tag = f"知識{overall_know:.0f}%買點{buy_conf:.0f}%"
                    neural["side"] = "BUY"
                    neural["decision_note"] = generate_buy_reason(
                        rsi=rsi_val, czsc=czsc_analysis, price_percentile=price_percentile,
                        neural_gate=neural_gate, neural_diff=neural_right-neural_left,
                        has_position=has_position
                    ) + f" [{learn_tag}]"
                else:
                    neural["decision_note"] = f"RSI {rsi_val:.1f} 超賣但纏論偏空({czsc_bull:.0f}/{czsc_bear:.0f})，觀望"

            # PRIMARY: RSI overbought (>=70) + CZSC confirmation → SELL
            # Learning boost: if fly mastered sell points (>=50%), accept RSI>=65
            rsi_sell_thresh = 55 if sell_conf >= 50 else 60
            if rsi_val is not None and rsi_val >= rsi_sell_thresh and has_position and trade_cooldown == 0:
                czsc_ok = czsc_bear > czsc_bull or czsc_dir == "down"
                # If learning is low (<20%), require stronger CZSC advantage
                if sell_conf < 20:
                    czsc_ok = czsc_bear > czsc_bull + 5
                if czsc_ok:
                    confirm_reason = "空頭壓倒" if czsc_bear > czsc_bull else "最後一筆向下"
                    learn_tag = f"知識{overall_know:.0f}%賣點{sell_conf:.0f}%"
                    neural["side"] = "SELL"
                    neural["decision_note"] = generate_sell_reason(
                        rsi=rsi_val, czsc=czsc_analysis, price_percentile=price_percentile,
                        neural_gate=neural_gate, neural_diff=neural_right-neural_left,
                        has_position=has_position
                    ) + f" [{learn_tag}]"
                else:
                    neural["decision_note"] = f"RSI {rsi_val:.1f} 超買但纏論偏多({czsc_bull:.0f}/{czsc_bear:.0f})，持有"

            # PRACTICAL: Chan Theory practical skills signal
            practical_signal = practical_learner.get_trading_signal(
                rsi=rsi_val if rsi_val else 50,
                czsc=czsc_analysis,
                has_position=has_position,
                price_percentile=price_percentile
            )
            if neural["side"] == "HOLD" and trade_cooldown == 0 and practical_signal["signal"] != "HOLD":
                pside = practical_signal["signal"]
                pconf = practical_signal["confidence"]
                # Require minimum 30% practical confidence
                if pconf >= 15:
                    if pside == "BUY" and not has_position:
                        neural["side"] = "BUY"
                        # Find which skill triggered
                        skill_key = ""
                        for s in practical_learner.skills.values():
                            if s.name_zh in practical_signal.get("reason", ""):
                                skill_key = s.name
                                break
                        neural["decision_note"] = generate_buy_reason(
                            rsi=rsi_val, czsc=czsc_analysis, price_percentile=price_percentile,
                            neural_gate=neural_gate, neural_diff=neural_right-neural_left,
                            practical_skill=skill_key, confidence=pconf, has_position=has_position
                        )
                    elif pside == "SELL" and has_position:
                        neural["side"] = "SELL"
                        skill_key = ""
                        for s in practical_learner.skills.values():
                            if s.name_zh in practical_signal.get("reason", ""):
                                skill_key = s.name
                                break
                        neural["decision_note"] = generate_sell_reason(
                            rsi=rsi_val, czsc=czsc_analysis, price_percentile=price_percentile,
                            neural_gate=neural_gate, neural_diff=neural_right-neural_left,
                            practical_skill=skill_key, confidence=pconf, has_position=has_position
                        )

            # PARTIAL: Neural network decision - requires minimum Chan knowledge
            # Fly must have >=20% overall knowledge to make neural decisions
            # Higher knowledge lowers gate/difference thresholds
            if neural["side"] == "HOLD" and trade_cooldown == 0:
                neural_diff = neural_right - neural_left
                # Bold mode: neural can trade at any knowledge level, lower thresholds
                if neural_gate >= 2 and neural_diff >= 3 and not has_position and (rsi_val is None or rsi_val < 55):
                    gate_ok = neural_gate >= 2
                    diff_ok = neural_diff >= 3
                    if gate_ok and diff_ok:
                        learn_tag = f"知識{overall_know:.0f}%買點{buy_conf:.0f}%"
                        neural["side"] = "BUY"
                        neural["decision_note"] = generate_buy_reason(
                            rsi=rsi_val, czsc=czsc_analysis, price_percentile=price_percentile,
                            neural_gate=neural_gate, neural_diff=neural_diff,
                            has_position=has_position
                        ) + f" [神經決策 {learn_tag}]"
                    else:
                        neural["decision_note"] = f"神經觀察中 (閘門{neural_gate} 差{neural_diff:.1f}Hz 未達門檻)"
                elif neural_gate >= 2 and neural_diff <= -3 and has_position and (rsi_val is None or rsi_val > 45):
                    gate_ok = neural_gate >= 2
                    diff_ok = neural_diff <= -3
                    if gate_ok and diff_ok:
                        learn_tag = f"知識{overall_know:.0f}%賣點{sell_conf:.0f}%"
                        neural["side"] = "SELL"
                        neural["decision_note"] = generate_sell_reason(
                            rsi=rsi_val, czsc=czsc_analysis, price_percentile=price_percentile,
                            neural_gate=neural_gate, neural_diff=neural_diff,
                            has_position=has_position
                        ) + f" [神經決策 {learn_tag}]"
                    else:
                        neural["decision_note"] = f"神經觀察中 (閘門{neural_gate} 差{neural_diff:.1f}Hz 未達門檻)"
                elif neural_gate < 3:
                    neural["decision_note"] = f"神經觀察中 (閘門{neural_gate}<2 RSI{rsi_val:.0f} 知識{overall_know:.0f}%)"
                else:
                    neural["decision_note"] = f"神經觀察中 (差{neural_diff:.1f}Hz RSI{rsi_val:.0f} 知識{overall_know:.0f}%)"

            # VISUAL: Photoreceptor input touches bottom -> buy, touches top -> sell
            if neural["side"] == "HOLD" and trade_cooldown == 0:
                if price_percentile <= 25 and not has_position:
                    neural["side"] = "BUY"
                    neural["decision_note"] = generate_buy_reason(
                        rsi=rsi_val, czsc=czsc_analysis, price_percentile=price_percentile,
                        neural_gate=neural_gate, neural_diff=neural_right-neural_left,
                        practical_skill="bottom_fractal", has_position=has_position
                    ) + " [視覺觸底]"
                elif price_percentile >= 75 and has_position:
                    neural["side"] = "SELL"
                    neural["decision_note"] = generate_sell_reason(
                        rsi=rsi_val, czsc=czsc_analysis, price_percentile=price_percentile,
                        neural_gate=neural_gate, neural_diff=neural_right-neural_left,
                        practical_skill="top_fractal", has_position=has_position
                    ) + " [視覺觸頂]"

            # Per-step cooldown: 40 seconds after every step (handled at end of loop)
            cooldown_remaining = 0
            trade_cooldown = 0
            # Minimum hold time: cannot sell within 180 seconds of last buy
            hold_remaining = 0
            if has_position and last_buy_time > 0:
                hold_remaining = max(0, MIN_HOLD_SECONDS - (time.time() - last_buy_time))
            if hold_remaining > 0 and neural["side"] == "SELL":
                neural["side"] = "HOLD"
                neural["decision_note"] = f"最短持有中 ({hold_remaining:.0f}秒)"

            # [纏論自動模式] 始終使用纏論決策（包括HOLD），完全覆蓋混合邏輯
            if chan_strategy is not None:
                neural["side"] = chan_decision_side
                neural["decision_note"] = chan_decision_note

            # Unlimited capital mode: no cash check, fixed 0.1 BTC per buy
            if neural["side"] != "HOLD":
                try:
                    # Neural integration can be slow; use a fresh execution book.
                    fresh = market.snapshot()
                    latest = fresh[product]
                    if abs(latest.bid - q.bid) / q.bid > D(settings.slippage):
                        raise Veto("Price moved beyond neural observation tolerance")
                    provider.quotes = fresh
                    # Fixed 0.1 BTC per buy, unlimited capital
                    fixed_btc = 1.0
                    if neural["side"] == "BUY":
                        guard.strategy_budget = fixed_btc * current_price
                    else:
                        guard.strategy_budget = float(ledger.cash)  # sell all
                    order = action.invoke({"product": product, "side": neural["side"]})
                    guard.strategy_budget = None
                except Veto as e:
                    order = {"status": "VETO", "reason": str(e)}
            # Record trade outcome for strategy learning
            if order.get("status") == "FILLED":
                strategy.record_trade(float(delta))
                last_trade_time = time.time()  # 40-second cooldown after each trade
                exec_side = order.get("side", "")
                if exec_side == "BUY":
                    last_buy_time = time.time()  # track buy time for min hold
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
                "hold_remaining": hold_remaining,
                "chan_learning": chan_learner.get_knowledge_summary(),
                "chan_bias": chan_learner.get_trading_bias(),
                "chan_practical": practical_learner.get_summary(),
                "advanced_learning": advanced_brain.get_status(),
                "strategy": strategy.to_dict(),
            }
            # Only record actual trades (FILLED) or BUY/SELL decisions, not HOLD
            _is_trade = order.get("status") == "FILLED" or neural["side"] in ("BUY", "SELL")
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
