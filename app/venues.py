# -*- coding: utf-8 -*-
"""各交易所资金费率适配器。只用标准库，不装任何依赖。

每个 fetch_* 返回 list[dict]:
    {venue, symbol, rate, interval_h, mark, next_ts}
rate 是「一个结算周期」的费率（小数，不是百分比）。
正数 = 多头付钱给空头；负数 = 空头付钱给多头。
"""
import json
import time
import urllib.parse
import urllib.request

TIMEOUT = 20
_HDR = {"User-Agent": "funding-radar/1.0", "Content-Type": "application/json"}


def _req(url, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url, data=body, headers=_HDR, method="POST" if body else "GET"
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


# --------------------------------------------------------------- 适配器
def fetch_hyperliquid():
    d = _req("https://api.hyperliquid.xyz/info", {"type": "metaAndAssetCtxs"})
    meta, ctxs = d[0], d[1]
    out = []
    for m, c in zip(meta.get("universe", []), ctxs):
        out.append({
            "venue": "hyperliquid", "symbol": m.get("name", ""),
            "rate": _f(c.get("funding")),
            "interval_h": 1.0,                      # HL 每小时结算
            "mark": _f(c.get("markPx")),
            "next_ts": None,
        })
    return out


def fetch_binance():
    prem = _req("https://fapi.binance.com/fapi/v1/premiumIndex")
    try:
        iv = {i["symbol"]: _f(i.get("fundingIntervalHours"), 8.0)
              for i in _req("https://fapi.binance.com/fapi/v1/fundingInfo")}
    except Exception:
        iv = {}
    return [{
        "venue": "binance", "symbol": p.get("symbol", ""),
        "rate": _f(p.get("lastFundingRate")),
        "interval_h": iv.get(p.get("symbol"), 8.0),
        "mark": _f(p.get("markPrice")),
        "next_ts": p.get("nextFundingTime"),
    } for p in prem]


def fetch_bybit():
    t = _req("https://api.bybit.com/v5/market/tickers?category=linear")
    rows = (t.get("result") or {}).get("list", [])
    iv = {}
    try:
        ii = _req("https://api.bybit.com/v5/market/instruments-info"
                  "?category=linear&limit=1000")
        for x in (ii.get("result") or {}).get("list", []):
            iv[x.get("symbol")] = _f(x.get("fundingInterval"), 480.0) / 60.0
    except Exception:
        pass
    return [{
        "venue": "bybit", "symbol": r.get("symbol", ""),
        "rate": _f(r.get("fundingRate")),
        "interval_h": iv.get(r.get("symbol"), 8.0),
        "mark": _f(r.get("markPrice")),
        "next_ts": r.get("nextFundingTime"),
    } for r in rows]


def fetch_gate():
    rows = _req("https://api.gateio.ws/api/v4/futures/usdt/contracts")
    return [{
        "venue": "gate", "symbol": r.get("name", ""),
        "rate": _f(r.get("funding_rate")),
        "interval_h": _f(r.get("funding_interval"), 28800.0) / 3600.0,
        "mark": _f(r.get("mark_price")),
        "next_ts": r.get("funding_next_apply"),
    } for r in rows]


def fetch_okx(keyword=None, want=None):
    """OKX 没有「一次拿全部资金费率」的接口，只能按 instId 逐个取。
    所以必须先筛选，避免几百次请求。"""
    inst = _req("https://www.okx.com/api/v5/public/instruments"
                "?instType=SWAP").get("data", [])
    ids = [i["instId"] for i in inst if i.get("settleCcy") in ("USDT", "USDC")]
    if keyword:
        ids = [i for i in ids if keyword.upper() in i.upper()]
    elif want:
        ids = [i for i in ids if i in want]
    else:
        return []
    out = []
    for iid in ids[:40]:
        try:
            d = _req("https://www.okx.com/api/v5/public/funding-rate?instId="
                     + urllib.parse.quote(iid)).get("data", [])
            if not d:
                continue
            x = d[0]
            ft, nt = _f(x.get("fundingTime")), _f(x.get("nextFundingTime"))
            ivh = (nt - ft) / 3600000.0 if (nt and ft) else 8.0
            out.append({
                "venue": "okx", "symbol": iid, "rate": _f(x.get("fundingRate")),
                "interval_h": ivh if 0 < ivh <= 24 else 8.0,
                "mark": 0.0, "next_ts": x.get("nextFundingTime"),
            })
        except Exception:
            pass
        time.sleep(0.12)
    return out


LIST_ALL = [
    ("hyperliquid", fetch_hyperliquid),
    ("binance", fetch_binance),
    ("bybit", fetch_bybit),
    ("gate", fetch_gate),
]


def apr(row):
    """单周期费率 -> 年化。正数=多头付钱，负数=多头收钱。

    这一步是整个项目的核心：各家结算周期 1h/4h/8h 不等，
    原始费率直接对比是错的。
    """
    iv = row.get("interval_h") or 8.0
    return row["rate"] * (24.0 / iv) * 365.0


def collect(want_okx=None):
    """拉一轮全市场快照。返回 (snapshot, health)。"""
    snap, health = {}, {}
    for name, fn in LIST_ALL:
        try:
            rows = fn()
            for r in rows:
                snap[(name, r["symbol"])] = r
            health[name] = {"ok": True, "n": len(rows)}
        except Exception as e:
            health[name] = {"ok": False, "err": str(e)[:200]}
    try:
        rows = fetch_okx(want=want_okx) if want_okx else []
        for r in rows:
            snap[("okx", r["symbol"])] = r
        health["okx"] = {"ok": True, "n": len(rows)}
    except Exception as e:
        health["okx"] = {"ok": False, "err": str(e)[:200]}
    return snap, health
