# -*- coding: utf-8 -*-
"""看板：/ 汇总（一标的一行），/a/<asset> 明细（一交易所一行）。
服务端渲染，无外部资源。"""
import html
import json
import time
import urllib.parse

from . import store

CANON = ["hyperliquid", "binance", "bybit", "okx", "gate",
         "bitget", "bingx", "edgex"]

CSS = """
*{box-sizing:border-box}
:root{--bg:#0d0d0f;--card:#151518;--line:#26262b;--fg:#e6e6e8;--mut:#8b8b93;
--faint:#66666e;--pos:#2fbf71;--neg:#ff5c50;--acc:#4a9eff}
body{margin:0;padding:20px;background:var(--bg);color:var(--fg);
font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
h1{font-size:16px;margin:0 0 2px;font-family:system-ui,sans-serif}
.sub{color:var(--mut);font-size:11px;margin-bottom:14px}
.wrap{overflow-x:auto}
table{border-collapse:collapse;background:var(--card);border:1px solid var(--line);
border-radius:6px;overflow:hidden;width:100%}
th,td{padding:7px 10px;text-align:right;border-bottom:1px solid var(--line);
white-space:nowrap;font-variant-numeric:tabular-nums}
th{background:#1c1c21;color:var(--mut);font-size:10.5px;font-weight:600;
text-align:right;font-family:system-ui,sans-serif}
th:first-child,td:first-child{text-align:left}
tr:last-child td{border-bottom:none}
tbody tr:hover{background:#1a1a1f}
.pos{color:var(--pos)}.neg{color:var(--neg)}.mut{color:var(--mut)}
.faint{color:var(--faint);font-size:10.5px}
.big{font-size:14px;font-weight:700}
.name{font-family:system-ui,sans-serif;font-weight:600}
.tag{display:inline-block;font-size:9px;padding:0 4px;border-radius:3px;
margin-left:5px;color:#0d0d0f;font-family:system-ui,sans-serif}
.t-long{background:var(--pos)}.t-short{background:var(--neg)}
.t-prem{background:#e0a92b}
.head{background:var(--card);border:1px solid var(--line);border-radius:6px;
padding:12px 16px;margin-bottom:12px;display:flex;gap:26px;align-items:baseline;
flex-wrap:wrap}
.head .px{font-size:22px;font-weight:700}
.note{color:var(--mut);font-size:11px;margin-top:16px;max-width:82ch;
font-family:system-ui,sans-serif;line-height:1.65}
.note b{color:var(--fg)}
.foot{margin-top:12px;font-size:11px;color:var(--mut);display:flex;gap:18px;
flex-wrap:wrap}
.dot{display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:4px}
.up{background:var(--pos)}.down{background:var(--neg)}
.empty{padding:36px;text-align:center;color:var(--mut);background:var(--card);
border:1px dashed var(--line);border-radius:6px}
"""

JS = """
function tick(){var n=Date.now();
document.querySelectorAll('[data-cd]').forEach(function(e){
var d=+e.getAttribute('data-cd')-n; if(!(d>0)){e.textContent='--';return;}
var s=Math.floor(d/1000),h=Math.floor(s/3600),m=Math.floor(s%3600/60);
e.textContent=(h<10?'0':'')+h+':'+(m<10?'0':'')+m+':'+
((s%60)<10?'0':'')+(s%60);});}
setInterval(tick,1000);tick();
"""

NOTE_SUM = """<b>折溢价</b> = 永续价 ÷ 锚价 − 1，锚价 = 真实股价 ÷ 汇率。
<b>只有溢价（正数）是你能执行的方向</b>：买入现货 + 做空永续；
折价需要做空现货，A 股散户做不到，所以折价只作记录。
<b>净年化</b> = 资金费最高的所（做空）− 最低的所（做多），已按各家真实结算周期折算；
两条腿各占保证金，对总投入资金的实际年化约为其一半。数值均未扣手续费与滑点。
标的与永续的交易时段不同，股市休市时锚价是上一个收盘价，此时的折溢价会失真——
看「行情时间」判断新鲜度。本页仅供研究，不构成投资建议。"""

