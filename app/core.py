# -*- coding: utf-8 -*-
"""一轮采集的业务逻辑：读 universe -> 拉快照 -> 配对 -> 落库。"""
import json
import os
import time

from . import store, venues

UNIVERSE_PATH = os.environ.get("UNIVERSE_PATH", "/app/config/universe.json")


def load_universe():
    """每轮都重新读，改完 config 不用重启容器。"""
    try:
        with open(UNIVERSE_PATH, encoding="utf-8") as f:
            u = json.load(f)
        return {k: v for k, v in u.items() if not k.startswith("_")}
    except Exception:
        return {}


def build_pairs(universe, snap):
    legs_out, pairs_out = [], []
    for asset, mapping in universe.items():
        legs = []
        for venue, symbol in mapping.items():
            if venue.startswith("_"):
                continue
            r = snap.get((venue, symbol))
            if not r:
                continue
            legs.append({
                "asset": asset, "venue": venue, "symbol": symbol,
                "rate": r["rate"], "interval_h": r["interval_h"],
                "apr": venues.apr(r), "mark": r["mark"],
            })
        legs_out.extend(legs)
        if len(legs) < 2:
            continue
        lo = min(legs, key=lambda x: x["apr"])   # 在这里做多（费率最负 = 收钱）
        hi = max(legs, key=lambda x: x["apr"])   # 在这里做空（费率最正 = 收钱）
        basis = ((hi["mark"] - lo["mark"]) / lo["mark"] * 100.0
                 if lo["mark"] else None)
        pairs_out.append({
            "asset": asset,
            "long_venue": lo["venue"], "long_apr": lo["apr"] * 100.0,
            "short_venue": hi["venue"], "short_apr": hi["apr"] * 100.0,
            "net_apr": (hi["apr"] - lo["apr"]) * 100.0,
            "mark_spread_pct": basis,
            "n_legs": len(legs),
        })
    return legs_out, pairs_out


def run_once():
    universe = load_universe()
    if not universe:
        return 0, 0, {"_": {"ok": False, "err": "universe.json 是空的"}}
    want_okx = {m.get("okx") for m in universe.values() if m.get("okx")}
    snap, health = venues.collect(want_okx=want_okx or None)
    legs, pairs = build_pairs(universe, snap)
    ts = int(time.time())
    store.write_round(ts, legs, pairs, health)
    return len(legs), len(pairs), health
