# PLAN 3: new ideas, written before any of their data is fetched or scored

Written 2026-10-14 22:20 local. Revised 2026-10-14 23:00 after an independent statistics review, still before any Test A
or Test B data was fetched or scored. The changes are listed at the end.

Research only. Nothing here changes the bot, v3, the gate or the stop date. Each test is scored ONCE by its rule below.
A passed test earns only a forward paper test with the same rules on markets after its scoring date (CLAUDE.md 11a).
Written at the user's request ("we need to identify patterns, even for the trades we lost... apply your recommendations").

## What prompted it (already known, so it is not evidence)
- research/results/inventory.md (2026-10-15 01:01 UTC snapshot):
  - KXRAIN trades about 1.4M contracts a day at 1c spreads.
  - KXHIGH* (about 20 cities, older KXHIGH<city> and newer KXHIGHT<city> series) trades 5k-260k a day at 1c.
  - KXLOWT* (about 20 cities) trades 1k-40k a day at 3-20c median spreads (thin).
  - Monthly rain/snow series trade at 3-20c.
- research/results/gaps.md:
  - On the same questions, Kalshi and Polymarket were within 0.3-2 points.
  - No pair cost under $1.00 after fees, except long-dated political markets (1-2.4c per dollar, locked for months to
    years).
  - Temperature "gaps" are different measurements, not mispricing. Polymarket uses airport hourly readings (e.g.
    LaGuardia); Kalshi uses the NWS daily climate report (e.g. Central Park). Not tested further here.
- learning.md (past rain markets, looked at after the plan-1 score):
  - Win rates matched prices within noise in every situation.
  - Losses by story mirror trade counts and prices.
  - The limit-order "patterns" near z 2.7 (NO side, "both said likely") are the overall limit-order lead (+9.6c, about
    2.6 SE) seen in its largest slices. They are not separate findings.

## Test A: late-day temperature ("already happened")
Question: once airport readings show a day's high has already passed a Kalshi strike, does the price lag enough to
profit after fees?

**Markets: the plan-2 market set** (research/data/kalshi_temp.jsonl).
- Every settled KXHIGH* contract (both series families) from 2026-07-01 to 2026-10-13 whose rules name a CLI station.
- Duplicates (same day, station, strike type and strikes) keep the one with the most volume.
- Stations are the 24 in research/results/temp_model.json.
- Strike type and strikes come from strike_type, floor_strike and cap_strike, as in PLAN2.
- Outcome = Kalshi's result.

**Observations**
- Source: the IEM ASOS archive (mesonet.agron.iastate.edu, the domain approved for research 2026-10-14) for the CLI
  station, routine and special METARs only.
- M = the maximum of tmpf (from the tenths-of-a-degree-C group when present) over reports valid from local-standard-time
  midnight up to and including the decision time. Not rounded before comparison.
- Not used: 5-minute data, and the 6-hour and 24-hour maximum groups. The 06 UTC 6-hour group covers the previous
  evening.
- A look needs at least 3 reports with a temperature valid in the 3 hours before the decision. Otherwise the look is
  skipped and counted.

**Decision times:** 13:00, 15:00 and 17:00 local standard time (three fixed looks).

**"Decided" sides.** M can only rise during the day, so only these calls are safe:
- "greater than F": decided YES if M >= F + 2.
- "between F and C": decided NO if M >= C + 2.
- "less than C": decided NO if M >= C + 1.
- Each margin is 1 degree F beyond the settlement boundary for whole-degree CLI highs.
- No "decided" call is ever taken from a low M, because the day can still warm up.

**Trade**
- Price: the standing quote at decision + 5 minutes, from the last minute candle ending at or before then:
  - YES: yes_ask close.
  - NO: 1 - yes_bid close.
  - Never a candle low.
  - No trade at that look (counted) if that candle ended more than 60 minutes earlier, or there is no offer for our
    side (no ask, or a 0 bid).
- A look qualifies when the market is decided AND that price is at most 97c.
- At most one trade per market: the earliest look that qualifies.
- One contract, with the Kalshi taker fee (core.fee rounding).

