# PLAN17: late reversals on cheap 15-minute contracts, tested once on past windows

Written 2026-11-18, 20:00 La Paz, at the user's request, before any of its numbers were computed. The user's idea
(19:13): "the biggest money opportunities are betting when there are really low odds and then a sudden reversal of
those odds ... compare the last 15 mins trading pattern and correctly identifying where the value will be (above/below
target) at the end of the bet time"; then (19:40) "think about it intelligently and implement the most intelligent
system". Research and paper only. Not financial advice.

## 0. Honest prior, stated before any data
- A contract at 1-5c pays $1 if it wins: up to 20-100 times the stake. Reversals happen, and the price already says
  about how often (a 3c price says about 3 in 100).
- The one large study of Kalshi trades (Burgi, Deng and Whelan, January 2026) found contracts priced 10c or less lose
  over 60% of their stake on average, and crypto has the strongest long-shot bias of any category. So buying cheap sides
  blindly is expected to lose money.
- The question is narrower: **can the last minutes' pattern pick the reversals that will happen more often than the
  price says?** A system can only make money if it can.
- "$1 to $900": one win at 1c turns $1 into about $100 before fees. $900 needs several such wins in a row with
  everything staked each time, and a run of losses first is far more likely. This plan tests the edge, not that target.
- **Expected result: no edge shown.** A well-calibrated model facing a long-shot bias may rarely sit 2 points above the
  ask; then the result is "not testable", which is an answer, not a fault.
- What had been seen before this was written: PLAN15F's live paper bets (a few, including YES at 9-11c); one window of
  one PLAN15 day file (BTC, Sep 11) printed to read the format, which showed a contract near 98c in minutes 12-13; the
  Burgi-Deng-Whelan paper. No cheap-side outcome on these markets has been counted. At writing, PLAN15's model has not
  been fitted and PLAN16 has not been scored; no result of either was looked at. These find-period days (Sep-Oct) now
  serve three plans; PLAN15's check period (Nov-Dec) stays unread. Only a forward test can confirm a lead.

## 1. The bets considered
- **Markets:** KXBTC15M and KXETH15M windows in PLAN15's saved day files (market record, result, Kalshi minute
  candles). Kalshi pays YES when the 60-second average of CF Benchmarks' BRTI before the close is at least the same
  average before the open (the floor_strike). The day of a window is the UTC day of its close.
- **Decision minutes:** k = 10, 11, 12 and 13 of each 15-minute window, using only what is known at the close of
  minute k.
- **Quotes:** every quote (minute k, k + 1, and k - 3 for x4) uses plan15.quote, which carries a candle forward at most
  5 minutes and never from before the window opened. YES ask = the yes ask; NO ask = 1 - the yes bid.
- **The cheap side:** the side whose ask at minute k is from 1c to 5c, on an uncrossed candle (0 < bid < ask). At most
  one side can be cheap.
- **Paid** like PLAN15 (plan15.fill): one contract at that side's ask at the close of minute k + 1, no trade if that ask
  is missing, $1.00, or the candle does not show 0 < bid < ask. (The k = 13 fill at minute 14 falls inside the closing
  average; that is allowed.)
- **Fee:** Kalshi's taker fee multiplier x 0.07 x P x (1 - P), rounded up to a hundredth of a cent, as Kalshi's fee
  schedule (effective July 7, 2026) states; the multiplier is read with plan15.multiplier_at. The schedule's sentence
  and date are quoted in plan17_model.json. At 3c this is about 0.2c. PLAN15's whole-cent round-up (1c on any cheap
  contract, a third of a 3c stake) is also reported; a pass that fails under it reads "lead under fine fee rounding
  only", and any forward test records the fees Kalshi actually charges.
- At most one bet per window and asset: the first decision minute where the rule fires.

