# PLAN20: cheap-side reversals on all of Kalshi's 15-minute markets (map, frozen model, forward paper test)

Written 2026-11-25, 23:10 La Paz, at the user's request ("we need a system to understand every detail about the chart to
beat that system ... detect those opportunities and place those bets, based on historical data, chart trends, and time
remaining ... come up with the correct plan"), before any of its data was read. Revised 2026-11-25 23:40 after its
statistics review (agents/statistician.md; CHANGELOG.md), still before any data. Research and paper only. Not
financial advice.

## 0. The question and the honest prior
- Question: is there any corner of Kalshi's 15-minute markets where a cheap side (ask 1-10c) wins more often than its
  price plus the fee, and can it be found in advance from the market's own chart and the time left?
- What we know: PLAN16 (chart-trend rules), PLAN17 (cheap reversals, BTC/ETH) and PLAN18 (GARCH, shift detection) found
  nothing on BTC/ETH; a study of 300,000+ Kalshi contracts (Burgi, Deng and Whelan, CESifo WP 12122) found cheap
  contracts win "far less often than required to break even". The user's own 14 days (Nov 12-25, logs\account.json):
  34 cheap sides held to the end, 2 won where their prices implied about 1.5. **Expected result: no edge shown.**
- **Data already seen:** every BTC/ETH 15-minute window from June to October was read by PLAN15-18, and the idea of
  studying cheap sides came from PLAN17's tables and the user's November fills. So BTC/ETH are fitted on but never
  tested (section 4); the "new data" claim holds only for the other series.
- A cheap side's winning bet pays 10-100x, so results are dominated by rare wins: everything below is sized for that.

## 1. Data (Kalshi only: already approved; no new source)
- **Series:** every Kalshi series whose markets run 15 minutes (series tickers ending "15M"), including series that
  are now inactive, read once from /series and stored with their asset group in research/results/plan20_series.json
  before any outcome is read. Groups: crypto (other than BTC and ETH), metals, energy, FX; a series that fits none goes
  to "other", which is never tested. BTC and ETH form a separate, descriptive row.
- **Markets:** settled yes/no markets closing 2026-06-01 to 2026-10-31 La Paz. Nothing from November on is read for any
  series (KXBTC15M/KXETH15M from Nov 1 are PLAN15's check period; the rest is kept clean).
- **Per market:** result, open and close time, and Kalshi's one-minute candles (yes bid, yes ask, last price, volume,
  open interest). The underlying asset's own price is not used (only BTC/ETH have an approved source). "The chart" is
  the market's own price chart.
- Downloaded on GitHub's runner, in chunks, saved as day files; counts and a format check before any outcome is used.

## 2. Bet opportunities (fixed now)
- **Candle m** (m = 1..14) is the one-minute candle with end_period_ts = open time + 60 x m. A side's **ask** in candle
  m is its closing yes_ask for YES, and 1 - closing yes_bid for NO; its bid is yes_bid for YES and 1 - yes_ask for NO.
  For the NO side every price feature uses this NO series.
- A **chance** is (market, m = 1..13, side) where the side's ask in candle m is 1-10c. Features may carry a quote
  forward from earlier candles; fills never do.
- **Fill:** at the side's ask in candle m+1, used only if that candle exists, shows 0 < bid < ask, and the ask is at
  most 10c; the rule is not re-checked at the fill price. A skipped fill does not use up the side; the next chance is
  judged at m+1.
- **One bet per window per series:** the first chance in the window that passes the rule and fills, scanning minutes
  in order and, within a minute, markets by ticker then YES before NO. Bets per window are reported.
- **Fee (scored):** a $1 bet, as section 6 would place it: C = floor(1.00 / P) contracts at fill price P, fee =
  round-up-to-cent(0.07 x C x P x (1-P)), profit per contract = (payout - P) - fee / C. The rule's threshold uses the
  same fee at the decision ask. A centicent-fee version is reported, descriptive only.
- **Features** (candles up to and including m only): ask; minutes left (15 - m); the side's ask change over the last
  1, 3 and 5 minutes; the window's high and low of the side's ask so far and where the ask sits between them; whether
  the last three candles made higher highs and higher lows (PLAN16 C); volume in the last 3 minutes against the window
  so far; spread; open interest change over the last 3 minutes; hour of day (six 4-hour bands, La Paz) and weekday
  (seven indicators); asset group and series indicators.

