# PLAN 8: Kalshi's price first, the airport forecast as a small correction (forward test, written before its data)

Written 2026-11-06 at about 01:35 local (America/La_Paz), at the user's request ("intelligently implement your
recommendations above", after the question "would you implement other forecast skills, tools or resources for a higher
success?"). Revised twice the same day, still before any forward data and before the fit (revision notes at the end):
- at about 01:45, after an independent statistics review;
- at about 17:20, after a statistics re-check and a code review.

Research only: it changes nothing in the bot, v3, the gate, the stop date, the single look, live.py, the $25 cap or any
limit. It places no order and has no trading rule; nothing in it can reach live.py.

**What the author knew when writing this.**
- **The earlier past-data test** (research/PLAN.md, scored once on 2026-10-14):
  - Kalshi's price scored Brier 0.0730; the calibrated airport forecast 0.0740; their 50/50 mix 0.0711.
  - The 50/50 mix was judged "not clear".
- **The exploration for this plan** (2026-11-06): the model of section 2, fitted on the same 1,711 past markets (81
  market days):
  - **Fitted and scored on all 81 days:** a = -0.047, weight on the price 0.753, weight on the forecast 0.447. The mean
    day Brier difference against the price is -0.0028 (day SD 0.0151, t about -1.66).
  - **Fitted on the first 40 days and scored on the last 41:** weights 0.742 and 0.453. Difference -0.0012 (SD 0.0060,
    t about -1.25).
  - **The control (the price recalibrated alone), the same split:** -0.0001 (t about -0.16). The mix against the
    control: -0.0010 (SD 0.0071).
- **What the exploration does and does not show:**
  - **The size of the gain:** none of these differences is clear on its own. The in-sample mix (-0.0028) is only a
    little better than PLAN.md's 50/50 mix (-0.0026), which was judged "not clear". So this is a new idea under
    CLAUDE.md section 11a, tested on new data, not a confirmed lead.
  - **Where the gain came from:** the weights hardly moved between the two fits, so the difference between -0.0028 and
    -0.0012 is mostly a difference between periods. The gain was concentrated in July and August showers. For November
    to February, 0.0012 is closer to an optimistic guess than a central one.
- **The live paper test (Oct 14 on):** the forecasts disagreed with Kalshi and lost. The airport forecast's own paper
  trades are about -12 cents a contract so far. Those are trades on disagreements, not this plan's measure.
- **What the author did not do:** no forward market day of this plan exists yet. The first one is scanned on the evening
  of Nov 6, after the freeze (section 3).

## 1. The question
Does a fixed mix of Kalshi's price and the calibrated airport forecast, with the price in charge, give more accurate
rain probabilities than the price alone on new market days? And is the gain the forecast's, not merely a recalibration
of the price?

**Why it matters.** The answer decides whether adding more forecast sources is worth proposing. HRRR is the example: the
weather service's hourly-updated short-range model, which needs the user's approval for a new data site and a package.

**What a result means:**
- **A confirmed result** is only an accuracy result, not a profit result (section 8).
- **A failed test** is not proof that the forecast carries no information, because the test's power is low (section 6).
  Not pursuing more forecasts afterwards is a policy choice.

**The honest expectation.** The effect seen on past data was small: 0.001 to 0.003 Brier, which is 2 to 4% of the
price's own Brier score. With the full rule (section 6), if the effect is like the half-split's:
- **The main test passes:** about 42%, or about 13% if the day-to-day noise is as large as in the summer data.
- **Both the main test and the attribution test pass:** about 20%, or about 5%.
- **The HRRR condition is met:** about 11%, or about 2%.

A summer-only effect makes all of these lower. "No edge demonstrated" is the likely end, and a useful one.

## 2. The model (fitted once, on past data, then frozen)
**Notation.** L(x) = logit(clip(x, 0.01, 0.99)), with:
- m: Kalshi's mid price, (bid + ask) / 2;
- s: the calibrated airport forecast (stationfc.py; the same formula and frozen coefficients as research/backtest.py,
  research/results/rain_model.json).

**The two models:**
- **The mix:** logit(q) = a + b_m L(m) + b_s L(s), with q clipped to [0.01, 0.99].
- **The control (the price recalibrated alone):** logit(q0) = a0 + c L(m), with q0 clipped the same way.

