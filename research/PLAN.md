# Backtest plan: rain (written 2026-10-14 02:05 local, BEFORE any backtest data was fetched or scored)

Purpose: answer the core question (does a forecast beat Kalshi's prices on daily rain markets?) on past data,
instead of waiting for the 13-day live test. Research only: it does not change the live bot, v3, the limits or the
gate. Nothing in this plan may be changed after the holdout is scored; a changed method is a new, separately
labelled analysis and its result does not replace this one.

## Data (all public, read-only)
- Markets and outcomes: every settled Kalshi KXRAIN market (first market day 2026-07-15). Outcome = Kalshi's own
  result. Station = the CLI code in the market's rules ("at CLIxxx"). Duplicate (date, station) pairs: keep the
  ticker with the most volume.
- Market price at scan time: Kalshi minute candles; the last candle ending at or before 00:55 UTC on the market
  day (= 8:55 PM the evening before in La Paz time, the live bot's scan time). Mid = (bid + ask) / 2. Usable only
  if 0 <= bid < ask <= 1 and ask - bid <= 0.06 (the bot's spread filter).
- Forecast at scan time: National Blend of Models station guidance (NBS) archived by the Iowa Environmental
  Mesonet (IEM), the 18 UTC run of the day before (issued about 7 hours before the scan; the next run is not out
  until after the scan). Four 6-hour precipitation probabilities (P06) ending 12Z, 18Z on the day and 00Z, 06Z
  the next day, and the matching 6-hour amounts (Q06). Any missing value -> market skipped (no fallback).
- Training outcomes: NWS daily climate reports (CLI) archived by IEM. Yes = precipitation > 0; trace (T) and
  missing (M) count as 0, as in Kalshi's rules.

## Split
- Training: 2025-07-01 to 2026-06-30, CLI outcomes, no market prices involved.
- Holdout: all settled KXRAIN market days (2026-07-15 onward). Scored once.

## Forecasts compared (all are P(YES) at scan time)
- M: the market mid.
- R (raw, v3's rule on station data): (max(P06) + 1 - prod(1 - P06)) / 2.
- C (calibrated, the "v4 candidate"): logistic regression fitted on the training period only:
  logit(P) = a + b*logit(R) + c*log(1 + 100*total Q06 in inches), one set of coefficients for all stations,
  probabilities clipped to [0.01, 0.99].
- B: the live bot's blend, 0.5*C + 0.5*M.

## Measures (holdout only)
1. Brier score of R, C and B vs M. Difference per market, averaged within each market day (cities on one day share
   weather), standard error from the day averages. "Clear" = forecast better by at least 2 standard errors (the
   same rule as the live gate). Calibration table by probability bucket.
2. Paper trading, one contract per signal, the live bot's rule: fair = B; buy YES at the ask if fair - ask >= 0.08,
   buy NO at 1 - bid if (1 - fair) - (1 - bid) >= 0.08. Taker fee per contract = 0.07*p*(1-p) rounded up to the
   cent. Report trades, win rate, net per contract and in total, with a day-clustered standard error.
   Limit-order variant: bid 1 cent better than the best bid (or join it when the spread is 1 cent), cancelled at
   the start of the market's day (00:00 local standard time); filled only if a whole minute after the order shows
   a trade or an offer at our price (strictly through it when joined). No maker fee.
3. Price moves: mid at the start of the market's day minus mid at scan, signed toward C.
4. Data check: agreement between CLI outcomes and Kalshi results on the holdout (not used for fitting).

## What counts as an edge (decided now)
Edge demonstrated only if BOTH: C (or B) beats M on Brier by a clear margin, AND the taker or limit-order paper
P&L is above zero by at least 2 day-clustered standard errors after fees. Otherwise: no edge demonstrated on past
data. Per-city results are shown for information only and are not used to pick cities.

## Known limits
- 85 market days; cities on a day are correlated, so the effective sample is far smaller than 2,100 markets.
- Four 6-hour periods cover 06Z-06Z, 0-2 hours off the local-standard day for Eastern, Mountain and Pacific cities.
- Fills are judged from minute candles without queue sizes; taker fills assume the quoted size was available.
- The market at 8:55 PM may already include newer information (hourly models) than the 18Z NBS run.

## Amendment 1 (2026-10-14 02:20 local, before any NBS data was fetched or anything was scored)
IEM's archive labels the evening NBS cycle 19 UTC through 2025 and 18 UTC in 2026 (the probe of Aug 2026 showed
00/06/12/18 UTC; Aug 2025 shows 01/07/13/19 UTC). Both are issued hours before the 00:55 UTC scan, so "the
evening run" means whichever of the two exists for the day before (the later one if both do). Nothing else changes.

## Result (scored once, 2026-10-14 03:04 local): no edge demonstrated on past data
See results/rain_backtest.md. 1,711 markets over 81 market days. Market Brier 0.0730; calibrated airport forecast
0.0740 (not better); 50/50 blend 0.0711 (better by 0.0026, noise 0.0039: not clear). Paying the ask: +6.9 cents a
contract over 125 trades (not clear). Limit orders: +9.6 cents a contract over 153 fills (clear on its own, 2.6
standard errors), but the rule needed both, so the verdict stands. Post-hoc checks, labelled as such:
results/rain_backtest_posthoc.md.

## Forward test of the one lead (written 2026-10-14 03:10 local, before any forward data exists)
The limit-order result is one positive out of several things measured, so it is a lead, not evidence. It is now
replicated forward with exactly the past-data rules, on fresh markets only: the frozen model (results/rain_model.json),
the quote at the evening scan, fair = 0.5 * airport forecast + 0.5 * mid, 8-point edge, one contract per signal, limit
order 1 cent better than the best bid (or joined), cancelled when the market's day starts, the same fill rule, no
maker fee; the paying-the-ask version alongside. shadow.py logs the forecast at each evening scan (v4_obs) and works
out the orders at each settle from Kalshi's minute candles (v4_paper). Nothing is ever placed.
Judgement: after 60 market days with signals (the past data suggests about 2 fills a day, and fewer days would not
be enough to tell a 10-cent edge from luck): confirmed only if the limit-order P&L per market day is above zero by
at least 2 day-clustered standard errors. Interim numbers are shown but not acted on, and nothing here changes the
live bot, v3 or the gate.

## Forward-test amendment (2026-10-14 12:50 local, after an independent statistical review; no forward result exists yet)
The review found the 60-day judgement underpowered (about a coin flip even if the past +9.6 cents were real, about 20%
for a more realistic 5 cents) and the test statistic not yet coded. Changed before any forward data, so nothing is
being tuned to a result:
1. Market days: every market day with at least one rain market logged in the quote window below counts, with zero
   profit on days without fills (the same denominator as the past test).
2. Quote window: only forecasts logged between 00:50 and 01:30 UTC (the 8:55 PM scan) count. A forecast logged at any
   other time (a manual or make-up scan) is kept but marked as outside the test.
3. Interim look at 60 market days, for futility only: stop if the mean limit-order profit per market day is zero or
   below. No "confirmed" verdict is possible at 60 days.
4. Final verdict at 110 market days: confirmed only if the mean limit-order profit per market day is above zero AND
   the 95% interval from a weekly block bootstrap (blocks of 7 consecutive market days, 5,000 resamples, fixed seed)
   lies above zero. Otherwise not confirmed, and the lead is dropped (CLAUDE.md section 11a).
5. Reading the past result: +9.6 cents was the best of several looks at one signal; after allowing for the number of
   tests it is at best a 3-6 cent hypothesis. Paper fills are an upper bound on real fills, so even a confirmed result
   would justify only a tiny, separately approved live test of execution, not a strategy.
shadow.py prints the running numbers in the same form (V4 FORWARD line); research/placebo.py holds post-hoc checks
of the past result (labelled as such).
