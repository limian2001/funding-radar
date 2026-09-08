# -*- coding: utf-8 -*-
"""前端：单页 + 标签页，切换标的不请求后端；数据每 60 秒后台刷新。
渲染逻辑只有 JS 一份，服务端只出数据。"""
import json

from . import quotes, store, universe as uni_store, venues

CANON = ["hyperliquid", "binance", "bybit", "okx", "gate",
         "bitget", "bingx", "edgex"]

CSS = """
*{box-sizing:border-box}
:root{--bg:#0d0d0f;--card:#151518;--line:#26262b;--fg:#e6e6e8;--mut:#8b8b93;
--faint:#66666e;--pos:#2fbf71;--neg:#ff5c50;--acc:#4a9eff;--warn:#e0a92b}
body{margin:0;padding:16px 20px;background:var(--bg);color:var(--fg);
font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
a{color:var(--acc);text-decoration:none}
h1{font-size:15px;margin:0;font-family:system-ui,sans-serif}
.top{display:flex;align-items:baseline;gap:14px;margin-bottom:10px}
.sub{color:var(--mut);font-size:11px}
.tabs{display:flex;gap:2px;flex-wrap:wrap;border-bottom:1px solid var(--line);
margin-bottom:12px}
.tab{padding:6px 14px;cursor:grab;color:var(--mut);border:1px solid transparent;
border-bottom:none;border-radius:5px 5px 0 0;font-family:system-ui,sans-serif;
font-size:12px;user-select:none;position:relative;top:1px}
.tab:hover{color:var(--fg)}
.tab.on{background:var(--card);border-color:var(--line);color:var(--fg)}
.tab:active{cursor:grabbing}
.tab .p.mut{opacity:.6}
.tab .p{font-size:10px;margin-left:6px}
.wrap{overflow-x:auto}
table{border-collapse:collapse;background:var(--card);border:1px solid var(--line);
border-radius:6px;overflow:hidden;width:100%}
th,td{padding:7px 10px;text-align:right;border-bottom:1px solid var(--line);
white-space:nowrap;font-variant-numeric:tabular-nums}
th{background:#1c1c21;color:var(--mut);font-size:10.5px;font-weight:600;
font-family:system-ui,sans-serif}
th:first-child,td:first-child{text-align:left}
tr:last-child td{border-bottom:none}
tbody tr:hover{background:#1a1a1f}
.pos{color:var(--pos)}.neg{color:var(--neg)}.mut{color:var(--mut)}
.faint{color:var(--faint);font-size:10.5px}
.name{font-family:system-ui,sans-serif;font-weight:600}
.tag{display:inline-block;font-size:9px;padding:0 4px;border-radius:3px;
margin-left:5px;color:#0d0d0f;font-family:system-ui,sans-serif}
.t-long{background:var(--pos)}.t-short{background:var(--neg)}
.t-prem{background:var(--warn)}
.head{background:var(--card);border:1px solid var(--line);border-radius:6px;
padding:11px 16px;margin-bottom:10px;display:flex;gap:28px;flex-wrap:wrap;
align-items:baseline}
.head .px{font-size:20px;font-weight:700}
.note{color:var(--mut);font-size:11px;margin-top:14px;max-width:84ch;
font-family:system-ui,sans-serif;line-height:1.65}
.note b{color:var(--fg)}
.foot{margin-top:10px;font-size:11px;color:var(--mut);display:flex;gap:16px;
flex-wrap:wrap;align-items:center}
.dot{display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:4px}
.up{background:var(--pos)}.down{background:var(--neg)}
.card{background:var(--card);border:1px solid var(--line);border-radius:6px;
padding:14px 16px;margin-bottom:12px}
.card h3{margin:0 0 10px;font-size:12px;font-family:system-ui,sans-serif;
color:var(--mut);font-weight:600}
input,select,button{background:#1c1c21;color:var(--fg);border:1px solid var(--line);
border-radius:4px;padding:5px 9px;font:12px ui-monospace,Menlo,monospace}
button{cursor:pointer;background:#25252c}
button:hover{background:#2f2f38}
button.primary{background:var(--acc);color:#08080a;border-color:var(--acc);
font-weight:600}
button.danger{color:var(--neg)}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
label{color:var(--mut);font-size:11px;font-family:system-ui,sans-serif}
.msg{font-size:11px;padding:6px 0;font-family:system-ui,sans-serif}
.msg.err{color:var(--neg)}.msg.ok{color:var(--pos)}
.empty{padding:34px;text-align:center;color:var(--mut)}
"""

