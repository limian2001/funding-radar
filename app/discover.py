# -*- coding: utf-8 -*-
"""按关键词在各所合约列表里搜同一标的的真实符号。

    docker compose run --rm radar python -m app.discover CXMT

跨所匹配是这类项目最容易出错的一步：同一标的在各家可能叫
CXMTUSDT / CXMT_USDT / CXMT-USDT-SWAP / CXMT-USDT，甚至带 k 前缀表示
合约乘数不同。不要猜，搜出来再填。
"""
import sys

from . import venues

# 能一次列出全部合约的所（可以直接按关键词筛）
LISTABLE = ["hyperliquid", "binance", "bybit", "gate", "bitget", "edgex"]
# 只能按符号逐个查的所，用常见命名规则猜几个再验证
GUESS = {
    "bingx": ["%s-USDT"],
    "okx": ["%s-USDT-SWAP"],
}


def main(keyword):
    kw = (keyword or "").upper()
    if not kw:
        print("用法: python -m app.discover CXMT")
        return
    hits = []
    for name in LISTABLE:
        try:
            hits += [r for r in venues.ADAPTERS[name]()
                     if kw in (r["symbol"] or "").upper()]
        except Exception as e:
            print("  [跳过] %-12s %s" % (name, str(e)[:120]), file=sys.stderr)
    try:
        hits += venues.fetch_okx(keyword=kw)
    except Exception as e:
        print("  [跳过] okx %s" % str(e)[:120], file=sys.stderr)
    for name, pats in GUESS.items():
        if name == "okx":
            continue
        want = {p % kw for p in pats}
        try:
            hits += [r for r in venues.ADAPTERS[name](want=want)]
        except Exception as e:
            print("  [跳过] %-12s %s" % (name, str(e)[:120]), file=sys.stderr)

    if not hits:
        print("没找到 '%s'。换个写法试试（去后缀、用交易所页面上的简称）。" % kw)
        return
    print("%-12s %-24s %13s %7s %12s %12s"
          % ("venue", "symbol", "单期费率", "周期", "年化%", "最新价"))
    for h in sorted(hits, key=lambda x: (x["venue"], x["symbol"])):
        print("%-12s %-24s %12.6f%% %7s %+11.1f%% %12s"
              % (h["venue"], h["symbol"], (h["rate"] or 0) * 100,
                 ("%gh" % h["interval_h"]) if h["interval_h"] else "?",
                 venues.apr(h) * 100,
                 ("%.4f" % h["last"]) if h.get("last") else "--"))
    print("\n把 symbol 填进 config/universe.json 的 venues 里，自动生效。")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