**Fit data.** Exactly research/PLAN.md's holdout rows:
- every settled KXRAIN market in research/data/kalshi_rain.jsonl (Jul 15 to Oct 12, 2026);
- with its quote at the 00:55 UTC scan time: 0 <= bid < ask <= 1 and ask - bid <= 0.06;
- with an airport forecast from the archived NBS evening run (research/backtest.py's features);
- the outcome y = 1 when the market resolved yes.

The control is fitted the same way on the same rows, which is what the attribution measure B needs.

**Method.** Maximum likelihood by Newton's method:
- start values: (0, 1, 0) for the mix and (0, 1) for the control;
- converged when every step is below 1e-10, within 50 steps;
- every market counts once.

**When.** Once, by `plan8.py fit` on the PC, before the first forward window opens (00:50 UTC on FORWARD_FIRST). A dry
run of the fit code on 2026-11-06 saved nothing; it read 1,711 markets on 81 days, found 0 rows where the archive's and
the live formula disagree, and gave the weights quoted above.

**The fit refuses, and saves nothing, in any of these cases.** Each can be fixed and the fit run again:
- the data is not exactly the holdout: 1,711 markets on 81 days, each ticker once, with 0 formula disagreements (a
  missing or partial data folder looks like this);
- the first forward window has opened (FORWARD_FIRST must then move first, section 3);
- PLAN7's shared code differs from the pins.

The result is frozen in research/results/plan8_model.json, with:
- the number of rows and days;
- a SHA-256 of the rows;
- the code identity of section 3.

**Keeping it whole.** It is copied off the folder (Documents\tradebot_backups\plan8), and it is never refitted. The
settle job's step keeps both copies whole:
- a lost local copy is restored from the off-folder copy;
- a damaged local copy is renamed aside and restored;
- a missing off-folder copy is made again from the local one;
- an existing off-folder copy is never replaced.

**The fit fails, and the test does not run (frozen as failed), only when:**
- Newton's method does not converge;
- or b_m <= 0 or b_s <= 0 (with no positive weight on the forecast there is nothing to test).

**Descriptive only, stored with the model:**
- day-clustered standard errors;
- the range of each coefficient over fits that leave out one calendar week at a time;
- the in-sample Brier scores.

**Summer weights in winter.** The weights are not refitted for winter. If winter needs other weights, the frozen mix is
worse than the best mix, which pushes the result toward "no gain". It can cause a false negative, never a false pass.

## 3. Forward data
**Source.** The PC's paper.db, never the cloud trial copy: its table v4_obs, shadow.py's nightly log of the airport
forecast. It stores, per rain market:
- the first log time;
- s, the forecast (fc);
- the bid and ask at that moment;
- the day start;
- the result, filled in at settle.

It does not depend on v3's forecast or on the gate, and it continues after a failed gate look (CLAUDE.md section 11).
A result missing from v4_obs is taken from paper.db's market_results, the settle's own record, when that has one.

**A market is counted when all of these hold:**
- Its market day is from FORWARD_FIRST = **2026-11-07** to BACKSTOP = 2027-06-30. Nov 7's evening scan starts at
  8:55 PM on Nov 6, after this plan is frozen. If the freeze slips past 8:50 PM on Nov 6, FORWARD_FIRST is the first
  market day whose scan window opens after the freeze, and the frozen plan8.py states it. The fit enforces this: it
  refuses once FORWARD_FIRST's window has opened.
- **It was logged inside the primary window,** which matches the fit's 00:55 UTC quotes and the airport-forecast test's
  rule: 00:50 (inclusive) to 01:30 UTC (exclusive) on the market day, that is 8:50 to 9:30 PM La Paz the evening before.
  It was also logged before its day start.
- s is present.
- 0 <= bid < ask <= 1 and ask - bid <= 0.06.

**The late window.** A market logged later inside the scan window (01:30 to 05:00 UTC, a make-up run) is not counted. Its
price may already reflect the 00 UTC model runs while s is still the 18 UTC run. Those markets are counted separately
for the sensitivity reading of section 4.

**The day set.** It is fixed from counted markets, not from results:
- the forward days are the market days with at least one counted market, in day order;
- a look uses exactly the first 60 or 110 of them;
- each market counts once;
- markets passed over are counted by reason, and the look reports the counts.

**Coverage needed.** Reaching 110 forward days by the backstop (236 market days from Nov 7 to Jun 30) needs at least
47% of evenings logged inside the primary window.
- Since Oct 27, every evening the PC scanned was logged at 00:56 to 00:58 UTC, inside it: 9 of the 11 evenings to Nov 6.
- The two earliest logged evenings fell outside it: Oct 24 at 07:31 UTC and Oct 25 at 03:56 UTC.
- An evening the PC misses is lost to this test. The cloud trial copy does not count.

**Code identity.** The SHA-256 of each of these is stored with the model. Line endings are normalized and the functions
are read with Python's ast module, never imported for this:
- the forecast's own code, stationfc.py: sig, logit, num, evening_run, features, predict, load_coef;
- its coefficients, research/results/rain_model.json "coef";
- the functions that log it, its prices and its day start: shadow.py v4_log and _t, kalshi.py quote and _p;
- this plan's own rule and text, research/plan8.py and research/PLAN8.md (whole files);
- the PLAN7 functions and constants this plan reuses, including its time zone (section 8). These are pinned in plan8.py
  itself.

**Changed code.** Each look compares the identities with the stored ones.
- A difference refuses the look until it is resolved.
- The only resolution is an amendment in research/results/plan8_amendments.json, made with the user's approval:
  {"amendments": [{"name", "sha256", "reason", "recorded"}]}. It needs evidence that the forecast values and the
  logged fields are unchanged.
- Nothing in plan8.py writes that file.

## 4. Measures
All day statistics use the gate's own construction (gate.margin, through PLAN7's pinned copy). The per-market value is
averaged within each market day, because cities on one day share weather, and the days are then averaged.

