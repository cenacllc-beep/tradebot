# PLAN19: resting bids for Kalshi's liquidity rewards, on every market that pays them (forward paper test)

Written 2026-11-25, 22:30 La Paz, at the user's request ("we need a better strategy to make money on kalshi ... think of
an intelligent way to make money on there", then "go" to this plan, offered in so many words), before any of its
order books, fills or rewards were sampled. Research and paper only. Not financial advice.

## 0. Why this, and the honest prior
- Every strategy we tested that pays the asking price lost about the fee (PLAN2-4, PLAN16-18; CHANGELOG): Kalshi's
  prices are well calibrated, so outguessing them did not work.
- Three facts favour a different approach:
  1. Resting (maker) orders pay no fee on markets of fee type "quadratic" (Kalshi fee schedule, July 7, 2026).
  2. Kalshi's Liquidity Incentive Program (help.kalshi.com, until 2027-01-01, "can end or modify at any time") pays $1
     to $1,000 per market per day to resting orders near the best bid, filled or not, by share of qualifying size.
  3. Rewards are paid by contract size, not dollars: a bid at 5c ties up 5c a contract and scores like a bid at 50c.
- What is known before this plan (PROBE19, research/results/probe19.json, 2026-11-26 02:2x UTC; counts only): 6,446
  active liquidity programs in 522 series (entertainment, financial/FX, politics, sports, economics, a few weather),
  nearly all with target size 1,000 contracts and discount factor 5,000 bps, about $100 a week per market; almost all
  of fee type "quadratic". Kalshi listed none on daily weather markets after Nov 5, which left PLAN5 L not testable.
- PLAN5 L (weather, 11 days, scored once 2026-11-25, not testable) saw prices move about 1.2-1.4% against the filled
  side within 5 minutes of a fill: resting orders get picked off. The question is whether rewards cover that.
- **Expected result:** on paper the rewards are real money, so a positive "with rewards" figure is plausible; the
  open questions are the size of our share, how often we are picked off, and whether the account is eligible. At $25
  even a pass earns cents to a few dollars a day. "Not testable" or "no edge shown" are useful answers too.

## 1. Universe and samples
- **Markets:** any market with an active liquidity program (incentive_type "liquidity", start <= sample < end; the
  program list is re-read when older than 6 hours) whose series' fee type is exactly "quadratic" (others, including
  "quadratic_with_maker_fees", are left out and counted), status active, closing more than 6 hours after the sample.
- **Samples:** hourly from 2026-11-28 00:00 to 2026-12-27 23:59 La Paz time (30 days), on GitHub's runner (Kalshi
  public GETs only; workflow cron every 20 minutes, one sample per clock hour, so a skipped start is made up within the
  hour; missed hours are counted). Each sample draws up to 40 markets at random from the universe, seeded by the hour.
- **Program end:** Kalshi's program ends 2027-01-01. Hours after a market's program ends earn no reward by
  construction.

## 2. The hypothetical quote (fixed now)
Per sampled market and side (YES and NO separately), from the order book at the sample:
- **Price:** the side's Reference Price (Kalshi's rule: the first level from the best bid down where cumulative size
  reaches one fifth of the target size). Resting there earns full credit (weight 1) while sitting behind the size at
  better prices, so it fills less often than at the best bid.
- **Size:** 100 contracts. Capital for the side = 100 x price. (10 and 1,000 contracts are reported too.)
- **Skips (counted):** a side without bids or whose cumulative size never reaches the reference; a market whose best
  YES bid plus best NO bid is 1.00 or more; a quote at 0c or 100c.
- It never improves the best bid and never crosses.

## 3. Reward for the hour after the sample (PLAN5's rule, unchanged)
- **Valid** only if each side's total resting size is at least the target size (Kalshi excludes snapshots without
  two-sided liquidity).
- **Qualifying size per side:** the sum of each level's size x d^k (k = cents below the reference, 0 at or above it;
  d = discount_factor_bps / 10,000).
- **Our share per side** = q / (qualifying size + q), weight 1 at the reference.
- **Side reward for the hour** = period_reward / 10,000 dollars x 3,600 / program length in seconds x share x f, if
  valid, else 0; f = the part of the hour before that side's first fill (1 if it never filled). The YES and NO sides
  are scored separately, as Kalshi does. The $1.00 minimum payout per program is applied at scoring (a market's total
  over the window under $1.00 counts as 0).
