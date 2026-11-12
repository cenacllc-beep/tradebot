# PLAN11: radar and the airport rain gauge during the market day, against Kalshi's price at that moment

Written 2026-11-11, 17:00 La Paz, before any radar frame, gauge report or intraday price for this test was downloaded
or looked at. Revised 2026-11-12 08:30 La Paz after the independent statistics review (4 MUST, 7 SHOULD, 3 COULD: all
applied below), still before any of its data. Research only: never part of the gate, never connected to live.py. A
result can lead only to a forward paper test, never straight to real money (CLAUDE.md section 11a).

**Disclosure.** Other code in this project has already read minute prices for some of these market days, for other
purposes: shadow.py's price moves (the mid at the day start), research/ohlc_audit.py (candle anomaly checks) and
marks.py (open paper trades). None of it compared prices with radar or gauge reports, and no radar frame or METAR rain
amount has been read for these days (PLAN3 test A read METAR temperatures only).

## 0. Where the idea comes from
- The user, 2026-11-11: "an open source live weather radar workflow which can identify patterns for different locations
  over an e.g. 90 day historical data replay ... patterns from the radar which confirmed rainfall, speeds of the wind,
  cloud formation, time of year".
- **What radar can and cannot do.** Radar shows rain that is falling now, and by following the echoes it predicts well
  for about one to two hours. The bot bets at 8:55 PM on the whole next day, where radar says little that the forecast
  models (which take radar in every hour) have not already put into the price.
- **So this plan tests the one place radar can add something:** during the market's own day, in the minutes between
  rain showing on radar and the market's price reacting.
- **Honest prior.** Other traders watch the same free radar. PLAN3 test A found that decided temperature markets already
  cost $1.00, so the price may not lag at all. Expected result: no lag worth trading.
- **Why not a pattern learner.** Mining many variables (wind, clouds, season) over about 120 correlated days would
  memorise noise. This plan fixes three simple rules now and tests only those.

## 1. The questions
For a rain market whose day has begun, each asked once per market:
- **G (gauge).** Once the airport's own gauge has reported measurable rain, is YES still for sale below its worth?
- **R (radar now).** Once radar shows rain over the station, before the gauge reports it, is YES underpriced?
- **P (radar approaching).** Once radar shows rain nearby and closing in, before it arrives, is YES underpriced?

## 2. Data (all public, read-only)
- **Markets and outcomes:** every settled Kalshi KXRAIN market with market day from 2026-07-15 to 2026-11-10, with
  Kalshi's yes/no result. Scalar and void markets are left out. Stations and coordinates as in PLAN10: v3's rain table
  (weather.RAIN) by CLI code; a station not in the table is left out and counted. One market per station and day; if
  Kalshi listed several, the one with the highest volume (as research/fetch.py does). The download date is recorded
  with the result.
- **The market's day:** starts at the market's own close_time minus 24 hours and ends at close_time, both read from
  the market itself. research/fetch.py's start_ts (built from a standard-time table) is compared with it; every
  mismatch is counted and the market's own value is used.
- **Intraday prices:** Kalshi's public minute candles (yes bid and ask) from the day start to its end, fetched with
  research/fetch.py's candle code.
- **Radar:** the Iowa Environmental Mesonet's national base-reflectivity mosaic (N0Q, every 5 minutes, 0.5 dBZ steps,
  EPSG:4326, 12200 x 5400 pixels), from its archive folder archive/data/YYYY/mm/dd/GIS/uscomp/ (an approved address
  since 2026-10-14). One whole frame per timestamp, by its exact stamp.
  - **Grid:** pixel size and corner are read from the archive's own world file (.wld) and recorded in plan11.py
    before the first frame is downloaded (expected: 0.005 degrees, about 0.5 km). A frame whose size differs from
    12200 x 5400 is treated as missing.
  - **dBZ:** from IEM's published colour table: index 0 is "no data" and counts as no echo; index i (1 or more) is
    -32.5 + 0.5 x i dBZ (index 1 = -32 dBZ, up to 90 dBZ). plan11.py checks the image's palette length against the
    table before the first download; a difference stops the plan until an amendment.
  - **Distance:** great-circle distance from the station's coordinates to pixel centres.
