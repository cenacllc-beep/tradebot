# PLAN17 result, ETH (scored once)

Plan: research/PLAN17.md (SHA-256 ceee706fb07aac21). Windows closing 2026-10-01 to 2026-10-31. Scored 2026-11-19T11:19:14.551932+00:00.

**Verdict: not testable (fewer than 100 bets or fewer than 15 days with a bet)**

## The rule (cheap side at minutes 10-13, model at least 2 points above the ask)

- Bets 71 on 29 days, wins 2 (win rate 0.028 at an average price 0.034); profit per contract -0.0077 (whole-cent fee -0.0162); day mean -0.0109 (SE 0.0106; whole-cent -0.0194, SE 0.0106); bet-weighted -0.0077 (day-clustered SE 0.0120).
- minute 10: 2 bets, day mean -0.0278 (SE 0.0213); whole-cent fee -0.0360 (SE 0.0200)
- minute 11: 6 bets, day mean -0.0358 (SE 0.0119); whole-cent fee -0.0435 (SE 0.0112)
- minute 12: 18 bets, day mean -0.0220 (SE 0.0046); whole-cent fee -0.0305 (SE 0.0043)
- minute 13: 45 bets, day mean +0.0137 (SE 0.0285); whole-cent fee +0.0049 (SE 0.0286)
- fills with volume in the fill minute: 71 bets, profit per contract -0.0077; median contracts traded there 27238.1 (an upper bound)

## Buy every cheap side at the first eligible minute (baseline, no model)

- 1699 bets, win rate 0.023 at an average price 0.027, profit per contract -0.0056 (whole-cent -0.0142).

## How often cheap sides won (all eligible minutes, descriptive)

Counted: every cheap side with all inputs present, at each decision minute 10-13 (up to 4 per window).

| Ask | Count | Won | Average ask |
|---|---|---|---|
| 1c | 664 | 0.008 | 0.012 |
| 2c | 1009 | 0.018 | 0.020 |
| 3c | 468 | 0.026 | 0.030 |
| 4c | 510 | 0.041 | 0.040 |
| 5c | 187 | 0.032 | 0.048 |

## The model's October calibration (deciles)

| n | Predicted | Actual |
|---|---|---|
| 283 | 0.0063 | 0.0000 |
| 284 | 0.0100 | 0.0211 |
| 284 | 0.0129 | 0.0106 |
| 284 | 0.0155 | 0.0176 |
| 284 | 0.0184 | 0.0141 |
| 283 | 0.0217 | 0.0247 |
| 284 | 0.0254 | 0.0387 |
| 284 | 0.0303 | 0.0282 |
| 284 | 0.0372 | 0.0211 |
| 284 | 0.0533 | 0.0423 |

## Data

- 2936 windows, 0 without a yes/no result, 6 missing Coinbase or Kalshi data, 2 cheap sides without an input; rule fired 74 times, unpaid {'candle does not show 0 < bid < ask': 3}; Coinbase agrees with Kalshi's result in 0.974 of windows.
- The 97%% agreement check is PLAN15's own (plan15.spot_up with PLAN15's reference), as the plan says.
- Windows with a result other than yes or no cannot appear: PLAN15's day files keep only yes/no, so such windows count as missing (the plan's strategy.payout clause has nothing to apply to).
- Windows without floor_strike: 0 (their cheap sides count as missing inputs); baseline first cheap minutes that did not fill: 40.

A pass is a lead on past data, not a working system: it earns a rule in the live paper bot with a forward rule written first. Real money would need a new live.py path that only the user can approve. Not financial advice.
