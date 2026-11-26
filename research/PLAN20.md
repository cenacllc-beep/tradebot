# PLAN20: cheap-side reversals on all of Kalshi's 15-minute markets (map, frozen model, forward paper test)

Written 2026-11-25, 23:10 La Paz, at the user's request ("we need a system to understand every detail about the chart to
beat that system ... detect those opportunities and place those bets, based on historical data, chart trends, and time
remaining ... come up with the correct plan"), before any of its data was read. Research and paper only. Not financial
advice. Draft: frozen only after its statistics review.

## 0. The question and the honest prior
- Question: is there any corner of Kalshi's 15-minute markets where a cheap side (ask 1-10c) wins more often than its
  price plus the fee, and can it be found in advance from the market's own chart and the time left?
- What we know: PLAN16 (chart-trend rules), PLAN17 (cheap reversals, BTC/ETH) and PLAN18 (GARCH, shift detection) found
  nothing on BTC/ETH; a study of 300,000+ Kalshi contracts (Burgi, Deng and Whelan, CESifo WP 12122) found cheap
  contracts win "far less often than required to break even". The user's own 14 days (Nov 12-25, logs\account.json):
  34 cheap sides held to the end, 2 won where their prices implied about 1.5. So the default is a loss; any edge must
  come from a narrow, predictable corner. **Expected result: no edge shown.**
- A cheap side's winning bet pays 20-100x, so results are dominated by rare wins: everything below is sized for that.

## 1. Data (Kalshi only: already approved; no new source)
- **Series:** every Kalshi series whose markets run 15 minutes (tickers ending "15M"; list read once from /series and
  stored before any outcome is read), e.g. BTC, ETH, SOL, XRP, DOGE, BNB, HYPE, gold, silver, platinum, palladium, WTI,
  natural gas, FX pairs.
- **Markets:** settled yes/no markets closing 2026-06-01 to 2026-10-31 La Paz. KXBTC15M and KXETH15M windows from
  2026-11-01 on are never read (PLAN15's check period). Nothing from November on is read for any series (kept clean for
  section 5).
- **Per market:** result, open and close time, and Kalshi's one-minute candles (yes bid, yes ask, last price, volume,
  open interest). The underlying asset's own price is NOT used (only BTC/ETH have an approved source; others would need
  the user's approval). "The chart" here is the market's own price chart, which already reflects the underlying.
- Downloaded on GitHub's runner, in chunks, saved as day files; counts and a format check before any outcome is used.

## 2. Bet opportunities (fixed now)
- A **chance** is (market, minute m = 1..13 after open, side) where the side's ask at the end of minute m is 1-10c.
  Bought at the ask one minute later (minute m+1's ask; skipped if over 10c or missing), one contract, Kalshi's taker fee
  (round up(0.07 x C x P x (1-P)) to the centicent). At most one bet per market and side: the first chance that passes
  the rule.
- **Features** (from candles up to the end of minute m only): ask; minutes left; side price change over the last 1, 3
  and 5 minutes; the window's high and low of the side's price so far and where the ask sits between them; whether the
  last three candles made higher highs and higher lows (PLAN16 C); volume in the last 3 minutes against the window so
  far; spread; open interest change; hour of day (La Paz) and weekday; the series' asset group (crypto, metals, energy,
  FX). No feature uses anything after minute m.

## 3. Stage A, the map (June-July; descriptive, cannot pass anything)
For every chance in markets closing 2026-06-01 to 2026-07-31: actual win rate against average ask, overall and by asset
group, series, ask band (1-2, 3-5, 6-10c), minutes left (1-4, 5-9, 10-14), last-3-minute move (falling, flat, rising)
and hour band; with 95% intervals clustered by day. Published in research/results/plan20_map.md before stage B is fit.

## 4. Stage B, the frozen model (fit on June-July, scored once on August-October)
- One ridge logistic regression on all section 2 features (asset group and series as indicators; ridge strength chosen
  by 5-fold cross-validation grouped by day inside June-July only), giving the chance's win probability p.
- **Rule:** bet when p >= ask + fee per contract + 0.01. Frozen with its coefficients in
  research/results/plan20_model.json (SHA-256 in CHANGELOG.md) before any August-October outcome is read.
- **Score (once)** on markets closing 2026-08-01 to 2026-10-31. BTC/ETH windows in that period were read by PLAN16-18,
  so they are scored but reported separately and cannot carry a pass alone. Four tests, one per asset group:
  - statistic: mean profit per bet after fees;
  - pass at 1.25% one-sided (Holm over the four, starting at 0.625%) only if all of: the day-clustered t reading, a
    2-day block bootstrap, a placebo (bets drawn at random among chances with the same ask band and minute, 1,000
    draws) and an exact Poisson-binomial bound on the number of wins (each bet's win chance = its ask) all clear it;
  - floor: at least 300 bets and 30 days in the group, else "not testable".
- Also reported (exploratory): calibration of p (predicted vs actual by decile), profit by ask band and minutes left.

## 5. Stage C, forward paper test (only for a group that passed)
- The frozen rule runs live on paper every minute on that group's 15-minute markets (an extension of research/live15.py
  with its own ledger; never imports live.py, never calls an order endpoint), from the first full day after the pass,
  for 42 days.
- Verdict at day 42, once: the same statistic, t reading, block bootstrap and Poisson-binomial bound at 2.5% one-sided;
  at least 300 bets. No look before day 42 except counts.

## 6. Real money (not part of this plan)
- Only after a stage C pass, and only with the user's explicit approval of a new live.py path: $1 per bet, its own daily
  and total caps inside live.MAX_AT_RISK, the kill switch and every existing lock, and its own code review. Raising bet
  sizes would be a separate decision after real results, never before.

## 7. Power (stated before the data)
For a 3c contract, one bet's profit has a standard deviation of about 17c. Seeing a real edge of +1c a contract (wins at
4% where the price says 3%) at the pass line with 80% power needs about 3,300 bets in a group, more with day clustering;
+3c needs about 400. So the test can see only large edges; small ones will read FAIL or "not testable".

## 8. Freeze
Frozen after its statistics review (agents/statistician.md); its SHA-256 goes into CHANGELOG.md. research/plan20.py is
written after the freeze, code-reviewed and frozen before the first download. Where code and text differ, the text
wins, by an amendment before any number is computed.
