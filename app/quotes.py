# -*- coding: utf-8 -*-
"""标的的真实股价 + 汇率。折溢价那一列的分母就来自这里。

口径：锚价(USD) = 股价 / 汇率
     折溢价 = 永续价 / 锚价 - 1
A 股用 CNH，港股用 HKD，美股汇率为 1。
"""
import json
import time
import urllib.request

TIMEOUT = 15
_HDR = {"User-Agent": "Mozilla/5.0 (compatible; funding-radar/2.0)"}

# 行情缓存：股价 60 秒、汇率 10 分钟，避免每轮都打
_cache = {}


def _get(url, headers=None, encoding="utf-8"):
    h = dict(_HDR)
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode(encoding, "replace")


def _cached(key, ttl, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    if val is not None:
        _cache[key] = (now, val)
    return val


# ------------------------------------------------------------ 股价
def _tencent_code(market, code):
    m = (market or "").upper()
    if m == "A":
        # 6 开头是上交所，其余深交所（北交所另有前缀，暂不支持）
        return ("sh" if code.startswith("6") else "sz") + code
    if m == "HK":
        return "hk" + code.zfill(5)
    if m == "US":
        return "us" + code.upper()
    return None


def _from_tencent(market, code):
    """qt.gtimg.cn 返回形如：v_sh688825="1~长鑫科技~688825~58.10~...";
    字段 3 是最新价，30 是行情时间。"""
    c = _tencent_code(market, code)
    if not c:
        return None
    txt = _get("https://qt.gtimg.cn/q=" + c, encoding="gbk")
    if "=" not in txt:
        return None
    body = txt.split('="', 1)[1].rstrip('";\n ')
    f = body.split("~")
    if len(f) < 4:
        return None
    try:
        px = float(f[3])
    except ValueError:
        return None
    if px <= 0:
        return None
    return {"price": px, "name": f[1] if len(f) > 1 else "",
            "quote_time": f[30] if len(f) > 30 else "", "src": "tencent"}


def _from_eastmoney(market, code):
    m = (market or "").upper()
    if m == "A":
        secid = ("1." if code.startswith("6") else "0.") + code
    elif m == "HK":
        secid = "116." + code.zfill(5)
    elif m == "US":
        secid = "105." + code.upper()
    else:
        return None
    txt = _get("https://push2.eastmoney.com/api/qt/stock/get"
               "?secid=%s&fields=f43,f57,f58,f86,f59" % secid)
    d = (json.loads(txt) or {}).get("data") or {}
    raw, dec = d.get("f43"), d.get("f59")
    if raw in (None, "-"):
        return None
    px = float(raw) / (10 ** int(dec if dec is not None else 2))
    if px <= 0:
        return None
    return {"price": px, "name": d.get("f58", ""),
            "quote_time": str(d.get("f86", "")), "src": "eastmoney"}


def stock_price(market, code):
    def _fetch():
        for fn in (_from_tencent, _from_eastmoney):
            try:
                v = fn(market, code)
                if v:
                    return v
            except Exception:
                pass
        return None
    return _cached("px:%s:%s" % (market, code), 60, _fetch)


# ------------------------------------------------------------ 汇率
def fx_rates(override=None):
    """返回 {'CNH': 7.1, 'HKD': 7.8, 'USD': 1.0}，即 1 USD 兑多少。
    config 里给了 override 就优先用手填的值（接口被墙时的兜底）。"""
    def _fetch():
        try:
            d = json.loads(_get("https://open.er-api.com/v6/latest/USD"))
            r = d.get("rates") or {}
            out = {"USD": 1.0}
            if r.get("CNY"):
                out["CNH"] = float(r["CNY"])   # CNY 近似 CNH，有小幅偏差
            if r.get("HKD"):
                out["HKD"] = float(r["HKD"])
            return out if len(out) > 1 else None
        except Exception:
            return None
    got = _cached("fx", 600, _fetch) or {}
    out = {"USD": 1.0}
    out.update(got)
    # 手填兜底值：跳过 _ 开头的注释键，非数字一律忽略，
    # 不能让 config 里的一句说明把整轮采集打挂
    for k, v in (override or {}).items():
        if k.startswith("_") or v in (None, "", 0):
            continue
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            continue
    return out


CCY_OF = {"A": "CNH", "HK": "HKD", "US": "USD"}


def anchor_usd(underlying, fx):
    """标的的美元锚价。拿不到就返回 None，折溢价那列显示 —。"""
    if not underlying:
        return None
    q = stock_price(underlying.get("market"), underlying.get("code"))
    if not q:
        return None
    ccy = CCY_OF.get((underlying.get("market") or "").upper(), "USD")
    rate = fx.get(ccy)
    if not rate:
        return None
    return {"anchor": q["price"] / rate, "stock_price": q["price"],
            "ccy": ccy, "fx": rate, "name": q.get("name", ""),
            "quote_time": q.get("quote_time", ""), "src": q.get("src", "")}