**Score (once)**
- Profit per contract after fees, averaged within each market day, with the standard error over market days.
- PASS only if all of these hold:
  1. The day mean is above 0 by at least 2.5 standard errors.
  2. At least 200 trades on at least 40 market days.
  3. Fewer than 2% of trades lost, AND the one-sided 95% upper bound (exact binomial) on the loss rate is below the
     break-even loss rate. Break-even = 1 - mean price - mean fee.
  4. Condition 1 still holds after leaving out each station in turn.
- Losses and the cases where the CLI high disagrees with M are listed and read by hand. This is descriptive only:
  nothing is excluded after scoring.
- Also reported: decided markets whose price was above 97c, and skipped looks.

**Expected outcome, stated in advance:** probably no edge, because other bots watch the same readings; the most likely
profit is 1-2c minus fees.

**Power:** losses are rare but cost about 97c each. The SE is about 0.6-0.8c, so a 2-3c edge is detectable. The real
risks are station or day mismatches, not rounding.

## Test B: low-temperature markets with limit orders
Question: KXLOWT markets have wide spreads. Does posting limit orders on the side a calibrated forecast prefers make
money after the spread, when paying the ask would not?

**Markets**
- Every settled KXLOWT* contract from 2026-07-01 to 2026-10-13 whose rules name a CLI station with a known time zone.
- Strike type, strikes, duplicates and outcome as in plan 2 (lows instead of highs; CLI lows are whole degrees F).

**Forecast**
- NBS evening run (18/19 UTC) of the day before: TXN valid 12 UTC on the market day (the overnight minimum), with its
  XND.
- Model: low ~ Normal(TXN + a, s0 + s1 * XND), fitted by maximum likelihood on 2025-07-01..2026-06-30 CLI lows at the
  same stations, with plan 2's fitting code.
- The model is written to research/results/low_model.json before any holdout market is read, and never refit.
- P(YES) as in plan 2, clipped to [0.01, 0.99].

**Quotes**
- Scan quote: the last minute candle ending at or before 00:55 UTC on the market day (yes_bid close, yes_ask close).
- Usable if 0 < bid < ask < 1. No spread cap: plan 2's 6c cap would drop most of these markets.

**Rule**
- The bot's rule: 50/50 blend with the market mid and an 8-point minimum edge, one contract per signal.
- Maker: 1c better than the best bid when the spread allows, else join (backtest2.entries).
- Filled only if a later minute candle, up to local-standard midnight that starts the market day, traded through our
  price: price.low < our YES price, or price.high > 1 - our NO price. Quotes do not count. No fee.
- Taker version (pay the ask, with fee): descriptive only.
- Placebo: the same maker rule with the forecast replaced by the market mid. Ties go to YES, as in the code. It fires
  only on wide spreads, so it measures spread capture alone.

**Score (once).** PASS only if all of these hold:
1. Maker profit per contract, averaged within each market day, is above 0 by at least 2.5 SE, with at least 150 fills
   on at least 40 market days.
2. Forecast Brier is below market-mid Brier by at least 2 day-clustered SE, over all usable markets (the plan-2 clear
   rule).
3. It beats the placebo. For each market day, take B's maker profit minus the placebo's, divided by the usable markets
   that day; the mean of those daily differences must be above 0 by at least 2 SE.

With fewer than 40 market days, B is not testable and the window is not extended. Fill rate and profit per order posted
are reported alongside.

**Power:** each fill varies by about 47c, so 150 fills give an SE of about 4.4c. The smallest detectable edge is about
15c (about 9c at 400 fills). A fail cannot rule out a 2-3c edge.

## C: descriptive forward checks (no pass/fail)
- Data: the limit-order lead's own forward ledger (shadow.py table v4_paper: limit-order version, one contract per
  signal, frozen NBS model), markets dated 2026-10-15 or later.
- When: reported once, at that lead's 110-market-day verdict.
- Groups:
  - C2: NO side.
  - C3: forecast and market both favour our side.
