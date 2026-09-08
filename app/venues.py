# -*- coding: utf-8 -*-
"""各交易所适配器。只用标准库。

每个 fetch_* 返回 list[dict]，字段：
    venue, symbol, rate, interval_h, mark, last, next_ts,
    bid, bid_sz, ask, ask_sz      (拿不到就为 None)
rate 是「一个结算周期」的费率（小数）。正数=多头付钱，负数=空头付钱。
"""
import json
import time
import urllib.parse
import urllib.request

TIMEOUT = 20
_HDR = {"User-Agent": "funding-radar/2.0", "Content-Type": "application/json"}


def _req(url, data=None, headers=None):
    body = json.dumps(data).encode() if data is not None else None
    h = dict(_HDR)
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h,
                                 method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def _f(x, d=None):
    try:
        v = float(x)
        return v
    except (TypeError, ValueError):
        return d


def _row(venue, symbol, rate, interval_h, mark=None, last=None, next_ts=None,
         bid=None, bid_sz=None, ask=None, ask_sz=None):
    return {"venue": venue, "symbol": symbol, "rate": rate or 0.0,
            "interval_h": interval_h or 8.0, "mark": mark, "last": last,
            "next_ts": next_ts, "bid": bid, "bid_sz": bid_sz,
            "ask": ask, "ask_sz": ask_sz}


# ------------------------------------------------------------ hyperliquid
def fetch_hyperliquid(want=None):
    d = _req("https://api.hyperliquid.xyz/info", {"type": "metaAndAssetCtxs"})
    meta, ctxs = d[0], d[1]
    out = []
    for m, c in zip(meta.get("universe", []), ctxs):
        imp = c.get("impactPxs") or [None, None]
        out.append(_row("hyperliquid", m.get("name", ""), _f(c.get("funding"), 0.0),
                        1.0, mark=_f(c.get("markPx")), last=_f(c.get("midPx")),
                        bid=_f(imp[0]), ask=_f(imp[1] if len(imp) > 1 else None)))
    return out


def book_hyperliquid(symbols):
    out = {}
    for s in symbols:
        try:
            d = _req("https://api.hyperliquid.xyz/info",
                     {"type": "l2Book", "coin": s})
            lv = d.get("levels") or [[], []]
            b = lv[0][0] if lv[0] else None
            a = lv[1][0] if len(lv) > 1 and lv[1] else None
            out[s] = {"bid": _f(b and b.get("px")), "bid_sz": _f(b and b.get("sz")),
                      "ask": _f(a and a.get("px")), "ask_sz": _f(a and a.get("sz"))}
        except Exception:
            pass
        time.sleep(0.05)
    return out


# ------------------------------------------------------------ binance
def fetch_binance(want=None):
    prem = _req("https://fapi.binance.com/fapi/v1/premiumIndex")
    try:
        iv = {i["symbol"]: _f(i.get("fundingIntervalHours"), 8.0)
              for i in _req("https://fapi.binance.com/fapi/v1/fundingInfo")}
    except Exception:
        iv = {}
    try:
        bt = {b["symbol"]: b for b in
              _req("https://fapi.binance.com/fapi/v1/ticker/bookTicker")}
    except Exception:
        bt = {}
    out = []
    for p in prem:
        s = p.get("symbol", "")
        b = bt.get(s, {})
        out.append(_row("binance", s, _f(p.get("lastFundingRate"), 0.0),
                        iv.get(s, 8.0), mark=_f(p.get("markPrice")),
                        last=_f(p.get("markPrice")),
                        next_ts=p.get("nextFundingTime"),
                        bid=_f(b.get("bidPrice")), bid_sz=_f(b.get("bidQty")),
                        ask=_f(b.get("askPrice")), ask_sz=_f(b.get("askQty"))))
    return out


