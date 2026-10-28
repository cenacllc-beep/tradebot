# Plan 2: temperature markets, overnight drift, later scan
Written 2026-10-14 08:20 local, before any of the data below was fetched or scored. Research only: nothing here changes
the live bot, v3, its limits or the gate. Same honesty rules as PLAN.md: the holdout is scored once; a changed method
is a new, separately labelled analysis.

## A. Temperature markets (Kalshi KXHIGH series)
Data
- Markets: every settled KXHIGH* market whose market day is 2026-07-01 or later (so nothing overlaps the training
  year). Station = the CLI code in the rules. Strike type and strikes from the market's fields (greater than F,
  less than C, between F and C inclusive; CLI highs are whole degrees F). Outcome = Kalshi's result. Duplicate
  contracts (same day, station, type and strikes): keep the one with the most volume.
- Price: quote at 00:55 UTC on the market day (8:55 PM La Paz the evening before); usable only if
  0 <= bid < ask <= 1 and ask - bid <= 0.06.
- Forecast: NBM station guidance (NBS) evening run (18/19 UTC) of the day before, from IEM: TXN valid 00 UTC the
  next day (the daytime maximum) and XND (its standard deviation). Missing -> skipped.
- Training: 2025-07-01..2026-06-30, NWS daily climate report highs at the same stations.
Model T: high ~ Normal(TXN + a, s0 + s1 * XND), fitted by maximum likelihood on the training year only, then frozen.
P(YES): greater than F -> P(X > F + 0.5); less than C -> P(X < C - 0.5); between F and C -> P(F - 0.5 < X < C + 0.5);
clipped to [0.01, 0.99].
Measures and verdict: exactly as PLAN.md for rain (Brier vs market with day-clustered noise and the 2-SE "clear"
rule; the bot's 50/50 blend; one contract per signal, paying the ask with fees, or a limit order cancelled at the
day start with the same fill rule). Edge demonstrated only if the forecast or the blend clearly beats the market on
Brier AND a trading version is above zero by 2 day-clustered standard errors.

## B. Overnight drift (rain and temperature)
At the 8:55 PM quote, the bot's rule decides direction (fair = 0.5 * forecast + 0.5 * mid; buy YES at the ask if
fair - ask >= 0.08; buy NO at 1 - bid if bid - fair >= 0.08). The position is sold when the market's day starts
(00:00 local standard time) at that moment's bid for the side held, so the weather outcome never matters. Taker fee
on both trades (round up to the cent, one contract). Second version: enter with the limit-order rule (same fill
rule), exit the same way. Skipped (and counted) if there is no quote at the day start. Clear = profit per market
day above zero by 2 day-clustered standard errors.

## C. Later scan (rain and temperature)
The same tests as the 8:55 PM ones, but at 03:30 UTC (11:30 PM La Paz) with the newest NBS run out by then (00 UTC in
IEM's 2026 labels, 01 UTC in 2025 labels), the same frozen models (no refit), the 03:30 UTC quote, limit orders
cancelled at the day start. Compared with 8:55 PM on the same markets: "later is better" only if the limit-order
profit per market day is higher by at least 2 standard errors of the paired daily differences.

## D. Reading the results
- Three new questions on top of the rain test. One "clear" result among several is weaker than it looks; the
  report says so.
- Any clear result is a lead only: it gets a forward test with identical rules on new markets, judged after 60
  market days, like the rain limit-order lead (PLAN.md).
- Stop rules are in CLAUDE.md section 11a.

## Amendments (written 2026-10-14 10:10 local, after the data was fetched and before anything was scored)
1. Which temperature markets have a station "in the rules". Markets from mid-August 2026 on name the NWS report in
   rules_primary ("Austin (CLIAUS)"). Earlier markets name only a place there ("Austin Bergstrom"); some (Houston)
   give the code in rules_secondary ("Data for CLIHOU can be found ..."), most do not. As written, the station must
   come from the rules, so a market is included only if rules_primary or rules_secondary names the CLI code. Earlier
   markets that name only a place are left out rather than guessed. In practice the temperature holdout starts in
   mid-August for most cities.
2. Forecasts used in B and C: the frozen rain model from plan 1 (research/results/rain_model.json) for rain markets
   and model T for temperature markets, each blended 50/50 with the mid as in the bot.

## Result (scored once, 2026-10-14 11:59 local; research/results/plan2.md)
Nothing clear, so no edge is demonstrated on past data and nothing new goes to a forward test.
- A. Temperature: 10,885 markets over 105 market days. Market Brier 0.1016; NBM as published 0.1200; calibrated model T
  0.1219 (high ~ Normal(TXN + 0.27, 1.10 + 0.76 x XND)); blend 0.1076. Paying the ask -4.4c a contract over 1,654 trades;
  limit orders -2.7c over 1,752 fills. Data checks: 99.98% agreement with NWS reports (shown rounded as 100.0% in plan2.md), one YES per complete city-day.
- B. Overnight drift: rain +0.1c (taker, 125 trades) and -0.5c (limit, 153); temperature -5.0c and -3.3c.
- C. Later scan (03:30 UTC): rain -2.2c a market day vs 8:55 PM (2 SE 16.2c); temperature -12.2c (2 SE 25.1c). Not better.
- Not part of the plan, noted only: the calibrated model scored slightly worse than the raw NBM numbers on Brier, so the
  maximum-likelihood spread fits the error distribution but not the threshold questions. Not tested further.
- Decision (user, 2026-10-14 12:07): the bot keeps logging temperature markets but no longer opens temperature paper trades.

