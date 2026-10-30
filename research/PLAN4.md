# PLAN 4: following other traders, written before any of its data is fetched

Written 2026-10-15 11:00 local. Revised 11:40 after an independent statistics review, and 15:10 after an independent
code review of research/plan4.py, both before any data, and 15:55 after a second code review and format checks of
each data source (only the wallet pool's fills had been fetched: wallets and amounts, no outcomes). The changes are
listed at the end.

Research only. Nothing here changes the bot, v3, the gate, the stop date, the $25 cap or any limit. Each test is scored
ONCE by its rule below. A passed P2, P2c or K1 earns only a forward paper test with the same rules on later data
(CLAUDE.md 11a). P1 is informational. Any real-money use after a forward pass needs the user's explicit go-ahead.

Asked by the user on 2026-10-15: "research into other users with very high success rates and possibly the option to
copy trades of the top performers ... identify common trades from top performers". The user approved Polymarket's
public Data API (data-api.polymarket.com, read-only, no account) for this on 2026-10-15.

## Why this needs a test, not a leaderboard
- A leaderboard ranks luck alongside skill. A high win rate is not profit: buying 95c favourites wins about 95% of the
  time and earns almost nothing.
- Many top accounts earn money a follower cannot copy:
  - market makers, who earn the spread;
  - speed and arbitrage bots;
  - occasional traders with private information.
- A follower always trades later, at a worse price. On Kalshi, takers lost almost 32% on average and makers about 10%
  (Burgi, Deng and Whelan, "Makers and Takers", 2025).

Expected outcome, stated in advance: little or no persistence after a fair selection, and no profit for a late copier
after costs. Realistic copy edges are a few cents, below what most of these tests can detect, so a FAIL usually means
"could not tell", not "no edge". Every result is reported, including failures.

## Data and privacy
- Sources:
  - Polymarket Data API v2 (trades, positions, activity, tokens, resolutions);
  - Polymarket Gamma API (market lists, end dates, fees);
  - Kalshi public API (series, markets, trades, candles).
- Kalshi's opt-in profiles are not used: there is no documented API.
- Name, pseudonym, bio, profile images and X handles are dropped on ingest. Only wallet addresses are kept.
- Reports show wallets shortened to their first 6 characters.
- Outcomes are keyed by (condition_id, outcome_index) through /v2/tokens. Markets carried over to Polymarket's v2
  exchange have two token pairs for the same outcome.

## Common statistics
- **Unit:**
  - P1: one wallet's positions in one event (a "wallet-event").
  - P2: one copy.
  - K1: one copy.
- **SE:** every scored statistic's standard error is the LARGEST of:
  - (a) the SE clustered by event (K1: by market date, the date in the event ticker, all series together);
  - (b) the SE clustered by the market's scheduled end date (shared news, crypto prices and game nights);
  - (c) the null SE.
- **Null SE:** the statistic's spread if every market paid our side with probability equal to the price paid. It is
  computed analytically from Bernoulli variances at that price, which is conservative: it ignores profit already
  realized by sells.
- **Bars:** "above 0 by k SE" means the statistic divided by that SE is at least k.
- **Payouts:** each token's actual payout (/v2/tokens final_price: 0, 1 or a split). Where an outcome has two token
  families (v1 and v2), both must agree. Disputed markets are kept; nothing is dropped because of how a market resolved.
- **Resolved:** a /v2/resolutions record with status "resolved". Its time is that record's last_update_timestamp (the
  earliest, if there are several). The format check found no resolved_at field; for one market this time matched
  Gamma's close time to the second.
- **Polymarket fee per share:** rate x (p x (1-p))^exponent, from the market's Gamma fee schedule. If fees are on and
  no rate is published, the rate is 0.07. If fees are off, there is no fee.
