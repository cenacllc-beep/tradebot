# PLAN19: resting bids for Kalshi's liquidity rewards, on every market that pays them (forward paper test)

Written 2026-11-25, 22:30 La Paz, at the user's request ("we need a better strategy to make money on kalshi ... think of
an intelligent way to make money on there", then "go" to this plan, offered in so many words), before any of its
order books, fills or rewards were sampled. Revised 2026-11-26 after its statistics review (agents/statistician.md;
findings in CHANGELOG.md), still before any of its data. Research and paper only. Not financial advice.

## 0. Why this, and the honest prior
- Every strategy we tested that pays the asking price lost about the fee (PLAN2-4, PLAN16-18; CHANGELOG): Kalshi's
  prices are well calibrated, so outguessing them did not work.
- Three facts favour a different approach:
  1. Resting (maker) orders pay no fee on markets of fee type "quadratic" (Kalshi fee schedule, July 7, 2026).
  2. Kalshi's Liquidity Incentive Program (help.kalshi.com, until 2027-01-01, "can end or modify at any time") pays $1
     to $1,000 per market per day to resting orders near the best bid, filled or not, by share of qualifying size.
  3. Rewards are paid by contract size, not dollars: a bid at 5c ties up 5c a contract and scores like a bid at 50c.
- What is known before this plan (PROBE19, research/results/probe19.json, 2026-11-26 UTC; counts only): 6,446
  active liquidity programs in 522 series, nearly all with target size 1,000 contracts and discount factor 5,000 bps,
  about $100 a week per market; almost all of fee type "quadratic". Many are long-dated (awards, primaries, season
  totals); section 1 leaves those out of the scored test.
- PLAN5 L (weather, scored once 2026-11-25, not testable) saw prices move about 1.2-1.4% against the filled side
  within 5 minutes of a fill. Quoting at the reference price (behind the best bid) rather than at the best bid is a
  design choice informed by that earlier result; the markets and the period here are new.
- **Expected result:** if reward eligibility is not on record before the first sample (section 5), only the
  spread-alone verdict counts, and for quotes that sit behind the book that is very likely "no edge shown" or "not
  testable". With rewards, a positive figure is plausible on paper, but it checks a model of the rewards, not Kalshi's
  payments. At $25 even a pass earns cents to a few dollars a day.
- The few weather series in the universe (e.g. KXRAINTHANKSGIVING, KXSNOWDAYS) are unrelated to v3 and the gate.

## 1. Universe and samples
- **Markets:** any market with an active liquidity program (incentive_type "liquidity", start <= sample < end; the
  program list is re-read when older than 6 hours) whose series' fee type is exactly "quadratic" (others, including
  "quadratic_with_maker_fees", are left out and counted), status active, closing more than 6 hours after the sample
  **and no later than 2026-12-27 23:59 La Paz**. Programs on longer-dated markets are counted and reported
  descriptively only (their count and total reward), never scored.
- **Samples:** hourly from 2026-11-28 00:00 to 2026-12-27 23:59 La Paz time (30 days), on GitHub's runner (Kalshi
  public GETs only; workflow cron every 20 minutes, one sample per clock hour, so a skipped start is made up within the
  hour). A "sampled hour" is a clock hour with a sample log entry; missed hours are reported by day.
- **Draw:** the eligible universe, sorted by ticker, minus any market whose previous sample's 60-minute window is still
  open, then `random.Random(seed).sample(universe, min(40, len))` with seed = the integer UTC epoch hour
  (unix seconds // 3600) of the sample.
- **Day:** the La Paz local date of the sample timestamp.

## 2. The hypothetical quote (fixed now)
Per sampled market and side (YES and NO separately), from the order book at the sample:
- **Price:** the side's Reference Price (Kalshi's rule, re-cited with its date at the freeze: the first level from the
  best bid down where cumulative size reaches one fifth of the target size).
- **Size:** q = 100 contracts. (10 and 1,000 are reported too, exploratory.)
- **Skips (counted):** a side without bids or whose cumulative size never reaches the reference; a market whose best
  YES bid plus best NO bid is 1.00 or more; a quote at 0c or 100c.
- It never improves the best bid and never crosses.
- **Capital-hours:** the sum over quoted sides of q x quote price x 1 hour. Capital held in filled positions is not
  added.

## 3. Reward for the hour after the sample
Kalshi's rules re-cited 2026-11-26 from help.kalshi.com/incentive-programs/liquidity-incentive-program (page "updated
over 3 weeks ago"): reference price = first level from the best bid where cumulative size reaches one fifth of the
target; a snapshot counts only if both YES and NO meet the target size; snapshots once a second; each side scored
separately, so one snapshot is worth at most 2.0 shares across all participants; the $1.00 minimum applies per market
program ("several sub-dollar programs stay unpaid rather than combining"); US members only, no IB/FCM customers, SSN
above IRS thresholds; ends 2027-01-01.
- **Program:** if more than one active program covers a market, the one with the lowest hourly rate is used; overlaps
  are reported.
- **Hourly pool** = period_reward / 10,000 dollars x 3,600 / program length in seconds.
- **Valid** only if each side's total resting size is at least the target size at the sample (Kalshi excludes
  snapshots without two-sided liquidity; rule re-cited with its date at the freeze).
- **Qualifying size per side:** the sum of each level's size x d^k (k = cents below the reference, 0 at or above it;
  d = discount_factor_bps / 10,000).
- **Our share per side** = q / (qualifying size + q).
- **Weight drift:** for each minute before the side's first fill, weight_t = d^max(0, B_t - B_0) (cents), with B_t the
  side's best bid from Kalshi's one-minute candles and B_0 its best bid at the sample; minutes without a candle carry
  the last known B_t; if the side has no candle at all in the hour, every minute's weight is 0.5.
