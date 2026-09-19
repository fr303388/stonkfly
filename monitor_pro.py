"""Professional Stonkfly monitor with 3D brain visualization.

Features:
- Three.js 3D point cloud of all 166,700 neurons at actual MaleCNS coordinates
- Binance ZECUSDT 1-minute klines
- Photoreceptor overlay on price chart
- 6-step process flow, decision panel, feedback panel
- Color by region, rotation controls, slow-motion firing animation

Usage:
    python monitor_pro.py [--port 8767] [--run runs/paper]
"""
import argparse
import json
import sqlite3
import time
import urllib.request
from pathlib import Path

import numpy as np
from flask import Flask, jsonify, send_file, make_response, send_from_directory

app = Flask(__name__)

@app.errorhandler(Exception)
def handle_all_errors(e):
    import traceback
    traceback.print_exc()
    return jsonify({"error": str(e), "type": type(e).__name__}), 500
RUN_DIR = Path("runs/paper")

_brain3d_cache = {"mtime": 0, "data": None}
_brain_cache = {"mtime": 0, "data": None}
_binance_cache = {}  # interval -> {time, data}
_token_cache = {"time": 0, "data": None}
_meta_cache = {"mtime": 0, "data": None}


def _read_json(path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_events(path, limit=300):
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:]


def _ledger_meta(db_path):
    if not db_path.exists():
        return {}
    try:
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        meta = {k: json.loads(v) for k, v in db.execute("SELECT key,value FROM meta")}
        db.close()
        return meta
    except Exception:
        return {}


def _get_graph_path():
    p = RUN_DIR.parent.parent / "data" / "graph.npz"
    if p.exists():
        return p
    return Path("data/graph.npz")