- **Kalshi fee:** 0.07 x the series' fee multiplier x C x P x (1-P), rounded up to the cent per order (C = 1
  contract per copy). The multiplier is on Kalshi's relative scale (1 = standard; the format check found 1 for weather
  and crypto and 0.5 for baseball games). The series list is not frozen if a multiplier is missing or outside 0 or
  0.25-2, or if a series' fee type is not quadratic ("quadratic" or "quadratic_with_maker_fees"; the taker fee is the
  same for both).

## Test P1: does past skill on Polymarket persist? (informational)

**Windows**
- Formation: positions first entered before 2026-07-01, in markets with a scheduled end date of
  2026-01-01..2026-06-30.
- Evaluation: positions first entered 2026-07-01..2026-09-30, in markets with a scheduled end date of
  2026-07-01..2026-10-07 that resolved by 2026-10-14.
- Markets ending later are left out even if they resolved early, because an early resolution of an open-ended market
  is nearly always one way. End date 1970-01-01 is left out. Both exclusions are counted.

**Wallet pool** (formation data only)
- Markets: the 300 highest-volume closed markets on Gamma with end dates in the formation window, combos excluded.
- From those markets, collect every fill of at least $500 cash (/v2/trades?condition=, taker_only=false, filter_type
  CASH, filter_amount 500).
- Pool: the 2,000 wallets that traded in the most of these markets (ties broken by cash).

**Positions**
- /v2/positions?user= with status CLOSED, plus status REDEEMABLE with include_archived=true. REDEEMABLE_LOST is a
  subset; it is fetched only for the 20 format-check wallets, to confirm that. Duplicates by token are removed.
- No start/end bounds. Every page is followed until has_more is false. A failed walk is not saved and is retried on
  the next run; a wallet that fails 3 runs is left out and counted.
- For each position:
  - Cost = total_size x avg_price + entry_fees_usdc.
  - Profit = total_pnl, minus entry_fees_usdc if the format check finds that total_pnl leaves fees out.
- Wallet-event return = the sum of profit / the sum of cost over that wallet's positions in the event.
- Combos (parlays) are left out everywhere and counted: a market with cyom set, or a combo condition ID (31 bytes, 62
  hex digits). Gamma's comboStatus is not a combo flag: it says whether a normal market may be a combo leg.
- Left out of scores (each counted):
  - rows with no buys (total_size or avg_price 0: tokens that came from splits, merges, conversions or transfers);
  - wallet-events costing under $10;
  - positions with avg_price >= 0.97, which are bought when the outcome is nearly known and can't be copied for profit.

**Checks before anything is scored** (each a format or completeness check, not a result)
- Format: on 20 wallets (seed 4), for REDEEMABLE rows with no sells, total_size x avg_price must equal entry_cost_usdc
  within 1%, and current_price must be 0 or 1. At most 2% of those rows may differ; otherwise nothing is selected or
  scored until the cost definition is fixed. The same check also needs:
  - losing rows to be present (current_price 0);
  - every REDEEMABLE_LOST (condition, outcome) to be in the REDEEMABLE walk;
  - CLOSED rows with buys: total_size x avg_price above 0 and total_pnl equal to realized_pnl (at most 2% differ);
  - first_entry_at in epoch seconds, a readable end_date and an event_id on at least 95% of rows with buys.
  - It also reads off winners whether total_pnl includes entry fees (the profit rule above).
  - Rows with no buys are left out of these checks (and of the scores).
  - These wallets are fetched again for the check, REDEEMABLE_LOST first and then CLOSED and REDEEMABLE, so a loss
    settling between the walks cannot break the subset test.
