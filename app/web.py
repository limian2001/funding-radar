# -*- coding: utf-8 -*-
"""极简看板。服务端渲染，不引外部资源，页面本身可离线打开。"""
import html
import json
import time

from . import store

CSS = """
:root{--bg:#fafafa;--fg:#1a1a1a;--mut:#777;--line:#e4e4e4;--card:#fff;
--pos:#0a7a52;--neg:#c0392b}
@media(prefers-color-scheme:dark){:root{--bg:#151517;--fg:#e8e8e8;--mut:#999;
--line:#2c2c30;--card:#1d1d20;--pos:#3ddc97;--neg:#ff6b5a}}
*{box-sizing:border-box}
body{margin:0;padding:24px;background:var(--bg);color:var(--fg);
font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
h1{font-size:18px;margin:0 0 4px}
.sub{color:var(--mut);font-size:12px;margin-bottom:18px}
.wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;min-width:760px;background:var(--card);
border:1px solid var(--line);border-radius:8px;overflow:hidden}
th,td{padding:10px 12px;text-align:right;border-bottom:1px solid var(--line)}
th{background:rgba(128,128,128,.08);font-weight:600;font-size:12px;color:var(--mut)}
th:first-child,td:first-child{text-align:left}
tr:last-child td{border-bottom:none}
.big{font-weight:700;font-size:15px}
.pos{color:var(--pos)}.neg{color:var(--neg)}
.v{font-weight:600}.s{color:var(--mut);font-size:11px}
.note{color:var(--mut);font-size:12px;margin-top:18px;max-width:70ch}
.health{margin-top:14px;font-size:12px;color:var(--mut)}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;
margin-right:5px;vertical-align:middle}
.up{background:var(--pos)}.down{background:var(--neg)}
.empty{padding:40px;text-align:center;color:var(--mut);background:var(--card);
border:1px dashed var(--line);border-radius:8px}
"""

NOTE = """净年化 = 空腿年化 − 多腿年化，已按各所真实结算周期（1h/4h/8h）折算，
未扣手续费、滑点、借贷成本。两条腿各占保证金，所以对总投入资金的实际年化约为该值的一半。
基差是两所标记价格的偏离——这是这类合约的主要残余风险：
股票类与 pre-IPO 合约没有可交割现货，两所价格没有强制收敛的力量，
要看的不是它此刻多少，而是它在历史里波动多大。
本页仅供研究，不构成投资建议。"""


def _num(v, digits=2, suffix="%"):
    if v is None:
        return '<td class="s">—</td>'
    cls = "pos" if v > 0 else ("neg" if v < 0 else "")
    return '<td class="%s">%.*f%s</td>' % (cls, digits, v, suffix)


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
            rows.append(
                "<tr><td><b>%s</b> <span class=s>%d腿</span></td>"
                "<td><span class=v>%s</span><br><span class=s>%.1f%%</span></td>"
                "<td><span class=v>%s</span><br><span class=s>%.1f%%</span></td>"
                "%s%s%s</tr>" % (
                    html.escape(p["asset"]), p["n_legs"],
                    html.escape(p["long_venue"] or "-"), p["long_apr"] or 0,
                    html.escape(p["short_venue"] or "-"), p["short_apr"] or 0,
                    '<td class="big %s">%.1f%%</td>' % (
                        "pos" if (p["net_apr"] or 0) > 0 else "neg",
                        p["net_apr"] or 0),
                    _num((p["net_apr"] or 0) / 2, 1),
                    _num(p["mark_spread_pct"], 3)))
        body = ('<div class=wrap><table><tr>'
                '<th>标的</th><th>做多腿<br>费率最低</th><th>做空腿<br>费率最高</th>'
                '<th>净年化</th><th>占用总资金</th><th>基差</th></tr>'
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
        body, hs or "—",
        NOTE.replace("\n", " "))


def api_latest():
    ts, pairs = store.latest_pairs()
    return json.dumps({"ts": ts, "pairs": pairs,
                       "health": store.latest_health()},
                      ensure_ascii=False, indent=2)
