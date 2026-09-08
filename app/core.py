# -*- coding: utf-8 -*-
"""一轮采集：读 universe -> 拉行情 -> 算折溢价与资金费差 -> 落库。"""
import time

from . import quotes, store, universe as uni_store, venues



def load_universe():
    """标的清单从可写副本读，每轮重新读——页面上加了标的立即生效。"""
    return uni_store.parsed()


def _prem(px, anchor):
    if not px or not anchor:
        return None
    return (px / anchor - 1.0) * 100.0


def build(universe, snap, fx):
    legs_out, pairs_out = [], []
    for asset, cfg in universe.items():
        info = quotes.anchor_usd(cfg.get("underlying"), fx) or {}
        anchor = info.get("anchor")

        legs = []
        for venue, symbol in cfg["venues"].items():
            r = snap.get((venue, symbol))
            if not r:
                continue
            # 折溢价用最新成交价，与交易所页面口径一致；
            # 拿不到再退回标记价
            px = r.get("last") or r.get("mark")
            legs.append({
                "asset": asset, "venue": venue, "symbol": symbol,
                "rate": r.get("rate"), "interval_h": r.get("interval_h"),
                "apr": venues.apr(r), "mark": r.get("mark"), "last": r.get("last"),
                "bid": r.get("bid"), "bid_sz": r.get("bid_sz"),
                "ask": r.get("ask"), "ask_sz": r.get("ask_sz"),
                "next_ts": _ms(r.get("next_ts")),
                "premium_pct": _prem(px, anchor),
            })
        legs_out.extend(legs)

        row = {"asset": asset, "n_legs": len(legs),
               "anchor_usd": anchor, "stock_price": info.get("stock_price"),
               "ccy": info.get("ccy"), "fx": info.get("fx"),
               "stock_name": info.get("name") or cfg.get("name"),
               "quote_time": info.get("quote_time"),
               "long_venue": None, "long_apr": None, "short_venue": None,
               "short_apr": None, "net_apr": None, "mark_spread_pct": None,
               "best_prem_venue": None, "best_prem_pct": None,
               "worst_prem_venue": None, "worst_prem_pct": None}

        # 折溢价：最贵的那家（溢价最高）才是你能做的方向——
        # 买入现货 + 做空永续；折价你没法做，因为现货做空对散户不可行。
        pl = [l for l in legs if l["premium_pct"] is not None]
        if pl:
            hi = max(pl, key=lambda x: x["premium_pct"])
            lo = min(pl, key=lambda x: x["premium_pct"])
            row.update(best_prem_venue=hi["venue"], best_prem_pct=hi["premium_pct"],
                       worst_prem_venue=lo["venue"], worst_prem_pct=lo["premium_pct"])

        if len(legs) >= 2:
            lo = min(legs, key=lambda x: x["apr"])   # 这里做多（费率最负=收钱）
            hi = max(legs, key=lambda x: x["apr"])   # 这里做空（费率最正=收钱）
            if lo["venue"] != hi["venue"]:
                basis = (((hi["mark"] or 0) - (lo["mark"] or 0)) / lo["mark"] * 100.0
                         if lo.get("mark") else None)
                row.update(long_venue=lo["venue"], long_apr=lo["apr"] * 100.0,
                           short_venue=hi["venue"], short_apr=hi["apr"] * 100.0,
                           net_apr=(hi["apr"] - lo["apr"]) * 100.0,
                           mark_spread_pct=basis)
        pairs_out.append(row)
    return legs_out, pairs_out


def _ms(v):
    """各家 next funding time 单位不一，统一成毫秒。"""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return int(n * 1000) if n < 1e11 else int(n)


def run_once():
    universe, fx_override = load_universe()
    if not universe:
        return 0, 0, {"config": {"ok": False, "n": 0,
                                 "err": "universe.json 为空或格式错误"}}
    want = {}
    for cfg in universe.values():
        for v, s in cfg["venues"].items():
            want.setdefault(v, set()).add(s)
    fx = quotes.fx_rates(fx_override)
    snap, health = venues.collect(want)
    legs, pairs = build(universe, snap, fx)
    store.write_round(int(time.time()), legs, pairs, health)
    return len(legs), len(pairs), health
