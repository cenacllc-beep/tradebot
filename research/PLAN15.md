# PLAN15: Kalshi's 15-minute "up or down" markets: can a model call the direction better than the price?

Written 2026-11-12, 19:45 La Paz, at the user's request of 2026-11-12 18:57 ("an intelligent ai system to trade the
kalshi live 15 min options with great accuracy to determine the up or down trends"), before any price, trade or
result of these markets was downloaded or looked at. Revised 2026-11-13 01:45 La Paz after the independent statistics
review (5 MUST, 3 SHOULD, 3 COULD, all applied) and the user's answer of 2026-11-12 (section 8), still before any of its
data; frozen at this revision. Research
and paper only: never part of the gate, never connected to live.py. A pass earns a forward paper test on new windows;
real money would need a separate change to live.py that only the user can approve after that test (CLAUDE.md sections
3, 11a). Not financial advice.

**Disclosure.** Seen before this plan: the market catalogue's series list with total volumes (research/data/
discovery.db, metadata only). About 20 active 15-minute series: BTC (by far the largest, about $207 million traded in
the catalogue's window), ETH, XRP, SOL, DOGE and smaller coins; gold, silver, oil, gas and other commodities;
currencies; Treasury yields; the S&P 500 (6 markets, about $145,000 in all). Nasdaq-100 and Dow 15-minute series are
listed but showed no markets. All use Kalshi's standard fee (quadratic, multiplier 1).
PLAN4 test K1 (copying large Kalshi trades, failed) covered markets closing by Oct 13, including 15-minute crypto, so
it overlapped this plan's find period; no 15-minute result of it was looked at separately. Check-period windows from
Nov 1 to Nov 12 already exist on Kalshi; none has been looked at.

## 0. Honest prior, stated before any data
- **"Great accuracy" is not on offer.** Over 15 minutes, the direction of a liquid asset is very close to a coin
  flip. Professional trading firms with servers next to the exchanges trade these prices. A model that calls the
  direction right 52 times in 100 would be an unusually good one.
- **The fee alone needs about 52%.** A contract bought at 50c pays a fee of about 2c, so the buyer must win about
  52% of the time just to break even, before the gap between the buy and sell price. Away from 50c, the win rate is
  the wrong yardstick: a contract at 80c must win more than about 82% of the time; profit per contract is what counts.
- **What the price already knows.** Once a window is under way, the fair chance of "up" depends mostly on how far the
  price already is from the window's opening level and how much time is left. Kalshi's price is expected to track
  this within seconds (an expectation, not yet measured; Q1 measures it). Any edge has to come from something beyond that, and quickly.
- **Expected result: no edge shown.** That outcome costs nothing and saves real money.

## 1. The questions
- **Q1 (is the price fair?).** At fixed points in each window (2, 5 and 10 minutes after it opens), is Kalshi's mid a
  fair chance of "up", or does a plain random-walk model of the spot price beat it?
- **Q2 (a trading rule).** Buying the side the random-walk model favours when it differs from the ask by enough to pay
  the fee: does it make money after fees, at a price a laptop could actually get?
- **Q3 (a small learned model, the "AI" part).** A logistic model with a fixed list of inputs, fitted once on the
  first period and frozen: does it beat the price on the later period, and does its trading rule make money?

## 2. Markets and data
- **Primary:** BTC 15-minute markets (KXBTC15M). **Secondary, same rules, separate family:** ETH (KXETH15M). Stocks:
  the S&P 500 15-minute series has too few markets to test; it is reported descriptively (count, volume, spread) only.
- **Kalshi (approved, read-only):** every settled window's market record (open time, close time, the rules text with
  its settlement source and reference price, result), its minute candles (yes bid, yes ask, last price, volume) and
  its trades.
