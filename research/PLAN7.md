# PLAN 7: v3 with its rain lean corrected ("v5 candidate"), forward test (written before its data)

Written 2026-11-05 15:30 local (America/La_Paz), at the user's request ("intelligently implement your
recommendations"). Revised the same day after an independent statistics review and its re-check, still before any
forward data and before the fit (revision notes at the end).

Research and paper only: it changes nothing in the bot, v3, the gate, the stop date, the single look, live.py, the $25
cap or any limit. It places no order, and nothing in it can reach live.py.

**What the author knew when writing this.**
- The interim, descriptive look of 2026-11-04 (CHANGELOG): across 305 resolved v3 rain markets on 10 market days, v3 ran
  low on rain in its middle range (it said about 41%, and it rained 59% of the time). Kalshi's prices were close to
  calibrated, and interim pooled Brier was v3 0.094 vs Kalshi 0.069.
- That look is the reason for this plan. So the correction below is fitted on the test's own days (in-sample), and it is
  judged only on market days that had not happened when this was written. A market day from Nov 11 on is scanned on the
  evening before it, so no forward outcome exists yet.

**What the author did not do.** No correction was fitted, and no forward number was computed, before this plan was
frozen.

## 1. The question
Once v3's lean is corrected by a fixed rule, is the corrected forecast more accurate than Kalshi's price on new market
days? And would the bot's own trading rule, applied to it, make money on paper after costs?

The honest expectation, stated now: v3 was about 0.025 Brier worse than Kalshi's prices in-sample. A correction removes
only the part of that gap that comes from its lean. So the most likely results are a stop at the futility look, or
"Kalshi's prices were clearly more accurate". "No edge demonstrated" is the likely end, and a useful one.

## 2. The correction (fitted once, then frozen)
- **Form.** Logistic recalibration, the same form as the airport forecast's calibration in research/PLAN.md:
  - logit(q) = a + b * logit(p), where p is v3's own forecast (strategy.estimate already keeps it inside [0.01, 0.99];
    the same clip is applied again);
  - q is clipped to [0.01, 0.99];
  - one (a, b) for all cities.
- **Data.** Every resolved v3 rain market of the test's own market days, Oct 14 to Nov 10: the same obs rows as the
  gate's look (paper.db on the PC; obs.fc and obs.result, version v3, market_type rain).
- **Method.** Maximum likelihood (Newton's method), starting from a = 0, b = 1. Every market counts once (unweighted).
  The correlation between cities on one day makes the usual standard errors too small, but they are not used to decide
  anything.
- **When.** At the first settle on or after Nov 11 when every v3 rain market of the test's days has its result. A
  test-day market that never gets a result does not block it: from Nov 13 the fit runs on the resolved markets, and the
  ones left out are listed in the model file.
- **Recorded with it** (descriptive, never used to decide):
  - (a, b), the number of markets and days, and a SHA-256 of the rows used;
  - day-clustered standard errors of a and b, and their range when each market day is left out in turn (a correction
    driven by one wet spell shows up there);
  - how many forecasts sat at the clip bounds, and how many fit rows were logged outside the scan window;
  - the model versions of the test days' decisions (section 3).
- **Frozen.** The fit is written once to research/results/plan7_model.json and never refitted, whatever the forward data
  show (CLAUDE.md section 11a).
- **No fit, no test.** The test does not run, and the report says so, if any of these hold:
  - fewer than 100 markets or 5 market days;
  - no model version recorded for the test days;
  - Newton's method does not converge in 50 steps;
  - b <= 0.

## 3. Forward data
- **Source.** The PC's paper.db decision ledger (table decisions, strategy forecast_alpha.rain.v3, strategy_version
  v3). Its rows hold v3's forecast (p_model) and the bid and ask at the scan. After a failed look, v3 still logs every
  market (CLAUDE.md section 11), so the ledger keeps filling.