- Completeness: for the selected wallets and 50 random other eligible wallets (seed 4), the positions must cover at
  least 98% of the BUY cash in /v2/trades?user= (taker_only=false) in each window, by fill time.
  - Matched by (condition, outcome). Only CLOSED and REDEEMABLE rows count as covered.
  - Buys of an outcome that is still open (an OPEN-walk row with status OPEN) leave the denominator.
  - A resolved holding that the OPEN walk returns but the scored walks miss counts as missing.
  - The checked wallets are fetched again, the OPEN walk first and then CLOSED and REDEEMABLE, so a holding that
    settles in between is never counted as missing.
  - A wallet with no formation buys at all fails (every pool wallet has fills of $500 or more, so the walk is broken).
  - Wallets below 98% are left out and counted.
  - If more than 10% of the checked wallets fail, P1 and P2 are not scored.

**Eligible wallets**
- At least 20 formation positions in at least 10 events.
- At most 3,000 formation positions.
- At most 10,000 rows in its CLOSED walk and in its REDEEMABLE walk (16:20 revision). Longer walks are stopped; such
  wallets are heavy bots or market makers, and one of them alone took 15 minutes and 114 MB.
- Not eligible if any of these hold (each a market-maker or arbitrage sign):
  - both outcomes of one condition in more than 20% of conditions;
  - 3 or more outcomes held in more than 20% of their neg-risk events;
  - formation SPLIT, MERGE and CONVERSION activity (/v2/activity, only rows of those types) above 20% of their
    formation cost (checked for every wallet that passes the other rules).

**Selection**
- Formation t for each eligible wallet = the mean over its events of its wallet-event return, divided by the SE above
  (computed over its events).
- Selected: the 50 eligible wallets with the highest formation t whose mean is positive.
- Nothing is frozen with fewer than 250 eligible wallets (50 selected plus the 200 placebo wallets). That would point
  to a data problem; it is reported, not worked around.

**Data checks before P1, P2 and P2c are scored** (failing any of these saves nothing, and the data problem is fixed
first):
- at least 90% of the evaluation wallet-event markets, and of the copied markets, have a resolution record;
- at least 90% of the resolved copied markets have payouts for every outcome;
- Gamma has details for at least 90% of the evaluation markets the copied wallets bought;
- every copied market has a trade list, except those whose walk failed on 3 runs (their copies count as "no trade
  list").

**Score (once)**
- Every condition in a wallet-event must have resolved by 2026-10-14; otherwise that wallet-event is left out (counted).
- Null variance of a wallet-event: (sum over its positions of size x sqrt(p(1-p)))^2 / cost^2, which is conservative
  for holdings that move together. An event's unit uses the squared mean SD of its wallet-events.
1. Selected return: for each event, the mean wallet-event return of the selected wallets in it; then the mean over
   events. It must be above 0 by at least 2.5 SE.
2. Selected vs the rest: for each event in which both groups have wallet-events, d = selected mean minus the other
   eligible wallets' mean. The mean of d must be above 0 by at least 2 SE.

"Not testable": fewer than 25 selected wallets with evaluation wallet-events, or fewer than 60 events.

**Also reported (descriptive):**
- the dollar-weighted pooled return;
- the rank correlation of formation t with evaluation return (all eligible wallets);
- each group's mean wallet-event return by tenth of its average price;
- how many selected wallets had no evaluation wallet-events;
- wallet-events left out, by reason.
- Results by category are not computed (the code has no category data); this was dropped before any data.

## Test P2: copying the selected wallets late, at real prices

**Buys copied**
- Selected wallets' BUY fills (/v2/trades?user=, taker_only=false), first entered 2026-07-01..2026-09-30, in evaluation
  markets (same end-date rule as P1).
- At most one copy per wallet per outcome per day (the first buy).
- Skipped:
  - a buy when the wallet bought the other outcome of that condition in the 7 days before (a hedge or an exit);
  - buys at a fill price of 0.97 or more.

**Copy price**
- The first taker BUY of the same outcome on that market's trade list (/v2/trades?condition=, taker_only default,
  side BUY) at or after fill time + 5 minutes and within 1 hour, plus the fee. When several fills of that outcome share
  its second (one order sweeping several prices), the highest price.
