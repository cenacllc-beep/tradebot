# PLAN16 result (scored once)

Plan: research/PLAN16.md (SHA-256 5e82af19f0dda166). Windows closing 2026-09-01 to 2026-10-31. Scored 2026-11-19T11:18:22.035577+00:00.

**Verdict: no edge shown**

| Test | Signals | Days | Filled | Win rate | Avg price | Profit / contract | Day mean (SE) | t | p | Holm level | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC A recent volatility | 6637 | 61 | 6637 | 0.521 | 0.521 | -0.0160 | -0.0177 (0.0075) | -2.35 | 0.9891 | 0.00417 | no edge shown |
| BTC B choosier (10 points) | 1233 | 61 | 1233 | 0.484 | 0.472 | -0.0044 | -0.0107 (0.0165) | -0.65 | 0.7413 | 0.00357 | no edge shown |
| BTC C trend (3 candles) | 3373 | 61 | 3373 | 0.629 | 0.629 | -0.0191 | -0.0180 (0.0075) | -2.39 | 0.9900 | 0.00500 | no edge shown |
| BTC D order flow | 542 | 61 | 542 | 0.284 | 0.324 | -0.0591 | -0.0830 (0.0229) | -3.63 | 1.0000 | 0.02500 | no edge shown |
| ETH A recent volatility | 6241 | 61 | 6241 | 0.448 | 0.450 | -0.0182 | -0.0154 (0.0066) | -2.35 | 0.9952 | 0.00833 | no edge shown |
| ETH B choosier (10 points) | 1034 | 61 | 1034 | 0.327 | 0.324 | -0.0122 | +0.0002 (0.0132) | 0.02 | 0.4928 | 0.00313 | no edge shown |
| ETH C trend (3 candles) | 3518 | 61 | 3518 | 0.622 | 0.630 | -0.0264 | -0.0265 (0.0081) | -3.28 | 0.9991 | 0.01250 | no edge shown |
| ETH D order flow | 1324 | 61 | 1324 | 0.419 | 0.424 | -0.0241 | -0.0306 (0.0122) | -2.50 | 0.9924 | 0.00625 | no edge shown |

## Per minute and delayed fills (descriptive)

- BTC A recent volatility: by minute k=2 -0.0136 (1903), k=5 -0.0160 (2406), k=10 -0.0178 (2328); fills 3 and 5 minutes later: k+3 -0.0178, k+5 -0.0178
- BTC B choosier (10 points): by minute k=2 +0.0303 (253), k=5 +0.0096 (362), k=10 -0.0269 (618); fills 3 and 5 minutes later: k+3 -0.0056, k+5 +0.0074
- BTC C trend (3 candles): by minute k=2 -0.0312 (1622), k=5 +0.0008 (1146), k=10 -0.0245 (605); fills 3 and 5 minutes later: k+3 -0.0218, k+5 -0.0252
- BTC D order flow: by minute k=2 -0.0646 (327), k=5 -0.0460 (200), k=10 -0.1143 (15); fills 3 and 5 minutes later: k+3 -0.0729, k+5 -0.0567
- ETH A recent volatility: by minute k=2 -0.0178 (1826), k=5 -0.0193 (2244), k=10 -0.0174 (2171); fills 3 and 5 minutes later: k+3 -0.0173, k+5 -0.0154
- ETH B choosier (10 points): by minute k=2 -0.0738 (130), k=5 +0.0152 (252), k=10 -0.0105 (652); fills 3 and 5 minutes later: k+3 +0.0035, k+5 -0.0054
- ETH C trend (3 candles): by minute k=2 -0.0317 (1662), k=5 -0.0209 (1172), k=10 -0.0230 (684); fills 3 and 5 minutes later: k+3 -0.0250, k+5 -0.0245
- ETH D order flow: by minute k=2 -0.0190 (749), k=5 -0.0360 (470), k=10 -0.0078 (105); fills 3 and 5 minutes later: k+3 -0.0235, k+5 -0.0244

## Reference (not a test): PLAN15's own rule on the same windows

- BTC: 6313 signals, 6313 filled, profit per contract -0.0181, win rate 0.466 at an average price 0.469.
- ETH: 5980 signals, 5980 filled, profit per contract -0.0167, win rate 0.381 at an average price 0.382.

## Data

- BTC: 5784 windows, 0 without a yes/no result, 10 missing Coinbase or candles, 0 missing Kalshi trades; Coinbase agrees with Kalshi's result in 0.972 of windows.
- ETH: 5784 windows, 0 without a yes/no result, 15 missing Coinbase or candles, 0 missing Kalshi trades; Coinbase agrees with Kalshi's result in 0.974 of windows.

A pass is a lead on past data, not a working system: it earns a place in the live paper bot with a forward rule written first. Real money would need a new live.py path that only the user can approve. Not financial advice.
