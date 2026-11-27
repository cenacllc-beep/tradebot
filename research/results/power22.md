# POWER22 (PLAN22 section 7)

Read-only on PLAN18's saved Jun-Aug files; no DVOL, no network. Day values: mean of Brier(RW, PLAN15's 60-minute SD) - Brier(mid) over rows (window, k = 2, 5, 10, 13).

| Asset | Days | Rows | SD of day means | SE (these days) | Stage 2 t (58 df) | Detectable at 80% power, stage 2 (59 days, 2.5%) |
|---|---|---|---|---|---|---|
| BTC | 92 | 34712 | 0.00702 | 0.00073 | 2.002 | 0.00260 |
| ETH | 92 | 34711 | 0.00642 | 0.00067 | 2.002 | 0.00238 |

Coverage:
- BTC: Kalshi days 92 (missing none), composite days 93 (missing none), Coinbase minutes 133903 of 133920; windows 8707, days with 96 windows 79; rows 34712 of 34828 (no result 0, no mid 28, no Coinbase 88); S_0 equals plan15.spot_close(w, 0) in 8707 of 8707 windows.
- ETH: Kalshi days 92 (missing none), composite days 93 (missing none), Coinbase minutes 133902 of 133920; windows 8707, days with 96 windows 79; rows 34711 of 34828 (no result 0, no mid 28, no Coinbase 89); S_0 equals plan15.spot_close(w, 0) in 8707 of 8707 windows.

The mean difference is deliberately not computed for display (PLAN22 section 7).