- **Market days.** From Nov 11 on.
- **One row per market.** The first decision row of the market that meets all of these:
  - p_model, bid, ask and the market's day start are present;
  - 0 <= bid < ask <= 1 and ask - bid <= 0.06 (the bot's spread filter);
  - the reason is not MARKET_STARTED;
  - its scan began inside the evening window: from 00:50 (inclusive) to 05:00 UTC (exclusive) on the market day,
    which is 8:50 PM to 1 AM La Paz the evening before. This is judged on the scan's start (table scans), as
    scan_window.py and PLAN6 B judge a scan; a row without its scan record is judged on its own time. The airport
    test's narrower 00:50-01:30 window is deliberately not used here;
  - its model_version (v3@ the hash of weather.py, nws.py and strategy.py) is one the test days' decisions carried.
    The correction fits one forecast, so the forecast code must not change under it.
- **Outcome.** obs.result (yes or no) for the same ticker and version.
  - A look waits while a counted day still has a market without a result less than 7 days old.
  - Older ones are left out and listed (a voided market cannot block a look).
- **v3's code stays as it is while this test runs.** docs/REFACTOR.md's stage 2 for the v3 path waits until PLAN7 ends.
  - The model version hashes all of weather.py, nws.py and strategy.py, so any byte change ends the forward data. That
    includes setting strategy.LOOK_DEADLINE (the user's decision if a test-day market is voided) and any fix to the gate
    look.
  - Rows with any version not listed do not count, and `plan7.py status` shows them by reason the next day.
  - **One narrow exception, decided now.** A new version counts only if an amendment is recorded in
    research/results/plan7_versions.json (version, reason, date) before the next look, with the user's approval, and
    with evidence:
    - weather.py and nws.py are byte-identical to the fit's: the model file records their SHA-256;
    - the strategy.py change lies outside the forecast path (estimate and the estimator list unchanged);
    - tests/golden.py shows no change, and a code review agrees.
    
    Nothing in plan7.py writes that list.
  - Without such an amendment, the data end at the change, and section 5's early-end rule applies.
- **Not used.**
  - The cloud trial copy. Its scans start later and less reliably, and one source keeps the test simple. This roughly
    doubles the calendar time on nights the PC misses.
  - The airport forecast, which has its own forward test (CLAUDE.md section 5b).
- **Rows not counted** are reported by reason at each look.

## 4. Measures
**A (primary): accuracy.** The gate's own day-mean statistic, with q in place of v3's forecast and the scan mid as the
market:
- Brier(q) minus Brier(mid) for each market, averaged within each market day, then the mean over days, its standard
  error and t;
- the t reading, with tcrit = Student-t 97.5%, days - 1 degrees of freedom, never below 2.0:
  - mean below zero by at least tcrit standard errors: "the corrected forecast was clearly more accurate than Kalshi's
    prices";
  - mean above zero by at least tcrit standard errors: "Kalshi's prices were clearly more accurate";
  - otherwise: "no clear difference", with the interval mean +/- tcrit x SE;
- weather runs in spells of several days, so A also reports:
  - the lag-1 correlation of its day series;
  - its own moving-block bootstrap 95% interval (blocks of 7 consecutive counted market days, not calendar weeks; 5,000
    draws, seed 11).

**A2 and A3 (secondary, descriptive).** The same statistic for v3's raw forecast against the market (A2), and for q
against v3 (A3: did the correction remove the lean?). Neither has a verdict.

**T: trading, one contract per signal.** The live bot's rule with q in place of v3's forecast:
- fair = 0.5 x q + 0.5 x mid;
- veto: no signal when |q - mid| > 0.30 (the bot's veto);
- **taker:** the side with the larger edge, YES at the ask or NO at 1 - bid. Signal when the edge is at least 0.08.
  Kalshi's taker fee for one contract, 0.07 x p x (1 - p), is rounded up to the cent;
- **maker (primary for T):** a limit order as in the shadow ledger and the airport-forecast test:
  - YES at the bid + 1c when that stays below the ask, else at the bid; NO likewise;
  - the side with the larger edge;
  - signal when the edge at the limit price is at least 0.08;
  - cancelled at the market's day start;
  - filled only if a whole minute candle after the order shows a trade or an offer at the limit price (strictly through
    it when the order joined the bid), judged on Kalshi's public minute candles;
  - maker fee 0;
- **maker on raw v3 (placebo, descriptive):** the same maker rule on v3's own forecast, on the same rows. It separates
  what the correction adds from spread capture or a market-wide lean;
- **P&L per contract:** 1 if the outcome matches the side, else 0, minus the price and the fee;
- **daily series:** the sum of that day's P&L over every forward market day, 0 on a day without a signal or fill (the
  airport-forecast test's definition);
- **reported:** the mean per day and its SE; from 14 days, the moving-block bootstrap 95% interval (as above).

**Candles.**
- Kalshi's minute candles for every forward market are stored once its day has started, before and after the fit, so
  the data do not depend on Kalshi keeping old history.
- A market still without candles 7 days after its day start, after at least 3 tries on separate runs (failed requests
  included), counts as not filled and is listed with the reason. Kalshi retiring the endpoint therefore cannot block a
  look forever.

**Pinned.** The rule values (blend 0.5, edge 0.08, spread 0.06, veto 0.30) and the functions (the gate's statistic and
t-table, the fill rule, the bootstrap, the taker fee) are copied into research/plan7.py when this plan is frozen. A later
change to config.py, gate.py or shadow.py cannot change how this test is judged. tests/test_plan7.py checked each copy
against its source on 2026-11-05.

## 5. Horizon, looks and verdict (decided now)
The test counts forward market days: days from Nov 11 on with at least one counted resolved market (section 3). There
are two looks and no others. In between, `plan7.py status` shows only counts.

**Futility look at 60 forward market days.** The test stops (no edge demonstrated) if either:
- A's mean is not below zero; or
- the maker arm's mean daily P&L is not above zero.

There is no early pass. The final look is refused unless the futility look was taken and said "continue" (enforced in
code).

**Final look at 110 forward market days.** "Correction confirmed on paper" only if all three hold:
- A's t reading is "clearly more accurate";
- A's block-bootstrap 95% interval lies below zero;
- the maker arm's bootstrap 95% interval lies above zero.

Anything else is "no edge demonstrated", and the idea stops (CLAUDE.md section 11a: no refit, no tweaked thresholds, no
extension). The taker arm, A2, A3 and the placebo are shown and never decisive.

**An early end is a failure, not a missing result.**
- **The backstop.** Market days after 2027-06-30 never count. If fewer than 110 counted days exist on or before that
  date, the final look is taken from 2027-07-07 (after the last days' results) and reads "not confirmed".
- **An early end.** If v3's logging ends, or its code changes without an amendment, before 110 counted days, the final
  look can be taken at once with --ended and reads "not confirmed".
- **In both cases,** with 60 or more counted days, the futility look is taken first.

**Read with the airport-forecast test.** A confirmation is always reported next to the airport-forecast test's own
result, with a Bonferroni line: would it also pass at 1.25% one-sided? That means all of these:
- for A, t at or beyond Student-t 98.75% (about 2.27 at 109 degrees of freedom), and A's bootstrap 98.75th percentile
  below zero;
- for the maker arm, the bootstrap's 1.25th percentile above zero.

Even "confirmed" is paper only. Any use of real money needs the user's explicit rule change and go-ahead (CLAUDE.md
sections 3, 3a and 11a), and this test never connects to live.py.

## 6. Expected precision and power (stated before the data)
The planning figures come from the scored holdout (research/results/rain_backtest.json, 81 market days). The SE is the
one the code uses: the SE of the day means.

**A: accuracy.**
- **Planning figure.** The calibrated airport forecast minus market had a day-level SD of 0.028 Brier (SE 0.0031 over
  81 days). A single forecast against the market varies about 1.5 times as much as the blend did (SD 0.018).
- **SE:** about 0.0036 at 60 days and 0.0027 at 110.
- **Pass threshold at 110 days.** tcrit is 2.0, so A reads "clearly more accurate" only when the corrected forecast
  beats the market by about 0.0053 Brier or more. That is about 7% of the market's Brier (0.073 in the holdout).
- **Power before the futility look and the other two conditions, which lower it further:**
  - no real difference: about 2.5%;
  - a true edge the size of the past blend's (0.0026 Brier, 3.6% of the market's Brier): about 15%;
  - a true edge of 0.005 Brier: about 45%;
  - 80% power needs a true edge of about 0.0075 Brier (about 10%).
- v3's own spread may differ from the airport forecast's. If it is wider, every figure above is optimistic.

**Maker arm.**
- **Planning figures.** In the holdout, maker profit per market day had an SD of about $0.63, with about 1.9 fills a
  day. That was a different forecast, without the veto, so the fill rate here may differ.
- **SE at 110 days:** about $0.060 per day, about 3c a contract.
- **Pass threshold:** the bootstrap interval lies above zero only for about 6c a contract or more, and 80% power needs
  about 9c.
- **Power for the past lead's honest size** (3-6c after the earlier review): about 15% to 45%.

**Both conditions together.** If A and the maker arm are roughly independent, the chance of "confirmed" is:
- about 2-7% at the past lead's size;
- about 20% for an A edge of 0.005 with a 6c maker edge.

The futility look alone stops a real effect of the past lead's size about 40% of the time.

**Calendar.**
- If the PC scans every night, the futility look comes about 2027-01-09 and the final look about 2027-02-28.
- Every missed night pushes both later.
- 110 counted days by the backstop (2027-06-30) need the PC to scan about 47% of nights (110 of 232). It scanned 5 of
  the first 16 test nights and every night since Oct 29, so the backstop may bind if the laptop's scanning slips
  again.

**The likely result,** stated plainly: a stop at the futility look, or "Kalshi's prices were clearly more accurate".
Even if the correction works as well as anything seen so far, "confirmed" is unlikely at this size. A "no clear
difference" reading rules out only large advantages.

## 7. Multiplicity and caveats
- **Two forward candidates now run on the same markets:** this test and the airport-forecast test.
  - Each confirmation is at most about 2.5% one-sided by chance. That is an upper bound: when neither forecast has any
    edge, the three-part rule is far stricter.
  - Up to about 5% that at least one of the two confirms by luck (less, since they share markets and are positively
    correlated).
  - Hence the Bonferroni line in section 5. A confirmation is never read without the other test's result.
- **The season changes.** The fit days are autumn; the forward days run into winter and spring. A failure cannot tell
  "the lean was noise" from "the lean was seasonal". A pass would show only that the correction carried over to those
  days.
- **Correlation:** cities on one day share weather, so the effective sample is the number of days, not markets.
- **Fills are optimistic:** paper fills ignore queue size, and taker fills assume the quoted size was there.
- **Laptop dependence:** the forward data depend on the PC scanning, and nights it misses are missing days.
- **The fit's rows and the forward rows differ a little.**
  - The fit uses obs first snapshots from any scan time, while forward rows come only from scans inside the window.
    The model file counts the fit rows logged outside the window, and the report prints that count.
  - The audit ledger's recording of p_model, bid and ask is not covered by the model-version hash.

## 8. How it is produced
**research/plan7.py.** It opens paper.db read-only and writes only its own files:
- research/results/plan7_model.json;
- plan7_score_60/110.md and .json;
- the candle store, research/data/plan7/candles (one gzip file per market day, compacted to the fields the fill rule
  reads).

**File safety.**
- Each day file is written atomically and retried while Windows holds it.
- An unreadable day file (any damage) is moved aside, never deleted, and the off-folder copy is read instead.
- The model and the day files are also copied to the off-folder backup (Documents\tradebot_backups\plan7, where
  backup.py already keeps paper.db):
  - a day file there is never replaced by one holding fewer markets;
  - the frozen model there is never replaced;
  - a model missing here is restored from there, never refitted.

Commands:
- **candles:** store candles for forward markets whose day has started, each market once. It reads Kalshi's public
  candlesticks (the domain the bot already reads).
- **fit:** once, refused when the model file exists.
- **auto:** candles, then the fit when section 2's condition holds. The settle job runs it (run.bat settle); it never
  scores and never fails the job.
- **status:** counts only: forward days, markets, candles stored. No outcome-based number.
- **score --look 60|110 [--ended REASON]:** run by hand at each look, each once. It counts only market days up to the
  backstop date, refuses an early look, and refuses the final look before a futility look that said "continue". With
  --ended, or from 2027-07-07 with fewer than 110 counted days, the final look reads "not confirmed".

tests/test_plan7.py covers it on fake data:
- the pinned copies equal their sources;
- a planted lean is recovered, and the null case;
- refit refused, and the Nov 13 fallback;
- the forward filter, including scan start and model version;
- the candle store: retry, and "none" after 7 days;
- the looks' order;
- early end and backstop;
- read-only use of paper.db.

## Revision notes
- **2026-11-05, about 17:30 local.** Independent statistics review (agents/statistician.md), applied before any forward
  data or fit. The reviewer saw no outcomes beyond the interim numbers quoted above.
  - **MUST items applied:**
    - the rule is pinned in plan7.py (copies checked against their sources);
    - forward rows must carry a model version of the test days, and v3's code stays unchanged while the test runs;
    - the final look is refused unless the futility look said "continue".
  - **SHOULD items applied:**
    - section 6 rewritten. The old guide figure, 0.035, was two standard errors, not one: an error carried over from
      PLAN6's precision note. It was an SD derived from the two-standard-error column (0.0039), so it was twice the
      right SD of 0.018 for blend minus market. A single calibrated forecast minus market has SD 0.028. Section 6 now states power, the maker arm's power, the calendar, and the likely
      result honestly;
    - an early end or a shortfall by the backstop date (2027-06-30) reads "not confirmed";
    - the fit runs from Nov 13 even if a test-day market never resolves;
    - candles are stored as soon as each day starts, and a market without candles after 7 days counts as unfilled;
    - a concrete Bonferroni line next to the airport-forecast test;
    - A's day-to-day correlation and block-bootstrap interval, the latter now required for "confirmed".
  - **NICE items applied:**
    - the fit's descriptive checks;
    - clip and window counts;
    - the scan window judged on the scan's start;
    - exclusions reported by reason;
    - the raw-v3 maker placebo;
    - wording on blocks and the blend's 3.6%;
    - the cloud copy left out, stated.
- **2026-11-05, evening.** The statistics re-check confirmed M1-M3, S1, S3, S4 and S5 as resolved, the power arithmetic
  correct, and the PLAN6 erratum correct. Applied:
  - **MUST:** the backstop is now enforced in code. Market days after 2027-06-30 never count, and a shortfall reads "not
    confirmed" from 2027-07-07 (sections 5 and 8 now agree).
  - **SHOULD:**
    - the brittleness of the model-version rule is stated, with one narrow amendment procedure;
    - status shows rows not counted, by reason;
    - the calendar states the scan rate the backstop needs.
  - **NICE:**
    - the Bonferroni line includes A's bootstrap;
    - "2.5%" is called an upper bound;
    - exclusions are counted on the look's days only;
    - market_day and the bot's date are pinned copies;
    - the fit-versus-forward window difference is reported;
    - this revision note's wording is fixed;
    - the joint power is stated.
- **2026-11-05, evening, code review (agents/code-reviewer.md)** of plan7.py, run before any forward data. It found the
  pinned copies faithful and the fit's numerics right. Applied:
  - **MUST:** a decision row without a day start is not counted (reason no_day_start); before, it could block both
    looks.
  - **SHOULD:**
    - the no-candles rule applies after 3 tries, whatever the cause;
    - auto runs each step on its own;
    - day files use their own temp names, retry on Windows locks, and an unreadable one is moved aside;
    - only a missing table means "no model versions";
    - a failed fit is reported at every run;
    - the model and the candles are copied off the folder.
  - **NICE:**
    - a look waits for pending results (older than 7 days: left out and listed);
    - KALSHI_BASE is honoured;
    - the clustered SEs get the small-sample correction.
- **2026-11-05, evening, code re-check.** It confirmed the earlier items fixed. Applied:
  - **MUST:**
    - damage only zlib notices is now treated as an unreadable day file;
    - the off-folder copy can no longer be overwritten by an emptier store or a refit. A lost local file is read
      from, or restored from, the off-folder copy.
  - **SHOULD:**
    - the repository's workflow copies are compared in both directions;
    - tests for corruption, a lost local copy and the Windows-lock retry.
  - **NICE:**
    - looks wait on pending results of any forward day up to the last counted one;
    - only a missing scans table is tolerated;
    - no temp file is left when a write gives up;
    - an empty error message still counts as a failed request;
    - moved-aside names are unique.

**Frozen 2026-11-05 16:30 local, before any forward data and before the fit.** research/plan7.py SHA-256 7526b84c9a870ba014fb379e5a2a8ccc25d7ecaa7c0781ff9f453327c9528068.
