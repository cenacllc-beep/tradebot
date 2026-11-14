# PLAN16: four ways to make the 15-minute bets more accurate, tested once on past windows

Written 2026-11-13, 22:00 La Paz, at the user's request ("How can we intelligently make those bets?", then "Go. Make
no mistakes" to the plan offered in so many words), before any of its numbers were computed. Research only, paper
only. Not financial advice.

## 0. Honest prior, stated before any data
- Kalshi's 15-minute BTC and ETH markets are priced by fast, well-equipped traders. Over minutes, the direction of
  bitcoin is close to a coin flip, and simple chart patterns are widely watched. The fee needs about 52% wins at 50c.
- **Expected result: no rule shows an edge.** "No edge shown" is a useful answer that costs nothing.
- **What had been seen before this was written:** the live paper bot's (PLAN15F) first 5 decisions with a price, from
  8:46 to 9:32 PM on Nov 13 (4 paper bets, 2 settled, both lost); they prompted the user's question, and the
  thresholds below (10 points, 20-80c, 0.4, 3 candles) are round numbers chosen without regard to them. One window of
  one PLAN15 day file (BTC, the first window of Sep 7) was printed to learn the file format, including its prices and
  result; a reviewer opened the same file. PLAN15's logistic model has not been fitted and none of PLAN15's results
  have been computed.
- The aim is accuracy against the price (profit after fees per contract), not a higher win rate: buying favourites
  wins often and still loses money.