# ------------------------------------------------------------ bybit
def fetch_bybit(want=None):
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
    return [_row("bybit", r.get("symbol", ""), _f(r.get("fundingRate"), 0.0),
                 iv.get(r.get("symbol"), 8.0), mark=_f(r.get("markPrice")),
                 last=_f(r.get("lastPrice")), next_ts=r.get("nextFundingTime"),
                 bid=_f(r.get("bid1Price")), bid_sz=_f(r.get("bid1Size")),
                 ask=_f(r.get("ask1Price")), ask_sz=_f(r.get("ask1Size")))
            for r in rows]


# ------------------------------------------------------------ gate
def fetch_gate(want=None):
    rows = _req("https://api.gateio.ws/api/v4/futures/usdt/contracts")
    tick = {}
    try:
        for t in _req("https://api.gateio.ws/api/v4/futures/usdt/tickers"):
            tick[t.get("contract")] = t
    except Exception:
        pass
    out = []
    for r in rows:
        n = r.get("name", "")
        t = tick.get(n, {})
        out.append(_row("gate", n, _f(r.get("funding_rate"), 0.0),
                        _f(r.get("funding_interval"), 28800.0) / 3600.0,
                        mark=_f(r.get("mark_price")),
                        last=_f(t.get("last")) or _f(r.get("last_price")),
                        next_ts=(_f(r.get("funding_next_apply"), 0) or 0) * 1000,
                        bid=_f(t.get("highest_bid")), bid_sz=_f(t.get("highest_size")),
                        ask=_f(t.get("lowest_ask")), ask_sz=_f(t.get("lowest_size"))))
    return out


# ------------------------------------------------------------ okx
def fetch_okx(want=None, keyword=None):
    """OKX 没有「一次拿全部资金费率」的接口，只能按 instId 逐个取，
    所以必须先筛出我们真正需要的合约。"""
    tick = {}
    try:
        for t in _req("https://www.okx.com/api/v5/market/tickers"
                      "?instType=SWAP").get("data", []):
            tick[t.get("instId")] = t
    except Exception:
        pass
    ids = list(tick) or [i["instId"] for i in _req(
        "https://www.okx.com/api/v5/public/instruments"
        "?instType=SWAP").get("data", [])]
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
            x, t = d[0], tick.get(iid, {})
            ft, nt = _f(x.get("fundingTime"), 0), _f(x.get("nextFundingTime"), 0)
            ivh = (nt - ft) / 3600000.0 if (nt and ft) else 8.0
            out.append(_row("okx", iid, _f(x.get("fundingRate"), 0.0),
                            ivh if 0 < ivh <= 24 else 8.0,
                            mark=_f(t.get("last")), last=_f(t.get("last")),
                            next_ts=x.get("nextFundingTime"),
                            bid=_f(t.get("bidPx")), bid_sz=_f(t.get("bidSz")),
                            ask=_f(t.get("askPx")), ask_sz=_f(t.get("askSz"))))
        except Exception:
            pass
        time.sleep(0.12)
    return out


# ------------------------------------------------------------ bitget
def fetch_bitget(want=None):
    d = _req("https://api.bitget.com/api/v2/mix/market/tickers"
             "?productType=USDT-FUTURES").get("data", [])
    out = []
    for r in d:
        s = r.get("symbol", "")
        out.append(_row("bitget", s, _f(r.get("fundingRate"), 0.0), 8.0,
                        mark=_f(r.get("markPrice")), last=_f(r.get("lastPr")),
                        next_ts=r.get("nextFundingTime") or r.get("fundingTime"),
                        bid=_f(r.get("bidPr")), bid_sz=_f(r.get("bidSz")),
                        ask=_f(r.get("askPr")), ask_sz=_f(r.get("askSz"))))
    # 结算周期只对我们关心的合约单独查，避免几百次请求
    for row in out:
        if want and row["symbol"] in want:
            try:
                fd = _req("https://api.bitget.com/api/v2/mix/market/funding-time"
                          "?productType=USDT-FUTURES&symbol=" + row["symbol"])
                v = (fd.get("data") or [{}])[0]
                iv = _f(v.get("ratePeriod") or v.get("fundingRateInterval"))
                if iv:
                    row["interval_h"] = iv
                if v.get("nextFundingTime"):
                    row["next_ts"] = v["nextFundingTime"]
            except Exception:
                pass
            time.sleep(0.08)
    return out


