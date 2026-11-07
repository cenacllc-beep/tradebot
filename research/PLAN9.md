# PLAN9: v3's hourly chances combined in 6-hour blocks, tested on new markets

Written 2026-11-06, 22:00 La Paz, before any forward data. Revised 2026-11-07 morning after an independent statistics
review and a code review, still before any forward data.

Research only: never part of the gate and never connected to live.py. A result can lead only to a proposal and a fresh
test, never straight to the bot (CLAUDE.md section 11a).

**Freeze.** The first forward market day is Nov 8. Its markets are logged by the evening scan of Nov 7, which starts
after this plan and its code are deployed and frozen.

**Fully free data.** The user asked on 2026-11-06 for open-source and then "fully free" options, so this plan uses only
data the bot already logs every evening from the US National Weather Service. That data is public domain and free for
any use. A second test with Open-Meteo's ensemble API was drafted and dropped before the freeze, because its free tier
is for non-commercial use only.

NOAA's National Blend of Models is the fully free ensemble source. It is already logged nightly as the airport
forecast and tested by PLAN8 and the airport-forecast forward test (CLAUDE.md section 5b).

## 1. The questions
- **B.** Is **v3-6h** (section 3) more accurate than **v3** as it is?
  - v3-6h is never lower than v3 on any market, so B passes whenever v3 runs low.
  - It cannot show *why* v3 runs low.
- **A.** Is v3-6h more accurate than Kalshi's price?

Expected results:
- **B:** likely confirmed only if v3's autumn lean persists into winter. The in-sample gain is inflated by having
  chosen v3-6h among six rules.
- **A:** not confirmed. Kalshi's price beat every forecast on the first 13 market days.

