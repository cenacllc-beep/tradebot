# PLAN 5: being the house, and same-city station gaps (written before any of its data)

Written 2026-10-15 19:55 local, before any Test L sample or Test S price was fetched.

Research only. Nothing here changes the bot, v3, the gate, the stop date, the $25 cap or any limit. Each test is scored
ONCE by its rule below. A pass earns only a next step that the user approves in so many words; it is not a strategy.

Asked by the user on 2026-10-15: "fully implement your recommendations above but lets try to achieve this 15 months
target". The target is $25 to $1M, about 40,000 times, which needs the money to double every month for 15 months.

## What prompted it (already known, so it is not evidence)
- Ordinary takers on Kalshi lost an estimated $584M from 2021 to May 2026 (Roosevelt Institute, July 2026). Market
  makers and sharp traders were on the other side.
- PLAN3 test B's placebo made +4.9c a contract over 179 fills. It posted at the mid on wide spreads in low-temperature
  markets. This was seen after scoring, so it is a hypothesis.
- Kalshi's Liquidity Incentive Program (help.kalshi.com, until 2027-01-01) pays most US members for resting orders near
  the best bid, filled or not. A format check on 2026-10-15 found:
  - /incentive_programs?status=active lists programs per market;
  - weather markets have them (for example KXLOWCC strikes, $100 a week each; 298 KXRAIN programs listed);
  - each has a target size (1,000 contracts) and a discount factor (5000 bps, meaning 0.5 a cent).
- period_reward is read as 1/10,000 of a dollar. That is the only unit consistent with Kalshi's stated $1-$1,000 per
  market per day: 1,000,000 a week is $100. Each score reports reward totals both ways, so a unit error would be
  visible.

## Test L: resting quotes on weather markets with liquidity rewards (forward paper test)
Question: would a small two-sided resting quote on these markets earn more, in rewards plus spread, than it loses to
being picked off when the price moves?

**Universe:**
- Markets in series starting KXRAIN, KXHIGH or KXLOW with an active liquidity program at the sample time
  (start <= sample < end; the program list is re-read when older than 6 hours).
- The market's status is active, it closes more than 2 hours after the sample, and it closes before 2026-11-23 00:00
  local, so every sampled market settles before the score date.
- Kalshi fee type "quadratic" (makers pay no fee). Other fee types are left out and counted.

**Samples:**
- Hourly, from the hourly scheduled run on the user's PC (`run.bat hourly`, at 20 minutes past the hour),
  2026-10-24 00:00 to 2026-11-20 23:59 local time (America/La_Paz). (Moved twice on 2026-10-22, before any sample:
  see the revision notes.)
- Each sample prices up to 40 markets drawn at random from the universe. The seed is the sample's hour, so a rerun
  draws the same markets.
- Hours the PC is off are simply missing; they are counted.

**The hypothetical quote**, per sampled market, from its order book at the sample:
- 10 contracts bid on YES at the best YES bid, and 10 on NO at the best NO bid. It joins the best price and never
  improves it or crosses.
- A side with no bids gets no quote.
- Markets where the best YES bid plus the best NO bid is 1.00 or more are skipped (counted).
- Capital = 10 x YES bid + 10 x NO bid: what both orders would tie up.

**Reward for the hour after the sample** (the program's published rule, applied to the sampled book):
- **Valid** only if each side's total resting size is at least the target size.
- **Reference price per side:** the first price level from the best bid down where the cumulative size reaches one
  fifth of the target size.
- **Qualifying size per side:** the sum of each level's size x d^k, where k = cents below the reference price (0 at or
  above it) and d = discount_factor_bps / 10,000.
- **Our share per side:** 10 / (qualifying size + 10). The quote sits at the best bid, at or above the reference, so its
  weight is 1.
- **Hour reward** = period_reward / 10,000 dollars x 3,600 / program length in seconds x (share YES x f YES + share
  NO x f NO) / 2 if valid, else 0. f is the part of the hour before that side's first fill (1 if it never filled): a
  filled quote stops resting, so it stops earning.
- When a market has more than one active program, the first listed is used and the overlap is counted.

