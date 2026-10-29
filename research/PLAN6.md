# PLAN 6: what the Nov 11 report shows next to the gate (written before the last 12 market days)

Written 2026-10-29 03:50 local (America/La_Paz). The market days Oct 30 to Nov 10 have not been scanned yet.

**What the author knew when writing this.**
- Counts of logged and resolved v3 rain markets, by market day.
- The scan history: which evenings ran and which were missed.
- The number of v3 rain paper trades: 6. Of these, 5 have settled, with a net paper P&L of -$1.67.

**What the author did not look at:** the interim forecast-vs-market Brier numbers, on the dashboard or anywhere else.

Asked by the user on 2026-10-29: "we can't move the november 11th deadline. do whats needed without weakening the test.
use historical data and patterns".

This plan is research only. It changes nothing in the bot, v3, the gate, the stop date, the single look, the $25 cap,
live.py or any limit. It adds no verdict.

## Why this plan exists
- **The gate's trade check cannot be met by Nov 11.** The gate (CLAUDE.md section 5) needs at least 50 settled v3 rain trades.
  - The bot opened 6 in its first 16 market days, about one per evening that was scanned.
  - 12 market days remain.
  - So the stored look (section 11) is expected to fail on that check, whatever the other checks show.
- **The 50-trade check was out of reach from the start, not because of the missed nights.** At about one trade per scanned night, even 28 scanned nights would give about 28 trades. The missed nights are therefore no reason to "rescue" the test.
- **Past data cannot fill the gap without weakening the test.**
  - Kalshi's rain markets begin on 2026-07-15. All of their history before the forward test (Jul 15 to Oct 12) was the holdout of research/PLAN.md, already scored once: no edge demonstrated.
  - Any new test on those markets would be a second look at scored data.
  - v3 cannot be replayed as it ran either. It reads the NWS gridpoint's hourly precipitation chances at scan time, and those are not kept. The public NDFD archive keeps 12-hour chances, which would make a different estimator (close to v2).
- **The core question still deserves the clearest honest answer the data allow:** does the forecast beat Kalshi's prices? This plan fixes in advance what the Nov 11 report shows next to the gate, and how each number is read, so nothing is chosen after the results are known.

## Expected precision (stated before the data)
The scored holdout's market-day spread gives a guide: blend minus market had SE 0.0039 over 81 days, a day-to-day
standard deviation of about 0.035. The forecast alone is likely wider.
- **Width:** with about 12 to 20 resolved market days, A's interval (mean +/- tcrit x SE) is expected to be at least about +/-0.016 to +/-0.022 Brier. That is roughly a quarter of the market's own Brier score (0.073 in the holdout).
- **Expected reading:** "no clear difference", even if the forecast is as good as the best forecast seen in past data. The blend there was about 3% better than the market (0.0711 vs 0.0730).
- **What that reading means:** the test was too short to tell. It rules out only differences beyond the interval.

## 1. Primary: the stored look, unchanged
The look stored in paper.db (table gate_look; strategy.gate_look) is quoted as stored:
- passed or failed;
- each check with its number: resolved markets, forecast and market Brier, clear margin, settled trades and net P&L.

Nothing below changes it, overrides it, adds a second verdict, opens paper trading for market days from Nov 11 on, or
unlocks real money.

**What a failed look means for real money:**
- The rules (CLAUDE.md section 11) say no real money.
- live.py's unlock still leaves the decision to the user: it says plainly that the gate did not pass, and asks for the typed phrase.
- v3 opens no new paper trades for market days from Nov 11 on, so live.py has nothing to copy.

**What a passed look means:** it is paper only. Real money still needs the user's own typed unlock, starts tiny and is
capped at $25 at risk.

**If the look is still pending** (a test-day market without a result), the report says so and shows nothing else. It is
produced once the look is stored.

## 2. Secondary A: the core question on the official data
**Data:** the PC's paper.db. Resolved v3 rain obs of market days Oct 14 to Nov 10, the same rows as the gate. Temperature, v1 and v2 never count.