## 2. Inputs (all fixed now)
From Coinbase's one-minute candles (approved 2026-11-12), re-read in memory with PLAN15's functions from 16 minutes
before the window opens to minute 13 (PLAN15's day files keep only some minutes; as in PLAN16, nothing raw is written),
with S_k the close of minute k, S_0 the market's floor_strike, and "toward" meaning in the direction that makes the
cheap side win:
- **x1 = logit(ask_k)**, the cheap side's ask at minute k (clipped to 0.5c-99.5c);
- **x2 = z, clipped to [-6, 6]**, z = ln(S_k / S_0) / (sigma15 x sqrt(T - k - 0.5)) signed toward the cheap side,
  T = 15, sigma15 = the SD (n - 1) of the 15 one-minute log returns ending at minute k (closes of minutes k - 15 to k);
- **x3 = momentum toward the cheap side:** ln(S_k / S_{k-3}) signed toward the cheap side, divided by
  sigma15 x sqrt(3), clipped to [-6, 6];
- **x4 = Kalshi's move:** the cheap side's ask at minute k minus its ask at minute k - 3, in dollars; 0 only when
  plan15.quote returns nothing for minute k - 3;
- **x5 = minutes left:** 15 - k.
A missing Coinbase minute among k - 15..k, sigma15 = 0, or a missing minute-k quote gives no bet (counted).

## 3. The model, fitted once
- **Rows:** every cheap-side (window, decision minute) on an uncrossed minute-k candle with all inputs present, whether
  or not minute k + 1 would fill, of windows closing **2026-09-01 to 2026-09-30** (both assets pooled, one shared
  model). The label is Kalshi's result for the cheap side.
- **Fit:** inputs standardised by the September rows' mean and SD (n - 1); a logistic regression with an intercept,
  maximising the summed log-likelihood minus 0.5 x 1.0 x (the sum of the five squared standardised slopes); the
  intercept is not penalised; Newton's method to a change below 1e-10. Frozen in research/results/plan17_model.json
  (with the means and SDs) before any October number is computed.
- Rows are correlated within a window, which is fine for a fit and is why the test below uses whole days.

## 4. The rule and the test (once, on October)
- **Rule:** at the first decision minute k of a window where the model's chance minus the cheap side's ask at minute
  k is at least 2 points, buy one contract of the cheap side (paid as section 1).
- **Test windows:** closing **2026-10-01 to 2026-10-31**, one test per asset, each at a one-sided 1.25% level
  (Bonferroni over the two assets; together 2.5%). An asset is scored once, when every October day of it is saved.
- **Unit:** the UTC day; a day's value is the mean profit per contract of its bets; days without a bet drop out.
- **Pass (all four):**
  1. the day-mean t above the one-sided Student-t value at 1.25% for days - 1 degrees of freedom (never below 2.3);
  2. a bootstrap of non-overlapping 2-day calendar blocks (Oct 1-2, ..., Oct 29-30, and Oct 31 alone; 20,000 draws,
     seed 17; a block contributes its days with a bet; a draw is the mean of those day values): the share of draws at
     or below zero at most 1.25%;
  3. **a matched random-pick placebo:** strata are UTC day x decision minute x the whole-cent ask at minute k. Each rule
     bet is replaced by a random candidate from its own stratum; candidates are cheap sides that would fill at k + 1,
     at most one per window, drawn without replacement, excluding no window the rule bet on. If a stratum is short,
     draw from day x ask cent; if still short, from day x the 1-2c / 3-5c band (how often each fallback was used is
     reported). 2,000 draws (seed 17), each paid the same way and scored with the rule's statistic (the mean of day
     means); p = (1 + the number of draws at least the rule's) / (1 + 2,000) at most 1.25%. This asks whether the
     model picks better reversals than chance at the same price and minute, not just whether cheap sides pay.
  4. **an exact bound:** treating bets as independent across windows, each bet wins with probability equal to its
     break-even price (price paid + fee); the exact (Poisson-binomial) chance of a total profit at least the rule's
     at most 1.25%. This holds up when there are only a handful of wins.
- **Not testable:** fewer than 100 bets or fewer than 15 days with a bet for an asset; more than 10% of an asset's
  October windows missing Coinbase (minutes -16..13) or Kalshi data; or Coinbase's up-or-down agreeing with Kalshi's
  result in fewer than 97% of windows (PLAN15's own check).
- Results other than yes or no follow strategy.payout (none seen in PLAN15's saved files, which keep only yes/no).

## 5. Reported for every asset, pass or fail
- The rule: bets, days, wins, win rate against the average price paid, profit per contract with its day-level
  standard error, by decision minute; with the whole-cent fee as well.
- A bet-weighted figure: total profit / total bets, with a day-clustered standard error. If its sign differs from the
  day-mean reading, the verdict carries a note saying so.
- **The calibration of cheap sides in October (descriptive):** for every eligible cheap side, in price bands 1c, 2c,
  3c, 4c, 5c: how many, how often they won, and the average price, so the long-shot bias on these markets is measured
  directly.
- "Buy every cheap side at the first eligible minute" (no model), profit per contract: the baseline.
- The model's slopes and its October calibration (predicted vs actual win rate in deciles).
- Capacity: median contracts traded in the fill minute (an upper bound on what one could buy), and the rule's profit
  restricted to fills where minute k + 1 volume is at least 1.

## 6. Power (written before the data)
A cheap-side bet wins about 3 times in 100, so one bet's profit has an SD near sqrt(0.03 x 0.97) = 17c. At about 5
bets a day for 31 days (155 bets), a day mean of about 5 bets has an SD near 17c / sqrt(5) = 7.6c and its standard
error over 31 days is about 1.4c; the one-sided 1.25% line (t about 2.3) plus 80% power needs a true edge near
(2.3 + 0.84) x 1.4c = 4.4c a contract. In wins: at 155 bets near 3c about 5 wins are expected at break-even; passing
at 1.25% needs about 12, a win rate near 8%. Smaller real edges will read "no edge shown". Fewer bets need a larger
edge.

## 7. What a pass leads to
A pass is a lead on past data, not a working system. It earns its own rule in the live paper bot (PLAN15F), with a
forward verdict rule written before its first live bet. Real money would need a new live.py path, its own limits,
a passed forward test, and the user's own decision (CLAUDE.md sections 3 and 11a). A failed rule is dropped: no new
thresholds, no second run.

## 8. Freeze
Statistics-reviewed 2026-11-18 (agents/statistician.md; MUST items 1-4, SHOULD 5-10 and the NITs applied). Frozen
after that review; its SHA-256 goes into CHANGELOG.md. research/plan17.py is written after the freeze, code-reviewed
and frozen before the first download. Where code and text differ, the text wins, by an amendment before any number is
computed.