NOTE_DET = """每行一家交易所。<b>资金费率</b>显示原始单期值与结算周期，右侧是折算后的年化：
1 小时结算的 0.01% 相当于 8 小时结算的 0.08%，不折算直接比较是错的。
<b>买一/卖一</b>的量决定你实际能吃多少——这是套利计算的必需项，
纸面上的价差如果只有几百 U 的深度，扣完滑点就没了。
<b>倒计时</b>是距下次资金费结算的时间，只有持仓到那一刻才收得到（或付得出）。
本页仅供研究，不构成投资建议。"""


def _f(v, d=2, sign=False, suffix=""):
    if v is None:
        return '<span class=mut>--</span>'
    cls = "pos" if v > 0 else ("neg" if v < 0 else "")
    fmt = "%+." + str(d) + "f" if sign else "%." + str(d) + "f"
    return '<span class="%s">%s%s</span>' % (cls, fmt % v, suffix)


def _sz(v):
    if v is None:
        return "--"
    for unit, div in (("M", 1e6), ("K", 1e3)):
        if abs(v) >= div:
            return "%.2f%s" % (v / div, unit)
    return "%.4g" % v


def _iv(h):
    if not h:
        return "?"
    return "%dm" % round(h * 60) if h < 1 else "%gh" % h


def _shell(title, body, extra_head=""):
    return ("<!doctype html><html lang=zh><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>%s</title><style>%s</style>%s%s"
            "<script>%s</script></html>"
            % (title, CSS, extra_head, body, JS))


def _health_bar():
    hs = store.latest_health()
    return " ".join(
        '<span><span class="dot %s"></span>%s</span>' % (
            "up" if h["ok"] else "down", html.escape(h["venue"]))
        for h in sorted(hs, key=lambda x: CANON.index(x["venue"])
                        if x["venue"] in CANON else 99))


# --------------------------------------------------------------- 汇总页
def render():
    ts, pairs = store.latest_pairs()
    if not pairs:
        return _shell("Funding Radar", "<h1>跨市场折溢价 / 资金费雷达</h1>"
                      "<div class=empty>还没有数据。先用 "
                      "<code>python -m app.discover CXMT</code> 找符号，"
                      "填进 config/universe.json，等下一轮采集。</div>")
    rows = []
    for p in sorted(pairs, key=lambda x: -(x["best_prem_pct"] or -999)):
        a = html.escape(p["asset"])
        stock = ("%s <span class=faint>%s %s</span>" % (
            _f(p["stock_price"], 3), p["ccy"] or "", p["quote_time"] or "")
            if p["stock_price"] else '<span class=mut>--</span>')
        rows.append(
            "<tr><td><a href='/a/%s'><span class=name>%s</span></a>"
            " <span class=faint>%s</span></td>"
            "<td>%s</td><td>%s</td>"
            "<td>%s <span class=faint>%s</span></td>"
            "<td>%s <span class=faint>%s</span></td>"
            "<td class=big>%s</td>"
            "<td class=faint>%s→%s</td>"
            "<td>%s</td><td class=faint>%d</td></tr>" % (
                urllib.parse.quote(p["asset"]), a,
                html.escape(p["stock_name"] or ""),
                stock, _f(p["anchor_usd"], 4),
                _f(p["best_prem_pct"], 2, sign=True, suffix="%"),
                html.escape(p["best_prem_venue"] or ""),
                _f(p["worst_prem_pct"], 2, sign=True, suffix="%"),
                html.escape(p["worst_prem_venue"] or ""),
                _f(p["net_apr"], 1, sign=True, suffix="%"),
                html.escape(p["long_venue"] or "--"),
                html.escape(p["short_venue"] or "--"),
                _f(p["mark_spread_pct"], 3, sign=True, suffix="%"),
                p["n_legs"]))
    body = ("<h1>跨市场折溢价 / 资金费雷达</h1>"
            "<div class=sub>%s UTC · 每 60 秒自动刷新 · 点标的看明细</div>"
            "<div class=wrap><table><thead><tr>"
            "<th>标的</th><th>股价</th><th>锚价 USD</th>"
            "<th>最高溢价</th><th>最低溢价</th>"
            "<th>资金费净年化</th><th>多→空</th><th>标记价差</th><th>腿</th>"
            "</tr></thead><tbody>%s</tbody></table></div>"
            "<div class=foot><span>数据源 %s</span></div>"
            "<p class=note>%s</p>" % (
                time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts)),
                "".join(rows), _health_bar(), NOTE_SUM.replace("\n", " ")))
    return _shell("Funding Radar", body,
                  "<meta http-equiv=refresh content=60>")


