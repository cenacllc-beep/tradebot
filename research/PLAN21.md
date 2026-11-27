# PLAN21: a walk-forward learning engine (monthly refit, freeze, screen, confirm, paper)

Written 2026-11-26 (La Paz) at the user's request for a system that "learns from wins and losses" and detects winning
patterns, before any of its numbers were computed and before any outcome was read for it. Revised the same day after
its statistics review (agents/statistician.md; section 11). Frozen 2026-11-26 after a second review and a final
re-check; its SHA-256 is in CHANGELOG.md. Changes only through an amendment the user approves. Research and paper only. Not financial advice.

## 0. The question, what "learning" means here, and the honest prior
- Question: if we keep proposing models, fit each one only on the past, freeze it and judge it on the next month's
  markets, does any of them beat Kalshi's price by more than luck allows, and does it hold up on new data?
- **Learning here means:** (1) every candidate is re-fitted each month on the newest data; (2) every scored bet and
  market is broken into wins and losses in a monthly report, which may suggest new candidates; (3) a new idea is written
  down in full before it meets new markets, and a candidate that keeps failing is retired. It never means tuning after
  a loss, re-scoring a month, or changing v3, the gate, live.py or a limit.
- **Plainly:** a monthly refit lets a model follow drift in prices and behaviour; it is not compounding learning, and
  more months do not make a candidate better. Kalshi's prices have been well calibrated in every test so far (PLAN2-4,
  PLAN16-18). **Expected result: no edge shown**, month after month, for nearly every candidate. Section 8's power
  table ignores clustering, so the edges this can really detect are larger than it shows.
- Searching many ideas makes a lucky monthly result likely, so a monthly pass is only a **screen**. A screening pass
  is a lead, not a result; only the confirmation month and the paper stage (section 6) can confirm it.

## 1. The monthly cycle (La Paz time, UTC-4)
- **Month M** runs from the 1st 00:00 to the last day 23:59:59 La Paz.
- **Freeze (once per candidate and month):** the nominal freeze time is M's 1st at 00:00; the job runs from 00:10 and
  retries hourly until the 2nd 23:59, else the candidate sits out M ("missed freeze", counted). Fit data are rows whose
  result the bot itself had recorded before the nominal freeze time: live20's results.json with settled_ts earlier, and
  for rain market_results.recorded_ts earlier, read from trial/paper.db as committed at or before that time. The fitted
  model (coefficients, scaling, fit rows' count and hash, code hash) is written to
  research/results/plan21/models/YYYY-MM/<id>.json; its SHA-256, the repository commit SHA read, the allowed rain
  model_versions (section 2) and **the list of tests holding M's scored slots** go into
  research/results/plan21/freezes.jsonl.
- **Scored markets:** those whose first decision moment (section 2) is after the nominal freeze time and whose
  close (rain: whose market day) falls inside M. Nothing settled before the freeze is scored; nothing from M is fitted
  on for M.
- **Score (once):** from the 8th of M+1 at 00:00, with M's frozen model, written once to
  research/results/plan21/scores/YYYY-MM.json and never recomputed.
- **First month:** December 2026. **Last month:** November 2028 (24 months). Continuing needs a new plan.

## 2. Data (already collected automatically; no new source, no new domain)
All read-only. Anything read before a freeze may be used for that freeze's fit only.
- **15-minute series:** research/live20.py's files in research/data/live20/ (GitHub): results.json ({ticker: result,
  yes_pay, no_pay, status, close, settled_ts}); Kalshi's one-minute candles in candles/SERIES/YYYY-MM-DD.json.gz (yes
  bid, yes ask, last, volume, open interest), parsed with research/plan20.py's parse_candles; the minute snapshots
  snap-*.jsonl.gz (ts, minute, ticker, series, event, open, close, yes_bid, yes_ask, no_bid, no_ask, last, volume, oi)
  only to count gaps. Asset groups from research/results/plan20_series.json.
- **Rain (GitHub's trial copy, trial/paper.db, opened read-only through tbcommon/db.py; never the PC's paper.db):**
  table obs, version "v3", market_type rain: ticker, ts (log time), fc (v3), mid; the result and its time from
  market_results (ticker, result, recorded_ts). **Join:** an obs row's decision row is the earliest row of table
  decisions with the same ticker and strategy_id "forecast_alpha.rain.v3", and it counts only if that row's ts is within
  5 seconds of obs.ts (seen read-only 2026-11-26: all 943 rain obs rows matched within 0.001 s) and its model_version is
  one of exactly **"v3@ecb9ddc276bf" and "v3@eca51ea91f19"** (the two seen 2026-11-26; "v3" rows belong to
  maker_spread.rain.v3 and never count). Each freeze record lists the allowed strings; a new version never counts
  without a dated amendment. Rows that fail the join are left out and counted. Table v4_obs:
  ticker, ts, fc (airport forecast), mid, bid, ask, result, start_ts; only rows logged 00:50-01:30 UTC. Day = the
  market day (tbcommon market_day).