def _load_brain3d():
    """Load 3D neuron positions, types, and current spike counts."""
    global _brain3d_cache
    import time as _time
    checkpoints = sorted(RUN_DIR.glob("brain-*.npz"), key=lambda p: p.stat().st_mtime)
    if not checkpoints:
        mtime_key = "static"
    else:
        mtime_key = checkpoints[-1].stat().st_mtime

    # Time-based cache: don't reload more than once every 30 seconds
    now = _time.time()
    if (_brain3d_cache["data"] is not None and
        _brain3d_cache.get("load_time", 0) > now - 30):
        return _brain3d_cache["data"]

    if _brain3d_cache["mtime"] == mtime_key and _brain3d_cache["data"] is not None:
        _brain3d_cache["load_time"] = now
        return _brain3d_cache["data"]

    graph_path = _get_graph_path()
    if not graph_path.exists():
        return {"error": "graph.npz not found"}

    with np.load(graph_path, allow_pickle=False) as g:
        ids = g["ids"]
        retina = g["retina"].astype(np.int32)
        uv = g["uv"]

    # Load annotations for 3D positions and types
    ann_path = graph_path.parent / "annotations.feather"
    import pyarrow.feather as feather
    ann = feather.read_table(ann_path).to_pandas().set_index("bodyId")
    ann = ann.reindex(ids)
    types = ann["type"].fillna("").astype(str)
    superclass = ann["superclass"].fillna("unassigned").astype(str)
    soma_side = ann["somaSide"].fillna("?").astype(str)

    # Extract 3D positions from somaLocation
    positions = np.zeros((len(ids), 3), dtype=np.float32)
    for i, loc in enumerate(ann["somaLocation"]):
        if loc is not None and hasattr(loc, "__len__") and len(loc) >= 3:
            positions[i] = [float(loc[0]), float(loc[1]), float(loc[2])]

    # Normalize positions to center and scale
    pos_min = positions.min(axis=0)
    pos_max = positions.max(axis=0)
    center = (pos_min + pos_max) / 2
    scale = 1.0 / max(pos_max - pos_min)
    positions = (positions - center) * scale * 2  # normalize to roughly [-1, 1]

    # Load spike counts from latest checkpoint
    counts = np.zeros(len(ids), dtype=np.int32)
    if checkpoints:
        try:
            with np.load(checkpoints[-1], allow_pickle=False) as a:
                counts = a["counts"].astype(np.int32)
        except Exception:
            pass

    # Identify key cell populations
    def idx_of(prefix=None, exact=None):
        if exact is not None:
            return np.flatnonzero(types.eq(exact)).astype(np.int32)
        return np.flatnonzero(types.str.startswith(prefix)).astype(np.int32)

    kc = idx_of(prefix="KC")
    pam11 = idx_of(exact="PAM11")
    ppl101 = idx_of(exact="PPL101")
    mbon07 = idx_of(exact="MBON07")
    mbon11 = idx_of(exact="MBON11")
    dnp20 = idx_of(exact="DNp20")
    dnpe017 = idx_of(exact="DNpe017")
    r8p = idx_of(exact="R8p")
    r8y = idx_of(exact="R8y")

    # Region coloring based on superclass
    region_map = {}
    for i, sc in enumerate(superclass):
        region_map.setdefault(sc, []).append(i)

    # Color palette for regions
    palette = [
        "#ffd700", "#00f0ff", "#ff00aa", "#00ff88", "#ff8800",
        "#aa00ff", "#ff0055", "#00aaff", "#88ff00", "#ffaa00",
        "#00ffaa", "#ff5500", "#5500ff", "#0088ff", "#ffff00",
        "#ff00ff", "#00ffff", "#88ff88", "#ff8888", "#8888ff",
    ]
    region_colors = {}
    for i, region in enumerate(sorted(region_map.keys())):
        region_colors[region] = palette[i % len(palette)]

    # Assign colors
    colors = np.zeros((len(ids), 3), dtype=np.float32)
    for region, indices in region_map.items():
        c = region_colors[region]
        r = int(c[1:3], 16) / 255.0
        g = int(c[3:5], 16) / 255.0
        b = int(c[5:7], 16) / 255.0
        colors[indices] = [r, g, b]

    # Key cells get special bright colors
    key_cells = {
        "KC": (kc, "#ffff00"),
        "PAM11": (pam11, "#00ff88"),
        "PPL101": (ppl101, "#ff0055"),
        "MBON07": (mbon07, "#aa00ff"),
        "MBON11": (mbon11, "#ff8800"),
        "DNp20": (dnp20, "#ff00aa"),
        "DNpe017": (dnpe017, "#ffffff"),
    }
    key_cell_info = {}
    for name, (indices, color) in key_cells.items():
        if len(indices):
            c = color
            r = int(c[1:3], 16) / 255.0
            g = int(c[3:5], 16) / 255.0
            b = int(c[5:7], 16) / 255.0
            colors[indices] = [r, g, b]
            # Average position for label
            avg_pos = positions[indices].mean(axis=0).tolist()
            key_cell_info[name] = {
                "count": int(len(indices)),
                "spikes": int(counts[indices].sum()),
                "position": avg_pos,
                "color": color,
                "indices": indices.tolist()[:20],  # sample for detail
            }

    # Downsample for transfer if too many (166k is fine, but let's be safe)
    max_points = 166700
    if len(ids) > max_points:
        step = len(ids) // max_points
        sel = np.arange(0, len(ids), step)
    else:
        sel = np.arange(len(ids))

    result = {
        "n_neurons": int(len(ids)),
        "positions": positions[sel].flatten().tolist(),
        "colors": colors[sel].flatten().tolist(),
        "spikes": counts[sel].tolist(),
        "types": types.iloc[sel].tolist(),
        "superclasses": superclass.iloc[sel].tolist(),
        "regions": {r: {"count": len(idx), "color": region_colors[r]} for r, idx in region_map.items()},
        "key_cells": key_cell_info,
        "retina_uv": uv.tolist(),
        "retina_indices": retina.tolist(),
        "total_spikes": int(counts.sum()),
        "active_neurons": int(np.count_nonzero(counts)),
    }
    _brain3d_cache["mtime"] = mtime_key
    _brain3d_cache["data"] = result
    _brain3d_cache["load_time"] = _time.time()
    return result


