"""Only RGB and engineered reinforcement enter the network. No market policy."""

import hashlib

import numpy as np

from .common import annotations
from .visual import VisualMemoryBrain


class Decoder:
    def __init__(self, ids, annotation, threshold):
        types = annotation.type.fillna("")
        sides = annotation.somaSide.fillna("")
        self.left = np.flatnonzero(types.eq("DNp20") & sides.eq("L"))
        self.right = np.flatnonzero(types.eq("DNp20") & sides.eq("R"))
        self.gate = np.flatnonzero(types.eq("DNpe017"))
        if not len(self.left) or not len(self.right) or not len(self.gate):
            raise RuntimeError("Missing annotated BCI outputs")
        self.threshold = threshold
        self.identities = {
            k: [str(ids[i]) for i in getattr(self, k)]
            for k in ["left", "right", "gate"]
        }

    def decode(self, counts, seconds):
        # Mean rates prevent side population size from creating a built-in bias.
        left = float(np.mean(counts[self.left]) / seconds)
        right = float(np.mean(counts[self.right]) / seconds)
        difference = right - left
        gate = int(counts[self.gate].sum())
        side = (
            "HOLD"
            if not gate or abs(difference) < self.threshold
            else "BUY"
            if difference > 0
            else "SELL"
        )
        return {
            "side": side,
            "left_hz": left,
            "right_hz": right,
            "difference_hz": difference,
            "gate_spikes": gate,
            "cell_ids": self.identities,
        }


class FlyController:
    def __init__(self, settings):
        self.s = settings
        self.brain = VisualMemoryBrain()
        self.brain.weights_frozen = not settings.learning
        self.decoder = Decoder(
            self.brain.ids, annotations(self.brain.ids), settings.decoder_threshold_hz
        )
        self.hz432_phase = 0.0  # accumulated phase for 432Hz oscillation

    def observe(self, rgb, reinforcement, czsc=None):
        if reinforcement not in ("none", "reward", "aversive"):
            raise ValueError("Unknown reinforcement")
        # CZSC 缠论 direct neural input: stimulate KC subpopulations
        czsc_bull = float(czsc.get("bullish_score", 50) / 100.0) if czsc else 0.5
        czsc_bear = float(czsc.get("bearish_score", 50) / 100.0) if czsc else 0.5
        czsc_trend = float(czsc.get("trend", 0)) if czsc else 0.0
        # Split KC neurons into two halves: bullish-encoding vs bearish-encoding
        kc_all = self.brain.circuit["kc"]
        kc_half = len(kc_all) // 2
        kc_bull_ids = kc_all[:kc_half]   # first half = bullish CZSC channel
        kc_bear_ids = kc_all[kc_half:]   # second half = bearish CZSC channel
        b = self.brain
        counts = np.zeros(b.n, dtype=np.int32)
        wall = 0.0
        remaining = round(self.s.neural_ms / b.dt)
        pulse = round(self.s.pulse_ms / b.dt) if reinforcement != "none" else 0
        delivered = 0
        while remaining:
            n = min(remaining, round(self.s.neural_bin_ms / b.dt))
            if pulse:
                n = min(n, pulse)
            stimulus = []
            if pulse:
                stimulus.append((b.circuit[reinforcement], self.s.pulse_current))
            # 432Hz oscillatory stimulation to KC (mushroom body)
            if getattr(self.s, "hz432", False):
                dt_sec = n * b.dt / 1000.0
                self.hz432_phase += 2 * 3.141592653589793 * 432 * dt_sec
                kc_current = float(self.s.hz432_current) * (0.5 + 0.5 * __import__("math").sin(self.hz432_phase))
                stimulus.append((b.circuit["kc"], kc_current))
            # CZSC 缠论 direct input: bullish stimulates first KC half, bearish second half
            if czsc is not None:
                bull_current = 8.0 * czsc_bull * (1.0 + 0.3 * czsc_trend)
                bear_current = 8.0 * czsc_bear * (1.0 - 0.3 * czsc_trend)
                if bull_current > 0.5:
                    stimulus.append((kc_bull_ids, bull_current))
                if bear_current > 0.5:
                    stimulus.append((kc_bear_ids, bear_current))
            c, elapsed = b.rgb_step(
                rgb, n * b.dt, learning=self.s.learning, stimulation=stimulus if stimulus else None
            )
            counts += c
            wall += elapsed
            remaining -= n
            if pulse:
                delivered += n
                pulse -= n
        b.counts[:] = counts
        return {
            **self.decoder.decode(counts, self.s.neural_ms / 1000),
            "brain_ms": b.sim_ms,
            "compute_seconds": wall,
            "stimulus": reinforcement,
            "stimulus_ms": delivered * b.dt,
            "reward_spikes": int(counts[b.circuit["reward"]].sum()),
            "aversive_spikes": int(counts[b.circuit["aversive"]].sum()),
            "KC_spikes": int(counts[b.circuit["kc"]].sum()),
            "total_spikes": int(counts.sum()),
            "hz432": bool(getattr(self.s, "hz432", False)),
            "hz432_phase": float(self.hz432_phase),
            "czsc_input": czsc is not None,
            "czsc_bull_current": float(8.0 * czsc_bull * (1.0 + 0.3 * czsc_trend)),
            "czsc_bear_current": float(8.0 * czsc_bear * (1.0 - 0.3 * czsc_trend)),
            "spike_sha256": hashlib.sha256(counts.tobytes()).hexdigest(),
            "input_sha256": hashlib.sha256(np.asarray(rgb).tobytes()).hexdigest(),
            "memory": b.memory(),
        }

    def save(self, path):
        self.brain.checkpoint(path)

    def restore(self, path):
        self.brain.restore(path)