- **PLAN19's samples** (research/data/plan19/): not used. PLAN19 shows no figures before its score and stops sampling
  on 2026-12-27, so nothing of it lies forward of a PLAN21 freeze.
- **Kept clean:** KXBTC15M/KXETH15M from Nov 2026 on are PLAN15's check period (section 3, S2). PLAN7, PLAN8 and
  PLAN9 keep their own data and verdicts; PLAN21 never changes them or stands in for them.
- **Dropped rows count:** windows or markets left out for an outcome-dependent reason (scalar, void, unresolved by
  the score) and for missing data (no candles, a night the trial scan did not log) are reported by reason. Dropped
  rows count against the floors; more than 5% outcome-dependent drops or 20% missing windows (or market days) makes
  the test "not testable" that month. Its slot is used up, never carried forward.

## 3. Starting candidates (fixed now; each is one test and holds one slot)
- **S1 `P20R-ALT`:** PLAN20's chances, features, fill, $1 bet and whole-cent fee (section 2) and its ridge procedure
  (section 4), re-fitted on the two whole calendar months before the freeze, pooling every 15-minute series of the
  crypto (other than BTC/ETH), metals, energy and FX groups; "other" series and KXBTC15M/KXETH15M are excluded. At
  least 20 fit days, else it sits out. Rule: p >= ask + fee per contract + 0.01, one bet per window per series.
  **No S1 freeze before PLAN20's score is recorded in CHANGELOG.md.** S1 and any PLAN20 stage C run on the same forward
  markets with related models, so their results are correlated: neither corroborates the other.
- **S2 `P20R-BTCETH`:** the same on KXBTC15M and KXETH15M only; first freeze no earlier than the 1st of the month after
  PLAN15's score is recorded in CHANGELOG.md.
- **S3 `RAIN-CAL`:** logit(q) = a + b logit(v3 fc), plain logistic regression (Newton, chances clipped to 1%-99%) on
  the two months of obs before the freeze; at least 300 markets and 20 market days, else it sits out.
- **S4 `RAIN-MIX`:** logit(q) = a + b_m logit(mid) + b_s logit(airport fc) on v4_obs, same fit and floors, with a
  **mid-only control** logit(q0) = a0 + b0 logit(mid) fitted the same way. Test A: S4 vs the mid; test B (as PLAN8): S4
  vs the control, judged only if A passes. A and B share S4's slot (B at the same level, only after A).
- **S3 and S4 are not fitted, scored or reported (no figure at all) until PLAN7, PLAN8 and PLAN9 have each recorded
  their final look.** They are accuracy tests only (obs keeps the mid, not the ask); a pass can only lead to a new
  trading plan.

## 4. Adding candidates from wins and losses
- Each monthly report breaks every scored bet and market into wins and losses by ask band, minutes left, last-3-minute
  move, hour band, group, city and forecast-price gap. **The report labels these breakdowns "exploratory" in the report
  itself**; nothing in them can pass.
- An idea from it (or from the user) becomes a candidate only by an entry appended to
  **research/plan21_candidates.json**: id (never reused), registered (La Paz time), origin, first month, data and
  fields, fit window and procedure, rule, statistic, floors, placebo, e-process settings (section 5), and the SHA-256
  of the definition. It must be registered by the 25th of the month before its first scored month, statistics-reviewed, and
  recorded in CHANGELOG.md with the file's new SHA-256. **At most 2 new registrations a month.** An idea from month k's
  report (published on the 8th of k+1) is first scored in month k+2 at the earliest.
- Entries are append-only and never edited. A candidate changes only by being **retired** and **superseded** by a new
  id; **at most 2 successors per original idea**, each a new candidate needing its own slot. Retirement is automatic
  after 3 scored months in a row with a mean at or below zero, or 6 scored months without a screening pass, and takes
  effect only from the next freeze. Consecutive months share markets' regimes and the refit's data, so these strikes
  are not independent; they are a housekeeping rule, not a test.
- At most **6 scored slots** a month; candidates registered first take them, the rest wait (counted).

## 5. Error control
- **Stage 1, monthly screen:** each test at **0.5% one-sided**. It passes only if every check clears 0.5%:
  1. the day-clustered t reading (La Paz day, or market day for rain; day means of profit per contract, or of
     Brier(q) - Brier(mid) below 0);
  2. a 2-day block bootstrap, 20,000 draws (share at or below zero at most 0.5%);
  3. 15-minute tests only: PLAN20's exact Poisson-binomial bound on wins at break-even, which leads (it is exact), and
     PLAN20's matched placebo (same bets per day from the same ask band x minute cells), 20,000 draws, p = (k+1)/(N+1).
     Monte Carlo resolution: one draw is 0.005% of p, and the standard error of a p near 0.5% is about 0.05%;
  4. floors: 300 bets (rain: 300 markets) and 20 days with a bet in the month, else "not testable".