**Fills during the hour after the sample**, from Kalshi's public trade list (/markets/trades, min_ts and max_ts):
- **YES quote at price b:** fills from trades where the taker sold YES (taker_side "no").
  - At a YES price below b, they count in full.
  - At exactly b, only the volume beyond the size that was already resting at b when the sample was taken counts (our
    place in the queue).
  - At most 10 contracts fill.
- **NO quote:** the same rule with taker_side "yes" and NO prices.
- **Filled contracts** are held to settlement: P&L = contracts x (payout - price), no fee.
- A YES fill plus a NO fill locks in 1.00 minus both prices.
- Fills are checked once the hour plus 7 minutes is over, so the 5-minute price after a late fill exists.

**Score (once, on or after 2026-11-25, so the sampled markets have settled):**
- **Which samples count:** a sampled market-hour counts only if its fills were checked, its market has settled, and
  its local day has at least 12 sampled hours. Everything left out is counted by reason.
- Settlement is looked up in batches, then one market at a time for any the batch call does not return.
- **Net** = hour reward + fill P&L, for each counted market-hour.
- **Statistic:** total net / total capital over the counted market-hours (return per dollar of capital per hour).
- **SE:** the largest of three:
  1. clustered by local day;
  2. clustered by event (all strikes of one city-date, in every hour they were sampled, settle together);
  3. the no-edge SE: each filled contract's sqrt(p(1-p)) at its price, added up within an event (they move together)
     and combined across events.
- **Two verdicts, the same rule:**
  - **Spread alone** (fill P&L only). This verdict applies.
  - **With rewards** (net). It applies only if the user's confirmation that the account is eligible is logged with
    its date in CHANGELOG.md and in fees.py (INCENTIVES_ELIGIBLE and ELIGIBILITY_CONFIRMED_ON) before 2026-11-21.
    Otherwise it is reported as "reported only".
- **PASS** (each verdict) only if all of these hold:
  1. The statistic is above 0 by at least 2.5 SE.
  2. At least 15 days, and at least 100 contracts filled across at least 20 different events.
  3. With rewards only: fill P&L alone is above -0.5 times the rewards (rewards carry the result, but the fills must
     not eat most of them).
- **Not testable:**
  - condition 2 fails;
  - or more than 2% of the filled market-hours belong to markets still unsettled at scoring;
  - or, for the rewards verdict only, any program's implied reward is outside Kalshi's stated $1-$1,000 per market per
    day (a unit error).
- **A FAIL means the test could not tell,** not that there is no edge (see Power).
- **Adverse selection (reported):** after each fill, Kalshi's one-minute candle mid (YES bid and ask at the close) 1
  minute and 5 minutes later, in the filled side's favour. The candle used is the latest one ending at or before
  that moment. Fills followed by moves against us mean the quotes are being picked off.
  Each fill record also keeps a descriptive `candle_check` (added 2026-10-23, before the first sample): anomaly codes
  of the fetched candles (tbcommon/ohlc.py) and how old the candle behind each mid was. score() never reads it; it
  only shows when an adverse-selection number rests on an old or broken candle.
- **Also reported:**
  - rewards and fill P&L separately;
  - by series;
  - the share of valid samples;
  - shares for 1 and 100 contracts instead of 10;
  - dollars per day at the $25 cap if quoted around the clock (headline return x 25 x 24). The headline is the
    spread-only figure unless the rewards verdict applies. Capital tied up in filled positions until they settle is
    not in this figure, so it overstates.

**Known limits (so a pass is read correctly):**
- Paper only: Kalshi's own reward statement is the real test.
- The queue model ignores order cancellations ahead of us, and hourly samples stand in for Kalshi's per-second
  snapshots.
- The largest market makers may dilute shares more than one snapshot shows.
- Real resting orders would need live.py to rest orders. Today it sends immediate-or-cancel only. That change needs the
  user's explicit instruction, and the $25 cap still applies: at 10 contracts a side, $25 covers one or two markets at
  a time.
- Program eligibility (US members, an SSN above IRS thresholds) is the user's to check.

