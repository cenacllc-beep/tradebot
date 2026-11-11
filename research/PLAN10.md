# PLAN10: NOAA's HRRR rain forecast against Kalshi's price, on past markets

Written 2026-11-09, 21:00 La Paz, before any HRRR data was downloaded or looked at. Revised 2026-11-11 after an
independent statistics review, still before any HRRR data. Research only: never part of the
gate, never connected to live.py. A result can lead only to a proposal and a forward test, never straight to real money
(CLAUDE.md section 11a).

## 0. Why now, and what changed
- The user, 2026-11-09: "write the HRRR plan with a $1000000 target from $25 plus the other free $25 promotional amount",
  after asking for "more successful winning bets".
- PLAN8 (frozen) says the HRRR plan would be proposed only after PLAN8's tests pass, and CLAUDE.md section 7 says free
  weather sources wait for PLAN8 or PLAN9. The user chose to start now. PLAN8's text, code and looks are unchanged.
  PLAN10 joins the family of forecast tests (section 7 below).
- HRRR (High-Resolution Rapid Refresh) is NOAA's 3 km weather model, run every hour. It is public domain. Its archive is
  on Amazon's Open Data servers (bucket noaa-hrrr-bdp-pds).
- **Honest prior.** The National Blend of Models, which PLAN.md tested and which already uses HRRR among its inputs, did not
  beat Kalshi's price on these markets (Brier 0.0740 vs 0.0730). HRRR's own value is its 3 km detail. Expected result: no
  gain shown.
- **These markets were scored before.** PLAN.md scored a blend of the airport forecast and the price on exactly these
  markets: it was better than the price by 0.0026 (t about -1.4, not clear), mostly in summer showers, where a 3 km
  model is strongest. HRRR's blend shares half its inputs (the price) and much of its weather errors with that blend.
  - So a pass here is not a fresh 2.5% result. With no real value in either forecast, B would pass about 4-7% of the
    time, not 2.5%.
  - A pass can therefore only justify writing a forward test (PLAN10F) on new markets. It is never evidence for money
    on its own.

## 1. The questions
- **B (primary).** Is the bot's blend with HRRR, 0.5 x H + 0.5 x M, more accurate than Kalshi's price M?
- **A (secondary, judged only if B is confirmed; it has no consequence of its own).** Is the calibrated HRRR forecast H on
  its own more accurate than M?
- **N (descriptive).** Does HRRR add anything over the airport forecast? The paired difference
  Brier(0.5 x H + 0.5 x M) - Brier(0.5 x C + 0.5 x M) on the same markets, where C is PLAN.md's calibrated airport
  forecast. Reported with its day standard error and the correlation between the two day series.
- **T (descriptive).** What the bot's own trading rule, with H in place of v3, would have made after fees. The money test
  belongs to PLAN10F, on new markets.