**Two readings and one interval are used throughout:**
- **The own-line reading, "clearly":** the mean is below 0 by at least tcrit x SE. tcrit is the Student-t 97.5% value
  for days - 1 degrees of freedom, never below 2.0; at 60 and 110 days it is 2.0, as in the gate.
- **The three-test reading:** the mean is below 0 by at least t(0.833%, days - 1) x SE, and the bootstrap's 99.17%
  upper bound is below 0 (section 7).
- **The bootstrap:** a 7-day moving-block bootstrap of the mean of the day series (5,000 draws, seed 11; with 14 or more
  days). It guards against correlated neighbouring days.

**The measures:**
- **A (primary): the mix against the price.** Brier(q) - Brier(m), per market, then per day. It is reported with:
  - both readings;
  - the bootstrap's 95% interval;
  - the series' day-to-day (lag-1) correlation.
- **B (attribution): the mix against the control.** Brier(q) - Brier(q0), with the same readings and bootstrap. It says
  whether a gain belongs to the forecast or only to recalibrating the price.
- **A0 (descriptive): the control against the price.** Brier(q0) - Brier(m).
- **A-late (sensitivity, descriptive):** A on the same days, with the late-window markets of section 3 added. The number
  of late markets is reported with it.
- **Also descriptive:**
  - the pooled Brier scores of m, s, q and q0;
  - the mix refitted on the counted forward markets (final look only). It helps tell "the frozen weights were wrong" from
    "the forecast carried nothing"; it is never used for the verdict.

**Clipping.** q and q0 are clipped to [0.01, 0.99]; m is not. On average that costs the mix a tiny amount of Brier on
near-certain markets. It helps the mix only when a near-certain price turns out wrong, which is rare.

## 5. Horizon, looks and verdict (decided now)
**Two looks, each taken once by hand.**

**1. Futility look at 60 forward days.** The test stops ("no edge demonstrated") if A's mean is 0 or above. Otherwise it
continues.
- It stores and shows A's mean only, with the counts: no standard error, no reading, no B and no other measure.
- It stores a SHA-256 of its counted markets' logged inputs.

**2. Final look at 110 forward days. The verdict, in a fixed order:**
1. **The main test.** A is confirmed only if:
   - A reads "clearly";
   - and A's bootstrap 95% upper bound is below 0;
   - and the code identity holds (or is amended).

   Otherwise: "no edge demonstrated: the idea stops" (CLAUDE.md section 11a: no re-tuning, no extra month).
2. **The attribution, only if A is confirmed.** "The forecast's own share is clear" needs B to read "clearly" and B's
   bootstrap 95% upper bound to be below 0. Judged only after A passes, in this order, it needs no extra allowance for
   multiple testing.
3. **The condition for proposing the HRRR plan:** A and B both pass the three-test reading (section 7). A confirmed A
   that misses this line is reported as such; it does not support the proposal.

When A is not confirmed, including an early end, B is reported as "not judged", with no reading.

The looks' results are written to research/results/plan8_score_<look>.json and .md, never into this file. Any edit to
this file or to plan8.py after the fit stops every look until an amendment is recorded (section 3).

**Backstop:**
- market days after 2027-06-30 never count;
- from 2027-07-07, a final look with fewer than 110 forward days reads "not confirmed";
- `--ended REASON` (the nightly log stopped for good) also reads "not confirmed".

