# PLAN22: options-implied volatility (Deribit's DVOL) for Kalshi's 15-minute BTC/ETH markets

Written 2026-11-26, about 20:40 La Paz, after the user's "Yes, approve Deribit" (20:20; CLAUDE.md section 3), before any
DVOL value was downloaded or looked at. Not yet statistics-reviewed; not frozen. Research and paper only: never part of
the gate, never connected to live.py, never writes paper.db or live.db, never calls an order endpoint. Not financial
advice.

## 0. Honest prior, stated before any data
- **The idea.** A 15-minute "up" market's fair chance is set by how far the index is from the strike compared with the
  volatility expected over the minutes left. PLAN15 (60-minute realized SD), PLAN16 A (15-minute SD) and PLAN18 G
  (composite of five exchanges plus GARCH) all estimated that volatility from past prices and lost about the fee
  (PLAN16 A: -1.6c and -1.8c a contract; PLAN18 G: -1.8c and -1.9c; side choice no better than a coin flip). Deribit's
  DVOL is a 30-day implied volatility, set by options traders and looking forward. The hope: Kalshi's traders underuse
  it.
- **Why it probably will not work.** (1) Volatility over 15 minutes is mostly intraday and event-driven; a 30-day index
  moves slowly and says little about the next 15 minutes beyond its level. (2) The level is roughly what realized
  volatility already gives, and realized volatility gave nothing. (3) Fast traders on Kalshi can read DVOL as easily as
  we can. (4) Late in a window the distance to the strike, not the volatility, decides almost everything.
- **Expected result: no edge shown.** That outcome costs nothing.
- **Seen before writing:** PLAN15's frozen text, PLAN16-18's results and PLAN17's tables (all Sep-Oct or Jun-Aug
  windows), Deribit's API documentation. No DVOL value, no November-December window and no window from 2027 has been
  read. Every month from June to October 2026 has been read by at least one earlier plan (PLAN18: Jun-Aug; PLAN15-17
  and PLAN20: Sep-Oct). This is the third volatility-scaled distance model on these markets: section 4's first stage
  is a screen on old data, and only the second stage, on windows that do not yet exist, can confirm anything.

## 1. Data (all approved, read-only, User-Agent tradebot-paper-research/1.0, no key, no account)
- **Deribit:** `public/get_volatility_index_data` (https://www.deribit.com/api/v2/public/..., JSON-RPC over GET):
  currency BTC or ETH; start_timestamp and end_timestamp in ms; resolution one of "1", "60", "3600", "43200", "1D"
  (seconds); each candle [timestamp ms, open, high, low, close]; `continuation`, when not null, is passed as the next
  end_timestamp. Resolution **"3600" (hourly)** is used: a 30-day index changes little within an hour, and hourly
  history is the most likely to reach back to June. The documentation states no history length, page size or rate
  limit; they are measured by the probe below.
- **Probe (PROBE22, before the freeze, counts only):** the number of hourly DVOL candles per month for each currency
  from 2026-06 to 2026-10, and whether a candle's timestamp marks the start or the end of its hour (from the latest
  candles against the clock). No value is printed or saved. Coverage under 95% of a month's hours makes that asset's
  stage 1 "not testable".
- **Kalshi:** KXBTC15M and KXETH15M market records, results and minute candles with PLAN15's functions (market_list,
  build_day, quote, fill, multiplier_at), reusing PLAN15's and PLAN18's saved day files where they hold what is needed.
- **Spot:** Coinbase one-minute BTC-USD / ETH-USD closes as in PLAN15 (labelled by the end of the minute), re-read in
  memory where the saved files lack a minute; nothing raw is written. S_0 = the market's floor_strike.
- **Never read:** anything (Kalshi, Coinbase or Deribit) dated 2026-11-01 to 2026-12-31: PLAN15's check period stays
  untouched until PLAN15's score, and this plan never uses it afterwards either.
- Runs on GitHub's runner (as PLAN17/18); results under research/results/plan22/.

