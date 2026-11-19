# PLAN18: reading the index's own exchanges, with a volatility model and a shift detector, tested once on past windows

Written 2026-11-18, 21:30 La Paz, at the user's request ("we need better detection systems to improve our odds. any
open source tools we can implement?", then "i want all options that will help with research and detection"), before
any of its numbers were computed. Research and paper only. Not financial advice.

## 0. Honest prior, stated before any data
- Kalshi's 15-minute BTC and ETH markets settle on CF Benchmarks' real-time indices (BRTI, ETHUSD_RTI): the average
  of the index's sixty one-second values before the close, against the same before the open (the floor_strike). The
  index is built from the order books of seven exchanges (CF Benchmarks' constituent list v13.7, 2026-08-24:
  Bitstamp, Coinbase, Kraken, Gemini, Crypto.com, Bullish, LMAX Digital). Our earlier plans read Coinbase alone.
- The idea: an average of the index's own exchanges should track the settlement price more closely than Coinbase,
  a volatility model should judge reversal chances better than a plain standard deviation, and a change-point
  detector might catch sudden shifts. Fast traders on Kalshi very likely watch the same exchanges, so any gain may
  already be priced in.
- **Expected result: no edge shown.** "No edge shown" costs nothing.
- **What had been seen before this was written:** PROBE18 (research/results/probe18.json, 2026-11-18): counts only,
  no prices or results. Bitstamp, Coinbase and Crypto.com give complete past one-minute candles from June to October
  2026; Bullish gives them with gaps (on one sample hour, 13 of 60 minutes for ETH); Kraken gives past trades only;
  Gemini gives neither for these months; LMAX Digital is not in ccxt. Kalshi's archive answers for 15-minute markets
  before September (its counts were not checked: section 1). No window from June to August 2026 has been read by any
  plan. PLAN15, PLAN16 and PLAN17 use September to December; none of their numbers has been looked at.
- **Limits stated now:** 5 of 7 exchanges; closes and last trades, not order books; GARCH ignores the time-of-day and
  weekend pattern in volatility; Coinbase is one of the composite's exchanges, so the Coinbase gap is partly mechanical.

## 1. Data and periods
- **Windows:** KXBTC15M and KXETH15M markets closing **2026-06-01 to 2026-08-31** (UTC), read with PLAN15's own
  functions (market_list, build_day: market records, results, Kalshi minute candles), saved under
  research/results/plan18/. Fit period: windows closing **June 1 to July 31**. Test period: windows closing **August 1
  to August 31**, scored once. Before the fit, the windows per month with Kalshi candles are reported; if June-July
  coverage of an asset is under 90% of 96 windows a day, that asset is not testable.