**Statistic:** the gate's own (strategy.margin):
- forecast Brier minus market Brier for each market;
- averaged within each market day;
- then the mean over days, its standard error, the number of days, and t = mean / SE.

Also reported:
- the gate's critical value, tcrit (Student-t 97.5%, days - 1 degrees of freedom, never below 2.0);
- the interval mean +/- tcrit x SE;
- the number of markets.

**How it is read (fixed now):**
- mean below zero by at least tcrit standard errors: "the forecast was clearly more accurate than Kalshi's prices";
- mean above zero by at least tcrit standard errors: "Kalshi's prices were clearly more accurate than the forecast";
- otherwise: "no clear difference". The interval shows how large a difference the data could still hide.

A is the same statistic as the gate's Brier check, so it is not an extra look. It is shown even when the look fails on
another check.
- **Consistency check:** A's mean, SE and day count are compared with the stored look's margin, and any mismatch is printed.
- **Reading basis:** the reading uses the day means, not the pooled Brier scores printed beside them, which can differ in sign.
- **The interval in the summary, in plain words, as a share of the market's Brier score averaged over market days** (the same day weighting as the interval): "the data fit anything from X% lower to Y% higher error than Kalshi's prices, measured by the Brier score; they do not show the two are equal, and they rule out only differences beyond that range".
  - Lower error is capped at 100%, since a Brier score cannot fall below 0.
  - The wording follows the reading.
- **Each market day is listed** with its number of resolved markets and the time (UTC) of its first log.

## 3. Secondary B: the same, with the cloud copy filling missed nights
**Data:** for each market day from Oct 14 to Nov 10:
- If the PC's paper.db logged any v3 rain market of that day, the day comes only from the PC.
- Otherwise it comes only from the GitHub runner's trial copy (trial/paper.db on the repository's main branch when the report is made), if that copy logged the day.

A day is never mixed from both sources. The trial copy runs the same code in the same evening window. Its first logged
market day is Oct 29, so it can only add days the PC missed from Oct 29 on.

**A cloud day counts only if both of these hold:**
- Every rain decision row the trial copy recorded for that day's markets (audit ledger, forecast_alpha.rain.v3) carries a model version (VERSION@hash of weather.py, nws.py and strategy.py) that the PC's own rain decisions also carry. In other words, the trial ran a model the PC ran: any version the PC ran during the test. That is acceptable because v3's forecast code is frozen. A day with no such rows cannot be checked, so it is not used.
- Its scan began inside that evening's scan window, as scan_window.py judges a scan: the day's earliest logged row falls between 00:50 (inclusive) and 05:00 UTC (exclusive) on the market day, which is 8:50 PM to 1 AM La Paz the evening before. Later rows of the same scan still count. The model check uses the decisions made while the markets were open to that scan (every reason but MARKET_STARTED, which a later evening records).

A cloud day that fails either rule is listed as not used.

**Recorded:** the trial file's SHA-256, and the repository commit it came from when given, so the numbers can be
reproduced.

**Statistic and reading:** the same as A, labelled "secondary, PC days plus cloud days the PC missed; does not change the
gate", with the same listing by day and the source of each day.

**Weight:**
- B is one extra look, reported as secondary.
- If A and B disagree, the report says so plainly, and neither changes the primary.
- Caveat to state: the trial copy's evening scan may start later than the PC's (GitHub starts runs late), so its prices and forecasts can be a few hours newer.
- A scan after 05:00 UTC skips the eastern markets, so a late day leans toward western markets. The first-log times in the listing show this.

## 4. Descriptive C: the paper trades
Settled v3 rain trades of the test's days, from the PC's paper.db:
- count, wins and losses;
- net paper P&L after the approximate fees;
- paper P&L per contract (see below).

They are shown split before and after the Oct 28 veto (CLAUDE.md section 5 keeps the two apart), and in total.
- **The split uses each trade's open time** (trades.ts), measured against the start of the first scan whose recorded config contains VETO_MAX_GAP (table scans, kind 'scan'). That is the Oct 28, 8:55 PM scan. If there is no such scan, every trade counts as before the veto.
- **The per-contract figure** is total net paper P&L divided by total contracts, labelled "paper P&L per contract (optimistic fills; not a test)".
- **No standard error is shown.**