- **Stage 2, confirmation month:** the first whole month whose freeze comes after the screening pass is recorded
  (normally k+2), new data only, the candidate's own procedure, every check and floor of stage 1 at **2.5% one-sided**,
  Holm across candidates confirming in the same month. A "not testable" confirmation month means **not confirmed**. A
  confirming candidate takes one of the 6 slots, ahead of every other. **Stage 3:** a PLAN20-style 42-day forward paper
  stage (section 6).
- **False-promotion bound:** at most 24 months x 6 slots = 144 screens; with no real edge the chance that any test
  passes both screen and confirmation is at most 144 x 0.005 x 0.025 = about 1.8% (plus section 5's e-processes, at
  most 0.15%), before the paper stage. **Two-stage power:** a true edge of 3.5 standard errors in each month passes
  the screen (t line 2.756 at 29 degrees of freedom) about 77% of the time (exact noncentral t 0.765) and the
  confirmation about 92%, about 0.71 together; requiring every check (bootstrap, placebo, bound, floors) lowers both further.
- **E-process per candidate (catches small edges that build up over months):** a betting martingale on the candidate's
  scored day values x_d, in date order across all its scored months: W = product of (1 + lambda x_d). Units: dollars
  per contract (15-minute: the day-mean profit per contract after fees) or Brier units (rain: day mean of
  Brier(mid) - Brier(q)). x_d is capped at 1 from above only; the code asserts 1 + lambda x_d >= 0 and never clips
  from below (a failed assertion stops the candidate's e-process, reported).
  - 15-minute: lambda = 0.5 / L, with L the largest possible loss per contract in the candidate's price band (top ask
    plus the largest fee per contract; about 0.11 for 1-10c cheap sides), fixed in the registry entry.
  - Rain: lambda_d = 0.5 / (the day mean of 2|m - q|), known before the outcome, since Brier(mid) - Brier(q) >=
    -2|m - q| for each market; a day where that mean is 0 is skipped. S4's e-process uses test A (S4 vs the mid).
  - Under no edge (each day's expected x at most 0 given the past) W is a nonnegative supermartingale, so by Ville's
    inequality it ever reaches 200 = 1/0.005 with chance at most 0.5%. Read once a month at the score.
  - At most 6 at a time and 12 in the whole programme. Each counts as a screening pass **once** and ends when it
    crosses; if the candidate then fails confirmation, any new e-process for it uses up another of the 12. So at most
    12 x 0.005 x 0.025 = 0.15% is added to the false-promotion bound. No online-FDR method.
  - **Days to cross (median growth, before data):** for a true 2c edge on 3c contracts, about 64 scored days at 100
    bets a day, 72 at 30, 103 at 10 (simulated median 99); at 3 or fewer bets a day it crosses slowly and unreliably
    (about 60%, 23% and 5% within 24 months at 3, 2 and 1 bets a day). A smaller edge takes longer still.
  - Days of a month whose test reads "not testable" still enter the e-process (all scored days count).

## 6. Promotion (never directly to real money)
- After confirmation, a 15-minute candidate runs a **42-day forward paper stage** as PLAN20 section 5 (its frozen rule
  of the confirmation month, live quotes, $1 bets, the fee; research/data/plan21/ledger.jsonl through live20's paper
  path, rows marked by candidate id), one verdict at day 42 at 2.5% one-sided by section 5's checks, at least 300 bets.
  A confirmed rain candidate only earns a new trading plan.
- Real money stays the user's explicit decision, through a new, code-reviewed live.py path ($1 bets, its own caps
  inside live.MAX_AT_RISK, every existing lock and the kill switch). Nothing in PLAN21 asks for it automatically.

## 7. Reporting
- research/results/plan21/report-YYYY-MM.md in plain English at each score: each test's verdict (screen pass is called
  "a lead, not a result"), bets, days, wins against what prices implied, mean profit per contract with its interval,
  rows dropped by reason, each e-process value, the registry and slots, and confirmation and paper-stage status. A
  dashboard section "Learning engine (PLAN21)" shows the same, read-only. Before a score only counts appear.

## 8. Power (stated before the data; ignores clustering, so real thresholds are higher)
At 0.5% one-sided with 80% power a monthly screen needs about 3.4 standard errors (normal) or 3.6 (t line 2.756, 30
day means):
- cheap sides (one bet's SD about 17c at 3c, about 30c at 10c; figures at 17c, so 10c bets need about 1.8 times
  more): 300 bets 3.4c, 1,000 bets 1.8c, 3,000 bets 1.1c a contract;