- **Minute labels:** "minute k" of a window is the minute ending at open + 60k. Every exchange's one-minute candle is
  labelled by the end of its minute (ccxt timestamps mark the start, as Coinbase's do in plan15.coinbase_end); a
  Kraken trade at time t belongs to the minute ending at ceil(t / 60) x 60.
- **Exchanges (5 of 7):** one-minute closes from Bitstamp, Coinbase, Crypto.com and Bullish (fetch_ohlcv, ccxt 4.5.85),
  and Kraken built from its public trades (the last trade in each minute), paginated until the whole day is covered;
  a day not fully covered has no Kraken closes. Gemini and LMAX Digital have no reachable history and are left out.
- **Composite (S):** for each minute, the median of the available exchanges' closes, only when at least 3 are
  available (else the minute's composite is missing). Saved per minute for whole days (rounded to 0.01), with
  Coinbase's own close (for section 2 and M's gap); other single-exchange series are never saved. Each exchange's
  presence by period is reported.
- **Dispersion:** the SD (n - 1) of the closes of Bitstamp, Coinbase and Crypto.com (complete throughout), divided by
  the composite; missing when any of the three is missing.
- **Returns:** r_t = 10^4 x ln(S_t / S_{t-1}) (basis points), missing unless both minutes have a composite.

## 2. Q1, descriptive: does the composite track Kalshi's result better than Coinbase?
For every window with a result: "up" by the composite = the composite close of minute 15 at or above floor_strike
(strictly above unless strike_type is greater_or_equal); "up" by Coinbase likewise with Coinbase's close. The minute-15
close is a proxy for the final-minute average. Reported for the test period (and, separately, the fit period): each
one's agreement with Kalshi's result, the windows where they differ, how often each is right there, and an exact
two-sided McNemar p. Descriptive only: no decision depends on it.

## 3. The volatility model and the three rules (fixed now)
**GARCH, fitted once per asset.** A GARCH(1,1) with zero mean and normal errors (arch 8.0.0, arch_model(r,
mean="Zero", vol="GARCH", p=1, q=1, dist="normal"), default backcast) on the returns of June 1 to July 31 with missing
minutes dropped and the rest treated as consecutive; omega, alpha, beta and the backcast value are frozen. The filter
then runs forward through every minute from the first fit minute to August 31 (starting at the backcast value):
sigma2_t = omega + alpha r_{t-1}^2 + beta sigma2_{t-1}; when r_{t-1} is missing, sigma2_t = sigma2_{t-1}. "The GARCH
SD of minute t" is sqrt(sigma2_t), which uses returns up to t - 1 only. Forecasts at minute k: E[sigma2_{k+j}] =
v + (alpha + beta)^(j-1) (sigma2_{k+1} - v), v = omega / (1 - alpha - beta), with sigma2_{k+1} from r_k.

All rules are decided at the close of minute k, use only what is known then, and are paid as PLAN15 pays (plan15.fill:
one contract at the ask on the chosen side at the close of minute k + 1; no trade when that ask is missing or $1.00 or
the candle does not show 0 < bid < ask). Fee: Kalshi's taker fee with the multiplier in force at the fill
(plan15.multiplier_at), rounded up to a hundredth of a cent (Kalshi's fee schedule effective July 7, 2026), with
PLAN15's whole-cent fee also reported. YES ask = the yes ask; NO ask = 1 - the yes bid; quotes from plan15.quote. A
minute-k candle that is crossed, locked or missing, or a missing input of that rule, gives no signal (counted for that
rule only).

- **G. Composite with the volatility model.** The variance left at minute k is V = (T - k - 2/3) x the mean of
  E[sigma2_{k+j}] for j = 1 .. T - k, T = 15 (the last minute counts one third, as the settlement averages it).
  p_up = Phi( 10^4 x ln(S_k / S_0) / sqrt(V) ), S_0 = floor_strike. Signal at k = 2, 5, 10 and 13: the side whose p
  minus its ask at minute k is at least 4 points (YES: p - YES ask; NO: (1 - p) - NO ask). Needs S_k.
- **R. Shift detector.** z = r_t / sqrt(sigma2_t) for the 30 returns ending at the close of minute k (any missing: no
  reading). bkps = ruptures.Pelt(model="l2", min_size=3, jump=1).fit(z).predict(pen=3 x ln 30) (ruptures 1.1.10). No
  change when bkps == [30]; otherwise the last change is bkps[-2], L = 30 - bkps[-2], and m = the mean of the last L
  values of z. Signal at k = 5, 10 and 13 when 3 <= L <= 5 and |m| x sqrt(L) >= 2 (a rule threshold applied after
  selection, not a test): YES when m > 0, NO when m < 0, only when that side's ask at minute k is from 20c to 80c.
  The "l2" model finds shifts in the mean only.
- **M. Learned model.** A ridge logistic (as PLAN17: inputs standardised by the fit rows' mean and SD (n - 1), sum of
  log-likelihoods minus 0.5 x 1.0 x the sum of squared slopes, intercept free, plan15.fit_ridge_logit) of "Kalshi's
  result is yes" on: logit(G's p_up) (clipped 0.5%-99.5%); logit(the mid (yes bid + yes ask) / 2 at minute k, from
  plan15.quote); the Coinbase gap 10^4 x ln(Coinbase_k / S_k) / sqrt(sigma2_k); the dispersion 10^4 x dispersion_k /
  sqrt(sigma2_k); R's signed statistic m x sqrt(L) when 3 <= L <= 5, else 0; and minutes left. A row needs every
  input, R's reading included (no R reading: no row, in the fit and in the signals). One model per asset, fitted once
  on every (window, k = 2, 5, 10, 13) of June 1 to July 31, frozen with the GARCH numbers in
  research/results/plan18_model.json before any August number is computed. Signal: model p minus the ask at least 4
  points on one side.

## 4. Scoring (once, on August)
- **Unit:** the UTC day of the window's close; a day's value is the mean profit per contract of its signals that day
  (all minutes together); days without a signal drop out.
- **Tests:** 3 rules x 2 assets = 6 tests, one family, one-sided (profit above zero), Holm at a family level of 2.5%.
- **One p per test,** the largest of: the day-mean t p; the bootstrap p (non-overlapping 2-day calendar blocks, the last
  day alone, 20,000 draws, seed 18, the share of draws at or below zero); and the side-flip placebo p: one fair coin
  per window flips all of that window's signals, each flipped signal paid at the other side's own ask and fee at
  minute k + 1 (for R even when that ask is outside 20-80c; a signal whose flipped side cannot be paid keeps its own
  side); 2,000 draws, seed 18; the statistic is the same mean of day means as the rule's; p = (1 + draws at least the
  rule's) / (1 + 2,000). The placebo is centred below zero (spread and fees), so it measures side selection; the t and
  bootstrap readings test profit against zero. Holm orders the tests by that p; a test passes when its p is at most
  its Holm level, its t is above max(2.0, the one-sided Student-t value at that level for days - 1 degrees of
  freedom), and every test before it passed. A not-testable test stays in the family and does not pass.
- **Not testable:** fewer than 200 signals or fewer than 20 days with a signal for a rule and asset; for an asset, more
  than 10% of August windows missing the composite at any minute from -30 to 15 or missing Kalshi candles (a trigger
  only: windows otherwise stay in, and each rule skips only the signals whose own inputs are missing).
- Results other than yes or no count as missing (PLAN15's files keep only yes/no).
- **Reported for every test, pass or fail:** signals, days, win rate against the average price paid, profit per
  contract (both fees) with its day-level SE, by minute; fills 3 and 5 minutes later (not reported when k + d > 14);
  median contracts traded in the fill minute (capacity, an upper bound); and, descriptively, the same rule with
  Coinbase in place of the composite (GARCH refitted on Coinbase's fit-period returns, M refitted without the gap and
  dispersion inputs, everything else identical), so any gain can be traced to the exchanges, the volatility model or
  the detector.
- **Also reported:** Q1 (section 2); the GARCH numbers; each exchange's presence by month; M's slopes (with the note
  that the Coinbase gap is partly mechanical) and its August calibration in deciles; the power actually achieved
  (section 5's arithmetic redone with the observed SE).

## 5. Power (written before the data)
31 test days. A rule firing about 10 times a day at about 50c has a day-mean SD near 16c and an SE near 2.9c; Holm's
first level, 2.5% / 6 = 0.42% (t(30) about 2.9), with 80% power needs about (2.9 + 0.84) x 2.9 = 11c a contract, and
the last level (2.5%, t about 2.04) about 8c. These are guesses: G can fire at four minutes in each of 96 windows a
day, but signals in one window share its outcome, so more signals add less than they seem; R and the k = 13 signals
may fire rarely. Real edges below about 8-11c a contract will read "no edge shown".

## 6. What a pass leads to
A pass is a lead on past data, not a working system. It earns its own rule in the live paper bot (PLAN15F), which
would then also read the five exchanges' live public prices (approved 2026-11-18), with a forward verdict rule
written before its first live bet. Real money would need a new live.py path, its own limits, a passed forward test
and the user's own decision (CLAUDE.md sections 3 and 11a). A failed rule is dropped: no new thresholds, no second
run.

## 7. Freeze
Statistics-reviewed 2026-11-18 (agents/statistician.md; MUST items 1-5, SHOULD 6-11 and the NITs applied). Frozen
after that review; its SHA-256 goes into CHANGELOG.md. research/plan18.py is written after the freeze, code-reviewed
and frozen before the first download (its identity record also covers plan15.py and the pinned package versions).
Where code and text differ, the text wins, by an amendment before any number is computed.