**Power:** unknown until sampled. Rewards vary little; fills are lumpy. Over about 25 days the smallest return the
test can reliably detect is about 0.7 times the standard deviation of the daily values (2.5 SE plus a margin for
power, with the SE of a mean over 25 days being one fifth of that deviation). Smaller real edges will usually score
FAIL.

## Test S: same city, different station (past data)
Question: Polymarket's daily high-temperature markets settle on an airport's readings, and Kalshi's on the NWS climate
station (for example LaGuardia vs Central Park). Does Polymarket's price, shifted by the two stations' usual
difference, forecast Kalshi's outcome better than Kalshi's own price?

**City pairs:**
- Kalshi KXHIGH (and KXHIGHT) cities with a Polymarket "highest temperature" event for the same city.
- The two settlement stations must differ. They are taken from the rule texts before any price is read, and saved to
  research/results/plan5_pairs.json.

**Station difference model:**
- Daily maximum at Kalshi's station minus the daily maximum at Polymarket's station, from IEM airport and climate
  data, 2025-07-01..2026-06-30.
- Fitted per pair and month as an empirical distribution (whole degrees).
- Frozen to research/results/plan5_diff.json before any market price is read.

**Markets:** each day 2026-08-16..2026-10-13 that has both venues' markets for a pair. Polymarket keeps 5-minute price
history for about 60 days; days without it are counted. Kalshi strikes, outcomes and duplicates are handled as in
plan 2.

**Forecast at the look time** (10:00 local standard time on the market day, from the last price point at or before it):
- Polymarket's implied distribution is each bucket's mid-price, normalized to sum to 1. A bucket's value is the
  temperature its rules name (edge buckets at their bound).
- Convolve it with the station difference model, then read off P(YES) for each Kalshi strike as in plan 2.
- Clip to [0.01, 0.99].

**Trade:**
- The bot's rule: a 50/50 blend with the Kalshi mid and an 8-point minimum edge, one contract.
- Taker at Kalshi's ask with core.fee. The maker version (backtest2.entries, fill by a later trade through our price
  before the market's close) is descriptive.

**Score (once).** PASS only if all of these hold:
1. Taker profit per contract, averaged within market days, is above 0 by 2.5 SE, with at least 150 trades on at least
   30 market days.
2. The cross-venue forecast's Brier score is below Kalshi's mid's by at least 2 day-clustered SE, over all usable
   strikes.
3. It beats a placebo that uses Polymarket's distribution with no station shift by at least 2 SE (per-day difference
   in profit per usable strike).

With fewer than 30 market days, S is not testable. A FAIL with Brier condition 2 passing is reported as "information,
no tradable edge".

## Multiplicity
- Three scored looks (L spread alone, L with rewards, S), each at a 2.5 SE bar.
- Everything "also reported" is exploratory.
- All results are reported, including failures.

## What a pass would and would not mean for the 15-month target
- Doubling monthly needs about +100% a month after fees, every month. No test so far has found any edge.
- Betting harder does not create an edge. Under the fixed limits (quarter Kelly, 6% a trade) even a large edge grows
  the account a few percent a month.
- Test L is the only idea here whose return can scale with money at risk without a forecasting edge (rewards are paid
  per resting contract). Even then:
  - rewards end 2027-01-01 unless Kalshi extends them;
  - shares shrink as more money competes;
  - thin weather markets hold only small quotes.
- If L passes, the next step is a tiny real pilot after Nov 11. It would need:
  - the user's go-ahead;
  - a live.py change for resting orders, which needs the user's explicit instruction;
  - the $25 cap.
  Kalshi's actual reward statement would then be the evidence. Bigger stakes would follow measured results, never the
  target date.

## Changes on 2026-10-22, before any Test L sample or Test S price
- **Test L window moved to 2026-10-23..2026-11-19, scored on 2026-11-24.** No sample was ever taken: the account hit its
  usage limit on Oct 15, and the scheduled runs on the user's PC stopped until Oct 22.
- **Rewards gated on eligibility.** The user's platform brief (2026-10-22) says incentive income must not count in
  expected returns until eligibility is confirmed. L therefore also reports a spread-only verdict, and that verdict
  is the one that applies until fees.INCENTIVES_ELIGIBLE is set.
