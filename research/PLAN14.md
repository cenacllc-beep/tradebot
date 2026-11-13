# PLAN14: telling skill from luck on Kalshi's sports and crypto markets

Written 2026-11-12, 19:30 La Paz, at the user's request of 2026-11-12 11:41 (quoted in section 0), before any trade,
price, result, injury report or rating for this plan was downloaded or looked at. Revised 2026-11-13 01:30 La Paz after
the independent statistics review (6 MUST, 6 SHOULD, 3 COULD, all applied) and the user's answers of 2026-11-12
(section 9), still before any of its data; frozen at this revision. Research and paper only: never part of the gate, never connected to live.py. Anything that
passes earns a forward paper test on new markets; real money would need a separate change to live.py that only the
user can approve after that test (CLAUDE.md sections 3, 11a).

**Disclosure.** Already seen before this plan: the market catalogue's series list and total volumes per category
(research/data/discovery.db, metadata only: Sports about $12.8 billion traded across 1,936 series, Crypto about
$0.5 billion). PLAN4 test K1 (copying large Kalshi trades, all categories, markets closing by Oct 13) FAILED at
-2.2c a contract over 37,669 copies, with a standard error so wide (about 4.5c per market date) that it could not
have detected less than about 15c. Nothing else from sports or crypto markets has been looked at.

## 0. The request
> Build a research system that tests whether skill can be told from luck on Kalshi's sports and crypto markets, and
> whether any of it can be used after costs. Write the rules before touching the data. (1) From Kalshi's public trade
> feed and order-book history (no scraping of profiles), measure whether large or early trades predict the closing
> price and the result. Rank patterns on one period and score them on a later one. (2) Measure how fast prices react
> to official injury reports, lineups and large trades, to learn whether a real-time signal is reachable from my
> setup. (3) Build one calibrated rating model for one league from official play-by-play and injury data. Judge it by
> closing-line value against Kalshi's prices and the sharpest sportsbook lines. (4) Run every test on a placebo as
> well, control for the number of patterns tried, and count fees and how much can be bet. (5) Report what failed as
> plainly as what passed. Anything that passes goes to paper trading on new markets before any real money. (6) For
> hyped penny stocks, study only how often they fall after the hype, as a risk to avoid.

## 1. Honest prior
- Sports prices on Kalshi follow the big sportsbooks closely, and crypto prices follow spot exchanges; professional
  market makers trade both. PLAN4 K1 found no edge in copying large trades. Expected result for every part: no edge
  shown. A clear "no" is a useful result and costs nothing.
- Kalshi's public trade feed has no trader names, so "skilled traders" can only be studied as trade patterns, not as
  people. Profiles are not scraped (no documented interface; the user was told).

## 2. Common rules for every part
- **Unit.** Outcomes inside one event (one game, one crypto day) move together, so the event is the unit: values are
  averaged within an event, and an event counts once. Events on one calendar day share news and flows, so standard
  errors are clustered by calendar day (US Eastern); the bootstrap is described below.
- **Find and check.** Every part that chooses anything (a pattern, a threshold, a calibration) chooses it on the
  "find" period only and is scored once on the later "check" period. The periods are fixed in section 3 by date,
  before any data is fetched.
- **Reference ("closing") price.** Games: the mid (when 0 < bid < ask, else the last trade) in the minute before the
  scheduled tip-off, taken from the league's official schedule (a game without a listed start is left out and
  counted). Crypto daily and hourly markets: the mid 15 minutes before close_time, because by the close the price is
  already about 0 or 1 and "closing-line value" would just be the result. "Closing-line value" (CLV) of a position =
  the reference price minus the price paid, on the position's side, in cents. Only signals made before the reference
  time count; trades after it (in-play, or the last 15 minutes of a crypto market) are never signals.
- **Costs.** Kalshi's taker fee as listed for each series (fee type and multiplier read from the series record and
  stored with the data, and checked against Kalshi's fee-change history for the period); quadratic type: round up(multiplier x 0.07 x C x P x (1 - P)) to the cent. A rule that buys
  pays the ask at the next minute after its signal; a rule that would rest a limit order is not tested here.
- **How much can be bet.** For every signal, the contracts traded in the 10 minutes after it (from the trade feed) are
  recorded. A rule's capacity = the median of those counts, labelled an upper bound (it counts both sides and includes
  the flow being copied); profit is reported per contract and for that capacity.
- **Bootstrap.** Days already absorb the dependence inside a day, so the bootstrap resamples 2-day blocks of days
  (20,000 draws, seed 14), read at the rule's Holm level.
