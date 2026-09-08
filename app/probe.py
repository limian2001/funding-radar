# -*- coding: utf-8 -*-
"""排错工具：把某家交易所 / 行情源的原始返回打出来。

    docker compose run --rm radar python -m app.probe bitget
    docker compose run --rm radar python -m app.probe stock A 688825
    docker compose run --rm radar python -m app.probe fx

跑不通的适配器，把这里的输出贴出来就能照着修，不用来回猜。
"""
import json
import sys
import traceback

from . import quotes, venues


def main(argv):
    what = (argv[0] if argv else "").lower()
    if what == "fx":
        print(json.dumps(quotes.fx_rates(), ensure_ascii=False, indent=2))
        return
    if what == "stock":
        market, code = argv[1], argv[2]
        print("tencent:", quotes._from_tencent(market, code))
        print("eastmoney:", quotes._from_eastmoney(market, code))
        return
    fn = venues.ADAPTERS.get(what)
    if not fn:
        print("可用: %s | stock <A|HK|US> <code> | fx"
              % ", ".join(sorted(venues.ADAPTERS)))
        return
    want = set(argv[1:]) or None
    try:
        rows = fn(want=want)
    except Exception:
        traceback.print_exc()
        return
    print("拿到 %d 条" % len(rows))
    for r in rows[:5]:
        print(json.dumps(r, ensure_ascii=False))
    if want:
        print("\n匹配你给的符号：")
        for r in rows:
            if r["symbol"] in want:
                print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