**Look discipline:**
- Looks use the PC's paper.db. The database path is recorded with each look.
- `--ended` applies to the final look only.
- Each look is taken once. Its result files are copied off the folder, and a look whose off-folder copy exists is
  refused even if the local copy was lost.
- The final look refuses unless its first 60 forward days' markets are the ones the futility look counted (the stored
  SHA-256).
- A look is refused before its number of forward days exists.
- It is refused while its last counted day is fewer than 7 days ago.
- If a market of the counted days still has no result, the look also needs proof that a settle ran after that 7-day
  mark: a result recorded in paper.db's market_results after the mark. The markets still without a result are those
  Kalshi has not resolved or has voided; they are left out and listed.
- The final look needs the futility look first.
- There is no other look: `plan8.py status` shows counts only, never an outcome-based number.

## 6. Expected precision and power (stated before the data)
From the past-data exploration (the notes at the top):
- **Day-level SD of A:** 0.006 to 0.015; of B, 0.007 to 0.017.
- **Correlation between A and B day by day:** 0.68 to 0.93.
- **Lag-1 correlation of A:** -0.33 and -0.06 (negative in both fits).
- **A real effect:** perhaps 0.001 to 0.003. The half-split value, 0.0012, is the more honest one, and may be optimistic
  for winter.
- **At 110 days:** SE = SD / sqrt(110), which is 0.0006 to 0.0014. The own-line bar is mean < -2.0 x SE, that is below
  -0.0011 to -0.0029.

**Approximate power at the final look (simulated, days with a lag-1 correlation of +0.3).** The full rule includes
the bootstrap and the futility look:

| Effect and SD | A, full rule | A and B, own line | A and B, three-test line (the HRRR condition) |
|---|---|---|---|
| half-split effect (A -0.0012, B -0.0010), half-split SD | about 42% | about 20% | about 11% |
| the same effect, in-sample SD | about 13% | about 5% | about 2% |

- **The t conditions alone** give 51%, 30% and 20% (first row) and 19%, 9% and 5% (second row). The bootstrap and the
  futility look cost A about 10 points, and they roughly halve the HRRR line.
- **With no effect at all:** under the same correlated days, the t condition alone passes about 7% of the time (nominal
  2.5%). Adding the bootstrap brings it to about 4%. The observed negative lag-1 makes this smaller.
- **Smallest effect A finds 80% of the time:** about 0.27 x SD (0.0016 to 0.0041), with independent days.
- **Futility look at 60 days:**
  - A real effect of 0.0012 is stopped by mistake about 13% of the time with the half-split SD, and about 34% with the
    in-sample SD (lag-1 +0.3). With independent days these are 6% and 27%.
  - With no effect, the test stops there about half of the time.
- **The season changes.** The forward months are November to February: winter rain from fronts, not the summer showers of
  the fit data. That can move both the SD and the effect.

## 7. Multiplicity and caveats
**Three tests on the same markets.** Three forward tests now run on the same rain markets:
- the airport forecast's limit-order test (shadow.py, CLAUDE.md section 5b);
- PLAN7;
- this plan.

**The three-test line.** This plan's own verdict uses the own line. The three-test line is 0.025 / 3, one-sided:
- t at 0.833% for days - 1 degrees of freedom;
- the bootstrap's 99.17% upper bound below 0.

The three-test line decides the only consequence a confirmation has, the HRRR proposal (section 5). It is conservative
here, because this plan and the airport-forecast test share the forecast, the prices and the days.

**PLAN7.** PLAN7's own line (1.25%, for two tests) was frozen before this plan existed and is unchanged. Read PLAN7 with
three tests in mind.

**Overlap with the airport-forecast test.** This plan uses the same forecast as the airport-forecast test, but asks a
different question: accuracy with the price in charge, not trading on disagreements.

**Caveats:**
- **The fit came from a different season** (July to October) and an earlier price history.
- **Kalshi's traders may change.** If they start using this forecast better, the forecast's weight is too high, and the
  test reads that as no gain.
- **The effective sample is the number of days,** not the number of markets.

## 8. How it is produced, and what a result means
**Code.** research/plan8.py (Python 3.8+, standard library only, no network):
- `fit`: once, section 2;
- `status`: counts only;
- `score --look 60|110 [--ended REASON]`;
- `auto`, which the settle job runs after PLAN7's (run.bat settle): it keeps the frozen model and its off-folder copy
  whole (section 2) and prints the status line. It never fits, never scores and never fails the job.