- For each group, the report gives:
  - the estimate and 95% interval (day-clustered, Student-t);
  - its difference from the rest of the ledger.
- No pass/fail, and no change to v3 or the lead because of them. By then they will hold about 80 and 45 trades, so
  only edges of about 17-27c would be visible.
- C1 (long shots) is dropped: a 17c long shot is expected to lose about 83% of the time, and the past excess was
  -0.8 +/- 6.4 points, so there is no pattern to check.

## Not tested (and why)
- Kalshi-Polymarket arbitrage: no gap after fees on identical questions in the first snapshot. `research/markets.py gaps`
  can be re-run to watch persistence; a pair only counts after both rule texts are compared.
- Sports, elections and economic releases: priced by specialists with better data (CLAUDE.md section 7).

## Multiplicity
- Tests A and B are two new looks at past data, each with a 2.5 SE bar (about 0.6% false pass each, one-sided). B also
  needs the Brier and placebo conditions.
- C has no tests.
- learn.py's daily screen is not a test (it says so).
- Every result is reported, including failures.

## Changes made in the 23:00 revision (statistics review, before any A or B data)
- **A**
  - Strike direction now covers all three strike types ("less than" markets were missing).
  - Market set and duplicates follow plan 2.
  - The "3 reports" rule and M are defined exactly, and the 6/24-hour groups are excluded.
  - The price is a close, never a low.
  - The rare-loss bound and the leave-one-station-out check were added.
- **B**
  - Quotes have no spread cap.
  - The forecast element is TXN at 12 UTC (TNN is not an NBS element).
  - Fill requires a trade through our price.
  - The placebo was added, and the taker version is descriptive only.
  - The power note was added.
- **C**
  - Moved to the lead's own ledger (v4_paper; the shadow ledger's choices depend on its own results).
  - Made descriptive. C1 dropped.
- **A, 23:45 (still before any A data):** the price is the standing quote at decision + 5 minutes (the last candle at
  or before then, at most 60 minutes old). A format check of one open market showed that Kalshi's minute candles
  appear only when something changes (76 candles in 6 hours). "The first candle after" would therefore skip quiet
  markets. Plans 1 and 2 read their scan quotes the same way.
- **A, 2026-10-15 (format check, still before any A data):** a 3-hour IEM request for KNYC and KATL showed that
  tmpf is the whole-degree F value the METAR's tenths-of-a-degree-C group encodes (T02390189 = 23.9 C = 75.02 F, shown
  as 75.00). Comparisons with whole-degree strikes are the same either way, so the rule is unchanged. The `tz`
  parameter returns UTC times.
- **A and B, 2026-10-15 (code review of research/plan3.py, still before any A or B data):**
  - **Completeness:** neither test is scored, and the low model is not frozen, until every market has its data:
    - every station has airport readings;
    - every decided A market and every B market has a quote row;
    - all NBS and climate-report files are present.
    - At most 2% of markets may come back from Kalshi with no candles after a retry. Those are counted and listed.
  - **A, quote windows:** the fetch window starts an hour before the 60-minute freshness limit, because Kalshi stamps its "latest candle before the start" at the window's start. The plan-2 data shows that stamp at exactly the start.
  - **A, "3 reports":** counts distinct report times.
  - **A, descriptive only:**
    - every decided market, traded or not, that settled against the decided side;
    - losses counted by station-day as well, since one bad reading can decide several strikes.
  - **B, data checks as in plan 2:** Kalshi's results against the climate-report lows, rule numbers, YES count per city-day.
    - If results and lows agree in under 95% of markets, the strike reading is wrong. B is not scored until the code is fixed; the rule does not change.
  - **B, "not testable":** fewer than 40 market days with a usable quote and forecast. With 40 or more, too few fills or fill days fail condition 1.
  - **Holdout wording:** fitB reads only training-year forecasts and lows, plus the station list. lowlist reads market metadata (including results) but no prices and no forecasts.
- **Prompting bullets:** the "forecast overrates long shots" reading was removed. It used the blend, and trades are
  chosen where the blend exceeds the price, so it was a selection effect.