- More than one active program on a market: the first listed is used; overlaps are counted.
- **Unit check:** period_reward is read as 1/10,000 of a dollar (PLAN5's check); a program whose implied reward lies
  outside $1-$1,000 per market per day makes the rewards verdict not testable.

## 4. Fills (PLAN5's queue rule) and what they are worth
- From Kalshi's public trades in the hour after the sample: a YES bid at price b fills from trades where the taker
  sold YES (taker_side "no") at a YES price below b in full, and at exactly b only beyond all size that rested at b
  and above when sampled (we join the back of the queue). At most q contracts. The NO side likewise.
- Filled contracts are held: P&L = contracts x (payout - price), no fee; a market's payout follows strategy.payout
  (yes, no, scalar, void). A YES fill and a NO fill in the same market-hour lock in 1.00 minus both prices.
- **Unsettled at scoring** (long-dated markets): each held side is valued at that side's best bid at scoring time (what
  it could be sold for), or 0 if it has no bid. This is conservative; the share of P&L valued this way is reported.
- **Adverse selection (reported):** the mid 1 and 5 minutes after each fill, in the filled side's favour (Kalshi's
  one-minute candles, PLAN5's adverse_mid).

## 5. Score (once, from 2026-12-29 00:00 La Paz)
- **Counted:** a sampled market-hour whose fills were checked and whose local day has at least 12 sampled hours;
  everything left out is counted by reason.
- **Statistic:** total net / total capital-hours (return per dollar of capital per hour), net = reward + fill P&L.
- **SE:** the largest of (1) clustered by local day, (2) clustered by event, (3) the no-edge SE of the fills (each
  filled contract's sqrt(p(1-p)) at its price, summed within an event).
- **Two verdicts, the same rule:**
  - **Spread alone** (fill P&L only). This verdict always applies.
  - **With rewards** (net). It applies only if, before 2026-12-27, the user confirms that his Kalshi account is
    eligible for the Liquidity Incentive Program (a US member, not an introducing-broker or FCM customer; an SSN on
    file for rewards above IRS thresholds) and that confirmation is logged with its date in CHANGELOG.md. Otherwise it
    is "reported only".
- **PASS** (each verdict) only if all hold:
  1. the statistic is above 0 by at least 2.5 SE;
  2. at least 20 days, and at least 300 contracts filled across at least 30 different events;
  3. with rewards only: fill P&L alone is above -0.5 x rewards (the rewards carry it, but fills must not eat most of
     them).
- **Not testable:** condition 2 fails; the unit check fails (rewards verdict only); or more than 25% of fill P&L is
  valued at a best bid rather than a settlement.
- A FAIL means the test could not tell, not that there is no edge.
- **Also reported:** rewards and fill P&L separately; by category and by series (top 10); price bands of the quote
  (1-5c, 6-20c, 21-50c, 51-99c), since cheap sides tie up the least capital; the share of valid samples; q = 10, 100,
  1,000; dollars per day at the $25 cap if all $25 rested around the clock (headline x 25 x 24; it overstates, since
  capital held in filled positions is not free).

## 6. Known limits (so a pass is read correctly)
- Paper only. Hourly samples stand in for Kalshi's per-second snapshots; cancellations ahead of us are ignored; big
  market makers may change shares between samples. Kalshi's own reward statement is the real test.
- Resting orders would need live.py to place resting (not immediate-or-cancel) orders, with its own limits; that change
  needs the user's explicit instruction and its own review, and live.py's $50 cap and loss stops still apply.
- Kalshi can end or change the program at any time; it is scheduled to end 2027-01-01, so a pass may have nothing left
  to trade on unless Kalshi extends it.

## 7. Power (stated before the data)
Unknown until sampled: rewards vary little, fills are lumpy. Over about 30 days the smallest return the test can
reliably see is about 0.55 times the standard deviation of the daily values (2.5 SE plus a power margin, with the SE
of a 30-day mean about 0.18 of that deviation). Smaller real edges will usually read FAIL.

## 8. Freeze
Frozen after its statistics review (agents/statistician.md); its SHA-256 goes into CHANGELOG.md. research/plan19.py is
written after the freeze (reusing research/lip.py's reward, queue and candle functions), code-reviewed and frozen
before the first sample. Where code and text differ, the text wins, by an amendment before any number is computed.
