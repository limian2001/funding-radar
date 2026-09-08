# -*- coding: utf-8 -*-
"""命令行版搜索。页面上的「设置」用的是同一套逻辑（venues.search）。

    docker compose run --rm radar python -m app.discover CXMT
"""
import sys

from . import venues


def main(keyword):
    if not keyword:
        print("用法: python -m app.discover CXMT")
        return
    rows, errs = venues.search(keyword)
    for v, e in errs.items():
        print("  [跳过] %-12s %s" % (v, e), file=sys.stderr)
    if not rows:
        print("没找到 '%s'。换个写法试试（去后缀、用交易所页面上的简称）。"
              % keyword)
        return
    print("%-12s %-24s %14s %7s %12s %12s"
          % ("venue", "symbol", "单期费率", "周期", "年化%", "最新价"))
    for h in rows:
        print("%-12s %-24s %13.6f%% %7s %+11.1f%% %12s"
              % (h["venue"], h["symbol"], (h["rate"] or 0) * 100,
                 ("%gh" % h["interval_h"]) if h["interval_h"] else "?",
                 h["apr_pct"], ("%.4f" % h["last"]) if h.get("last") else "--"))
    print("\n把 symbol 填进设置页，或直接写进 universe.json 的 venues 里。")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
