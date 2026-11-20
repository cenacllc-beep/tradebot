# PLAN18 result (scored once)

Plan: research/PLAN18.md (SHA-256 717909c8aaa78c8d). Windows closing 2026-08-01 to 2026-08-31. Scored 2026-11-20T06:59:55.921410+00:00.

**Verdict: no edge shown**

Amendments in force: A1 (research/results/plan18_amendments.json).

| Test | Signals | Days | Filled | Win rate | Avg price | Profit / contract (whole-cent) | Day mean (SE) | t | p | Holm level | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC G composite + volatility model | 4704 | 31 | 4676 | 0.324 | 0.331 | -0.0178 (-0.0231) | -0.0148 (0.0070) | -2.11 | 0.9991 | 0.00417 | no edge shown |
| BTC M learned model | 76 | 23 | 76 | 0.513 | 0.604 | -0.1017 (-0.1071) | -0.0827 (0.0667) | -1.24 | - | 0.00625 | not testable (fewer than 200 signals or fewer than 20 days with a signal) |
| BTC R shift detector | 7 | 6 | 7 | 0.714 | 0.629 | +0.0721 (+0.0686) | +0.0745 (0.2085) | 0.36 | - | 0.00833 | not testable (fewer than 200 signals or fewer than 20 days with a signal) |
| ETH G composite + volatility model | 5381 | 31 | 5369 | 0.255 | 0.264 | -0.0188 (-0.0243) | -0.0199 (0.0059) | -3.35 | 1.0000 | 0.00500 | no edge shown |
| ETH M learned model | 104 | 30 | 104 | 0.635 | 0.541 | +0.0804 (+0.0755) | +0.0529 (0.0425) | 1.24 | - | 0.01250 | not testable (fewer than 200 signals or fewer than 20 days with a signal) |
| ETH R shift detector | 2 | 2 | 2 | 1.000 | 0.735 | +0.2514 (+0.2450) | +0.2514 (0.0242) | 10.41 | - | 0.02500 | not testable (fewer than 200 signals or fewer than 20 days with a signal) |

## By minute, delayed fills, power (descriptive)

- BTC G: k=2 -0.0257 (SE 0.0159; whole-cent -0.0298) n=1074, k=5 -0.0011 (SE 0.0126; whole-cent -0.0056) n=1245, k=10 -0.0143 (SE 0.0094; whole-cent -0.0196) n=1357, k=13 -0.0150 (SE 0.0092; whole-cent -0.0222) n=1000; delayed k+3 -0.0192 (3665), k+5 -0.0231 (2319); edge needed for 80% power at Holm's first level, from the observed SE: +0.0257
- BTC M: k=2 -0.1573 (SE 0.3269; whole-cent -0.1667) n=3, k=5 +0.1114 (SE 0.0813; whole-cent +0.1058) n=16, k=10 -0.2925 (SE 0.0713; whole-cent -0.2965) n=28, k=13 +0.0058 (SE 0.0959; whole-cent -0.0003) n=29; delayed k+3 -0.1075 (46), k+5 +0.0180 (19); edge needed for 80% power at Holm's first level, from the observed SE: +0.2494
- BTC R: k=5 - (SE -; whole-cent -) n=1, k=10 +0.1853 (SE 0.1237; whole-cent +0.1817) n=4, k=13 -0.1922 (SE 0.7047; whole-cent -0.1950) n=2; delayed k+3 +0.1475 (5), k+5 +0.5832 (1); edge needed for 80% power at Holm's first level, from the observed SE: +1.0550
- ETH G: k=2 -0.0369 (SE 0.0124; whole-cent -0.0414) n=1302, k=5 -0.0311 (SE 0.0104; whole-cent -0.0358) n=1459, k=10 -0.0149 (SE 0.0095; whole-cent -0.0204) n=1508, k=13 +0.0015 (SE 0.0063; whole-cent -0.0063) n=1100; delayed k+3 -0.0224 (4261), k+5 -0.0237 (2761); edge needed for 80% power at Holm's first level, from the observed SE: +0.0218
- ETH M: k=2 +0.1526 (SE 0.0840; whole-cent +0.1484) n=22, k=5 +0.0990 (SE 0.0850; whole-cent +0.0944) n=28, k=10 -0.0628 (SE 0.1040; whole-cent -0.0675) n=23, k=13 +0.0725 (SE 0.0972; whole-cent +0.0669) n=31; delayed k+3 +0.0595 (73), k+5 +0.1069 (50); edge needed for 80% power at Holm's first level, from the observed SE: +0.1562
- ETH R: k=10 +0.2514 (SE 0.0242; whole-cent +0.2450) n=2; delayed k+3 +0.2838 (2), k+5 - (0); edge needed for 80% power at Holm's first level, from the observed SE: +1.8651

