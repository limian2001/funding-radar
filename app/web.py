# -*- coding: utf-8 -*-
"""看板：每家交易所一列，横向对齐；右侧是推导值与 24h 历史。
服务端渲染，不引外部资源。"""
import html
import json
import time

from . import store

# 列顺序固定，方便横向扫视；不在这个表里的所会追加到后面
CANON = ["hyperliquid", "binance", "bybit", "gate", "okx"]

CSS = """
:root{--bg:#fafafa;--fg:#1a1a1a;--mut:#777;--faint:#9a9a9a;--line:#e4e4e4;
--card:#fff;--pos:#0a7a52;--neg:#c0392b;
--longbg:rgba(10,122,82,.09);--shortbg:rgba(192,57,43,.09)}
@media(prefers-color-scheme:dark){:root{--bg:#151517;--fg:#e8e8e8;--mut:#999;
--faint:#767676;--line:#2c2c30;--card:#1d1d20;--pos:#3ddc97;--neg:#ff6b5a;
--longbg:rgba(61,220,151,.11);--shortbg:rgba(255,107,90,.11)}}
*{box-sizing:border-box}
body{margin:0;padding:24px;background:var(--bg);color:var(--fg);
font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
h1{font-size:18px;margin:0 0 4px}
.sub{color:var(--mut);font-size:12px;margin-bottom:16px}
.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;background:var(--card);border:1px solid var(--line);
border-radius:8px;overflow:hidden}
th,td{padding:8px 10px;text-align:right;border-bottom:1px solid var(--line);
white-space:nowrap;vertical-align:top}
th{background:rgba(128,128,128,.08);font-weight:600;font-size:11px;
color:var(--mut);line-height:1.35;vertical-align:bottom}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;
background:var(--card);z-index:1}
th:first-child{background:#efefef}
@media(prefers-color-scheme:dark){th:first-child{background:#26262a}}
tr:last-child td{border-bottom:none}
.grp{border-left:2px solid var(--line)}
.asset{font-weight:700;font-size:14px}
.apr{font-weight:600;font-size:13px;font-variant-numeric:tabular-nums}
.raw{color:var(--faint);font-size:10.5px;font-variant-numeric:tabular-nums}
.big{font-weight:700;font-size:15px;font-variant-numeric:tabular-nums}
.pos{color:var(--pos)}.neg{color:var(--neg)}
.s{color:var(--mut);font-size:11px}
.long{background:var(--longbg)}.short{background:var(--shortbg)}
.tag{display:inline-block;font-size:9.5px;line-height:1.5;padding:0 4px;
border-radius:3px;margin-right:4px;vertical-align:1px;color:#fff}
.t-long{background:var(--pos)}.t-short{background:var(--neg)}
.note{color:var(--mut);font-size:12px;margin-top:18px;max-width:78ch}
.note b{color:var(--fg)}
.health{margin-top:14px;font-size:12px;color:var(--mut)}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;
margin-right:5px;vertical-align:middle}
.up{background:var(--pos)}.down{background:var(--neg)}
.empty{padding:40px;text-align:center;color:var(--mut);background:var(--card);
border:1px dashed var(--line);border-radius:8px}
"""

NOTE = """<b>怎么读：</b>中间每一列是一家交易所，每格三个信息——折算后的<b>年化</b>、
以及下方的<b>原始单期费率 / 结算周期</b>。原始费率是你在交易所页面上看到的那个数；
年化是把它乘上一年的周期数得来的，所以<b>周期不同的两家不能直接比原始费率</b>：
1 小时结算的 0.01% 相当于 8 小时结算的 0.08%。
绿底标「多」的是费率最低那家（在那边做多收钱），红底标「空」的是费率最高那家。
净年化 = 空腿 − 多腿，未扣手续费、滑点与借贷成本；两条腿各占保证金，
对总投入资金的实际年化约为其一半。
<b>右侧几列比左侧重要。</b>把一个 1 小时的费率外推成一年，在新上市合约上几乎必然失真；
24h 区间、均值与站上门槛的时间占比，才是机会站不站得住的证据。
<b>基差</b>是两所标记价格的偏离——这类合约没有可交割现货，两所价格没有强制收敛的力量，
基差摆动一旦大过资金费收益，这笔交易就是亏的。本页仅供研究，不构成投资建议。"""


def _cell(v, digits=1, cls_by_sign=True, suffix="%", extra="", sign=""):
    if v is None:
        return '<td class="s %s">—</td>' % extra
    cls = ("pos" if v > 0 else ("neg" if v < 0 else "")) if cls_by_sign else ""
    fmt = ('<td class="%s %s">%+.*f%s</td>' if sign
           else '<td class="%s %s">%.*f%s</td>')
    return fmt % (cls, extra, digits, v, suffix)


def _iv(h):
    if not h:
        return "?"
    return "%dm" % round(h * 60) if h < 1 else "%gh" % h