- **Spot price (needs the user's yes, section 8):** one-minute BTC-USD and ETH-USD prices from one public exchange
  interface, read-only, no account. Kalshi settles on an index (stored from each market's own rules text); the spot
  source is a stand-in, and how often the spot source's "up or down" agrees with Kalshi's result is reported. Windows
  where they disagree stay in.
- **Window and reference price.** Each market's reference window and its reference price S_0 are taken from its rules
  text and from the strike or reference fields of its market record. Before the code is frozen, a handful of markets'
  records are read (metadata only, no prices or results) to confirm that these fields are set when the window opens
  and are not filled in afterwards, and that open_time is the start of the reference window (a market may list
  before its window begins). Kalshi settles on the average of the index's last 60 seconds; the model's time left is
  therefore T - k - 0.5 minutes.
- **Periods (fixed now by date):** find period = windows closing 2026-09-01 to 2026-10-31 (UTC); check period =
  windows closing 2026-11-01 to 2026-12-31, collected as they settle. If Kalshi's history does not reach back to
  Sep 1, the find period starts at the first available window and the plan records it before any price is read.

## 3. Timing (no look-ahead)
- **Decision minutes:** 2, 5 and 10 minutes after the window opens. Each window is scored at each of the three
  minutes separately (three sub-tests), never mixed.
- **Candle labels.** A one-minute candle is labelled here by the minute it ENDS ("minute k" = the candle that closes
  at k minutes after the window opened). Kalshi's and Coinbase's own labels are converted to this before anything
  else, and a test in the code checks the conversion on a known example.
- **What is known at decision minute k:** spot prices up to the close of minute k; Kalshi's candles up to the close of
  minute k.
- **The signal** compares the model at minute k with the ask at minute k (both known then).
- **The price paid:** the ask on the chosen side at the close of minute k + 1: one full minute of delay, the realistic
  lag of a laptop polling Kalshi. The trade is made at that price whether or not the edge still holds. No trade (and
  counted) when that ask is missing or $1.00, or when the candle does not show 0 < bid < ask.
- **Fee:** round up(multiplier x 0.07 x C x P x (1 - P)) to the cent, one contract per signal, with the fee type and
  multiplier read from KXBTC15M's and KXETH15M's series records (and checked against Kalshi's fee-change history);
  maker fees do not arise, because every trade here pays the ask.

## 4. The models (fixed now)
- **Random walk (RW).** p_up = Phi( ln(S_k / S_0) / (sigma x sqrt(T - k - 0.5)) ), where S_0 is the window's reference
  price as Kalshi defines it (from the rules text; if only the spot stand-in is available, the spot price at the
  window's open), S_k the spot at minute k, the time left T - k - 0.5 minutes (T = 15), and sigma the standard deviation of one-minute log returns
  over the 60 minutes before the window opened. Nothing is fitted.
- **Learned model (LM, Q3).** Logistic regression of "up" on exactly these inputs at minute k: RW's logit; Kalshi's
  mid logit; spot return over the last 1 and the last 5 minutes (each divided by sigma); sigma itself (log); hour of
  day (UTC) as sin and cos; Kalshi volume so far in the window (log 1 + contracts). Fitted once by maximum likelihood
  with a fixed ridge of 1.0 on the standardised inputs, on the find period only, then frozen with its hash. One model
  per asset and decision minute (six in all). No other inputs, no tuning, no second fit.

## 5. Scoring (once, on the check period)
- **Unit:** windows within one UTC day share market conditions, so the day is the unit: values are averaged within a
  day, and each day counts once. Days already absorb the dependence inside a day, so the bootstrap resamples 2-day
  blocks of days, 20,000 draws, seed 15, read at the rule's Holm level.
- **Q1:** day-mean Brier(RW) - Brier(mid). Read two-sided: below zero means RW beats the price; above zero means the
  price beats RW (expected).
- **Q2:** signal when RW - ask on one side is at least 4 points (the fee plus a margin). Day-mean profit after fees.
- **Q3:** day-mean Brier(LM) - Brier(mid), and the same trading rule as Q2 with LM in place of RW.
- **Pass (each of Q2 and Q3's trading rule, which are the only ones that could lead to a forward paper test):**
  1. the day-mean t above the one-sided Student-t value at the rule's Holm level, days - 1 degrees of freedom, never
     below 2.0;
  2. the bootstrap's lower bound above zero at the same level;
  3. **the placebo (matched to the rule's prices and fees):** the same signals with their sides flipped by a fair coin,
     paid at the same asks, 2,000 draws; the share of draws at least as profitable as the real rule must be at most
     the rule's Holm level. A second placebo, the real rule filled 3 and 5 minutes later instead of 1, is reported
     (descriptive): a real edge should fade with delay, not grow.
- **Many tries:** 2 assets x 3 decision minutes x 2 trading rules = 12 tests, one family. Holm at a family level of
  2.5% one-sided over the 12. Q1 and Q3's accuracy result are reported for each asset and minute, not tested for a
  pass.
- **Spot stand-in check:** if the spot source's "up or down" agrees with Kalshi's result in fewer than 97% of windows
  for an asset, RW and LM are called mis-specified for that asset and its tests read "not testable".
- **Not testable:** fewer than 200 signals or fewer than 20 days with a signal, for a rule; more than 10% of windows
  missing spot or candle data, for the whole asset.
- **How much can be bet:** the contracts traded in the minute after each signal (from the trade feed); the median is
  reported as the rule's capacity, labelled an upper bound (it counts both sides), and profit is shown per contract and at that capacity.
- **Verdicts:** "lead on past data: justifies a forward paper test" or "no edge shown". Failures reported with the
  same detail as passes.

## 6. Power (written before the data)
BTC has 96 windows a day and the check period about 60 days. Suppose a rule fires in a quarter of windows (24 a day;
optimistic against a well-priced market). At about 50c the per-contract standard deviation is about 0.5 dollars, so
the day mean's is 0.5 / sqrt(24) = 10c and its standard error over 60 days 10 / sqrt(60) = 1.3c. Holm's first step is
2.5%/12 = 0.21% one-sided, t(59) about 2.98, so 80% power needs (2.98 + 0.84) x 1.3 = about 5c per contract; at the
last step (2.5%, t about 2.0) about 3.7c. Rules that fire less often need more. Real edges below about 4-5c a contract
will read "no edge shown".

## 7. What a result can and cannot show
- A pass on past windows is a lead, not a working system: it earns a forward paper test on new windows (PLAN15F) with
  the same rules and its own verdict rule, written before the first forward result.
- Fills at the ask with one minute of delay ignore queue and size; the capacity figure says how small the bets would
  have to be.
- The spot source is not Kalshi's settlement index; disagreements are counted and reported.
- Real money on 15-minute markets would need a new live.py path (orders every 15 minutes, not once an evening), with
  its own limits and a forward test first. That is the user's decision after a pass, never before.

## 8. Sources
- Approved: Kalshi's public API, read-only.
- Approved by the user 2026-11-12 (asked in so many words): Coinbase's public market-data feed for one-minute BTC-USD
  and ETH-USD prices (read-only, no account, no key), for this plan and PLAN14 Part 2.
- Every request uses the User-Agent tradebot-paper-research/1.0 and no personal data. Downloads run on GitHub Actions
  (public data only is written there) or on the PC's scheduled jobs, never touching paper.db or live.db.

## 9. Freeze
This file is frozen after its statistics review; its SHA-256 goes into CHANGELOG.md. research/plan15.py is written
after the freeze, code-reviewed, and frozen before the first download. Where code and text differ, the text wins, by
an amendment before any data. No tuning, no second run with other thresholds, no rescue (CLAUDE.md section 11a).