**What it reads.**
- **paper.db:** opened read-only. It reads v4_obs, plus market_results for results missing from v4_obs and for the
  settle check.
- **The past data:** read only by `fit`.

**What it writes.** Only research/results/plan8_model.json and plan8_score_<look>.json/.md, plus their off-folder
copies, which are never replaced. A damaged model is renamed aside, never deleted.

**Reused code.** It reuses PLAN7's pinned implementations of:
- the gate's day-mean statistic, tcrit, the moving-block bootstrap and the t quantile;
- the window test and logistic helpers.

They are imported from research/plan7.py, and their source hashes are pinned (section 3), so a later change to PLAN7
cannot change how PLAN8 is judged.

**What a confirmed result means.** Only that the price with the airport forecast mixed in was more accurate than the
price on new market days.
- **It does not mean money.** An accuracy gain of 0.001 to 0.003 Brier is far smaller than the edge a trade needs after
  the spread and fees, and this plan has no trading rule.
- **What it allows:** proposing the HRRR plan, its own pre-registered test (it needs the user's approval for the data
  site and the package), and only under the condition of section 5.
- **What it never allows:** changing the bot, v3, the gate or live.py. That needs the user's explicit rule change.

**A failed or stopped test.** No information beyond Kalshi's price was demonstrated. Because power is low, that is not
proof of none. Not pursuing more forecasts of the same kind then is a policy decision, made because the expected gain is
too small to be worth the cost.

## Revision notes
- **2026-11-06 about 01:45, after the statistics review (before any forward data, and before the fit was run):**
  - **B's rule is now complete:** "clearly" plus the bootstrap upper bound below 0, judged only after A is confirmed.
    The HRRR condition needs A and B to pass the three-test line (review MUST 1 and SHOULD 5).
  - **The opening notes** now give the t values, the period difference, the closeness to PLAN.md's 50/50 mix, and the
    "new idea, not a confirmed lead" status (SHOULD 1).
  - **Power** is restated for correlated days and for A and B together, and the null false-pass rate is given
    (SHOULD 2).
  - **The primary window** is now 00:50-01:30 UTC, matching the fit and the airport-forecast test; the late window is
    reported as a sensitivity reading (SHOULD 3).
  - **The day set** is fixed from counted markets, not results. A look needs its last day 7 days past and, while any
    result is missing, a settle recorded after that mark; a result missing from v4_obs is taken from market_results
    (SHOULD 4).
  - **Notes on summer weights, clipping and what a stop means** were added, and so was a descriptive refit at the final
    look (NOTE items).
- **2026-11-06 about 17:20, after a statistics re-check and a code review (before any forward data, and before the fit
  was run):**
  - **Power** is now given for the full rule (bootstrap and futility look included), and the futility stop rates for
    correlated days (re-check MUST 1).
  - **This plan's own rule and text** (plan8.py and PLAN8.md), kalshi.py's quote and PLAN7's time zone are in the code
    identity checked at each look (re-check SHOULD 1; review NOTE).
  - **The data a look uses is fixed** (re-check SHOULD 2; review NOTE):
    - the PC's paper.db only, with its path recorded;
    - a hash of the futility look's markets, checked at the final look;
    - result files copied off the folder;
    - once-only even after a local loss.
  - **The fit enforces FORWARD_FIRST** (re-check SHOULD 3; review SHOULD).
  - **The futility look shows A's mean only, and B is "not judged" unless A passes** (re-check SHOULD 4).
  - **Coverage** needed for 110 days, and the observed log times, are stated (re-check SHOULD 5).
  - **The fit refuses, saving nothing,** unless the data is exactly the holdout. A missing data folder had frozen the
    test as failed (review MUST). A damaged model is repaired from the off-folder copy (review SHOULD).
  - **Other changes:** --ended is final-look only; each past-data ticker counts once; the clipping and window wording was
    corrected; the times above were corrected (the first draft had stated 02:30 and 04:30; the file times show about
    01:35 and 01:45).
- **2026-11-06 about 17:24, after a final verification by a fresh reviewer (no must-fix):** B is "not judged" on an early
  end too; the futility look stores A's mean without its standard error; kalshi.py _p and shadow.py _t are in the code
  identity; results never go into this file.

**Frozen 2026-11-06 17:24 local, before the fit and before any forward data.** research/plan8.py SHA-256 2c0d027d400a4a702a6d400dfcb06aad2cbb02b7c3d354ef001613f2e6ff1bad. Any later
edit to this file or to plan8.py stops every look until an amendment is recorded (section 3).