## 2. Data (all public)
- **Markets, prices and outcomes:** PLAN.md's holdout, research/data/kalshi_rain.jsonl. That is every settled KXRAIN market
  from 2026-07-15 to 2026-10-12, with:
  - Kalshi's result;
  - the station ("at CLIxxx");
  - the quote at 00:55 UTC on the market day (the bot's 8:55 PM scan);
  - the market's day start (start_ts);
  - the price range after the scan (lo_after, hi_after), for the limit-order fill rule.
  - **The base set N0** (fixed now): every market in that file with a usable quote as in PLAN.md (0 <= bid < ask <= 1 and
    ask - bid <= 0.06), whose station is in v3's rain table and whose station has one consistent day-start hour (below).
    PLAN.md's 1,711 markets are a slightly different set (it also dropped markets without an airport forecast), so
    PLAN10 reports its own count and scores the airport-forecast blend on its own set too.
  - **Station exclusions:** every station left out is listed with its markets. If they hold more than 10% of the markets
    that pass the quote rule, the verdict is "not testable".
- **Training outcomes:** NWS daily climate reports (CLI), already fetched for PLAN.md from the Iowa Environmental Mesonet
  (research/data/cli). The period is 2025-07-01 to 2026-06-30, for the same stations. Yes = precipitation above 0; trace
  and missing count as 0, as in Kalshi's rules. No market prices are used in training.
- **HRRR:** the CONUS surface files (wrfsfc) from the noaa-hrrr-bdp-pds bucket.
  - Only the precipitation field accumulated since the run started ("APCP, 0-N hour acc").
  - Only the 12 UTC and 18 UTC runs of the day before the market day. Both run to 48 hours, and both are out before the
    00:55 UTC scan. The 00 UTC run is not reliably complete by then and is not used.
- **Station position:** the coordinates in v3's rain table (weather.RAIN), matched by CLI code. A holdout station that is
  not in the table is left out and counted.
  - West Palm Beach was re-coded from CLIPBI to CLIDJT in July 2026 (same airport). Its training outcomes use whichever
    of the two codes has the report for that date.
- **Day window:**
  - For each holdout market, Kalshi's own day, from start_ts to start_ts + 24 hours.
  - For training days, the same UTC start hour per station. It is read from that station's holdout markets: the hour must
    be the same for all of them, or the station is left out.

## 3. Features (fixed now)
For each run r (12 UTC or 18 UTC of the day before) and each station:
- **D_r** = APCP_r at the forecast hour of the day's end minus APCP_r at the forecast hour of the day's start, on every HRRR
  grid point. Negative values (rounding) count as 0.
- **F_r** = the share of grid points whose centres lie within 40 km of the station with D_r >= 0.254 mm (0.01 inch).
- **A_r** = D_r at the grid point nearest the station, in inches.
- **F** = the mean of F_12 and F_18; **A** = the mean of A_12 and A_18.
- A market or training day with any of its four fields missing (2 runs x 2 hours) is left out and counted. If more than
  10% of N0's markets are left out for this reason, the verdict is "not testable".
- Reported as counts only: the share of F = 0 and of F = 1, in training and in the holdout. F = 0 will be common on dry
  days, where H is constant; that is expected.
- No other radius, threshold, run or field is tried.

## 4. The forecast H (fitted once, then frozen)
- **Form:** logit(H) = a + b x logit(clip(F, 0.02, 0.98)) + c x log(1 + 100 x A). The coefficients are shared by all stations,
  and H is clipped to [0.01, 0.99].
  - This is the form of PLAN.md's calibrated forecast C, kept for parity, not tuned. The parity is the form only:
    PLAN.md clips its input at 0.005, PLAN10 clips F at 0.02.
  - The fit uses a full year, while the holdout is summer. That can only push toward "no gain".
- **Fit:** maximum likelihood (Newton's method) on the training station-days only.
  - It is stored in research/results/plan10_model.json, with a SHA-256 of the training rows.
  - That happens before any holdout HRRR value is worked out.
- **Failure:** if the fit does not converge or b <= 0, the verdict is "not testable".

## 5. Scoring (once, on the holdout)
- **The statistic:** the gate's day-mean statistic.
  1. For each market, Brier(X) - Brier(M).
  2. Average within each market day.
  3. Take the mean over days and its standard error.
- **B:** X = 0.5 x H + 0.5 x M.
- **A:** X = H.
- **The bootstrap:** a moving-block bootstrap of the day means over consecutive market days. Blocks of 7 days, 5,000 draws,
  seed 11. It reuses PLAN7's boot_means and boot_interval, pinned by SHA-256 as PLAN8 and PLAN9 do.
- **"Confirmed"** needs both:
  - the day-mean t below minus the one-sided 2.5% Student-t value, with days - 1 degrees of freedom, never below 2.0
    (PLAN7's pinned tcrit, as in the gate);
  - the bootstrap's 2.5% upper bound below zero.
- **Fixed order:** B first. A is judged only if B is confirmed; otherwise A reads "not judged". On fresh markets this
  would hold the error at 2.5%; on these reused markets it is higher (section 0).
- **T, trading (descriptive),** one contract per signal, with the bot's rule and fair = B's blend:
  - buy YES at the ask if fair - ask >= 0.08; buy NO at 1 - bid if (1 - fair) - (1 - bid) >= 0.08;
  - the bot's 30-point veto, applied to H: no bet when |H - M| > 0.30;
  - taker fee rounded up to the cent.
  - Paying the ask (taker) and limit orders (PLAN.md's maker rule and fill model), both reported with day-clustered
    standard errors. With about 125 signals the standard error is at least about 4 cents a contract, so this cannot
    show a realistic edge either way. The maker numbers use the same markets and fills as PLAN.md's maker lead, so they
    can never count as its replication.
- **Verdict:**
  - B confirmed: **"lead on reused past data: justifies writing PLAN10F only"**.
  - Otherwise: **"no gain shown; PLAN10 ends"**.
  - A, N, T, the calibration table, per-month and per-station results are descriptive and never used to pick anything.

## 6. Power (approximate; the t test alone, and the bootstrap lowers it further)
- **PLAN.md's blend of the airport forecast and the price:** better than the price by 0.0026 Brier, with a day-level
  standard error of about 0.0019 over 81 days.
- **What 81 days can detect:** at that noise, 80% power needs a true gain of about (1.99 + 0.85) x 0.0019 ≈ 0.0054. That is
  about twice the airport forecast's gain.
- **Realistic gains:** power is about 17% for a true gain of 0.002 and about 34% for 0.003.
- **How to read the result:** a pass needs HRRR to be much better than anything tested so far. A fail does not prove HRRR
  useless; it only means no large gain. Most likely, even a useful HRRR reads "no gain shown" here.

## 7. Multiplicity across plans
- **The family:** forecast tests that could each lead to a trading proposal:
  - the airport-forecast limit-order test;
  - PLAN7;
  - PLAN8 A;
  - PLAN9 A;
  - PLAN10 B.
- **The five-test line:** PLAN10 reports whether B also passes at 0.5% one-sided (t, and the bootstrap with 20,000 draws
  for that reading only, because the 0.5% bound is noisy at 5,000). It decides nothing here, because PLAN10's only
  consequence is PLAN10F. PLAN10F must carry the family's multiplicity into its own rule.

## 8. Freeze and leakage controls
- **This file is frozen at its review.** Its SHA-256 goes into CHANGELOG.md.
- **research/plan10.py comes next.** It is the download, feature, fit and scoring code.
  - It is written after this plan, code-reviewed, and frozen (SHA-256 recorded) before the first HRRR download.
  - Where code and text differ, the text wins. The fix is an amendment at the end of this file, made before any download.
- **Order, verifiable from the repository's history:**
  1. Download the training fields.
  2. Work out the training features.
  3. Fit the model, and commit research/results/plan10_model.json with its SHA-256 to the repository.
  4. Only then download the holdout fields and work out their features. The holdout step refuses to run without that
     committed file, and prints only counts: no holdout feature values appear in the public Actions logs.
  5. Score once.
  6. Store the result, with a copy outside the tradebot folder.
- **No re-runs:** no other form, radius, run or period, and no rescue. A failed test ends PLAN10 (CLAUDE.md section 11a). A
  genuinely new idea needs its own plan.
- **Data checks** (counting, never tuning):
  - HRRR fields found and missing;
  - the model version that made each day's fields (from the files' metadata). An HRRR upgrade inside the window is
    reported as a finding. Whether HRRR will keep running (NOAA plans to replace it with RRFS) is checked before PLAN10F
    is written; if it is retiring, PLAN10F would be moot;
  - CLI vs Kalshi results on the holdout (PLAN.md found 100% agreement);
  - stations left out.

## 9. Practical notes
- **Tools:** open source. Herbie (MIT) for byte-range downloads of single fields, and xarray with cfgrib/ecCodes
  (Apache 2.0) to read GRIB2.
  - Installing them and downloading from Amazon's servers is a new package set and a new web address for the project.
  - The user asked on 2026-11-09 for the plan to be implemented; the install and the first download wait for his
    explicit yes after this plan's review.
- **Where it runs:**
  - Downloads and features run on GitHub Actions in the public repository (free while public, with open internet). Only
    the per-station features, small public numbers derived from NOAA data, are kept.
  - Scoring runs on the PC, where the Kalshi holdout file lives, read-only on research/data.
  - Nothing touches paper.db or live.db.
- **Requests:** every request carries the User-Agent tradebot-paper-research/1.0 and no personal data.
- **Size:** about 450 days x 2 runs x up to 8 forecast hours of one field each (about 1 MB each). That is a few GB moved,
  with only the features kept. Expect a result within days of the yes.

## 10. The money target: $1,000,000 from $25 plus a $25 promotional credit
The user set this target on 2026-11-09. Plainly: **this strategy cannot reach it**, even if PLAN10 passes.
- **The multiple:** $50 to $1,000,000 is a 20,000-fold gain, about 14.3 doublings.
- **The bot's own staking** (quarter Kelly, at most 6% a bet, taker fee included), compounding every bet:

  | If the bot had this edge (it has none shown) | Stake a bet | Growth a bet | Bets to reach $1,000,000 | Years at 1 bet a night | Years at 5 a night (upper bound) |
  |---|---|---|---|---|---|
  | 5 points at 30c (very good) | 1.1% | 0.090% | about 11,000 | 30 | 6 |
  | 3 points at 30c (good) | 0.4% | 0.010% | about 99,000 | 270 | 54 |
  | 5 points at 50c | 1.6% | 0.079% | about 12,500 | 34 | 7 |
  | No edge (the price is right) | 0 | 0 | never | - | - |

  - The last column is an upper bound: it compounds the bets one after another, while real bets on one night are placed
    together, on correlated weather, under the 15% open cap and live.py's $25 cap. That cap stops compounding entirely
    unless the user raises it.
  - With the very good 5-point edge, one year at one bet a night turns $50 into about $69; at three bets a night, about
    $134.
  - **The end rule comes first.** Even with the very good 5-point edge, a 25% fall from the peak happens within 365 bets
    about 34% of the time, and within 1,095 bets about 76% of the time (about 660 bets on average). That fall ends the
    real-money trial (live.py's end rule). The road to $1,000,000 ends the trial long before it gets there.
- **Market size:** Kalshi's daily rain markets traded about 1.4 million contracts in one day across all cities (snapshot
  of 2026-10-15). A single market's order book at any moment holds far less.
  - Bets of thousands of dollars would move the price against the bot.
  - So even a real edge stops growing somewhere in the thousands of dollars, long before $1,000,000.
- **The promotional $25:** check its terms on Kalshi (expiry, whether it or its winnings can be withdrawn).
  - live.py's cap is $25 at risk across the whole account (MAX_AT_RISK). With $50 in the account it still risks at most
    $25.
  - Using the credit means raising that cap, which only the user can decide (CLAUDE.md section 3).
- **A realistic aim, if an edge is ever confirmed forward:** grow the stake slowly, withdraw the original money once the
  account doubles (CLAUDE.md section 11a), and judge success in tens of dollars in the first year, not in millions.

## 11. What a result can lead to
- **Edge demonstrated on past data:** a forward plan (PLAN10F), written before its data. It would get HRRR at each evening
  scan and score on new markets.
  - It would need the nightly download set up, with the user's go-ahead.
  - Only after it confirms could the user consider HRRR for real money.
- **No edge demonstrated:** stop. The forward tests already running (PLAN7, PLAN8, PLAN9, the airport-forecast test) go on
  as written.
- **Real money:** nothing here touches live.py, its filters, its cap or its locks.