def _load_brain_summary():
    """Lightweight brain summary for the side panels."""
    global _brain_cache
    checkpoints = sorted(RUN_DIR.glob("brain-*.npz"), key=lambda p: p.stat().st_mtime)
    if not checkpoints:
        return None
    mtime = checkpoints[-1].stat().st_mtime
    if _brain_cache["mtime"] == mtime and _brain_cache["data"] is not None:
        return _brain_cache["data"]
    try:
        with np.load(checkpoints[-1], allow_pickle=False) as a:
            counts = a["counts"].astype(np.int64)
            v = a["v"].astype(np.float32)
        graph_path = _get_graph_path()
        with np.load(graph_path, allow_pickle=False) as g:
            ids = g["ids"]
        import pyarrow.feather as feather
        ann = feather.read_table(graph_path.parent / "annotations.feather").to_pandas().set_index("bodyId")
        types = ann["type"].reindex(ids).fillna("")
        pops = {}
        for name, mask in [
            ("retina", types.str.startswith("R")),
            ("lamina", types.isin(["L1", "L2", "L3", "L5"])),
            ("kc", types.str.startswith("KC")),
            ("pam11", types.eq("PAM11")),
            ("ppl101", types.eq("PPL101")),
            ("mbon07", types.eq("MBON07")),
            ("mbon11", types.eq("MBON11")),
            ("dnp20", types.eq("DNp20")),
            ("dnpe017", types.eq("DNpe017")),
        ]:
            idx = np.flatnonzero(mask.to_numpy())
            pops[name] = {"count": int(counts[idx].sum()), "n": int(len(idx)), "mean_v": float(np.mean(v[idx])) if len(idx) else 0}
        result = {"populations": pops, "total_spikes": int(counts.sum()), "mean_v": float(np.mean(v))}
        _brain_cache = {"mtime": mtime, "data": result}
        return result
    except Exception as e:
        return {"error": str(e)}


def _fetch_binance(interval="1m", limit=200):
    """Fetch Binance ZECUSDT klines."""
    global _binance_cache
    now = time.time()
    if interval in _binance_cache and now - _binance_cache[interval]["time"] < 3:
        return _binance_cache[interval]["data"]
    url = f"https://api.binance.com/api/v3/klines?symbol=ZECUSDT&interval={interval}&limit={limit}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        klines = [{"t": k[0], "o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4]), "v": float(k[5])} for k in raw]
        _binance_cache[interval] = {"time": now, "data": klines}
        return klines
    except Exception as e:
        return {"error": str(e)}


def _fetch_token_info():
    """Fetch ZECUSDT 24hr ticker from Binance."""
    global _token_cache
    now = time.time()
    if _token_cache["data"] and now - _token_cache["time"] < 5:
        return _token_cache["data"]
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr?symbol=ZECUSDT"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            d = json.loads(resp.read().decode("utf-8"))
        info = {
            "price": float(d["lastPrice"]),
            "symbol": "ZEC",
            "quote": "USDT",
            "price_change": {"h24": float(d["priceChangePercent"]), "h1": 0, "m5": 0},
            "volume": {"h24": float(d["quoteVolume"])},
            "liquidity": 0,
        }
        _token_cache = {"time": now, "data": info}
        return info
    except Exception as e:
        return {"error": str(e), "price": 0}



@app.route("/")
def index():
    resp = make_response(send_file(Path(__file__).with_name("monitor_pro.html")))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/api/state")