- No copy, counted, if:
  - there is no such buy;
  - the price is 0.97 or more (before fees);
  - the buy comes at or after the market's close or resolution;
  - reaching it would need more than 200 pages of that market's trades (the walk must reach the copy's whole hour).

**Copy profit:** a $1 stake held to resolution: payout x (1 / copy price), minus the stake.

**Score (once):** mean copy profit per dollar, averaged within events, SE as above. PASS only if both hold:
1. The mean is above 0 by at least 2.5 SE, with at least 300 copies in at least 60 events.
2. It beats the placebo by at least 2 SE: P2's mean minus the reweighted placebo mean, with SE = the square root of the
   sum of the two squared SEs.

"Not testable": fewer than 300 copies or 60 events.

**Placebo:** the same copy rule on 200 random eligible wallets that were not selected (seed 4). They are reweighted to
P2's mix of copy-price tenths, so a price-level effect (the favourite-longshot bias) cannot pass as following skill.
- Each placebo copy in tenth b gets weight (P2's share of copies in b) / (the placebo's share of copies in b), so the
  reweighted mean is the sum over tenths of P2's share x the placebo's mean in that tenth.
- A tenth with fewer than 5 placebo events is pooled with its nearest tenth that has 5 or more.
- Its SE: one weighted computation over the placebo's events (each event's weight = the sum of its copies' weights),
  with the same three-way maximum.

**Also reported:**
- the copied wallets' own return on the same buys (the cost of being late);
- copies of maker fills and taker fills separately;
- delays of 30 minutes and 2 hours;
- the placebo's mean without reweighting.
- The wallets' own exits are not computed (positions show only totals per outcome); dropped before any data.

**P2c, consensus (separate test):**
- An outcome counts when at least 3 different selected wallets bought it within 24 hours.
- One copy per outcome, at the 3rd buy + 5 minutes, with the same price rule.
- PASS if above 0 by 2.5 SE with at least 100 copies in at least 40 events; fewer is "not testable" (likely, from
  the power estimate).
- One trader with several wallets may count more than once; this is noted, not corrected.

## Test K1: large trades on Kalshi

**Series**
- The 40 series whose ticker does not contain COMBO, ranked by total volume of markets with a scheduled close
  2026-07-15..2026-10-13.
- Ranked from /markets metadata only, and written to research/results/plan4_series.json before any trade is read.
- The ranking uses Kalshi's live market listing, which can be filtered by close time. It holds millions of markets,
  so it is read twice: once keeping only each series' total volume, then series by series for the 40 chosen (the two
  counts must agree within 1%). Kalshi's archive (markets
  settled before its cutoff, 2026-08-16) cannot be filtered that way, so it is read series by series for the 40 chosen,
  keeping markets that closed in the window. (Format check, 2026-10-15.)

**Markets:** each series' settled markets with a scheduled close in that window. At most 300 per series, drawn with
random.Random(4).sample over the sorted tickers.

**Trades:** each sampled market's trades from both Kalshi's archive (/historical/trades) and the live endpoint
(/markets/trades), merged by trade_id, so a market whose trades straddle the archive cutoff (2026-08-16) keeps all of
them. Prices are read in dollars, or in cents where only those are given. K1 is not scored (nothing saved) if more
than 5% of trade rows have no price for the taker's side.

**Large trades**
- A taker order = one market's trade rows with the same created_time and taker_side (one order can fill at several
  prices).
- Notional = sum of count x the taker's price.
- Large = at least $1,000, and not a block trade.

**Copy**
- Buy the large order's side at the highest price paid in the next other order on that side, 60 seconds to 60 minutes
  later, plus the Kalshi fee.
- No copy, counted, if there is no such order or the price is 97c or more (before fees).
- The next order must not be a block trade either.
- At most one copy per market and side within 60 minutes of a copy (measured between copy times).

