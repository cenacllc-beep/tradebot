# PLAN17 result, BTC (scored once)

Plan: research/PLAN17.md (SHA-256 ceee706fb07aac21). Windows closing 2026-10-01 to 2026-10-31. Scored 2026-11-19T11:18:21.434476+00:00.

**Verdict: not testable (fewer than 100 bets or fewer than 15 days with a bet)**

## The rule (cheap side at minutes 10-13, model at least 2 points above the ask)

- Bets 65 on 28 days, wins 2 (win rate 0.031 at an average price 0.020); profit per contract +0.0097 (whole-cent fee +0.0009); day mean +0.0047 (SE 0.0192; whole-cent -0.0040, SE 0.0191); bet-weighted +0.0097 (day-clustered SE 0.0199).
- minute 10: 2 bets, day mean -0.0112 (SE 0.0006); whole-cent fee -0.0205 (SE 0.0005)
- minute 11: 1 bets, day mean - (SE -); whole-cent fee - (SE -)
- minute 12: 12 bets, day mean +0.0591 (SE 0.0854); whole-cent fee +0.0507 (SE 0.0853)
- minute 13: 50 bets, day mean -0.0016 (SE 0.0164); whole-cent fee -0.0104 (SE 0.0164)
- fills with volume in the fill minute: 65 bets, profit per contract +0.0097; median contracts traded there 417921.4 (an upper bound)

## Buy every cheap side at the first eligible minute (baseline, no model)

- 1666 bets, win rate 0.025 at an average price 0.025, profit per contract -0.0016 (whole-cent -0.0102).

## How often cheap sides won (all eligible minutes, descriptive)

Counted: every cheap side with all inputs present, at each decision minute 10-13 (up to 4 per window).

| Ask | Count | Won | Average ask |
|---|---|---|---|
| 1c | 648 | 0.008 | 0.012 |
| 2c | 994 | 0.017 | 0.020 |
| 3c | 532 | 0.024 | 0.030 |
| 4c | 498 | 0.034 | 0.040 |
| 5c | 207 | 0.063 | 0.048 |

## The model's October calibration (deciles)

| n | Predicted | Actual |
|---|---|---|
| 287 | 0.0056 | 0.0139 |
| 288 | 0.0090 | 0.0035 |
| 288 | 0.0115 | 0.0069 |
| 288 | 0.0142 | 0.0243 |
| 288 | 0.0168 | 0.0174 |
| 288 | 0.0199 | 0.0208 |
| 288 | 0.0237 | 0.0347 |
| 288 | 0.0282 | 0.0347 |
| 288 | 0.0346 | 0.0243 |
| 288 | 0.0500 | 0.0451 |

## Data

- 2936 windows, 0 without a yes/no result, 4 missing Coinbase or Kalshi data, 0 cheap sides without an input; rule fired 71 times, unpaid {'candle does not show 0 < bid < ask': 6}; Coinbase agrees with Kalshi's result in 0.972 of windows.
- The 97%% agreement check is PLAN15's own (plan15.spot_up with PLAN15's reference), as the plan says.
- Windows with a result other than yes or no cannot appear: PLAN15's day files keep only yes/no, so such windows count as missing (the plan's strategy.payout clause has nothing to apply to).
- Windows without floor_strike: 0 (their cheap sides count as missing inputs); baseline first cheap minutes that did not fill: 38.

A pass is a lead on past data, not a working system: it earns a rule in the live paper bot with a forward rule written first. Real money would need a new live.py path that only the user can approve. Not financial advice.