def api_state():
    try:
        latest = _read_json(RUN_DIR / "latest.json") or {}
        meta = _ledger_meta(RUN_DIR / "ledger.sqlite")
        events = _read_events(RUN_DIR / "events.jsonl")
        brain = _load_brain_summary()
        watchdog = _read_json(RUN_DIR / "watchdog_stats.json") or {"restart_count": 0}
        # 無腦交易紀錄與狀態
        no_brain_state = _read_json(RUN_DIR / "no_brain_state.json") or {}
        no_brain_trades = no_brain_state.get("trades", [])
        return jsonify({"latest": latest, "meta": meta, "events": events, "brain": brain, "watchdog": watchdog, "no_brain_trades": no_brain_trades, "no_brain_state": no_brain_state, "server_time": time.time()})
    except Exception as e:
        return jsonify({"latest": {}, "meta": {}, "events": [], "brain": {}, "watchdog": {"restart_count": 0}, "no_brain_trades": [], "no_brain_state": {}, "error": str(e), "server_time": time.time()})


_brain3d_json_cache = {"json": None, "time": 0}

@app.route("/api/brain3d")
def api_brain3d():
    try:
        import time as _t
        now = _t.time()
        # Cache serialized JSON for 30 seconds to avoid re-serializing 18MB
        if _brain3d_json_cache["json"] and _brain3d_json_cache["time"] > now - 30:
            from flask import Response
            return Response(_brain3d_json_cache["json"], mimetype="application/json")
        data = _load_brain3d()
        json_str = json.dumps(data)
        _brain3d_json_cache["json"] = json_str
        _brain3d_json_cache["time"] = now
        from flask import Response
        return Response(json_str, mimetype="application/json")
    except Exception as e:
        return jsonify({"error": str(e), "neurons": 0, "positions": []})


@app.route("/api/binance")
def api_binance():
    from flask import request
    interval = request.args.get("interval", "5m")
    if interval not in ("1m", "5m", "15m", "30m", "1h", "4h", "8h", "1d"):
        interval = "1m"
    return jsonify(_fetch_binance(interval=interval))



@app.route("/api/czsc")
def api_czsc():
    from flask import request
    interval = request.args.get("interval", "15m")
    if interval not in ("1m", "5m", "15m", "30m", "1h", "4h", "8h", "1d"):
        interval = "15m"
    try:
        from stonkfly.czsc_chart import extract_czsc_structures
        klines = _fetch_binance(interval=interval, limit=200)
        structures = extract_czsc_structures(klines, freq=interval)
        return jsonify(structures)
    except Exception as e:
        return jsonify({"fractals": [], "strokes": [], "pivots": [], "signal": f"error: {e}"})


_depth_cache = {"time": 0, "data": None}

@app.route("/api/depth")
def api_depth():
    """Fetch Binance ZECUSDT order book depth."""
    global _depth_cache
    now = time.time()
    if _depth_cache["data"] and now - _depth_cache["time"] < 1:
        return jsonify(_depth_cache["data"])
    try:
        url = "https://api.binance.com/api/v3/depth?symbol=ZECUSDT&limit=20"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        bids = [[float(b[0]), float(b[1])] for b in raw.get("bids", [])]
        asks = [[float(a[0]), float(a[1])] for a in raw.get("asks", [])]
        result = {"bids": bids, "asks": asks, "timestamp": now}
        _depth_cache = {"time": now, "data": result}
        return jsonify(result)
    except Exception as e:
        return jsonify({"bids": [], "asks": [], "error": str(e)})


@app.route("/api/token")
def api_token():
    return jsonify(_fetch_token_info())


@app.route("/api/input.png")
def api_input():
    p = RUN_DIR / "latest-input.png"
    if not p.exists():
        return ("no input", 404)
    return send_file(p, mimetype="image/png")


@app.route("/trade_sound.mp3")
def trade_sound():
    p = Path(__file__).with_name("trade_sound.mp3")
    if not p.exists():
        return ("no sound", 404)
    return send_file(p, mimetype="audio/mpeg")


@app.route("/fly_brain_3d.js")
def fly_brain_3d_js():
    p = Path(__file__).with_name("fly_brain_3d.js")
    if not p.exists():
        return ("not found", 404)
    return send_file(p, mimetype="application/javascript")