**Score (once):** mean profit per contract after fees, averaged within each market date. The market date is the date in
the event ticker; when a ticker has none, the scheduled close date (counted). SE as above, using market
dates and the null SE. PASS only if above 0 by at least 2.5 SE, with at least 300 copies over at least 40 dates. Fewer
is "not testable".

**Also reported:**
- the large orders' own excess win rate (outcome minus the price they paid);
- the same numbers for orders under $50 (the known taker loss), descriptive only;
- the share of large orders with no later order on their side;
- after scoring, a standing-ask check (yes_ask close of the first minute candle ending at least 60 seconds after the
  order) on a sample of 300 copies (seed 4).

## Power (from the review; counts unknown until fetched)
Smallest detectable edge at 80% power with the 2.5 SE bar:

| Test | Expected size | Smallest detectable edge |
|---|---|---|
| P1 | about 2-3k wallet-events over 1-1.5k events | 10-16% |
| P2 | about 700-1,000 copies over 400-700 events | 12-25c per $ |
| P2c | likely below its minimum | about 50c per $ |
| K1 | thousands of copies over about 90 dates | 3-4c per contract |

## What a pass would and would not mean
- A pass is a lead, not a strategy. It earns a forward paper test on new trades with the same rules, and a verdict
  horizon written down before the first forward result.
- Trading on Polymarket would need a crypto wallet the bot controls. CLAUDE.md forbids wallet access unless the user
  changes that rule, and Polymarket's availability depends on the user's country.
- A Polymarket signal could be traded on Kalshi when the question is the same (research/data/pairs.json), only through
  live.py inside the $25 cap.
- Bigger bets are not part of any test here. Bet size would follow a measured edge, never the wish for fast profit.

## Multiplicity
- Four scored looks (P1, P2, P2c, K1), each at 2.5 SE. P1 and P2 also need their 2 SE comparisons. That is about 0.6%
  false pass each, and about 2.5% that at least one passes by chance.
- Categories, other delays, the placebo's own numbers and every "also reported" item are exploratory.

## Changes in the 11:40 revision (statistics review, before any data)
1. **Cost basis.** Position cost is total_size x avg_price + fees: total_cost_usdc is about 0 on closed rows. Returns
   are per wallet-event, with a format check before scoring.
2. **Position coverage.**
   - Fetch CLOSED, plus REDEEMABLE with include_archived; drop REDEEMABLE_LOST, which double-counts.
   - No time bounds, full walks, and a completeness check against each wallet's trades.
3. **Windows.** Defined by scheduled end date and first entry. Open-ended markets that resolved early are left out.
4. **Skew.** The SE is floored by the null SE and by end-date clustering, because $1 copies of favourites and heavy-tailed
   wallets broke the 2.5 SE bar in simulation (up to 24% false passes). P1's score is an event mean, not a pooled
   dollar ratio.
5. **Uncopyable winners.** Buys at 97c or more are left out. Neg-risk arbitrage and split/merge-heavy wallets are not
   eligible.
6. **P2 price.** The trade list's next real taker buy is used, not a price-history point (which can be a midpoint, a
   payout point or after the close). This also removes the 60-day limit.
7. **Clustering and K1.**
   - K1 clusters by market date across series.
   - K1's series list is defined from market metadata and saved first.
   - A taker order means fills with the same timestamp and side.
8. **New definitions.**
   - P1 condition 2 is defined.
   - P2 must also beat a reweighted placebo.
   - Hedges are skipped.
   - Fees, payouts, token families, privacy, power and "not testable" are defined, and P1 is informational only.

## Changes in the 15:10 revision (code review of research/plan4.py, before any data)
An independent code review read research/plan4.py against this plan before any PLAN4 data was fetched. The rules above
now say exactly what the code does. The changes:
1. **Placebo reweighting** is defined: per-copy weights from copy shares by tenth, sparse tenths pooled, and one
   weighted SE. (The first code averaged events equally, which ignored the weights across events.)
