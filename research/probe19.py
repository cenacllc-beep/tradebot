"""PROBE19: which Kalshi markets carry an active liquidity-incentive program right now, before PLAN19 is written.
Read-only public GETs (Kalshi's /incentive_programs and /series), User-Agent tradebot-paper-research/1.0. Counts only:
programs per series, their total period reward, target size and discount factor, and each series' fee type. No order
books, no prices, no results. Writes research/results/probe19.json.
  python research/probe19.py"""
import collections, json, os, sys
from datetime import datetime, timezone
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path: sys.path.insert(0, _p)
import lip   # noqa: E402  (its http client: same domain, User-Agent and retries)

OUT = os.path.join(HERE, "results", "probe19.json")


def main():
    progs, cur = [], None
    for _ in range(100):
        prm = dict(status="active", limit=1000)
        if cur: prm["cursor"] = cur
        j = lip.http("/incentive_programs", prm) or {}
        page = j.get("incentive_programs") or []
        progs += page
        cur = j.get("next_cursor") or j.get("cursor")
        if not cur or not page: break
    by = collections.defaultdict(lambda: dict(programs=0, reward_units=0.0, targets=collections.Counter(),
                                              discounts=collections.Counter(), types=collections.Counter(),
                                              ends=[], starts=[]))
    keys = sorted(progs[0].keys()) if progs else []
    for x in progs:
        t = x.get("market_ticker") or ""; s = t.split("-")[0]
        e = by[s]; e["programs"] += 1; e["types"][x.get("incentive_type")] += 1
        try: e["reward_units"] += float(x.get("period_reward") or 0)
        except (TypeError, ValueError): pass
        e["targets"][str(x.get("target_size_fp") or x.get("target_size"))] += 1
        e["discounts"][str(x.get("discount_factor_bps"))] += 1
        for k, lst in (("end_date", "ends"), ("start_date", "starts")):
            if x.get(k): e[lst].append(x.get(k))
    fee = {}
    for s in sorted(by, key=lambda s: -by[s]["programs"])[:60]:
        try:
            ser = (lip.http("/series/%s" % s) or {}).get("series") or {}
            fee[s] = dict(fee_type=ser.get("fee_type"), fee_multiplier=ser.get("fee_multiplier"), category=ser.get("category"),
                          title=ser.get("title"))
        except RuntimeError as ex:
            fee[s] = dict(error=str(ex)[:120])
    res = dict(probe="PROBE19", run=datetime.now(timezone.utc).isoformat(), programs=len(progs), keys=keys,
               note="counts only; period_reward read as 1/10,000 of a dollar (PLAN5's unit check)",
               series={s: dict(programs=e["programs"], reward_usd=round(e["reward_units"] / 1e4, 2),
                               types=dict(e["types"]), targets=dict(e["targets"].most_common(3)),
                               discounts=dict(e["discounts"].most_common(3)),
                               first_start=min(e["starts"]) if e["starts"] else None,
                               last_end=max(e["ends"]) if e["ends"] else None, **fee.get(s, {}))
                       for s, e in sorted(by.items(), key=lambda kv: -kv[1]["programs"])})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT + ".tmp", "w", encoding="utf-8") as f: json.dump(res, f, indent=1)
    os.replace(OUT + ".tmp", OUT)
    print("PROBE19: %d active programs in %d series" % (len(progs), len(by)))


if __name__ == "__main__":
    main()
