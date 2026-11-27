# PLAN22: options-implied volatility (Deribit's DVOL) for Kalshi's 15-minute BTC/ETH markets

Written 2026-11-26, about 20:40 La Paz, after the user's "Yes, approve Deribit" (20:20; CLAUDE.md section 3), before any
DVOL value was downloaded or looked at. Revised the same evening after its independent statistics review (section 8),
still before any DVOL value; not frozen yet (PROBE22 and POWER22 come first, section 7). Research and paper only: never
part of the gate, never connected to live.py, never writes paper.db or live.db, never calls an order endpoint. Not
financial advice.

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
- **Seen before writing:** PLAN15's frozen text and code, PLAN16-18's results and PLAN17's tables (all Sep-Oct or
  Jun-Aug windows), Deribit's API documentation. No DVOL value, no November-December window and no window from 2027 has
  been read. Every month from June to October 2026 has been read by at least one earlier plan (PLAN18: Jun-Aug;
  PLAN15-17 and PLAN20: Sep-Oct). This is the third volatility-scaled distance model on these markets: stage 1 (section
  4) is a loose screen on old data, and only stage 2, on windows that do not yet exist, can confirm anything.

## 1. Data (all approved, read-only, User-Agent tradebot-paper-research/1.0, no key, no account)
- **Deribit:** `public/get_volatility_index_data` (https://www.deribit.com/api/v2/public/..., JSON-RPC over GET):
  currency BTC or ETH; start_timestamp and end_timestamp in ms; resolution one of "1", "60", "3600", "43200", "1D"
  (seconds); each candle [timestamp ms, open, high, low, close]; `continuation`, when not null, is passed as the next
  end_timestamp. Resolution **"3600" (hourly)** is used: a 30-day index changes little within an hour, and hourly
  history is the most likely to reach back to June. The documentation states no history length, page size or rate
  limit; PROBE22 measures what matters (section 7).
- **Kalshi:** KXBTC15M and KXETH15M market records, results and minute candles with PLAN15's functions (market_list,
  build_day, quote, fill, multiplier_at). Saved day files are reused: research/results/plan18/kalshi/ and comp/
  (Jun-Aug, whole days, Coinbase closes per minute) and research/results/plan15/days/ (Sep-Oct); minutes those files
  lack are re-read in memory with PLAN15's functions; nothing raw is written.
- **Spot and reference (one source):** Coinbase one-minute BTC-USD / ETH-USD closes as in PLAN15, labelled by the end of
  the minute. **S_k = plan15.spot_close(w, k) and S_0 = plan15.spot_close(w, 0)**, the Coinbase close at the window's
  open (what plan15.reference returns when the record's field is not used), so the distance compares Coinbase with
  Coinbase. Kalshi's floor_strike (the index's 60-second average) is not used in the model.