JS = r"""
var D=null, TAB=localStorage.getItem('tab')||null, SR=null, DRAG=null;

function n(v,d,sign,suf){
  if(v===null||v===undefined||isNaN(v)) return '<span class=mut>--</span>';
  var c = v>0?'pos':(v<0?'neg':'');
  return '<span class="'+c+'">'+((sign&&v>0?'+':'')+Number(v).toFixed(d)+(suf||''))+'</span>';
}
function sz(v){ if(v===null||v===undefined) return '--';
  var a=Math.abs(v);
  if(a>=1e6) return (v/1e6).toFixed(2)+'M';
  if(a>=1e3) return (v/1e3).toFixed(2)+'K';
  return Number(v).toPrecision(4).replace(/\.?0+$/,''); }
function iv(h){ if(!h) return '?'; return h<1?Math.round(h*60)+'m':(h+'h'); }
function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g,
  function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];}); }

function load(cb){
  fetch('/api/latest').then(function(r){return r.json();}).then(function(d){
    D=d; render(); if(cb)cb();
  }).catch(function(e){
    document.getElementById('panes').innerHTML =
      '<div class=empty>拿不到数据：'+esc(e)+'</div>';
  });
}

/* 标签来源 = 标的清单（加了立刻出现）∪ 已有数据的标的，
   顺序由服务端保存的 _order 决定，可拖拽调整 */
function items(){
  var byName={}; (D.pairs||[]).forEach(function(p){byName[p.asset]=p;});
  var order=(D.order||[]).slice();
  Object.keys(D.universe||{}).forEach(function(k){
    if(order.indexOf(k)<0) order.push(k); });
  (D.pairs||[]).forEach(function(p){
    if(order.indexOf(p.asset)<0) order.push(p.asset); });
  return order.map(function(k){
    return {key:k, pair:byName[k]||null, cfg:(D.universe||{})[k]||null}; });
}

function render(){
  if(!D) return;
  var its=items(), keys=its.map(function(i){return i.key;});
  if(TAB!=='__set__' && keys.indexOf(TAB)<0) TAB = keys[0]||'__set__';
  document.getElementById('tabs').innerHTML = its.map(function(i){
    var prem = i.pair ? i.pair.best_prem_pct : null;
    var pc = (prem===null||prem===undefined)?'mut':(prem>0?'pos':'neg');
    var ptxt = (prem===null||prem===undefined)?'…'
               :((prem>0?'+':'')+prem.toFixed(2)+'%');
    return '<div class="tab'+(TAB===i.key?' on':'')+'" draggable="true" '+
      'data-key="'+esc(i.key)+'">'+esc(i.key)+
      '<span class="p '+pc+'">'+ptxt+'</span></div>';
  }).join('') + '<div class="tab'+(TAB==='__set__'?' on':'')+
      '" data-key="__set__">⚙ 设置</div>';
  document.getElementById('ts').textContent = D.ts
    ? new Date(D.ts*1000).toISOString().replace('T',' ').slice(0,19)+' UTC' : '--';
  document.getElementById('health').innerHTML = (D.health||[]).map(function(h){
    return '<span title="'+esc(h.err||((h.n||0)+' 个合约'))+'"><span class="dot '+
      (h.ok?'up':'down')+'"></span>'+esc(h.venue)+(h.ok?'':' ✕')+'</span>';
  }).join(' ');
  var cur = its.filter(function(i){return i.key===TAB;})[0];
  // 单个标的的数据有问题时，只让那一格报错，不能让整个界面卡住不切换
  try{
    document.getElementById('panes').innerHTML =
      TAB==='__set__' ? settingsPane() : assetPane(cur);
  }catch(err){
    document.getElementById('panes').innerHTML =
      '<div class=empty>这个标的渲染出错了：'+esc(err&&err.message||err)+
      '<br><br>把这行发给我，我照着修。</div>';
  }
  tick();
}

function go(t){ TAB=t; localStorage.setItem('tab',t); render(); }

/* 事件委托：标签是重绘出来的，不能挂内联 onclick */
document.addEventListener('click', function(e){
  var t=e.target.closest && e.target.closest('.tab');
  if(t && t.dataset.key) go(t.dataset.key);
});
document.addEventListener('dragstart', function(e){
  var t=e.target.closest && e.target.closest('.tab');
  if(t && t.dataset.key!=='__set__'){ DRAG=t.dataset.key;
    e.dataTransfer.effectAllowed='move'; }
});
document.addEventListener('dragover', function(e){
  if(DRAG && e.target.closest && e.target.closest('.tab')) e.preventDefault();
});
document.addEventListener('drop', function(e){
  var t=e.target.closest && e.target.closest('.tab');
  if(!DRAG || !t || !t.dataset.key || t.dataset.key==='__set__') return;
  e.preventDefault();
  var order=items().map(function(i){return i.key;});
  var from=order.indexOf(DRAG), to=order.indexOf(t.dataset.key);
  if(from<0||to<0||from===to){DRAG=null;return;}
  order.splice(to,0,order.splice(from,1)[0]);
  D.order=order; DRAG=null; render();
  fetch('/api/universe/order',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({order:order})});
});

function assetPane(it){
  if(!it) return '<div class=empty>没有数据</div>';
  var p=it.pair, cfg=it.cfg||{};
  var waiting = !p || !p.legs || !p.legs.length;
  var head = '<div class=head>'+
    '<div><div class=faint>标的</div><div class=name style="font-size:16px">'+
      esc((p&&p.stock_name)||cfg.name||it.key)+
      ' <span class=faint>'+esc(it.key)+'</span></div></div>'+
    '<div><div class=faint>股价</div><div class=px>'+n(p&&p.stock_price,3)+
      ' <span class=faint>'+esc((p&&p.ccy)||'')+'</span></div></div>'+
    '<div><div class=faint>汇率</div><div>'+n(p&&p.fx,4)+'</div></div>'+
    '<div><div class=faint>锚价 USD</div><div class=px>'+n(p&&p.anchor_usd,4)+'</div></div>'+
    '<div><div class=faint>行情时间</div><div>'+esc((p&&p.quote_time)||'--')+'</div></div>'+
    '<div><div class=faint>资金费净年化</div><div class=px>'+n(p&&p.net_apr,1,1,'%')+
      '</div><div class=faint>'+esc((p&&p.long_venue)||'--')+' → '+
      esc((p&&p.short_venue)||'--')+'</div></div></div>';

  var rows;
  if(waiting){
    // 新加的标的：先把配置里的交易所列出来占位，数据下一轮补上
    rows = Object.keys(cfg.venues||{}).map(function(v){
      return '<tr><td><span class=name>'+esc(v)+'</span></td>'+
        '<td class=faint>'+esc(cfg.venues[v])+'</td>'+
        '<td colspan=8 class=mut>采集中…</td></tr>';
    }).join('') || '<tr><td colspan=10 class=mut>采集中…</td></tr>';
  } else {
    rows = p.legs.map(function(l){
      var tag='';
      if(l.venue===p.long_venue) tag+='<span class="tag t-long" title="在这家做多">多</span>';
      if(l.venue===p.short_venue) tag+='<span class="tag t-short" title="在这家做空">空</span>';
      if(l.venue===p.best_prem_venue && p.best_prem_pct>0)
        tag+='<span class="tag t-prem" title="溢价最高">溢价</span>';
      var cd = l.next_ts ? '<span data-cd="'+l.next_ts+'">--</span>'
                         : '<span class=mut>--</span>';
      return '<tr><td><span class=name>'+esc(l.venue)+'</span>'+tag+'</td>'+
        '<td class=faint>'+esc(l.symbol)+'</td><td>'+n(l.last,4)+'</td>'+
        '<td>'+n(l.premium_pct,2,1,'%')+'</td>'+
        '<td>'+n(l.rate*100,4,1,'%')+' <span class=faint>/'+iv(l.interval_h)+'</span></td>'+
        '<td>'+n(l.apr*100,1,1,'%')+'</td><td>'+cd+'</td>'+
        '<td>'+n(l.bid,4)+' <span class=faint>× '+sz(l.bid_sz)+'</span></td>'+
        '<td>'+n(l.ask,4)+' <span class=faint>× '+sz(l.ask_sz)+'</span></td>'+
        '<td>'+n(l.mark,4)+'</td></tr>';
    }).join('');
  }
  var t=(p&&p.trailing_24h)||{};
  var foot='<div class=foot><span>24h 净年化 '+
    (t.min_net==null?'--':(t.min_net.toFixed(0)+' ~ '+t.max_net.toFixed(0)+'%'))+
    '</span><span>均值 '+n(t.avg_net,1,1,'%')+'</span><span>站上 10% 的时间 '+
    n(t.pct_above,0,0,'%')+'</span><span>样本 '+(t.n||0)+'</span></div>';
  return head+'<div class=wrap><table><thead><tr>'+
    '<th>交易所</th><th>合约</th><th>最新价</th><th>折溢价</th>'+
    '<th>资金费率/周期</th><th>年化</th><th>结算倒计时</th>'+
    '<th>买一 × 量</th><th>卖一 × 量</th><th>标记价</th>'+
    '</tr></thead><tbody>'+rows+'</tbody></table></div>'+foot+
    '<p class=note><b>「多」「空」是程序给出的建仓方向</b>：'+
    '「多」标在资金费率最低（最负）的那家——在那边开多仓，是收资金费的一方；'+
    '「空」标在费率最高（最正）的那家——在那边开空仓，同样是收钱的一方。'+
    '两条腿同时持有，价格方向基本对冲掉，净收 = 空腿年化 − 多腿年化，'+
    '也就是表头那个「资金费净年化」。<br>'+
    '<b>折溢价</b> = 永续价 ÷ 锚价 − 1，锚价 = 真实股价 ÷ 汇率。'+
    '只有溢价（正数）是你能执行的方向：买入现货 + 做空永续；'+
    '折价需要做空现货，A 股散户做不到。'+
    '<b>资金费率</b>左边是原始单期值与结算周期，右边是折算后的年化：'+
    '1 小时结算的 0.01% 相当于 8 小时结算的 0.08%。'+
    '<b>买一/卖一的量</b>决定实际能吃多少。股市休市时锚价是上一个收盘价，'+
    '折溢价会失真，看「行情时间」判断新鲜度。'+
    '本页仅供研究，不构成投资建议。</p>';
}

function tick(){
  var now=Date.now();
  document.querySelectorAll('[data-cd]').forEach(function(e){
    var d=+e.getAttribute('data-cd')-now;
    if(!(d>0)){e.textContent='--';return;}
    var s=Math.floor(d/1000),h=Math.floor(s/3600),m=Math.floor(s%3600/60),q=s%60;
    e.textContent=(h<10?'0':'')+h+':'+(m<10?'0':'')+m+':'+(q<10?'0':'')+q;
  });
}

/* ----------------------------------------------------------- 设置页 */
function settingsPane(){
  var cur = items().filter(function(i){return i.cfg;}).map(function(i){
    var u=i.cfg;
    var und = u.underlying ? (u.underlying.market+' '+u.underlying.code) : '无锚（纯加密）';
    return '<tr><td><span class=name>'+esc(i.key)+'</span> <span class=faint>'+
      esc(u.name||'')+'</span></td><td class=faint>'+esc(und)+'</td>'+
      '<td class=faint>'+esc(Object.keys(u.venues||{}).join(', '))+'</td>'+
      '<td><button class=danger data-del="'+esc(i.key)+'">删除</button></td></tr>';
  }).join('');
  return '<div class=card><h3>已监控的标的 · 标签栏可直接拖动排序</h3>'+
    '<div class=wrap><table><thead><tr><th>代号</th><th>锚（股票）</th>'+
    '<th>交易所</th><th></th></tr></thead><tbody>'+
    (cur||'<tr><td colspan=4 class=mut>还没有</td></tr>')+'</tbody></table></div></div>'+
    '<div class=card><h3>添加新标的</h3>'+
    '<div class=row><label>1. 搜合约</label>'+
    '<input id=q placeholder="关键词，如 MEITUAN / CXMT / BTC（大小写都行）" size=32 '+
    'onkeydown="if(event.key===\'Enter\')doSearch()">'+
    '<button class=primary onclick="doSearch()">搜索各交易所</button>'+
    '<span id=smsg class=msg></span></div><div id=sres></div>'+
    '<div class=row style="margin-top:12px"><label>2. 锚（可选）</label>'+
    '<select id=mk><option value="">无锚 · 纯加密标的</option>'+
    '<option value="A">A 股</option><option value="HK">港股</option>'+
    '<option value="US">美股</option></select>'+
    '<input id=code placeholder="股票代码 如 688836" size=12>'+
    '<button onclick="checkStock()">验证股票</button>'+
    '<span id=cmsg class=msg></span></div>'+
    '<div class=row><label>3. 保存为</label>'+
    '<input id=key placeholder="标的代号 如 CXMT" size=12>'+
    '<input id=nm placeholder="中文名 如 长鑫科技" size=16>'+
    '<button class=primary onclick="doAdd()">添加到看板</button>'+
    '<span id=amsg class=msg></span></div></div>'+
    '<p class=note>搜索会去各家交易所的合约列表里找名字含关键词的永续合约。'+
    '<b>同一标的在各家命名不同</b>（CXMTUSDT / CXMT_USDT / CXMT-USDT-SWAP），'+
    '所以不要手填，搜出来再勾。<b>验证股票这一步别跳过</b>：'+
    '代码填错不会报错，只会安静地给出一个完全错误的折溢价。'+
    '添加后标签立即出现，数据在下一轮采集补上（已自动催了一次）。</p>';
}

document.addEventListener('click', function(e){
  var b=e.target.closest && e.target.closest('[data-del]');
  if(b) del(b.dataset.del);
});

function doSearch(){
  var q=document.getElementById('q').value.trim();
  if(!q) return;
  var m=document.getElementById('smsg');
  m.textContent='搜索中，各家轮一遍要几秒…'; m.className='msg';
  fetch('/api/search?q='+encodeURIComponent(q))
   .then(function(r){return r.json();}).then(function(d){
    SR=d.results||[];
    m.textContent='找到 '+SR.length+' 条'+
      (Object.keys(d.errors||{}).length?('，失败: '+Object.keys(d.errors).join(',')):'');
    m.className='msg ok';
    if(!document.getElementById('key').value)
      document.getElementById('key').value=q.toUpperCase();
    var seen={};
    document.getElementById('sres').innerHTML='<div class=wrap><table><thead><tr>'+
      '<th>选</th><th>交易所</th><th>合约</th><th>单期费率/周期</th><th>年化</th>'+
      '<th>最新价</th></tr></thead><tbody>'+SR.map(function(r,i){
        var first=!seen[r.venue]; seen[r.venue]=1;
        return '<tr><td><input type=checkbox id="c'+i+'"'+(first?' checked':'')+'></td>'+
          '<td><span class=name>'+esc(r.venue)+'</span></td><td>'+esc(r.symbol)+'</td>'+
          '<td>'+n(r.rate*100,4,1,'%')+' <span class=faint>/'+iv(r.interval_h)+'</span></td>'+
          '<td>'+n(r.apr_pct,1,1,'%')+'</td><td>'+n(r.last,4)+'</td></tr>';
      }).join('')+'</tbody></table></div>';
  }).catch(function(e){
    m.textContent='搜索失败：'+e; m.className='msg err'; });
}

function checkStock(){
  var mk=document.getElementById('mk').value;
  var code=document.getElementById('code').value.trim();
  var m=document.getElementById('cmsg');
  if(!mk||!code){ m.textContent='选市场并填代码'; m.className='msg err'; return; }
  m.textContent='查询中…'; m.className='msg';
  fetch('/api/stock?market='+mk+'&code='+encodeURIComponent(code))
   .then(function(r){return r.json();}).then(function(d){
    if(d.error){ m.textContent='查不到：'+d.error; m.className='msg err'; return; }
    m.textContent='✓ '+d.name+' 现价 '+d.price+'（'+d.src+' '+(d.quote_time||'')+'）';
    m.className='msg ok';
    if(!document.getElementById('nm').value)
      document.getElementById('nm').value=d.name||'';
  });
}

function doAdd(){
  var key=document.getElementById('key').value.trim().toUpperCase();
  var m=document.getElementById('amsg');
  if(!key){ m.textContent='填标的代号'; m.className='msg err'; return; }
  var venues={};
  (SR||[]).forEach(function(r,i){
    var c=document.getElementById('c'+i);
    if(c&&c.checked) venues[r.venue]=r.symbol; });
  if(!Object.keys(venues).length){
    m.textContent='先搜索并勾选至少一个合约'; m.className='msg err'; return; }
  var mk=document.getElementById('mk').value;
  var code=document.getElementById('code').value.trim();
  m.textContent='保存中…'; m.className='msg';
  fetch('/api/universe/add',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({key:key,name:document.getElementById('nm').value.trim(),
      underlying: mk&&code?{market:mk,code:code}:null, venues:venues})})
   .then(function(r){return r.json();}).then(function(d){
    if(d.error){ m.textContent='失败：'+d.error; m.className='msg err'; return; }
    m.textContent='✓ 已添加，已切到该标签，数据马上补上';
    m.className='msg ok';
    load(function(){ go(d.key||key); });
    setTimeout(load, 8000); setTimeout(load, 20000);
  });
}

function del(k){
  if(!confirm('从看板移除 '+k+'？历史数据保留，只是不再采集。')) return;
  fetch('/api/universe/remove',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({key:k})})
   .then(function(){ if(TAB===k){TAB='__set__';localStorage.setItem('tab',TAB);} load(); });
}

setInterval(function(){ load(); }, 60000);
setInterval(tick, 1000);
load();
"""