- **Placebo.** Every scored statistic is also computed on a placebo with the same number of signals in the same
  markets, each moved to a random other time in the same timing bucket of the same market at which the price lies in
  the same price band (redrawn until it does; a signal with no such time is dropped from both the real and the
  placebo sets, and the count is reported), and the side taken from the trade at that time. 1,000 draws. The share of
  placebo draws at least as good as the real one is reported. A rule passes only if that share is at most its Holm
  level (for example 0.5% at Holm's first step), in addition to its own test. Spread, fee and price level then match.
- **Many tries.** The number of patterns tried in each part is fixed here. Within a part: Holm at a family level of
  2.5% one-sided. Across the parts that can pass (1 and 3): a trading proposal also reports the line for both families
  together (1.25%).
- **Verdicts.** "Lead: justifies a forward paper test on new markets", "no edge shown", or "not testable" (fewer than
  100 signals or fewer than 30 days with a signal in the check period; even at that size only an edge of about 25c a
  copy-day could show, and the report says so). Failures are reported with the same detail as
  passes, in the same table.
- **Data hygiene.** Downloads first; signals and features worked out without printing any result; scored once; the
  result stored with a copy outside the tradebot folder; a second scoring is refused. No outcome is printed during
  collection.

## 3. Periods and markets (fixed now)
- **Markets.** Settled, binary, single markets (no combos) from these series families, read from the catalogue's
  series list at download time and stored before any price is fetched:
  - Sports: game-winner markets of the NBA, NFL, college football, NHL and the top European football leagues;
  - Crypto: the daily and hourly BTC and ETH price markets (the 15-minute markets belong to PLAN15).
  At most 400 markets per series and month, chosen by a seeded random draw (seed 14) among those with at least 100
  contracts traded by the market's reference time (section 2), so that a few huge events cannot dominate. Volume is
  correlated with news; this selection is recorded as a known effect.
- **Find period:** markets closing 2026-10-14 to 2026-11-10 (after K1's window, which ended Oct 13).
- **Check period:** markets closing 2026-11-11 to 2027-01-10, collected forward as they settle.
- Part 3 uses its own history (section 6).

## 4. Part 1: do large or early trades predict the closing price and the result?
- **Data.** Kalshi's public trade feed (GET /markets/trades, read-only, the approved Kalshi domain): time, price, count,
  taker side for every trade; minute candles for the closing price.
- **Patterns (fixed menu, 36 in all).** A trade's direction is its taker side. Each pattern is size x timing x price:
  - size: large (count in the top 1% of the series' trades in the find period), medium (top 1-10%), any; a series with
    no find-period trades uses the thresholds of all series of its family (sports or crypto) together;
  - timing, measured from the market's open_time to its reference time (section 2), both known when the trade happened
    (never the actual close, which can come early once a result is known): early (first 20%), middle, late (last 20%);
  - price band of the trade: under 30c, 30-70c, over 70c, all;
  ... 3 x 3 x 4 = 36 patterns.
- **Copy rule.** At most one copy per market and direction per pattern: the first qualifying trade. The copy buys one
  contract on the same side at the next minute's ask.
- **Measures per copy:** (a) CLV in cents; (b) profit after fees at settlement.
- **Find step.** In the find period, a pattern is kept if its mean CLV per day is above zero by at least the Student-t
  value at the Bonferroni level 2.5%/36 (one-sided). At most the 5 kept patterns with the largest t go on. If none is
  kept, Part 1 reads "no edge shown" and stops.
- **Check step (once).** For each kept pattern: day-mean profit after fees, its t above the one-sided Student-t value
  at its Holm level, the bootstrap's lower bound above zero, and the placebo rule (section 2). CLV is reported next
  to it but does not decide (it is the measure of skill; profit is the measure of use).
- **Standard error used by the code:** the day-mean standard error, with a floor of 0.43 dollars / sqrt(days) (K1's
  null floor per day; it stops a few heavy favourites with tiny spread from looking precise). Fixed now.
- **Power (written before the data, from that standard error).** Check period about 60 days: SE = 0.43 / sqrt(60) =
  5.6c. With 5 kept patterns, Holm's first step is 0.5% one-sided, t(59) about 2.66, so 80% power needs
  (2.66 + 0.84) x 5.6 = about 20c per copy-day; at the last step (2.5%, t about 2.0) about 16c. The find screen runs on
  about 28 days at 2.5%/36 (t(27) about 3.5), so a pattern must first look strong there too; overall power is the
  screen's times the check's. Real edges below about 15-20c a copy-day will read "no edge shown". This is said up
  front, not discovered afterwards.

## 5. Part 2: how fast do prices react? (descriptive only; nothing passes or fails)
- **Events.** (a) NBA official injury report releases (the report's own time stamp) in which a player's status changed
  to or from "out"; (b) large trades from Part 1's definition; (c) for crypto, minutes in which BTC moved 0.5% or more
  on the spot price (Coinbase, approved 2026-11-12).
- **Measure.** For the markets each event concerns, the signed change in Kalshi's mid in the direction of its move from
  30 minutes before to 30 minutes after the event, at -30, -15, -5, 0, +1, +2, +5, +15 and +30 minutes. The same
  measure at 200 random non-event minutes in the same markets (signed the same way) is subtracted, because even pure
  noise grows with time. The pre-event points show how much was already in the price, since news often comes out
  before the official report.
- **Reading, fixed now.** "Reachable from this setup" only if, in the median event, less than half of the baseline-
  corrected move from -30 to +30 minutes has happened by +2 minutes and the move after +2 minutes is larger than the
  fee. The laptop polls every few minutes at best, so a faster market is out of reach, whatever the size of the move.
  The answer is reported for each event type.

## 6. Part 3: one calibrated rating model for one league
- **League.** The NBA (the user's choice of 2026-11-12). Regular-season and play-off games only; preseason games are
  left out. Neutral-site games (the in-season tournament's final rounds in Las Vegas, games abroad) have home
  advantage 0.
- **Model (fixed, no tuning).** An Elo rating with published standard settings: K = 20, home advantage 100 points,
  margin-of-victory multiplier ((MOV + 3)^0.8) / (7.5 + 0.006 x the winner's Elo lead before the game), as in the
  published FiveThirtyEight NBA Elo (checked against its published description before the code is frozen), start-of-
  season carry-over of 0.75 toward 1505. Win chance = 1 / (1 + 10^(-(rating gap + home advantage)/400)). Ratings use
  only games completed before each decision time.
- **Version 3b (injuries; its own test, not a replacement).** Each player listed "out" in the last official injury
  report before the decision time removes from his team's rating his share of team minutes in the team's previous ten
  games times a fixed 100 points. 3 and 3b are judged together under one Holm over six tests (A, C, T for each).
- **History to warm up the ratings:** all game results of the previous two seasons and this season up to the find
  period, from the NBA's official published results (approved 2026-11-12). If the official source does not give the
  earlier seasons, the warm-up uses what it gives, and the plan records that before any Kalshi price is read.
- **Calibration.** One logistic map logit(q) = a + b logit(Elo chance), fitted once on the find period's games against
  results, then frozen.
- **Decision time.** Two hours before the scheduled start. Kalshi's ask on each side at that minute.
- **Judged in the check period, once:**
  - **A (accuracy):** game Brier score of q against Kalshi's mid at the decision time; day-mean difference, t and
    bootstrap as in section 2.
  - **C (closing-line value):** for each game where q differs from the mid by 5 points or more, the CLV of buying the
    side q favours at the decision time; day-mean CLV, t and bootstrap.
  - **T (money):** the same bets held to settlement, profit after fees.
  - Holm over the six tests (3 and 3b); T is the only kind that could justify a forward paper test of a trading rule.
- **Sportsbook comparison.** Not made (the user's choice of 2026-11-12: Kalshi's own closing price is the benchmark).
  The report says plainly that the sharpest sportsbooks were not compared.
- **Power:** assuming a per-game Brier-difference standard deviation of about 0.07, 7 games a night and 60 nights:
  SE = 0.07 / sqrt(7) / sqrt(60) = 0.0034; at Holm's first step of six (0.42%, t about 2.7) the detectable gain is
  about (2.7 + 0.84) x 0.0034 = 0.012 a game. The market's own Brier is about 0.21, so only a large real advantage
  could show.

## 7. Part 6 (Parts 4 and 5 of the request are the common rules in section 2): hyped penny stocks (risk study only)
- **No tool for buying stocks is built.** This part says how often heavily promoted small stocks fall afterwards, as
  a warning. It is not investment advice.
- **The user's choice of 2026-11-12: a written summary only.** A short summary of published research on promoted
  stocks and of the SEC's investor alerts on stock promotions, with every source listed. No new data source, no
  download, no test.

## 8. What the results can and cannot show
- A pass is a lead on one period of markets; it earns a forward paper test on new markets with the same rules, written
  before the first forward result. A fail says these patterns do not work; it does not prove that no pattern does.
- Paper fills at the ask ignore queue and size beyond the recorded capacity. Fees are approximate.
- Sports and crypto markets change quickly (new market makers, new rules), so a past lead can fade.

## 9. Sources (the user's answers of 2026-11-12, asked in so many words)
- Already approved: Kalshi's public API (trade feed, candles, markets; read-only) and Polymarket's public prices.
- Approved 2026-11-12: the NBA's official published game results, schedule and injury reports (read-only), for
  Parts 2 and 3; Coinbase's public market-data feed for one-minute BTC-USD and ETH-USD prices (read-only, no account,
  no key), for Part 2 and PLAN15.
- Declined 2026-11-12: a paid sportsbook-odds service (Kalshi's close is the benchmark) and new stock-data sources
  (Part 6 is a written summary).
Every request uses the User-Agent tradebot-paper-research/1.0 and no personal data. Downloads run on GitHub Actions
(public data only is written there) or on the PC's scheduled jobs, never touching paper.db or live.db.

## 10. Freeze
This file is frozen after its statistics review; its SHA-256 goes into CHANGELOG.md. research/plan14.py is written
after the freeze, code-reviewed, and frozen before the first download. Where code and text differ, the text wins, by
an amendment before any data. No tuning, no second run with other thresholds, no rescue (CLAUDE.md section 11a).