- 50c contracts (SD about 50c): 300 bets 9.9c, 1,000 bets 5.4c, 3,000 bets 3.1c;
- rain accuracy: about 0.66 day-level SDs of Brier(q) - Brier(mid) over 30 market days. Rain loses about one market
  day a month at each freeze (markets logged before the freeze but closing after it are neither fitted nor scored).
The 50c fee is about 1.75c and cheap sides carry a documented long-shot bias, so even a real edge must be large to show.

## 9. Operations
- GitHub Actions (cloud/workflows/plan21.yml; public repository: no keys, no PC data). It reads live20's and the
  trial's files; any candle fetch goes through live20's own public Kalshi GETs. No order endpoint, no live.py import,
  never writes paper.db, live.db or trial/paper.db. The KILL file lives on the PC only; this is paper research.
- Pure Python (Python 3.8 syntax). numpy is approved for PLAN20 only: PLAN21 uses it only if the user approves it for
  PLAN21; otherwise the ridge fit is plain Python (about 30 features, Newton's method).
- research/plan21.py is written after this plan's freeze, code-reviewed, and frozen before the first freeze; its hash
  and the registry's are checked at every freeze and score, and a difference stops the cycle until an amendment.

## 10. Freeze
Where code and text differ, the text wins, by a dated amendment before any number is computed.

## 11. Review (2026-11-26)
1. (High) A single 0.0174% level gave almost no power: now a 0.5% screen, a 2.5% confirmation month (Holm) and a
   42-day paper stage, with the false-promotion bound and two-stage power stated (sections 0, 5, 6).
2. (High) Small persistent edges were invisible month by month: an e-process per candidate (fraction 0.2 [superseded by the second review, item 1], 0.5% each,
   at most 6 at a time and 12 in all, Ville's inequality); crossing counts as a screen pass only (section 5).
3. (High) S3/S4 overlapped PLAN7-9: no fit, score or figure until their final looks; S4 gets a mid-only control and a
   B test as PLAN8 (section 3).
4. (Medium-high) S1 waits for PLAN20's score; correlation with stage C stated (section 3).
5. (Medium) 20,000 draws kept; the exact Poisson-binomial bound leads; Monte Carlo resolution stated (section 5).
6. (Medium) Slots recorded in freezes.jsonl; retirement from the next freeze; at most 2 successors per idea (1, 4).
7. (Medium-low) At most 2 registrations a month; breakdowns labelled exploratory in the report (section 4).
8. (Medium-low) v3 model_versions pinned via plan7_versions.json [superseded by the second review, item 3: versions written literally]; rain by market day; S1's series listed ("other"
   excluded); outcome-dependent drops reported and counted against floors (sections 2, 3).
9. (Low) Fit cutoffs use the bot's own recorded settle time; strikes noted as not independent (sections 1, 4).
10-11. (Low) BTC/ETH exclusion kept; honest paragraph on what refitting is and is not, and on clustering (0, 8).

### Second review (2026-11-26)
1. E-process: units stated (dollars per contract; Brier units for rain); x capped at 1 from above only, with an
   assertion that 1 + lambda x >= 0 and no clipping; lambda = 0.5 / L (15-minute) and 0.5 / mean 2|m - q| (rain);
   days to cross for a 2c edge stated, at 3 or fewer bets a day slow and unreliable (corrected at the final re-check) (section 5).
2. Each e-process counts once and ends on crossing; a new one after a failed confirmation uses another of the 12;
   tied to the 0.15% bound (section 5).
3. Rain data checked read-only in trial/paper.db (2026-11-26): allowed model_versions written literally, strategy
   forecast_alpha.rain.v3 (the review's "forward_alpha" is "forecast_alpha" in the table), the obs-decision join
   stated; fit cutoff on market_results.recorded_ts; the commit SHA goes into freezes.jsonl (sections 1, 2).
4. Confirmation uses every check and floor at 2.5%; "not testable" means not confirmed; it takes a slot first (5).
5. Notes added: SD 17c at 3c and 30c at 10c; screen power about 0.77 and two-stage about 0.72 at the t line 2.756;
   S4's e-process uses test A; rain loses about one market day a month at each freeze (sections 5, 8).

### Final re-check (2026-11-26)
Verdict: valid e-process (nonnegative supermartingale under the null; bounds hold for 15-minute and rain), one crossing
and 12 in all consistent, rain rows confirmed (two allowed versions; all 943 obs rows join within 0.001 s), confirmation
rules consistent. Corrected: days to cross at 3 or fewer bets a day (slow and unreliable, not "never"); exact
noncentral-t powers (0.765 screen, 0.92 confirmation, about 0.71 together); earlier items marked superseded; scored days
of a "not testable" month enter the e-process. Frozen after these text corrections.