## Coinbase in place of the composite (descriptive)

- BTC G: 4630 signals, 4605 filled, day mean -0.0144 (SE 0.0075), win rate 0.300
- BTC M: 59 signals, 59 filled, day mean +0.0654 (SE 0.0534), win rate 0.661
- BTC R: 7 signals, 7 filled, day mean +0.2461 (SE 0.1333), win rate 0.714
- ETH G: 5399 signals, 5383 filled, day mean -0.0222 (SE 0.0059), win rate 0.244
- ETH M: 78 signals, 78 filled, day mean +0.0481 (SE 0.0529), win rate 0.538
- ETH R: 2 signals, 2 filled, day mean +0.2514 (SE 0.0242), win rate 1.000

## Q1 and data (descriptive)

- BTC: composite agrees with Kalshi's result in 0.9544 of 2938 windows, Coinbase in 0.9394; they differ in 74, composite right 59, Coinbase right 15 (McNemar p 0.0000). The minute-15 close is a proxy for the final-minute average.
  GARCH omega 0.1334 alpha 0.0673 beta 0.9327 (integrated: False; Coinbase's integrated: True); M slopes [0.4614, 2.2244, 0.0112, 0.0268, -0.0064, -0.0534] (the Coinbase gap is partly mechanical: Coinbase is one of the composite's exchanges); missing share 0.012; inputs missing {'G': 12, 'R': 0, 'M': 12}; exchange presence by month {'2026-05': {'bitstamp': 1440, 'coinbase': 1436, 'cryptocom': 1440, 'bullish': 1087, 'kraken': 1437}, '2026-06': {'bitstamp': 43200, 'coinbase': 43188, 'cryptocom': 43200, 'bullish': 39381, 'kraken': 43183}, '2026-07': {'bitstamp': 44640, 'coinbase': 44639, 'cryptocom': 44640, 'bullish': 34701, 'kraken': 44610}, '2026-08': {'bitstamp': 44640, 'coinbase': 44640, 'cryptocom': 44640, 'bullish': 33158, 'kraken': 44592}}.
- ETH: composite agrees with Kalshi's result in 0.9516 of 2934 windows, Coinbase in 0.9451; they differ in 55, composite right 37, Coinbase right 18 (McNemar p 0.0145). The minute-15 close is a proxy for the final-minute average.
  GARCH omega 0.4545 alpha 0.0856 beta 0.9144 (integrated: True; Coinbase's integrated: False); M slopes [0.491, 2.1801, 0.0658, -0.0107, 0.0084, -0.0437] (the Coinbase gap is partly mechanical: Coinbase is one of the composite's exchanges); missing share 0.012; inputs missing {'G': 28, 'R': 0, 'M': 28}; exchange presence by month {'2026-05': {'bitstamp': 1440, 'coinbase': 1436, 'cryptocom': 1440, 'bullish': 755, 'kraken': 1414}, '2026-06': {'bitstamp': 43200, 'coinbase': 43188, 'cryptocom': 43200, 'bullish': 36297, 'kraken': 42825}, '2026-07': {'bitstamp': 44640, 'coinbase': 44638, 'cryptocom': 44640, 'bullish': 33828, 'kraken': 44192}, '2026-08': {'bitstamp': 44640, 'coinbase': 44640, 'cryptocom': 44640, 'bullish': 31135, 'kraken': 44068}}.

A pass is a lead on past data, not a working system: it earns a rule in the live paper bot with a forward rule written first. Real money would need a new live.py path that only the user can approve. Not financial advice.