# ------------------------------------------------------------ bingx
def fetch_bingx(want=None):
    """BingX 用 symbol 形如 CXMT-USDT。逐个查我们需要的，不全量拉。"""
    if not want:
        return []
    out = []
    for s in list(want)[:30]:
        try:
            p = _req("https://open-api.bingx.com/openApi/swap/v2/quote/"
                     "premiumIndex?symbol=" + urllib.parse.quote(s))
            d = p.get("data") or {}
            if isinstance(d, list):
                d = d[0] if d else {}
            b = {}
            try:
                bb = _req("https://open-api.bingx.com/openApi/swap/v2/quote/"
                          "bookTicker?symbol=" + urllib.parse.quote(s))
                b = bb.get("data") or {}
                if isinstance(b, list):
                    b = b[0] if b else {}
            except Exception:
                pass
            out.append(_row("bingx", s, _f(d.get("lastFundingRate"), 0.0), 4.0,
                            mark=_f(d.get("markPrice")), last=_f(d.get("markPrice")),
                            next_ts=d.get("nextFundingTime"),
                            bid=_f(b.get("bidPrice")), bid_sz=_f(b.get("bidQty")),
                            ask=_f(b.get("askPrice")), ask_sz=_f(b.get("askQty"))))
        except Exception:
            pass
        time.sleep(0.1)
    return out


# ------------------------------------------------------------ edgex
def fetch_edgex(want=None):
    """edgeX 的公开接口结构尚未实测，先按文档写，跑不通会在健康栏显示失败。
    用 python -m app.probe edgex 打出原始返回，再照着修。"""
    d = _req("https://pro.edgex.exchange/api/v1/public/quote/getTicker")
    rows = d.get("data") or d.get("result") or []
    out = []
    for r in rows if isinstance(rows, list) else []:
        s = r.get("contractName") or r.get("symbol") or ""
        out.append(_row("edgex", s, _f(r.get("fundingRate"), 0.0), 4.0,
                        mark=_f(r.get("markPrice") or r.get("oraclePrice")),
                        last=_f(r.get("lastPrice")),
                        bid=_f(r.get("bestBid")), ask=_f(r.get("bestAsk"))))
    return out


# want_by_venue: {venue: set(symbols)}
ADAPTERS = {
    "hyperliquid": fetch_hyperliquid,
    "binance": fetch_binance,
    "bybit": fetch_bybit,
    "gate": fetch_gate,
    "okx": fetch_okx,
    "bitget": fetch_bitget,
    "bingx": fetch_bingx,
    "edgex": fetch_edgex,
}
NEEDS_BOOK = {"hyperliquid": book_hyperliquid}


def apr(row):
    """单周期费率 -> 年化。各家周期 1h/4h/8h 不等，不折算直接比较是错的。"""
    iv = row.get("interval_h") or 8.0
    return (row.get("rate") or 0.0) * (24.0 / iv) * 365.0


def collect(want_by_venue):
    snap, health = {}, {}
    for name, fn in ADAPTERS.items():
        want = want_by_venue.get(name) or set()
        if not want:
            continue                      # universe 里没用到这家就不打它
        try:
            rows = fn(want=want)
            for r in rows:
                if r["symbol"] in want:
                    snap[(name, r["symbol"])] = r
            miss = [s for s in want if (name, s) not in snap]
            bookfn = NEEDS_BOOK.get(name)
            if bookfn:
                for s, b in bookfn([s for s in want
                                    if (name, s) in snap]).items():
                    snap[(name, s)].update(b)
            health[name] = {"ok": True, "n": len(rows),
                            "err": ("未匹配: " + ",".join(miss)) if miss else ""}
        except Exception as e:
            health[name] = {"ok": False, "n": 0, "err": str(e)[:200]}
    return snap, health