- **Adverse selection added:** price 1 and 5 minutes after each fill. The fill rule itself is unchanged.
- The statistics review requested on Oct 15 did not run (usage limit). It is requested again before the first sample.

## Second revision on 2026-10-22, after the statistics review and still before any Test L sample
- **Window moved to 2026-10-24..2026-11-20, scored on or after 2026-11-25.** This leaves a day for the user to approve
  the hourly runner on the PC.
- **Markets that settle after 2026-11-22 are left out of the universe**, so the score never waits on them.
- **Statistic and SE changed:** total net over total capital, with the largest of three SEs (by day, by event, no-edge),
  in place of the mean of day values with a day SE. Strikes of one city-date settle together, so a day SE alone could
  overstate the evidence.
- **Fill condition widened** to at least 100 contracts across at least 20 events, plus at least 12 sampled hours for a
  day to count.
- **Not testable** if more than 2% of filled market-hours are unsettled, or the reward units look wrong.
- **Rewards verdict applies** only with dated eligibility evidence logged before the window ends.
- **Rewards prorated** to the part of the hour before a side fills.
- **Adverse selection** now uses the one-minute candle mid, not the next trade, and fills are checked 7 minutes after
  the hour.
- **Monthly figure replaced** by dollars per day at the $25 cap, and the power statement corrected.

Guidance for Test S from the same review (Test S is not built yet): build its station pairs and difference model
before reading any price, and fetch Polymarket's price history first, since about 60 days are kept and each day lost
shortens the test.


## Logistics on 2026-10-28 (no rule changed; after Test L samples had begun)
- **Where Test L is sampled:** from the next hour after the cutover, GitHub Actions in the repository runs `lip.py sample`
  and `lip.py settle` at :20 every hour (cloud/workflows/plan5-lip.yml), instead of the PC's hourly job. Reason: the
  laptop missed hours while asleep or offline. The code, window, universe, market choice per hour, fill rule and score
  are unchanged; the workflow carries on from the PC's files (research/data/lip/ copied into the repository at the
  cutover), so each hour is still sampled at most once.
- **The PC's copy** is marked research/data/lip/MOVED.txt: there lip.py neither samples, settles nor scores, so nothing
  is collected twice and the PC's partial copy is never scored.
- **The single score** runs in the same workflow, on its first run on or after 2026-11-25, and is committed with the data.

## Logistics on 2026-10-29 (no rule changed)
- On its first evening GitHub's scheduler started 1 of 16 scheduled sample runs (hours 21, 22, 23 and 01 UTC were missed;
  02 and 03 UTC were sampled by runs started by hand).
- **Both copies now sample:** the PC's hourly job runs `lip.py sample` and `settle` again, and GitHub keeps sampling. The
  PC's copy holds research/data/lip/SECONDARY.txt and is never scored itself.
- **Each hour counts once:** before the single score, `lip.py merge <PC copy>` adds to the repository's copy every hour that
  only the PC took (samples, fill records, log row, hours.json entry) and the PC's settled results. For an hour both
  has sample rows for, the repository's copy is kept; an hour it took with no rows gives way to the PC's rows. Both
  copies apply the same rules, but their universes can differ by the minute of sampling (markets closing within 2 hours
  are left out) and by each copy's cached program list, so for an hour both took they may hold different markets. The
  choice of copy is fixed here, in advance, and never looks at outcomes.
- **Overlapping fill windows:** the PC samples at :20 and GitHub at :05 to :50, so consecutive merged hours can have fill
  windows that overlap for the same market and count some trades twice. The score's event-clustered standard error
  already covers correlated market-hours; this is noted, not corrected.
- **Order before the score (procedure, not a rule):** after the window ends, `lip.py merge <PC copy>` (it checks the
  folder, refuses the wrong direction, never adds a market-hour twice and records data/lip/merged.json), push, let the
  hourly job run once (fill checks and results for merged hours), then `lip.py score`. The repository's copy holds
  data/lip/PRIMARY.txt and its score refuses to run without a merge taken after the window (or `lip.py merge-none
  REASON` if the PC copy is lost).
- **The score** runs once, by hand, after that merge, on or after 2026-11-25. The workflow no longer scores by itself.