- **Gauge:** the airport's METAR reports archived by the Iowa Environmental Mesonet, routine and special, read from
  the raw report text. For New York the settlement station is Central Park, which is not an airport; its own reports
  are used.
  - Only the hourly rain group (Pxxxx) of each report counts. Never the 6-hour (6xxxx) or 24-hour (7xxxx) groups,
    never IEM's derived columns, never IEM's 1-minute or 5-minute rows.
  - Amounts are never added together (a special report's group is a running total since the last routine report).
  - P0000 (a trace) and rain named in the weather text without an amount do not count.
  - Reports up to and including the first routine report after the day start are ignored (that report's hour began
    before the day did, so it can carry yesterday's rain).
  - A corrected (COR) report is ignored; the first version stands.
- Kalshi settles on the NWS daily climate report, which uses the same gauge, so the gauge is close to but not exactly
  the settlement source.

## 3. Decision times and delays (fixed now)
- **Decision times:** every 30 minutes, at :00 and :30 UTC, from 30 minutes after the market's day starts until 60
  minutes before it ends.
- **What is known at a decision time t:**
  - radar: the frames stamped exactly t - 10 minutes and t - 40 minutes (a frame takes several minutes to appear). No
    other frame is substituted. Without the t - 10 frame, R and P cannot fire at t; without the t - 40 frame, P
    cannot.
  - gauge: reports whose observation time is at or before t - 10 minutes.
- **The price paid:** the YES ask at the close of the minute candle ending exactly at t + 1 minute; if there is none,
  the last candle ending no more than 5 minutes before that; otherwise no trade, counted. The candle must show
  0 < bid < ask, and an ask of $1.00 means no trade.
- A market trades at most once per rule: at the first decision time the rule's conditions hold.

## 4. The three rules (fixed now; no other threshold is tried)
- **G:** a counted report (section 2) whose own hourly group is 0.01 inch or more, and the ask is 95c or less.
- **R:** at least 4 pixels of 20 dBZ or more within 10 km of the station in the frame at t - 10, G's gauge condition
  not yet met, and the ask is 90c or less.
- **P:** with "echo distance" = the distance to the 4th-nearest pixel of 25 dBZ or more within 150 km of the station
  (fewer than 4 such pixels: no echo), all of these:
  - R's radar condition is not met in the frame at t - 10 (it is not raining at the station yet);
  - the echo distance at t - 10 is 75 km or less;
  - the frame at t - 40 has an echo distance, and the distance at t - 10 is at least 10 km shorter (closing in at 20 km
    an hour or more: the "speed" measured from the radar itself). A frame at t - 40 without an echo means P cannot
    fire: a newly formed cell is not an approaching one;
  - G's gauge condition is not yet met;
  - the ask is 85c or less.
- The 4-pixel minimum (about 1 square km) is there so that a single pixel of ground clutter cannot fire a rule.
- Each signal buys one YES contract at the price in section 3 and pays the taker fee, rounded up to the cent. It is held
  to settlement.

## 5. Scoring (once)
- **Per rule:** profit per contract = (1 if the market resolved yes, else 0) - price - fee.
- **Days:** every market day in the range with at least one included market. The day's value is its summed profit (a
  day without a signal counts as 0). Cities on one day share weather, so the day is the unit.
- **"Money shown" for a rule needs all three, each at the rule's own Holm level:**
  1. the day-mean t above the one-sided Student-t value for days - 1 degrees of freedom, never below 2.0 (computed
     exactly in plan11.py; with about 118 degrees of freedom: about 2.43, 2.27 and 2.0 for the three levels below);
  2. the lower bound of the 7-day moving-block bootstrap of the day values above zero (20,000 draws, seed 11, PLAN7's
     pinned functions; one bootstrap, read at the rule's level);
  3. **the win-rate bound.** These bets win a few cents often and lose almost everything rarely, so a sample without
     a loss would pass 1 and 2 by luck. Count signal days as trials; a signal day wins only if every signal of that
     day won. The exact (Clopper-Pearson) one-sided lower bound for the day win rate must be above the rule's mean
     price plus fee per contract.
- **Holm over G, R and P** at a family level of 2.5% one-sided: order the rules by their t p-value; the smallest is
  judged at 0.833%, the next at 1.25%, the last at 2.5%; a rule passes only if all three conditions hold at its level;
  stop at the first rule that fails (later ones read "no lag shown").
- **What condition 3 demands (stated before the data):** with no losing day at all, a rule that pays about 96c needs
  about 118 signal days at the 0.833% level; 91c needs about 40 signal days at 2.5%; 15 signal days can only confirm a
  mean cost under about 78c. There are about 119 market days in all, so **G is almost surely not confirmable here**,
  and R and P only if they buy well below their caps.
- **Not testable:** a rule with fewer than 30 signals, or signals on fewer than 15 market days, reads "not testable".
  If more than 10% of markets lose their radar frames, gauge reports or candles, the whole plan reads "not testable".
- **Verdict per rule:** "lead on past data: justifies a forward paper test" or "no lag shown". Nothing here can justify
  real money. Leads for R and P on the same storms are not independent of each other.
- **Descriptive only, never used to pick anything:** signals and win rate by rule, by month and by price band; how long
  after a P signal the gauge first reported rain; how fast the ask moved in the 30 minutes after each signal; the share
  of rain days where each rule fired at all; G's profit without signals in the day's first hour; missing data by
  outcome (outages cluster in storms); how often the gauge rule and Kalshi's result agree.

## 6. What the test can and cannot show
- **Capacity is small by nature.** These are bets at high prices: many wins, a few cents each, and a full loss when the
  rain misses the gauge. A rule that buys at 80c needs to win more than about 81 times in 100 after fees.
- **Radar is not the gauge.** Light echoes often do not reach the ground or miss the gauge (the climate report needs
  0.01 inch). The rules' thresholds are plain choices made in advance, not tuned; a fail does not prove no radar rule
  works, only that these do not.
- **The gauge is not the settlement.** G can fire on a day Kalshi settles "no": a false tip or maintenance later
  removed from the climate report, frozen precipitation, or an hour that straddles the day boundary.
- **A cheap ask after a gauge report is a warning.** Whoever is selling may know the report was one of those cases.
  The profit measure includes this; it is why G is tested rather than assumed.
- **The delays are conservative.** A report at :53 is first used at :30, 37 minutes later. A fail therefore says
  nothing about lags of a few minutes, which this laptop could not trade anyway.
- **Thin prices.** Minute candles show the best bid and ask, not how many contracts were for sale. Results assume one
  contract fills at the ask.
- **Power:** low, and stated in section 5. "Not testable" or "no lag shown" are the likely readings.

## 7. Multiplicity across plans
PLAN11 is its own family (intraday rules), separate from the evening-forecast family (the airport test, PLAN7, PLAN8,
PLAN9, PLAN10). A forward plan from PLAN11 must carry Holm's three-rule correction into its own rule.

## 8. Freeze and leakage controls
- This file is frozen at this revision; its SHA-256 goes into CHANGELOG.md.
- research/plan11.py (download, features, scoring) is written after this plan, code-reviewed, and frozen before the
  first download. Where code and text differ, the text wins, by an amendment before any download.
- **Order:** download candles, radar frames and gauge reports; work out the signals without printing any outcome; score
  once; store the result with a copy outside the tradebot folder.
- No tuning, no second run with other thresholds, no rescue (CLAUDE.md section 11a). A new idea needs its own plan.

## 9. Practical notes
- **Tools:** Python with Pillow and numpy to read the radar images (open source). They are installed on the GitHub
  Actions runner, not on the PC (approved by the user 2026-11-11).
- **Size:** about 119 days x 48 decision times x 2 frames, most shared between decision times: about 5,800 frames of
  1-3 MB each, fetched slowly (at most one request a second) with the User-Agent tradebot-paper-research/1.0. Only the
  per-station readings are kept.
- **Where it runs:** downloads and features on GitHub Actions in the public repository; only public data (NOAA radar
  readings, airport reports, Kalshi's public prices) is written there. Nothing touches paper.db or live.db.
- **Time:** a few hours of runner time for the downloads; the score within days.

## 10. What a result can lead to
- **A lead for G, R or P:** a forward paper test (PLAN11F) with a daytime job on the PC that reads radar and prices
  every few minutes and logs hypothetical orders. It would need the user's go-ahead, because it is a new scheduled job.
  Real money would need live.py to place daytime orders, a separate change that only the user can approve after the
  forward test.
- **No lag shown:** stop. Radar stays out of the bot.