2. **Coverage** counts only the scored rows (CLOSED and REDEEMABLE), with the open-market and survivorship rules.
3. **Format check** also checks losers, REDEEMABLE_LOST and duplicates, and reads whether total_pnl includes fees.
4. **Split/merge** activity is checked for every wallet that passes the other eligibility rules.
5. **Kalshi fee** is written out with the 0.07 base; the series list is not frozen with a missing or off-scale
   multiplier, or if more than 5% of listed markets have no volume (the ranking would be meaningless).
6. **P2 copy price:** the highest fill in the first matching second; each copy's hour must be inside the walked trade
   list.
7. **K1:** the next order excludes block trades; the one-copy-per-hour rule uses copy times; market dates fall back to
   the close date; orders with no contracts or a zero price are dropped; under-$50 copies are descriptive.
8. **P1:** every condition of a wallet-event must have resolved; the wallet-event null variance is written out;
   results by category and the wallets' own exits are dropped (no data for them); the other descriptive items are
   defined.
9. **Combos (format check, 15:30):** Gamma's comboStatus is "enabled" or "disabled" on every market (whether it may be a
   combo leg), so the first code treated every market as a combo. Combos are now cyom markets or 31-byte combo
   condition IDs, left out everywhere.
10. **Robustness (no rule change):** failed fetches are not cached and are retried; unresolved markets are asked again
   at scoring; time stamps with any offset format are read; files are written atomically.

