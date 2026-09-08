# -*- coding: utf-8 -*-
"""按关键词在各所合约列表里搜同一个标的的真实符号。

    docker compose run --rm radar python -m app.discover CXMT

跨所匹配是这类项目最容易出错的一步：同一个标的在各家可能叫
CXMTUSDT / CXMT_USDT / CXMT-USDT-SWAP，甚至带 k 前缀表示合约乘数不同。
所以不要猜，先搜出来看。
"""
import sys

from . import venues


def main(keyword):
    kw = keyword.upper()
    hits = []
    for name, fn in venues.LIST_ALL:
        try:
            hits += [r for r in fn() if kw in (r["symbol"] or "").upper()]
        except Exception as e:
            print("  [跳过] %-12s %s" % (name, e), file=sys.stderr)
    try:
        hits += venues.fetch_okx(keyword=kw)
    except Exception as e:
        print("  [跳过] okx %s" % e, file=sys.stderr)

    if not hits:
        print("没找到 '%s'。换个写法试试（去掉后缀、用交易所页面上的简称）。" % kw)
        return
    print("%-13s %-24s %13s %7s %12s" %
          ("venue", "symbol", "rate", "周期h", "年化%"))
    for h in sorted(hits, key=lambda x: (x["venue"], x["symbol"])):
        print("%-13s %-24s %13.6f %7.1f %12.1f" %
              (h["venue"], h["symbol"], h["rate"], h["interval_h"],
               venues.apr(h) * 100))
    print("\n把上面的 symbol 填进 config/universe.json，容器会自动生效，不用重启。")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