@app.route("/brain-swat/")
def brain_swat_index():
    return send_file(Path(__file__).with_name("brain_swat.html"))


@app.route("/fly-game/")
def fly_game_index():
    return send_file(Path(__file__).with_name("fly_game.html"))


@app.route("/fonts/<path:filename>")
def fonts(filename):
    return send_from_directory(Path(__file__).with_name("fonts"), filename)


@app.route("/swat/")
def swat_index():
    p = Path(__file__).with_name("swat_atlas")
    return send_from_directory(p, "index.html")


@app.route("/swat/<path:filename>")
def swat_static(filename):
    p = Path(__file__).with_name("swat_atlas")
    return send_from_directory(p, filename)


@app.route("/brain3d/")
def brain3d_index():
    return send_file(Path(__file__).with_name("brain3d_fastfly.html"))


@app.route("/cerebra/")
def cerebra_index():
    p = Path(__file__).with_name("cerebra_atlas")
    return send_from_directory(p, "index.html")


@app.route("/cerebra/<path:filename>")
def cerebra_static(filename):
    p = Path(__file__).with_name("cerebra_atlas")
    return send_from_directory(p, filename)


@app.route("/data/<path:filename>")
def cerebra_data(filename):
    p = Path(__file__).with_name("cerebra_atlas")
    return send_from_directory(p, f"data/{filename}")


@app.route("/api/neuron/<neuron_id>")
def cerebra_neuron_api(neuron_id):
    # Cerebra neuron API - try to serve from data directory
    p = Path(__file__).with_name("cerebra_atlas")
    neuron_file = p / "data" / "neurons" / f"{neuron_id}.json"
    if neuron_file.exists():
        return send_file(neuron_file, mimetype="application/json")
    # Return minimal neuron info if file not found
    return jsonify({"id": neuron_id, "status": "not_cached"})


@app.route("/api/advanced")
def api_advanced():
    """Advanced learning status: knowledge base, trade reviews, market regime"""
    result = {"knowledge": None, "reviews": None, "lessons": []}
    try:
        kp = RUN_DIR / "advanced_knowledge.json"
        if kp.exists():
            data = json.loads(kp.read_text(encoding="utf-8"))
            concepts = data.get("concepts", {})
            domains = {}
            for key, cdata in concepts.items():
                domain = key.split(".")[0] if "." in key else "other"
                if domain not in domains:
                    domains[domain] = []
                domains[domain].append(cdata.get("level", 0))
            domain_avg = {d: sum(v)/len(v) for d, v in domains.items() if v}
            overall = sum(c.get("level", 0) for c in concepts.values()) / len(concepts) if concepts else 0
            result["knowledge"] = {
                "overall": round(overall, 1),
                "domains": domain_avg,
                "total_concepts": len(concepts),
                "mastered": sum(1 for c in concepts.values() if c.get("level", 0) >= 80),
                "study_time_min": round(data.get("total_study_time", 0) / 60, 1),
            }
    except Exception as e:
        result["knowledge_error"] = str(e)
    try:
        rp = RUN_DIR / "trade_reviews.json"
        if rp.exists():
            data = json.loads(rp.read_text(encoding="utf-8"))
            result["reviews"] = {
                "total": data.get("total_reviews", 0),
                "strategy_stats": data.get("strategy_stats", {}),
                "regime_stats": data.get("regime_stats", {}),
            }
    except Exception as e:
        result["reviews_error"] = str(e)
    return jsonify(result)



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--run", type=Path, default=Path("runs/paper"))
    args = parser.parse_args()
    global RUN_DIR
    RUN_DIR = args.run.resolve()
    print(f"[PRO] Stonkfly Pro Monitor -> http://127.0.0.1:{args.port}")
    print(f"[PRO] Run dir: {RUN_DIR}")
    app.run(host="127.0.0.1", port=args.port, debug=False, load_dotenv=False)


if __name__ == "__main__":
    main()