## Changes in the 15:55 revision (second code review and format checks, before any data was scored)
A second independent code review, and one format request to each data source (research/plan4_formatcheck.py, output
in research/results/plan4_formatcheck.txt), found the following. Only the wallet pool's fills had been fetched (wallets
and amounts, no outcomes). The Kalshi series listing was stopped before anything was saved.
1. **Resolutions:** /v2/resolutions has no resolved_at field, so the first code would have found no market resolved
   and written every Polymarket test as "not testable". The resolution time is now the resolved record's
   last_update_timestamp. Payouts are /v2/tokens final_price (the plan's wording said /v2/resolutions).
2. **Rows with no buys:** REDEEMABLE and OPEN rows from splits, conversions or transfers have total_size 0,
   avg_price 0 and first_entry_at 0. They are left out (counted); the format check would otherwise have failed on them.
3. **CLOSED rows:** total_size is the total bought (the format check showed 403,412 shares bought and 0.008 left), so
   total_size x avg_price is the right cost. The format check now also checks CLOSED rows.
4. **Fresh snapshots** for the format check and the coverage check (the order of walks above). Matching is by
   (condition, outcome).
5. **Guards** so a data problem stops the work before anything is frozen or scored: at least 250 eligible wallets;
   field plausibility in the format check; the resolution, payout and market-detail checks before scoring; the
   Kalshi price check.
6. **Kalshi:**
   - both trade endpoints merged by trade_id;
   - the fee type checked;
   - prices in cents read;
   - orders sorted by time, then created_time;
   - the next-order search stops after an hour.
7. **Smaller fixes:**
   - split/merge activity counts only those types;
   - a cursor with has_more missing is followed;
   - epoch times are read;
   - condition IDs are normalized;
   - a trade list that fails 3 runs counts as "no trade list";
   - Gamma markets missing earlier are asked again;
   - (condition, outcome) rows sharing one outcome are informational only, not a check: v1 and v2 tokens of one
     outcome are legitimate.

## Changes in the 16:20 revision (fetch limits, before any data was scored)
- **Position walk cap.** The pool is the 2,000 wallets that traded in the most formation markets, so its top holds heavy
  bots: in 19 minutes the positions fetch finished 4 wallets, one of them 114 MB. A wallet with more than 10,000 rows in
  its CLOSED or REDEEMABLE walk is now not eligible (counted). The walk stops there, and the 4 wallets fetched in full
  are judged by the same row counts. No positions had been looked at beyond file sizes.
- **Kalshi listing.** The listing passed 2.5 million markets and 1.5 GB of memory, so it now runs in two passes (above).
  It was stopped before anything was saved.


## Finishing on 2026-10-29 (logistics only; no rule, window or threshold changed)
- **Where things stood:**
  - The Polymarket chain stopped on Oct 15 at pselect: the format check counted 12 REDEEMABLE_LOST rows as missing that the scored walks list as CLOSED. That check was corrected before any selection (CHANGELOG, Oct 22). It reuses the format-check snapshots saved on Oct 15, so the corrected check reads the same rows.
  - The Kalshi trade lists were complete on Oct 16. Nothing has been selected or scored.
- **Remaining steps** run as two detached chains on the laptop (research/plan4_run.ps1):
  - KS: scoreK, then the descriptive kquotes.
  - PS: pselect, pcopies twice, then scoreP.
- **Scoring:** each scorer runs only after every earlier step in its chain succeeded. It refuses (nothing saved) on any of the guards above, and each test is still scored once.
- **Dates:** all windows are fixed dates (formation, evaluation to Oct 1, resolved by Oct 14, K1 markets closing by Oct 13). Fetching two weeks later changes no window. Resolutions are looked up fresh at scoring, as written.

## Results (scored once; recorded 2026-10-30)
- **K1, large trades on Kalshi: FAIL** (scored 2026-10-29 04:17).
  - -2.2c a contract after fees over 37,669 copies on 92 market dates; t -0.49 against the 2.5 bar. The 95% interval is about -11c to +7c.
  - **What it shows:** no edge. It rules out an average copy edge above about +7c on these 40 series (sports and 15-minute crypto and commodities, Jul 15 to Oct 13). It cannot tell a small gain from a small loss.
  - **Descriptive only:**
    - the large orders' own excess was -0.8c before fees;
    - copying orders under $50 the same way gave -2.1c;
    - 6% of large orders had no later order to copy;
    - the quote check (300 sampled copies) found a median ask minus copy price of 0.0.
- **P1, P2 and P2c, Polymarket wallets: NOT SCORED** (2026-10-30 05:28).
  - 11 of the 100 checked wallets covered less than 98% of their buys. The rule above says P1 and P2 are not scored if more than 10% fail. P2c copies the same selected wallets, so it is left unscored with them; that is an interpretation, recorded here.
  - The result says nothing either way. There is no re-run, re-check or relaxed threshold: the outcome sits at the threshold, so a re-check would be a forking path. A new idea needs its own plan.
- **Statistics review (agents/statistician.md, 2026-10-30):**
  - Both verdicts are correct applications of the rules.
  - **K1's power was over-stated.** K1's standard error is the plan's null floor per market date (0.431/sqrt(92), about 4.5c). It does not shrink with more copies: the 303,369 under-$50 copies have the same SE. The power table's 3-4c never applied; the smallest edge the test could detect was about 15c. Future plans must work out power from the SE the code actually uses.
  - The format check could not tell whether total_pnl includes fees (fee_adjust 0); this matters only if P had been scored.
  - The coverage failures are mostly 2-10% shortfalls in the evaluation window; one wallet is at 0.27. That pattern fits a data-source gap, but it is descriptive and the cause is not known. One code point is unverified: coverage() counts combo buys in its denominator.
- **Logistics (no rule changed):**
  - On 2026-10-29 both finishing chains were started twice by mistake, at 02:21:52 and 02:21:58.
    - The two scoreK and two kquotes copies printed identical results (deterministic from frozen files with a fixed seed); plan4_K.json is the second write.
    - One pselect copy crashed at 02:26 on a shared .tmp file in the split/merge activity cache, before the coverage step. Every coverage snapshot was written after that, by the surviving copy (02:43 to 03:33), so the open-walk-first order held.
  - A Windows Update restart at 04:59 cut pcopies off after the selection was frozen. It resumed from saved files at 14:20.