## 2. The model (fixed now)
- **Decision minutes** k = 2, 5, 10 and 13 of each window (PLAN18's), using only what is known at the close of minute
  k (t_k = open + 60k).
- **Implied volatility:** D_k = the close of the latest hourly DVOL candle that has ended by t_k (if timestamps mark the
  start, timestamp + 3600 s <= t_k). Missing if that candle ended more than 2 hours before t_k.
- **Time left:** tau = (15 - k) - 2/3 minutes (the settlement averages the last minute, as in PLAN18), as a share of
  a year of 525,600 minutes (crypto trades every minute; DVOL is quoted on a 365-day year).
- **Probability of finishing up:** p = Phi( ln(S_k / S_0) / (m x (D_k / 100) x sqrt(tau / 525,600)) ), clipped to
  0.5%-99.5%. When S_k equals S_0, p = 0.5 (strictly above unless strike_type is greater_or_equal, as PLAN18).
- **One fitted number per asset, m:** a 30-day implied volatility is not the 15-minute volatility (time of day, the
  options' risk premium, weekend quiet). m is the value in [0.20, 3.00] that minimises the summed log-loss of p
  against Kalshi's result over every (window, k) row of the fit period, by golden-section search to 1e-6 (one
  parameter; no other input, no hour or weekday terms). Frozen with its hash in research/results/plan22_model.json
  before any scored number is computed. m = 1 (no fit) is reported, descriptive only.

## 3. Rules scored
- **Accuracy (Q-A):** per row (window, k, uncrossed minute-k candle, all inputs present): Brier(p) - Brier(mid), mid =
  (yes bid + yes ask) / 2 at minute k from plan15.quote. Below zero means DVOL's model beats Kalshi's price.
- **Money (Q-M):** signal at minute k when p minus a side's ask at minute k is at least 4 points (YES: p - YES ask;
  NO: (1 - p) - NO ask; PLAN15's margin). **One contract per signal**, paid as plan15.fill: the ask on that side at
  the close of minute k + 1; no trade when it is missing, $1.00, or the candle does not show 0 < bid < ask. Fee:
  Kalshi's taker fee, multiplier x 0.07 x P x (1 - P), multiplier from plan15.multiplier_at, rounded up to a hundredth
  of a cent (fee schedule effective July 7, 2026), as PLAN17/18; PLAN15's whole-cent fee is also reported.
  Why one contract, not PLAN20's $1 bet: signals here sit mostly at 20-80c, where $1 buys 1-4 contracts and the per-
  contract result is nearly the same, and one contract keeps the result comparable with PLAN15, 16 and 18. Several
  minutes of one window may each signal; the day is the unit, so they are not counted as independent.

## 4. Two stages, in order
- **Stage 1, screen on old months.** Fit m on windows closing **2026-06-01 to 2026-08-31** (UTC); score once on windows
  closing **2026-09-01 to 2026-10-31**. Both periods were read by earlier plans and their results shaped what we
  expect here, so a pass is weak evidence: it can earn only stage 2, never a paper-bot rule. Stage 1 failing for every
  test ends the plan: "no edge shown".
- **Stage 2, forward confirmation (only the tests that passed stage 1).** m stays as frozen in stage 1 (no refit).
  Scored once on windows closing **2027-01-01 to 2027-02-28** (59 days), all after this plan's freeze, read from
  Kalshi's, Coinbase's and Deribit's archives from 2027-03-02 (or recorded live by a GitHub job, if PROBE22 shows that
  Deribit's hourly history is not kept that long). If those windows cannot be complete by 2027-04-30: "not
  confirmed". Only a stage 2 pass is a lead; it earns a rule in the live paper bot (PLAN15F) with its own forward
  verdict rule written before its first bet. Real money would need a new live.py path, its own limits and the user's
  own decision (CLAUDE.md sections 3, 11a).

## 5. Statistics (the same in both stages)
- **Unit:** the UTC day of the window's close. A day's value is the mean of its rows (Q-A) or of its signals' profit
  per contract (Q-M); days without a row or signal drop out.
- **Tests:** stage 1 has 4: {BTC, ETH} x {Q-A, Q-M}, one family, one-sided, Holm at a family level of 2.5% (0.625%,
  0.833%, 1.25%, 2.5%). Stage 2 has the stage 1 passes only, Holm at 2.5% over them. A not-testable test stays in its
  family and does not pass.
- **One p per test, the largest of:**
  1. the day-mean t (Student-t, days - 1 degrees of freedom); a pass also needs t above max(2.0, the one-sided value
     at the test's Holm level);
  2. the bootstrap: non-overlapping 2-day calendar blocks (an odd last day alone), 20,000 draws, seed 22; p = the share
     of draws at or below zero for Q-M, at or above zero for Q-A;
  3. the placebo. **Q-M: side flip** as PLAN18 (one fair coin per window flips all its signals; each flipped signal is
     paid at the other side's own ask and fee at k + 1; a signal whose flipped side cannot be paid keeps its side;
     2,000 draws, seed 22; p = (1 + draws at least the rule's) / 2,001). **Q-A: shuffled DVOL**: each day's hourly
     DVOL series is replaced by that of a random other day of the same period (a permutation of days; m unchanged),
     2,000 draws, seed 22; p = (1 + draws with a day-mean Brier difference at most the real one) / 2,001. It asks
     whether that day's DVOL matters, not just a typical volatility level.
- **Floors (not testable):** Q-M fewer than 200 signals or 20 days with a signal; Q-A fewer than 20 days or 2,000 rows;
  for an asset, DVOL coverage under 95% of hours, or more than 10% of windows missing Coinbase or Kalshi data, or
  Coinbase's up-or-down agreeing with Kalshi's result in under 97% of windows (PLAN15's check).
- Results other than yes or no count as missing (PLAN15's files keep only yes/no).
- **Reported, pass or fail:** rows, signals, days, win rate against the average price paid, profit per contract (both
  fees) with its day-level SE, by minute k; fills 3 and 5 minutes later (a real edge fades with delay); median
  contracts traded in the fill minute (an upper bound on capacity); m and its log-loss; calibration of p in deciles;
  Brier of p, of the mid and of the same model with PLAN15's 60-minute realized SD in place of DVOL (its own m fitted
  the same way), so any gain can be traced to the implied volatility itself; the ratio of DVOL to realized volatility
  by month; the power actually achieved (section 6 redone with the observed SE).

## 6. Power (from the SE the code will use: the SD of day means / sqrt(days))
- **Q-M:** PLAN16 A, a rule of the same kind on the same Sep-Oct windows, had a day-mean SE of 0.75c (BTC) and 0.66c
  (ETH) over 61 days. At Holm's first level (0.625% one-sided, t(60) about 2.6) 80% power needs about (2.6 + 0.84) x
  0.75 = 2.6c a contract; at the last level (2.5%, t 2.0) about 2.1c. Stage 2 (59 days) is about the same. Edges below
  about 2-3c a contract will read "no edge shown"; the fee alone is about 1.7c at 50c.
- **Q-A:** no day-level SE of a Brier difference on these markets has been measured. As a guess, a day SD of 0.004
  over 61 days gives an SE of 0.0005 and a detectable difference of about 0.0017 in Brier (the mid's Brier is likely
  near 0.15-0.20, so about 1%). The real figure is reported. A model that ignores the price must beat it outright,
  which is a high bar.
- The two stages together: a weak edge that passes stage 1 at 80% power passes stage 2 at about 80% again, so about
  64% end to end; a false lead passes both at about 2.5% x 2.5%.

## 7. Freeze
Statistics-reviewed (agents/statistician.md) before the freeze; findings and fixes in CHANGELOG.md with this file's
SHA-256. PROBE22 (counts only) runs before the freeze, and any change it forces is made before the freeze.
research/plan22.py is written after the freeze, reuses plan15.py's functions by source hash, is code-reviewed and
frozen before the first DVOL download. Where code and text differ, the text wins, by a dated amendment before any
scored number. No refit of m, no other margin, no other months, no second run (CLAUDE.md section 11a).