- **Side reward for the hour** = hourly pool x share x (sum of weight_t over minutes before the first fill) / 60 / 2,
  if valid, else 0. The pool is split equally between YES and NO, as in lip.py.
- **$1 minimum payout:** per program, estimated payout = mean sampled hourly reward of that market x hours the market
  was eligible in the window (program active, inside section 1's rules); a program whose estimate is under $1.00
  contributes 0 (per market program, as Kalshi's page says).
- **Unit check:** period_reward is read as 1/10,000 of a dollar (PLAN5's check); a program whose implied reward lies
  outside $1-$1,000 per market per day makes the rewards verdict not testable.

## 4. Fills and what they are worth
- **Queue:** the size resting at the quote price b on that side when sampled.
- **Fills** from Kalshi's public trades in the hour after the sample: on the YES side, trades where the taker sold YES
  (taker_side "no") at a YES price below b fill us in full up to their size, and trades at exactly b fill us only
  after their cumulative size passes the queue. Total filled is capped at q. The NO side likewise. (lip.py's queue is
  the best bid's size; this needs new code.)
- **P&L** = contracts x (payout - quote price), no fee; payout follows strategy.payout (yes, no, scalar, void). A YES
  fill and a NO fill in the same market-hour lock in 1.00 minus both prices.
- **Still open at scoring:** valued at what selling the filled contracts into that side's bid ladder at scoring time
  would bring, level by level, minus Kalshi's taker fee (0 for any part the ladder cannot absorb).
- **Adverse selection (reported):** the mid 1 and 5 minutes after each fill, in the filled side's favour.

## 5. Score (once, from 2026-12-29 00:00 La Paz)
- **Which verdict applies is fixed before the first sample** (2026-11-28 00:00 La Paz), from the eligibility record in
  CHANGELOG.md as it stands then: the rewards verdict applies only if the user has confirmed by then that his Kalshi
  account is eligible for the Liquidity Incentive Program (a US member, not an introducing-broker or FCM customer; an
  SSN on file for rewards above IRS thresholds). Otherwise the rewards figures are reported only.
- **No interim figures:** before the score only counts are shown (samples, markets, fills); no reward or P&L number.
- **Counted:** a sampled market-hour whose fills were checked and whose day has at least 12 sampled hours; everything
  left out is counted by reason.
- **Statistic:** total net / total capital-hours (return per dollar of capital per hour).
- **SE:** the largest of (1) two-way clustered by day and event (Cameron-Gelbach-Miller), (2) clustered by day,
  (3) clustered by event, (4) clustered by series, (5) the no-edge SE of the fills (each filled contract's
  sqrt(p(1-p)) at its price, summed within an event).
- **Two verdicts, the same rule:**
  - **Spread alone** (fill P&L only). Always applies.
  - **With rewards** (net = rewards + fill P&L), if it applies (above).
- **PASS** (each verdict) only if all hold:
  1. the statistic is above 0 by at least 2.5 SE; for the rewards verdict this must also hold with rewards x 0.5 (a
     haircut, because the rewards are modelled, not observed);
  2. at least 20 counted days, and at least 100 filled market-hour-sides across at least 30 events;
  3. rewards verdict only: fill P&L alone is above -0.5 x rewards.
- **Not testable:** condition 2 fails; the unit check fails (rewards verdict only); or more than 5% of filled
  contracts are valued at the bid ladder rather than a settlement.
- A FAIL means the test could not tell, not that there is no edge.
- **Also reported (exploratory; none can PASS or support a forward rule without a new plan):** rewards and fill P&L
  separately; by category and series (top 10); quote price bands (1-5c, 6-20c, 21-50c, 51-99c); share of valid
  samples; q = 10 and 1,000; long-dated programs (count and total only); and an illustration at $25: the number of
  100-contract sides $25 funds at the median quote price x the mean net per side-hour x 24 (an upper bound: capital in
  filled positions is not free).

## 6. Known limits (so a pass is read correctly)
- Paper only, and the rewards are modelled: a rewards PASS checks this model's arithmetic, not Kalshi's payment.
  Hourly samples stand in for Kalshi's per-second snapshots, and cancellations ahead of us are ignored; both push the
  paper reward up. Big market makers may change shares between samples. Kalshi's own reward statement is the real test.
- Resting orders would need live.py to place resting (not immediate-or-cancel) orders, with its own limits; that change
  needs the user's explicit instruction and its own review, and live.py's $50 cap and loss stops still apply.
- Kalshi can end or change the program at any time; it is scheduled to end 2027-01-01, so a pass may have nothing left
  to trade on unless Kalshi extends it.

## 7. Power (stated before the data)
A day-SE approximation (the scored SE is the largest of several): with 30 days the SE of the mean is about 0.18 of the
day-to-day standard deviation, and 2.5 SE plus 80% power (3.34 SE) means the smallest return the test reliably sees is
about 0.61 times that deviation. Smaller real edges will usually read FAIL. Indicative figure from PLAN5 L's weather
data (its scored SE 0.042 over 11 days, so a day-level deviation of about 0.14 per dollar-hour): the smallest edge
PLAN19 would reliably see is about 8-9% of capital per hour, far above any plausible spread edge. Read plainly: the
spread-alone verdict will almost surely be FAIL or not testable, and only a large modelled reward can pass.

## 8. Freeze
Frozen after its statistics review; its SHA-256 goes into CHANGELOG.md. research/plan19.py is written after the freeze
(reusing research/lip.py's ladder, reward and candle functions where they match this text), code-reviewed and frozen
before the first sample. Where code and text differ, the text wins, by an amendment before any number is computed.