## 3. Stage A, the map (June-July; descriptive, cannot change anything)
For every chance in markets closing 2026-06-01 to 2026-07-31: actual win rate against average ask, overall and by asset
group, series, ask band (1-2, 3-5, 6-10c), minutes left (1-4, 5-9, 10-14), last-3-minute move (falling, flat, rising)
and hour band; 95% intervals clustered by day; wins counted. Published in research/results/plan20_map.md.
**The features, groups, rule and threshold are fixed by this text; nothing in the map may change them.** A change needs
a dated amendment before the fit, recorded with the map's SHA-256.

## 4. Stage B, the frozen model (fit on June-July, scored once on August-October)
- **Model:** one ridge logistic regression on all section 2 features of every chance (all groups, BTC/ETH included).
  Continuous features standardised on the fit data; intercept not penalised; strength from 13 log-spaced values
  1e-4 to 1e2, chosen by mean log-loss under 5-fold cross-validation grouped by day inside June-July only. A series
  never seen in June-July gets 0 for its series indicator and keeps its group indicator.
- **Rule:** bet when p >= ask + fee per contract (section 2) + 0.01. Frozen with its coefficients and scaling in
  research/results/plan20_model.json (SHA-256 in CHANGELOG.md) before any August-October outcome is read.
- **Score (once)** on markets closing 2026-08-01 to 2026-10-31. Four tests, one per group (crypto other than BTC/ETH,
  metals, energy, FX). BTC/ETH bets are left out of every statistic, floor and placebo and shown only as a descriptive
  fifth row.
  - Statistic: mean profit per contract after fees.
  - Family level 2.5% one-sided; Holm over the four tests at 0.625%, 0.833%, 1.25% and 2.5%. A group passes at its
    Holm level only if all of these clear it:
    1. the day-clustered t reading;
    2. a 2-day block bootstrap (10,000 draws);
    3. the placebo: 4,000 draws of the same number of bets per day from the same ask band x minute cells, without
       replacement, comparing mean profit after fees; p = (k+1)/(N+1). It tests "better than random cheap sides", not
       "profitable";
    4. an exact Poisson-binomial bound on the number of wins, each bet's null win chance set to break-even (ask plus
       fee per contract). It treats bets as independent, so it is a necessary condition only.
  - Floor: at least 300 bets and 30 days in the group, else "not testable".
- **Also reported (exploratory):** calibration of p by decile; bets, wins and profit by ask band and minutes left;
  wins per group; the centicent-fee version.

## 5. Stage C, forward paper test (only for a group that passed)
- The frozen rule runs on paper every minute on that group's live 15-minute markets (an extension of research/live15.py
  with its own ledger; never imports live.py, never calls an order endpoint), from the first full day after the pass,
  for 42 days. The decision uses the live quote at each minute's end; the fill is the live ask about 60 seconds later,
  at most 10c, $1 bets and the section 2 fee.
- Verdict at day 42, once: the same statistic, t reading, block bootstrap and Poisson-binomial bound at 2.5% one-sided
  (Holm across groups if two or more are tested); at least 300 bets. No look before day 42 except counts.

## 6. Real money (not part of this plan)
- Only after a stage C pass, and only with the user's explicit approval of a new live.py path: $1 per bet, its own daily
  and total caps inside live.MAX_AT_RISK, the kill switch and every existing lock, and its own code review. Raising bet
  sizes would be a separate decision after real results, never before.

## 7. Power (stated before the data)
For a 3c contract one bet's profit has a standard deviation of about 17c. Seeing +1c a contract (wins at 4% where the
price says 3%) at the 0.625% line with 80% power needs about 3,300 bets in a group; +3c (doubling the win rate) about
400. Day clustering and requiring all four checks lower power further, and small groups may not reach the floor. Ridge
pulls predictions toward the average cheap-side win rate, so the rule may bet mostly the cheapest asks. Only very large
edges can pass.
- Paper fills are an upper bound: candles show no depth, and a $1 bet at 2-3c is 33-50 contracts.

## 8. Freeze
Frozen after its statistics review; its SHA-256 goes into CHANGELOG.md. research/plan20.py is written after the freeze,
code-reviewed and frozen before the first download. Where code and text differ, the text wins, by an amendment before
any number is computed.