## 2. Where the idea comes from (honest record)
- **Six rules were compared.** On 2026-11-06 six ways of combining v3's hourly chances were compared on the test's own
  data: 407 resolved rain markets, 13 market days, Oct 14 to Nov 6, unclipped. The Brier scores (lower is better):

  | Rain chance | Brier |
  |---|---|
  | Kalshi's price | 0.0666 |
  | v3 as it is (mean of the half-days' maximum and their union) | 0.0828 |
  | The highest hour of the whole day | 0.0907 |
  | The two half-day maxima treated as independent | 0.0778 |
  | **Four 6-hour block maxima treated as independent (v3-6h)** | **0.0755** |
  | Eight 3-hour block maxima treated as independent | 0.0887 |
  | Every hour treated as independent | 0.1542 |

- **How v3-6h did against the price:** 0.0084 ± 0.0053 worse, day-clustered. When it said 30-80% (mean 54%), it
  rained 53%, where v3 said 55% and it rained 72%.
- **Only new markets can test it.** Choosing among six rules on the same days makes the in-sample result a screen, not
  evidence.
- **Two known weaknesses:**
  - Treating the blocks as independent can count one rain event twice: a front spanning blocks, or an NWS period that
    straddles a block edge.
  - The block edges fall at 05-08 UTC, depending on the time zone.
- **The related tests are separate:**
  - PLAN7 corrects v3 statistically: one fitted curve on its output.
  - PLAN9 changes how v3's inputs are combined, with no fitting.
  - Both target the same lean, so if both are confirmed they are not two independent results.

## 3. Definitions (fixed now)
- **v3's hourly chances.**
  - These are the 24 numbers v3 logs for each rain market (paper.db obs.slices, version v3). Each is the highest NWS
    chance of precipitation overlapping that hour of the Kalshi day, in percent, hour 0 being the day start.
  - The code that makes them (weather.py's `_rain_v3`, nws.py) is frozen and checked at each look (section 8).
- **v3-6h.**
  - Split the 24 hours into four blocks: hours 0-5, 6-11, 12-17 and 18-23. Take each block's highest chance.
  - Then v3-6h = 1 - (1 - b1)(1 - b2)(1 - b3)(1 - b4), with chances as fractions.
  - It is clipped to [0.01, 0.99], like v3 (strategy.estimate), so dry markets do not give it a free edge.
  - A market without exactly 24 numeric chances from 0 to 100 is left out.
- **v3.** obs.fc, the forecast the gate scores.
- **Price.** obs.mid: Kalshi's mid at the v3 scan, the same price the gate scores.
- **Outcome.** Kalshi's yes/no result, from obs.result, else paper.db's market_results. Scalar and void markets are
  left out, as the gate leaves them out.

## 4. Which markets count
- Market days from **2026-11-08** to **2027-06-30** (the backstop). Later market days never count.
- Each market's v3 row (version v3, market type rain) must meet all of these:
  - its own log time (obs.ts) falls inside the evening window, 00:50 to 05:00 UTC on the market day (PLAN7's window);
  - it has a price and a v3 forecast;
  - it has usable hourly chances (section 3);
  - it has a yes/no result.
- Both tests use the same markets. Each look reports the excluded markets by reason, for the look's own days.

## 5. The statistic
- **Per test,** the gate's day-mean statistic:
  1. For each market, v3-6h's Brier score minus the reference's Brier score. The reference is v3 for B and the price
     for A.
  2. Average within each market day.
  3. Report the mean over days and its standard error.
- **The bootstrap:** a moving-block bootstrap of the day means over consecutive counted market days. Blocks of 7 days,
  5,000 draws, seed 11 (PLAN7's `boot_means` and `boot_interval`).
- Every function and constant reused from research/plan7.py is pinned by a SHA-256, including PLAN7's t table.
- **Two readings at the final look:**
  - The gate's own reading at its 2-SE line is shown, labelled "the gate's own line, not this plan's verdict".
  - Only section 6 decides.

## 6. The looks
- **Counted days.**
  - A market day is ready once every one of its markets has a result.
  - Otherwise it is ready once 7 days have passed **and** the settle has recorded a result after that 7-day mark. That
    shows a settle ran, so the markets still without a result are left out for good.
  - A ready day with no resolved market takes no slot.
  - The looks use the first 60 (then 110) ready days in date order, and only when every earlier day is ready.
- **Futility look at 60 counted days.**
  - It shows only whether each mean difference is below zero, with counts. No standard error, t or bootstrap, so that
    nothing is acted on early.
  - A test whose mean is not below zero stops: **"not confirmed (futility)"**.
- **Final look at 110 counted days**, in a fixed order that keeps the family's one-sided error at 2.5%:
  - **B first.** "Confirmed" needs both:
    - the day-mean t below minus the one-sided 2.5% t value, with days - 1 degrees of freedom;
    - the bootstrap's 2.5% upper bound below zero.
  - **A**, by the same rule, **only if B is confirmed.** Otherwise A reads "not judged".
- **Across plans.** A trading proposal from A must also report the four-test line, 0.625% one-sided: the
  airport-forecast test, PLAN7, PLAN8 A and PLAN9 A.
- **Backstop.** With fewer than 110 counted days on 2027-07-07 (the backstop plus a week for results), the final look
  happens then and reads "not confirmed", as in PLAN7 and PLAN8.
- **Each look is stored once and never recomputed.** The files are research/results/plan9_look60.json and
  plan9_look110.json, each with a Markdown copy and a copy off the folder.
  - If the local file is lost, its off-folder copy is restored.
  - A damaged file stops the looks until the user decides.
  - The final look needs the stored futility look.
  - For the futility look's days, the final look uses exactly the markets the futility look counted, checked by a
    digest of their logged inputs.
- **Descriptive only, at the final look; never decisive:**
  - calibration in the 30-80% range for v3, v3-6h and the price;
  - A and B on the markets logged 00:50 to 01:30 UTC.
- **No other looks:** none, no re-tuning and no rescue. A failed test is not re-run with tweaks (CLAUDE.md section
  11a).

## 7. What a result can lead to
- **B confirmed, A not confirmed or not judged:** v3-6h is less wrong than v3 and still worse than Kalshi's price.
  - A v5 proposal then has no trading value. At most it makes the paper bot's forecast less biased.
  - It would need the user's go-ahead and its own forward test, after PLAN7 ends, because PLAN7 needs v3 unchanged.
- **B and A confirmed:** propose a trading rule under its own plan, tested on paper first, reporting the four-test line
  (section 6).
- **Nothing confirmed:** stop.
- **Real money:** none of this touches live.py. Whether real money follows any result is the user's decision.

## 8. Frozen
- **Frozen files:** research/PLAN9.md and research/plan9.py.
- **The identity record.** plan9.py stores its record once, at the deploy, before 2026-11-08 00:50 UTC, and copies it
  off the folder. It covers:
  - the hashes of the two frozen files;
  - the forecast's code: weather.py's `_rain_v3` and nws.py;
  - PLAN7's reused functions and constants.
- **No re-creation:** after that time a missing record is never re-created. Its off-folder copy is restored, or the
  looks stop until the user approves an amendment. A damaged record also stops the looks.
- **Checks:** each look compares the code with the record. A difference stops the looks until the user approves an
  amendment in research/results/plan9_amendments.json (PLAN8's format: a `name` and the `sha256` it accepts).
- CHANGELOG.md quotes the frozen files' hashes at the freeze.

## 9. Power (approximate; the t test alone, and the bootstrap lowers power further)
- **A.**
  - In-sample, the day-level SD of the difference is about 0.019. At 110 days the bar is about -0.0041.
  - 80% power needs a true advantage of about 0.006 Brier. In-sample, v3-6h was 0.0084 *worse*, so the futility look
    will almost surely stop A unless the gap reverses.
  - At a true advantage of 0.0057, futility stops A wrongly about 1% of the time.
- **B.**
  - The effect 80% power can detect is 0.0024, 0.0035 or 0.0053 for a day SD of 0.008, 0.012 or 0.018.
  - With no effect, futility stops B half the time. At a true advantage of 0.0036 it stops 0-6% of the time.
- **With no effect,** the t condition alone passes about 1.2% of the time with independent days, and about 5% with a
  lag-1 correlation of +0.3. The block bootstrap brings this down.

## 10. Practical notes
- **Data:** none new, and no new web address or package. v3 logs the hourly chances every evening.
- **Settle job:** `plan9.py auto` runs in it. It prints the status and any code change; at a due look it scores and
  stores that look once.
- **Expected pace:** about 30 markets per scanned night. 60 counted days is about two months if the PC scans every
  evening.