C is descriptive only. The report says the sample is too small for any conclusion. The cloud copy's trades are not used
(separate bankroll and exposure).

## 5. Context D: earlier results, quoted, not re-scored
- **The past-data test (research/PLAN.md, scored once on 2026-10-14):**
  - market Brier 0.0730;
  - calibrated airport forecast 0.0740;
  - 50/50 blend 0.0711, not clear;
  - verdict: no edge demonstrated.
- **The research tests that continue with their own pre-set ends:**
  - the airport-forecast limit-order forward test: futility look at 60 market days, verdict at 110;
  - PLAN5 test L: scored once from Nov 25.
  
  They are mentioned, not scored.

## 6. The plain summary for the user
**Built only from the rules above:**
1. The gate's result, and the checks that failed.
2. The core-question sentence from A, with its interval in plain words.
   - If A reads "clearly more accurate", the same line says it covers only these market days, and that a more accurate forecast is not a profitable one: the bot trades few markets and pays the spread and fees.
   - Unless the look passed, it also says the gate was not passed, so the rules say no real money.
   - If B's reading differs, B's sentence follows, labelled "secondary; does not change the gate".
3. The number of trades, with "too few to conclude anything".
4. The real-money sentence from section 1, for a failed or a passed look.

**What the summary must not do:**
- No claim of an edge beyond these readings.
- No new thresholds.
- No suggestion to extend or re-run the test. The user decided on 2026-10-29 that Nov 11 does not move. A genuinely new idea would need its own plan written before its data (CLAUDE.md section 11a).

## 7. How it is produced
**research/nov11.py:**
- Read-only: it opens both databases read-only, and writes only research/results/nov11.md (and its JSON twin).
- Makes no network call.
- Never writes paper.db and never computes or stores a look.
- Running it again gives the same numbers, because the test's days are settled.

**On Nov 11, a scheduled Claude task runs it in the cloud:**
- after the PC's 2:51 PM settle has stored the look;
- on a copy of the PC's paper.db and the repository's trial copy;
- then it copies the report to the PC and tells the user.

If the look is still pending, the task tries again the next afternoon.

## Revision notes
- **2026-10-29, about 04:15 local.** Independent statistics review (agents/statistician.md), applied before the evening scan that logs the first of the 12 remaining market days. No verdict, threshold or rule of the gate changed. Applied:
  - the expected-precision statement;
  - the trade check out of reach from the start;
  - the real-money wording (live.py's unlock leaves the decision to the user);
  - the limits that go with "clearly more accurate" and the interval in plain words;
  - day means as the reading's basis;
  - per-day listing with first-log times;
  - B's same-model and scan-window rules, the file hash and commit, and B's label;
  - the trade split by open time against the first veto scan;
  - per-contract P&L as total net over total contracts, with no standard error.
- **2026-10-29, about 04:45 local.** The statistics re-check found nothing that must be fixed. Applied:
  - the plain-words interval now reads as Brier-score error, lower or higher;
  - it is measured against the market Brier averaged over days, with lower error capped at 100%;
  - the wording follows the reading;
  - "a model the PC ran" is defined as any version the PC ran during the test;
  - the precision figure is +/-0.022 at 12 days;
  - the "too short to tell" wording;
  - the pending-look sentence is on its own.
  
  The cloud and PC model versions for Oct 29 were compared (hashes only, no outcomes): both v3@ecb9ddc276bf, so B can use cloud days.
- **2026-10-29, about 05:00 local.** The code re-check found the failed-look wording missing a sentence from section 1; added. Also applied:
  - the scan-window rule now judges when the scan began (the day's earliest row), as scan_window.py does, not every row;
  - the model check uses only decisions made while the markets were open to that scan;
  - a damaged trial copy loses only B;
  - not-used days say "not counted".