# --------------------------------------------------------------- 明细页
def render_asset(asset):
    ts, pairs = store.latest_pairs()
    p = next((x for x in pairs if x["asset"] == asset), None)
    if not p:
        return _shell("未找到", "<h1>没有这个标的</h1>"
                      "<p><a href='/'>返回汇总</a></p>")
    legs = store.latest_legs(asset)
    order = {v: i for i, v in enumerate(CANON)}
    legs.sort(key=lambda l: order.get(l["venue"], 99))

    rows = []
    for l in legs:
        tags = ""
        if l["venue"] == p["long_venue"]:
            tags += '<span class="tag t-long">多</span>'
        if l["venue"] == p["short_venue"]:
            tags += '<span class="tag t-short">空</span>'
        if l["venue"] == p["best_prem_venue"] and (p["best_prem_pct"] or 0) > 0:
            tags += '<span class="tag t-prem">溢价</span>'
        cd = ('<span data-cd="%d">--</span>' % l["next_ts"]
              if l.get("next_ts") else '<span class=mut>--</span>')
        rows.append(
            "<tr><td><span class=name>%s</span>%s</td>"
            "<td class=faint>%s</td><td>%s</td><td>%s</td>"
            "<td>%s <span class=faint>/%s</span></td><td>%s</td><td>%s</td>"
            "<td>%s <span class=faint>× %s</span></td>"
            "<td>%s <span class=faint>× %s</span></td><td>%s</td></tr>" % (
                html.escape(l["venue"]), tags, html.escape(l["symbol"]),
                _f(l["last"], 4), _f(l["premium_pct"], 2, sign=True, suffix="%"),
                _f((l["rate"] or 0) * 100, 4, sign=True, suffix="%"),
                _iv(l["interval_h"]),
                _f(l["apr"] * 100 if l["apr"] is not None else None, 1,
                   sign=True, suffix="%"),
                cd,
                _f(l["bid"], 4), _sz(l["bid_sz"]),
                _f(l["ask"], 4), _sz(l["ask_sz"]),
                _f(l["mark"], 4)))

    head = ("<div class=head>"
            "<div><div class=faint>标的</div>"
            "<div class=name style='font-size:17px'>%s <span class=faint>%s</span>"
            "</div></div>"
            "<div><div class=faint>股价</div><div class=px>%s</div></div>"
            "<div><div class=faint>汇率 %s</div><div>%s</div></div>"
            "<div><div class=faint>锚价 USD</div><div class=px>%s</div></div>"
            "<div><div class=faint>行情时间</div><div>%s</div></div>"
            "<div style='margin-left:auto'><a href='/'>← 汇总</a></div>"
            "</div>" % (
                html.escape(p["stock_name"] or asset), html.escape(asset),
                _f(p["stock_price"], 3), p["ccy"] or "--", _f(p["fx"], 4),
                _f(p["anchor_usd"], 4),
                html.escape(p["quote_time"] or "--")))

    body = ("<h1>%s</h1><div class=sub>%s UTC · 每 60 秒自动刷新</div>%s"
            "<div class=wrap><table><thead><tr>"
            "<th>交易所</th><th>合约</th><th>最新价</th><th>折溢价</th>"
            "<th>资金费率/周期</th><th>年化</th><th>结算倒计时</th>"
            "<th>买一 × 量</th><th>卖一 × 量</th><th>标记价</th>"
            "</tr></thead><tbody>%s</tbody></table></div>"
            "<div class=foot><span>数据源 %s</span></div>"
            "<p class=note>%s</p>" % (
                html.escape(asset),
                time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts)),
                head, "".join(rows), _health_bar(),
                NOTE_DET.replace("\n", " ")))
    return _shell(asset + " · Funding Radar", body,
                  "<meta http-equiv=refresh content=60>")


def api_latest():
    ts, pairs = store.latest_pairs()
    out = []
    for p in pairs:
        d = dict(p)
        d["legs"] = store.latest_legs(p["asset"])
        d["trailing_24h"] = store.trailing(p["asset"], hours=24)
        out.append(d)
    return json.dumps({"ts": ts, "pairs": out,
                       "health": store.latest_health()},
                      ensure_ascii=False, indent=2)