- **Agreement check:** plan15.spot_up(w, use_ref=False) (PLAN15's measure SPOT_AGREE_MEASURE = "ohlc15": the mean of
  minute 15's open, high, low and close against S_0; at or above when strike_type is greater_or_equal) against Kalshi's
  result, at least 97% (plan15.MIN_AGREE) in the fit period, in the score period and in stage 2, for each asset.
  Below 97% in the fit or stage 1 score period: that asset is "not testable"; in stage 2: "not confirmed".
- **Never read:** anything (Kalshi, Coinbase or Deribit) dated 2026-11-01 to 2026-12-31: PLAN15's check period stays
  untouched until PLAN15's score, and this plan never uses it afterwards either.
- Runs on GitHub's runner (as PLAN17/18); results under research/results/plan22/.

## 2. The model (fixed now)
- **Decision minutes** k = 2, 5, 10 and 13 of each window (PLAN18's), using only what is known at the close of minute
  k (t_k = open + 60k).
- **Implied volatility:** D_k = the close of the latest hourly DVOL candle that has ended by t_k (if timestamps mark the
  start, timestamp + 3600 s <= t_k; PROBE22 settles which). Missing if that candle ended more than 2 hours before t_k.
- **Time left:** tau = (15 - k) - 2/3 minutes (the settlement averages the last minute, as in PLAN18), as a share of
  a year of 525,600 minutes (crypto trades every minute; DVOL is quoted on a 365-day year).
- **Probability of finishing up:** p = Phi( ln(S_k / S_0) / (m x (D_k / 100) x sqrt(tau / 525,600)) ), clipped to
  0.5%-99.5%. When S_k equals S_0, p = 0.5.
- **One fitted number per asset, m:** a 30-day implied volatility is not the 15-minute volatility (time of day, the
  options' risk premium, weekend quiet). m minimises the summed log-loss of p against Kalshi's result over every
  (window, k) row of the fit period: a grid search over 0.20 to 3.00 in steps of 0.01, then golden-section refinement
  within one step of the grid minimum to 1e-6. **A grid minimum at 0.20 or 3.00 makes that asset "not testable
  (misspecified)"** for all its tests. No other input, no hour or weekday terms. The m that minimises Brier instead is
  reported as a check (a large gap between the two is a sign of misspecification). Frozen with its hash in
  research/results/plan22_model.json before any scored number is computed. m = 1 (no fit) is reported, descriptive.

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
- **Stage 1, a loose screen on old months.** Fit m on windows closing **2026-06-01 to 2026-08-31** (UTC); score once
  on windows closing **2026-09-01 to 2026-10-31**, at a **10% one-sided family level** (section 5). Both periods were
  read by earlier plans and their results shaped what we expect here, so a pass is weak evidence: it earns only stage 2,
  never a paper-bot rule. Stage 1 passing nothing ends the plan: "no edge shown".
- **Stage 2, forward confirmation (only the tests that passed stage 1), at 2.5%.** m stays as frozen (no refit).
  Scored once on windows closing **2027-01-01 to 2027-02-28** (UTC), all after this plan's freeze, from 2027-03-02.
  **Nothing timestamped before 2027-01-01 00:00 UTC is read from any source**: no DVOL candle that started earlier, no
  Coinbase minute before it (PLAN15's 60-minute SD lookback for the realized control included), no Kalshi candle or
  record before it; a window whose inputs would need earlier data drops out. The code asserts these timestamps for all
  three sources and stops if one fails. If the windows cannot be complete by 2027-04-30: "not confirmed". A change in
  Kalshi's fee, settlement index or series terms for KXBTC15M/KXETH15M during January-February reads "not confirmed"
  unless the user approves an amendment before any stage 2 number is computed. Only a stage 2 pass is a lead; it earns a
  rule in the live paper bot (PLAN15F) with its own forward verdict rule written before its first bet. Real money would
  need a new live.py path, its own limits and the user's own decision (CLAUDE.md sections 3, 11a).

## 5. Statistics (the same in both stages, except the family level)
- **Unit:** the UTC day of the window's close. A day's value is the mean of its rows (Q-A) or of its signals' profit
  per contract (Q-M); days without a row or signal drop out.
- **Tests:** stage 1 has 4: {BTC, ETH} x {Q-A, Q-M}, one family, one-sided, Holm at a family level of 10% (2.5%,
  3.33%, 5%, 10%). Stage 2 has the stage 1 passes only, Holm at 2.5% over them. A not-testable test stays in its family
  and does not pass.
- **One p per test, the largest of:**
  1. the day-mean t (Student-t, days - 1 degrees of freedom); a pass also needs t above max(2.0, the one-sided value
     at the test's Holm level) in stage 2, and above the one-sided value at its Holm level in stage 1;
  2. a Newey-West t on the day series (Bartlett kernel, lag 6, compared with the normal), for runs of similar days;
  3. the bootstrap: non-overlapping 7-day calendar blocks (a short last block kept), 20,000 draws, seed 22; p = the
     share of draws at or below zero for Q-M, at or above zero for Q-A;
  4. the placebo. **Q-M: side flip** as PLAN18 (one fair coin per window flips all its signals; each flipped signal is
     paid at the other side's own ask and fee at k + 1; a signal whose flipped side cannot be paid keeps its side;
     2,000 draws, seed 22; p = (1 + draws at least the rule's) / 2,001). **Q-A: shuffled DVOL**, a test of
     day-specific information only: each draw is a random derangement of the period's days (no day keeps its own
     DVOL), each day's hourly DVOL series replaced by its partner day's at the same hours, m unchanged; 2,000 draws,
     seed 22; p = (1 + draws with a day-mean Brier difference at most the real one) / 2,001.
- **Floors (not testable):** Q-M fewer than 200 signals or 20 days with a signal; Q-A fewer than 20 days or 2,000 rows;
  for an asset, DVOL coverage under 95% of hours, more than 10% of windows missing Coinbase or Kalshi data, the 97%
  agreement check failing (section 1), or m at a grid bound (section 2).
- Results other than yes or no count as missing (PLAN15's files keep only yes/no).
- **Reported, pass or fail (descriptive unless named above):** rows, signals, days, win rate against the average price
  paid, profit per contract (both fees) with its day-level SE; profit collapsed to one figure per window (the mean of
  its signals) and then to day means; by minute k and fills 3 and 5 minutes later (descriptive only; a real edge
  fades with delay); median contracts traded in the fill minute (an upper bound on capacity); m (log-loss and Brier
  fits); calibration of p in deciles; Brier of p, of the mid, of a constant-DVOL control (the fit period's median DVOL,
  its own m) and of the realized-SD model (PLAN15's 60-minute SD in place of DVOL, its own m fitted the same way), so
  any gain can be traced to the implied volatility itself; the ratio of DVOL to realized volatility by month; the
  power actually achieved (section 6 redone with the observed SEs).

## 6. Power (from the SE the code will use: the SD of day means / sqrt(days))
- **Q-M:** PLAN16 A, a rule of the same kind on the same Sep-Oct windows, had a day-mean SE of 0.75c (BTC) and 0.66c
  (ETH) over 61 days. Stage 1 at its first Holm level (2.5% one-sided, t about 2.0) needs about (2.0 + 0.84) x 0.75 =
  2.1c a contract for 80% power, at its last (10%, t about 1.3) about 1.6c. Stage 2 (59 days, 2.5%, t at least 2.0)
  needs about 2.1c again. The fee alone is about 1.7c at 50c.
- **Q-A:** the detectable Brier difference is filled in here from POWER22 (section 7) before the freeze, as 2.84 x its
  measured SE. If that is implausibly large (bigger than any gain a volatility input could make, e.g. above 0.005), the
  plan says so here: Q-A then has almost no power, and its result can only be "no edge shown".
  **Measured (POWER22, run 2026-11-26 23:20 La Paz; research/results/power22.md):** SD of day means of Brier(RW) -
  Brier(mid) over 92 Jun-Aug days: BTC 0.00702, ETH 0.00642 (34,712 and 34,711 rows; the mean was not computed for
  display). Stage 2 (59 days, 2.5%, t 2.002): detectable at 80% power about 0.0026 (BTC) and 0.0024 (ETH); stage 1 on
  about 61 Sep-Oct days is similar at its first Holm level and about 0.0021 at its last. Below the 0.005 line, so Q-A
  is not declared powerless, but a Brier gain of 0.0024-0.0026 over Kalshi's mid is large for a volatility input
  alone; read Q-A as able to see only a big accuracy gain. (Measured with PLAN15's realized SD, not DVOL; the stage
  results restate power with the observed SEs.)
- **End to end:** a true edge at the stage 2 80% line passes stage 1 with somewhat more than 80% (looser level) and
  stage 2 with about 80%, so about 65-70% overall before the further checks; taking the largest of four p's lowers this
  further, perhaps to 50-60%. A false lead passes both at most about 10% x 2.5% = 0.25% per test.

## 7. Before the freeze (counts and already-read data only), then freeze
- **PROBE22 (no DVOL value printed or saved):** (a) hourly DVOL candles per month per currency, 2026-06 to 2026-10;
  (b) whether a candle's timestamp marks the start or end of its hour (latest candles against the clock); (c) revision
  check: the same past candles (one week of each currency) fetched on two days at least 24 hours apart, compared by
  SHA-256 only, printed "same" or "different" (different: the plan is amended before the freeze, or abandoned);
  (d) the oldest hourly candle each currency returns. It decides, and the plan records before the freeze, whether stage
  2 needs a live DVOL recorder: if history is rolling or would not reach back to 2027-01-01 by 2027-03-02, a GitHub job
  recording each hourly candle is written, code-reviewed and started before 2027-01-01.
- **POWER22 (no DVOL):** on the saved Jun-Aug files (research/results/plan18/comp/ and kalshi/, already read by PLAN18),
  for each asset: rows (window, k = 2, 5, 10, 13) with an uncrossed minute-k candle and Coinbase closes for the 60
  minutes before the open and at minute k; p_rw = plan15.rw_prob(S_k, S_0, sigma, k) with sigma = plan15.sigma_from
  of those 60 closes and S_0 = Coinbase's minute-0 close; the day means of Brier(p_rw) - Brier(mid); their SD and SE
  (SD / sqrt(days)). Only these two numbers and the day count are printed and copied into section 6. Not run yet.
- Then: statistics review of the final text (agents/statistician.md); findings in CHANGELOG.md with this file's
  SHA-256. research/plan22.py is written after the freeze, reuses plan15.py's functions by source hash, is code-reviewed
  and frozen before the first DVOL download. Where code and text differ, the text wins, by a dated amendment before any
  scored number. No refit of m, no other margin, no other months, no second run (CLAUDE.md section 11a).

## 8. Review (2026-11-26)
Independent statistics review of the first draft; every finding applied, before any DVOL value:
1. (High) S_0 and S_k from different sources: S_0 is now Coinbase's minute-0 close (plan15.spot_close), the agreement
   function is named (plan15.spot_up, use_ref=False, "ohlc15"), the 97% check covers the fit period too, and stage 2
   below 97% reads "not confirmed" (section 1).
2. (High) Stage 2 could read pre-2027 data: nothing before 2027-01-01 00:00 UTC from any source; such windows drop out;
   code asserts on all three sources' timestamps (section 4).
3. (High) Q-A power was a guess: POWER22 measures the SE on already-read Jun-Aug data before the freeze; an implausible
   result is stated as "almost no power" (sections 6, 7).
4. (Medium) 7-day block bootstrap instead of 2-day; a Newey-West t (lag 6) added to the maximum of p's (section 5).
5. (Medium) Placebo is a derangement, labelled a test of day-specific information; constant-DVOL and realized-SD
   controls reported alongside (section 5).
6. (Medium) m by grid 0.20-3.00 step 0.01 then golden-section; a bound minimum is "not testable (misspecified)"; the
   Brier-fitted m reported (section 2).
7. (Medium) PROBE22 decides the live recorder before the freeze and checks that past candles are not revised; a Kalshi
   fee, index or terms change in Jan-Feb reads "not confirmed" without a prior amendment (sections 4, 7).
8. (Low) Stage 1 is a 10% screen (Holm over 4), stage 2 stays at 2.5%; end-to-end power stated (sections 4-6).
9. (Low) By-minute and delayed-fill results labelled descriptive; profit per window reported (section 5).