def _venue_cell(leg, role):
    if not leg:
        return '<td class=s>—</td>'
    apr = (leg["apr"] or 0) * 100.0
    tag = ('<span class="tag t-long">多</span>' if role == "long" else
           '<span class="tag t-short">空</span>' if role == "short" else "")
    return ('<td class="%s"><div class="apr %s">%s%+.1f%%</div>'
            '<div class=raw>%+.4f%% / %s</div></td>' % (
                role, "pos" if apr > 0 else ("neg" if apr < 0 else ""),
                tag, apr, leg["rate"] * 100.0, _iv(leg["interval_h"])))


def render():
    ts, pairs = store.latest_pairs()
    health = store.latest_health()
    age = int(time.time()) - ts if ts else None

    if not pairs:
        body = ('<div class=empty>还没有数据。<br><br>'
                '1) 先跑 <code>docker compose run --rm radar '
                'python -m app.discover CXMT</code> 找符号<br>'
                '2) 填进 <code>config/universe.json</code><br>'
                '3) 等下一轮采集（无需重启）</div>')
    else:
        legs_by_asset = {p["asset"]: {l["venue"]: l
                                      for l in store.latest_legs(p["asset"])}
                         for p in pairs}
        seen = set()
        for m in legs_by_asset.values():
            seen |= set(m)
        cols = [v for v in CANON if v in seen] + sorted(seen - set(CANON))

        rows = []
        for p in pairs:
            legs = legs_by_asset[p["asset"]]
            t = store.trailing(p["asset"], hours=24)
            tds = []
            for v in cols:
                role = ("long" if v == p["long_venue"] else
                        "short" if v == p["short_venue"] else "")
                tds.append(_venue_cell(legs.get(v), role))
            if p["net_apr"] is None:
                net_td = ('<td class="s grp" colspan=2>各家费率相同，'
                          '无可对冲价差</td>')
            else:
                net_td = ('<td class="big grp %s">%+.1f%%</td>'
                          '<td class="%s">%+.1f%%</td>' % (
                              "pos" if p["net_apr"] > 0 else "neg", p["net_apr"],
                              "pos" if p["net_apr"] > 0 else "neg",
                              p["net_apr"] / 2))
            rng = ("%+.0f ~ %+.0f%%" % (t["min_net"], t["max_net"])
                   if t.get("min_net") is not None else "—")
            rows.append(
                '<tr><td class=asset>%s <span class=s>%d腿</span></td>%s%s%s'
                '<td class="s grp">%s</td>%s%s<td class=s>%d</td></tr>' % (
                    html.escape(p["asset"]), p["n_legs"], "".join(tds), net_td,
                    _cell(p["mark_spread_pct"], 3, extra="grp", sign="+"),
                    rng,
                    _cell(t.get("avg_net"), 1, sign="+"),
                    _cell(t.get("pct_above"), 0, cls_by_sign=False),
                    t.get("n") or 0))

        head = ("<tr><th>标的</th>"
                + "".join("<th>%s</th>" % html.escape(v) for v in cols)
                + '<th class=grp>净年化<br>此刻</th><th>占用<br>总资金</th>'
                  '<th class=grp>基差<br>此刻</th>'
                  '<th class=grp>24h<br>净年化区间</th><th>24h<br>均值</th>'
                  '<th>24h 站上<br>10% 的时间</th><th>样本</th></tr>')
        body = '<div class=wrap><table>%s%s</table></div>' % (
            head, "".join(rows))

    hs = " &nbsp; ".join(
        '<span class="dot %s"></span>%s%s' % (
            "up" if h["ok"] else "down", html.escape(h["venue"]),
            "" if h["ok"] else " (失败)")
        for h in sorted(health, key=lambda x: x["venue"]))

    return """<!doctype html><html lang=zh><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Funding Radar</title><style>%s</style>
<meta http-equiv=refresh content=60>
<h1>跨所资金费率雷达</h1>
<div class=sub>最近一轮：%s（%s 秒前）· 每 60 秒自动刷新</div>
%s
<div class=health>数据源 %s</div>
<p class=note>%s</p>
</html>""" % (
        CSS,
        time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ts)) if ts else "—",
        age if age is not None else "—",
        body, hs or "—", NOTE.replace("\n", " "))


def api_latest():
    ts, pairs = store.latest_pairs()
    out = []
    for p in pairs:
        d = dict(p)
        d["legs"] = [
            {"venue": l["venue"], "symbol": l["symbol"], "rate": l["rate"],
             "interval_h": l["interval_h"], "apr_pct": (l["apr"] or 0) * 100.0,
             "mark": l["mark"]}
            for l in store.latest_legs(p["asset"])]
        d["trailing_24h"] = store.trailing(p["asset"], hours=24)
        out.append(d)
    return json.dumps({"ts": ts, "pairs": out,
                       "health": store.latest_health()},
                      ensure_ascii=False, indent=2)