## 1. What is already settled (no test needed)
- **How Kalshi settles** (read from the markets' own rules text, stored by PLAN15 on 2026-11-13): Yes if the simple
  average of the sixty seconds of CF Benchmarks' BRTI before the close is at least the same average before the open.
  PLAN15's model already allows for the closing average (time left T - k - 0.5 minutes). The reference price is the
  market's floor_strike. Coinbase is a stand-in for BRTI; how often its up-or-down agrees with Kalshi's result is
  reported (PLAN15's 97% check is reused).
- **Seeing the price sooner:** the live paper bot (PLAN15F) now reads each minute's price 3-10 s after the minute
  ends (fixed 2026-11-13, r92). The live Coinbase ticker the user approved is kept for later; it is not needed here.

## 2. The four rules (fixed now; nothing is fitted)
All four are decided at minutes k = 2, 5 and 10 of each window, use only what is known at the close of minute k, and
are paid exactly as PLAN15 pays: one contract at the ask on the chosen side at the close of minute k + 1 (one full
minute of delay), fee round up(multiplier x 0.07 x P x (1 - P)) to the cent, no trade when that ask is missing or
$1.00 or the candle does not show 0 < bid < ask. YES ask = the candle's yes ask; NO ask = 1 - the candle's yes bid.
"RW" is PLAN15's random-walk chance p_up = Phi( ln(S_k / S_0) / (sigma x sqrt(T - k - 0.5)) ), S_0 = floor_strike,
S_k = Coinbase's close of minute k, T = 15.

- **A. Recent volatility.** RW with sigma = the standard deviation (n - 1) of the 15 one-minute log returns that end
  at minute k (closes of minutes k - 15 to k, Coinbase), instead of PLAN15's 60 minutes before the window. Signal:
  RW_A minus the ask (at minute k) on one side at least 4 points (YES: RW_A - YES ask; NO: (1 - RW_A) - NO ask).
- **B. Choosier.** PLAN15's own RW (60-minute sigma), but a signal only when RW minus the ask on one side is at least
  10 points (PLAN15 uses 4), with the edges defined as in A.
- **C. Trend (the user's video, 2026-11-13).** Using Coinbase's one-minute candles k - 2, k - 1 and k: "up" when each
  high and each low is above the one before (H_k > H_k-1 > H_k-2 and L_k > L_k-1 > L_k-2), "down" when each is below.
  Signal: bet that side when its ask at minute k is from 20c to 80c. Otherwise no signal.
- **D. Order flow.** Kalshi's public trades in the market whose time is after the close of minute k - 3 (and after
  the window's open_time) and at or before the close of minute k: imbalance I = (contracts bought by YES takers -
  contracts bought by NO takers) / all contracts, fractional counts summed. Needs at least 50 contracts (a floor that
  will almost never bind on these markets). A window whose trade fetch is incomplete has no D signal and counts as
  missing. Signal: YES when I >= +0.4, NO when I <= -0.4, when that side's ask at
  minute k is from 20c to 80c.

- **No signal** when the minute-k candle is crossed or locked (bid >= ask) or missing, when sigma is 0, or when a
  Coinbase minute the rule needs is missing (A: closes k - 15 to k; B and RW: the close of minute k and PLAN15's
  60-minute sigma; C: candles k - 2 to k); each such case is counted as missing. With an uncrossed book at most one
  side can signal.
- Results other than yes or no (scalar, void) are settled by the project's rule (strategy.payout / settled_pnl).

## 3. Data and periods
- **Windows:** KXBTC15M and KXETH15M markets closing 2026-09-01 to 2026-10-31 (UTC): PLAN15's find period, read from
  PLAN15's saved day files (market records, results, Kalshi minute candles), complete days only. PLAN15's check period
  (Nov-Dec) is not read. PLAN15 itself is not changed and its looks are unaffected: nothing here is fitted, and
  PLAN15's models are fitted on these days for a different question.
- **Coinbase:** one-minute BTC-USD and ETH-USD candles for every minute from 75 minutes before the first window to the
  last close (approved 2026-11-12), read with PLAN15's own functions; used in memory to work out each window's inputs
  and never written to disk (as in PLAN15). Only the derived inputs per window and minute are saved.
- **Kalshi trades:** each window's public trades with taker side and count, read with PLAN15's fetch_trades; only the
  imbalance and the contract count per window and minute are saved.
- Saved under research/results/plan16/ on the GitHub runner (public data only).

## 4. Scoring (once)
- **Unit:** the UTC day of the window's close. For each rule and asset, a day's value is the mean profit per contract
  over all its signals that day (all three minutes together); days without a signal drop out; each day counts once.
- **Tests:** 4 rules x 2 assets = 8 tests, one family, one-sided (profit above zero), Holm at a family level of 2.5%.
- **One p per test.** Each test's p is the largest of: the one-sided day-mean t p-value; the bootstrap p (the share of
  draws at or below zero); and the placebo p, (1 + the number of draws at least as profitable) / (1 + 2,000). Holm
  orders the 8 tests by that p. A not-testable test stays in the family (m = 8) and counts as not passed. The smallest
  possible placebo p is 1/2001 = 0.05%, below Holm's first level of 0.31%.
- **Bootstrap:** blocks are 2 consecutive calendar days; a resampled block contributes only its days with a signal; a
  draw is the mean of those day values.
- **Placebo:** each signal's side is flipped independently by a fair coin, paid at the same ask and fee as the side it
  becomes (the ask on that side at the close of minute k + 1); the statistic is the rule's own (the mean of day means).
- **Pass (all three, at the test's Holm level; equivalently, the test's p from above is below its Holm level):**
  1. the day-mean t above the one-sided Student-t value, days - 1 degrees of freedom, never below 2.0;
  2. the lower bound of a bootstrap of 2-day blocks of days (20,000 draws, seed 16) above zero;
  3. the side-flip placebo above (2,000 draws, seed 16): its p at most the Holm level.
- **Not testable:** fewer than 200 signals or fewer than 20 days with a signal for a rule and asset; for an asset,
  more than 10% of windows missing Coinbase or Kalshi data, or Coinbase's up-or-down agreeing with Kalshi's result in
  fewer than 97% of windows, computed with PLAN15's own function on the same windows (then A, B and C read "not
  testable" for that asset). D does not use Coinbase: its 10% guard counts only Kalshi candles and trades.
- **Reported for every rule, pass or fail:** signals, days, win rate against the average price paid, profit per
  contract with its day-level standard error, the split by minute (descriptive), the profit with fills 3 and 5 minutes
  later (a real edge should fade with delay), and the median contracts traded in the minute after a signal (capacity,
  an upper bound).
- **Reference, not a test:** PLAN15's own rule (RW, 4 points) on the same windows, so the four can be compared with
  what the live paper bot does. It is a free preview of PLAN15's Q2 on its find period: it says nothing about PLAN15's
  verdict and is not to be used to change PLAN15 or PLAN15F.

## 5. Power (written before the data)
About 60 days. A rule firing 10 times a day at about 50c has a day-mean standard deviation near 0.5 / sqrt(10) = 16c
and a standard error near 2c over 60 days. Holm's first step is 2.5% / 8 = 0.31% one-sided (t(59) about 2.85), so 80%
power needs about (2.85 + 0.84) x 2 = 7-8c a contract; the last step (2.5%, t about 2.0) about 6c. Rules that fire
less often need more. Signals within one window share its outcome, so the real power is lower than this; a rule
near the 200-signal / 20-day floor has almost none. Real edges below about 5-8c a contract will read "no edge shown".
B and C may fire rarely.

## 6. What a pass leads to
A pass is a lead, not a working system. It earns a place in the live paper bot (PLAN15F) as its own rule, with a
forward verdict rule written before its first live bet. Real money on these markets would need a new live.py path,
its own limits and a passed forward test, and only the user can decide that (CLAUDE.md sections 3 and 11a). A failed
rule is dropped: no new thresholds, no second run (CLAUDE.md section 11a).

## 7. Freeze
Statistics-reviewed 2026-11-13 (agents/statistician.md; all five MUST items and the SHOULD and NIT items applied).
This file is frozen after its statistics review (agents/statistician.md); its SHA-256 goes into CHANGELOG.md.
research/plan16.py is written after the freeze, code-reviewed and frozen before the first download. Where code and
text differ, the text wins, by an amendment before any number is computed.