def shell():
    return ("<!doctype html><html lang=zh><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Funding Radar</title><style>" + CSS + "</style>"
            "<div class=top><h1>跨市场折溢价 / 资金费雷达</h1>"
            "<span class=sub>最近一轮 <span id=ts>--</span> · 每 60 秒刷新</span></div>"
            "<div class=tabs id=tabs></div><div id=panes></div>"
            "<div class=foot><span>数据源 <span id=health></span></span></div>"
            "<noscript><p class=note>这个页面需要 JavaScript。</p></noscript>"
            "<script>" + JS + "</script></html>")


def api_latest(poll_sec=300):
    ts, pairs = store.latest_pairs()
    uni, _ = uni_store.parsed()
    out = []
    for p in pairs:
        d = dict(p)
        d["legs"] = store.latest_legs(p["asset"])
        d["trailing_24h"] = store.trailing(p["asset"], hours=24)
        out.append(d)
    return json.dumps({"ts": ts, "pairs": out, "universe": uni,
                       "order": uni_store.get_order(), "poll_sec": poll_sec,
                       "health": store.latest_health()},
                      ensure_ascii=False)


def api_search(q):
    rows, errs = venues.search(q)
    return json.dumps({"results": rows, "errors": errs}, ensure_ascii=False)


def api_stock(market, code):
    q = quotes.stock_price(market, code)
    if not q:
        return json.dumps({"error": "没查到 %s %s" % (market, code)},
                          ensure_ascii=False)
    return json.dumps(q, ensure_ascii=False)
