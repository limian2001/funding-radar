# -*- coding: utf-8 -*-
"""极简看板。服务端渲染，不引外部资源，页面本身可离线打开。"""
import html
import json
import time

from . import store

CSS = """
:root{--bg:#fafafa;--fg:#1a1a1a;--mut:#777;--faint:#999;--line:#e4e4e4;
--card:#fff;--pos:#0a7a52;--neg:#c0392b}
@media(prefers-color-scheme:dark){:root{--bg:#151517;--fg:#e8e8e8;--mut:#999;
--faint:#777;--line:#2c2c30;--card:#1d1d20;--pos:#3ddc97;--neg:#ff6b5a}}
*{box-sizing:border-box}
body{margin:0;padding:24px;background:var(--bg);color:var(--fg);
font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
h1{font-size:18px;margin:0 0 4px}
.sub{color:var(--mut);font-size:12px;margin-bottom:18px}
.wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;min-width:980px;background:var(--card);
border:1px solid var(--line);border-radius:8px;overflow:hidden}
th,td{padding:9px 11px;text-align:right;border-bottom:1px solid var(--line);
white-space:nowrap;vertical-align:top}
th{background:rgba(128,128,128,.08);font-weight:600;font-size:11px;
color:var(--mut);line-height:1.35;vertical-align:bottom}
th:first-child,td:first-child{text-align:left}
tr:last-child td{border-bottom:none}
.grp{border-left:1px solid var(--line)}
.big{font-weight:700;font-size:15px}
.pos{color:var(--pos)}.neg{color:var(--neg)}
.v{font-weight:600}
.s{color:var(--mut);font-size:11px}
.raw{color:var(--faint);font-size:10.5px;font-variant-numeric:tabular-nums}
.others{color:var(--faint);font-size:10.5px;font-weight:400}
.note{color:var(--mut);font-size:12px;margin-top:18px;max-width:76ch}
.note b{color:var(--fg)}
.health{margin-top:14px;font-size:12px;color:var(--mut)}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;
margin-right:5px;vertical-align:middle}
.up{background:var(--pos)}.down{background:var(--neg)}
.empty{padding:40px;text-align:center;color:var(--mut);background:var(--card);
border:1px dashed var(--line);border-radius:8px}
"""

NOTE = """<b>怎么读：</b>每条腿显示三行——交易所、折算后的年化、以及
<b>原始单期费率 / 结算周期</b>。原始费率才是你在交易所页面上看到的那个数，
年化是把它乘上一年的周期数得来的，所以<b>周期不同的两个所不能直接比原始费率</b>：
1 小时结算的 0.01% 相当于 8 小时结算的 0.08%。
净年化 = 空腿年化 − 多腿年化，未扣手续费、滑点与借贷成本；
两条腿各占保证金，对总投入资金的实际年化约为其一半。
<b>右边几列比左边重要。</b>把一个 1 小时的费率外推成一年，在新上市合约上几乎必然失真；
右侧是过去 24 小时真实观测到的区间、均值与站上门槛的时间占比，那才是机会站不站得住的证据。
<b>基差</b>是两所标记价格的偏离——这类合约没有可交割现货，两所价格没有强制收敛的力量，
基差摆动一旦大过资金费收益，这笔交易就是亏的。本页仅供研究，不构成投资建议。"""


def _cell(v, digits=1, cls_by_sign=True, suffix="%", extra=""):
    if v is None:
        return '<td class="s %s">—</td>' % extra
    cls = ("pos" if v > 0 else ("neg" if v < 0 else "")) if cls_by_sign else ""
    return '<td class="%s %s">%.*f%s</td>' % (cls, extra, digits, v, suffix)


def _iv(h):
    """0.5 -> 30m; 1.0 -> 1h; 8.0 -> 8h"""
    if not h:
        return "?"
    if h < 1:
        return "%dm" % round(h * 60)
    return ("%gh" % h)


def _leg_cell(venue, apr_pct, leg):
    """一条腿：所名 / 年化 / 原始费率+周期"""
    if leg:
        raw = '<div class=raw>%+.4f%% / %s</div>' % (
            leg["rate"] * 100.0, _iv(leg["interval_h"]))
    else:
        raw = '<div class=raw>—</div>'
    return ('<td><div class=v>%s</div>'
            '<div class="s %s">%+.1f%% 年化</div>%s</td>' % (
                html.escape(venue),
                "pos" if apr_pct > 0 else "neg", apr_pct, raw))


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
        rows = []
        for p in pairs:
            legs = {l["venue"]: l for l in store.latest_legs(p["asset"])}
            t = store.trailing(p["asset"], hours=24)

            if p["long_venue"] is None:
                legs_cell = ('<td colspan=4 class=s>四家费率相同（多为新合约'
                             '尚未产生真实结算），无可对冲的价差</td>')
                used = set()
            else:
                legs_cell = (
                    _leg_cell(p["long_venue"], p["long_apr"],
                              legs.get(p["long_venue"]))
                    + _leg_cell(p["short_venue"], p["short_apr"],
                                legs.get(p["short_venue"]))
                    + '<td class="big %s">%+.1f%%</td>' % (
                        "pos" if p["net_apr"] > 0 else "neg", p["net_apr"])
                    + _cell(p["net_apr"] / 2, 1))
                used = {p["long_venue"], p["short_venue"]}

            others = " · ".join(
                "%s %+.4f%%/%s" % (v, l["rate"] * 100.0, _iv(l["interval_h"]))
                for v, l in sorted(legs.items()) if v not in used)
            rng = ("%+.0f ~ %+.0f%%" % (t["min_net"], t["max_net"])
                   if t.get("min_net") is not None else "—")

            rows.append(
                "<tr><td><div><b>%s</b> <span class=s>%d腿</span></div>"
                "<div class=others>%s</div></td>%s"
                "%s<td class='s grp'>%s</td>%s%s<td class=s>%d</td></tr>" % (
                    html.escape(p["asset"]), p["n_legs"],
                    html.escape(others) if others else "&nbsp;",
                    legs_cell,
                    _cell(p["mark_spread_pct"], 3, extra="grp"),
                    rng,
                    _cell(t.get("avg_net"), 1),
                    _cell(t.get("pct_above"), 0, cls_by_sign=False),
                    t.get("n") or 0))

        body = ('<div class=wrap><table><tr>'
                '<th>标的<br><span class=s>其余腿：费率/周期</span></th>'
                '<th>做多腿<br>费率最低</th><th>做空腿<br>费率最高</th>'
                '<th>净年化<br>此刻</th><th>占用<br>总资金</th>'
                '<th class=grp>基差<br>此刻</th>'
                '<th class=grp>24h<br>净年化区间</th><th>24h<br>均值</th>'
                '<th>24h 站上<br>10% 的时间</th><th>样本</th></tr>'
                + "".join(rows) + '</table></div>')

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
