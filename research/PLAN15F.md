# PLAN15F: live paper bets on Kalshi's 15-minute BTC and ETH markets

Written 2026-11-13, 19:10 La Paz, at the user's request ("Still no automated live bets / research, for live bets using
the paper account"), before any live paper bet. Paper only: no order is ever sent, nothing here imports live.py, and
nothing here writes paper.db or live.db. Not financial advice.

## 0. Why it exists, and what it is not
- PLAN15 (frozen 2026-11-13) tests the same idea on past windows and is scored once, after 2026-12-31. PLAN15 said a
  live paper test would come only after a pass; **the user chose to start it now.** This record says so plainly.
- **It cannot change PLAN15.** PLAN15's code and rules are frozen and checked by hash; nothing in PLAN15F feeds them.
  The live bets also overlap PLAN15's check windows (Nov 1 to Dec 31). So they are a second, live look at the same
  idea, with real timing and the real order book, not new evidence for PLAN15's single score.
- Expected result, as for PLAN15: no edge after fees. Fifteen-minute direction is close to a coin flip, and the fee
  alone needs about 52% at 50c.

## 1. The rule (the same model as PLAN15, no tuning)
- **Markets:** the open KXBTC15M and KXETH15M window of the moment (open_time <= now < close_time).
- **Model:** PLAN15's random walk, its own code (research/plan15.py: rw_prob, sigma from the 60 one-minute returns
  before the window, time left T - k - 0.5): p_up from Coinbase's one-minute close at the end of minute k against the
  market's own reference price (floor_strike). Only windows that ask "above the reference" (strike_type greater or
  greater_or_equal) are bet on; any other kind is skipped and logged (fail closed).
- **Decision minutes:** 2, 5 and 10. At each, as soon as Coinbase's candle for that minute is out (asked from 2 seconds
  after the minute ends, for up to 58 seconds; both assets are asked in turn and each is decided as soon as its own
  candle is out), the live Kalshi order book is read once. If the price or the book is not in hand within 60 seconds
  of the minute's end, the decision is recorded as missed. (Amended 2026-11-13 21:10 after the first live run: Coinbase
  published its candles about 46 s after the minute, so the first version's 45 s wait, BTC first, missed every BTC
  decision. The model and the rule are unchanged.) Because the candle comes out about 46 s late, the price the model
  uses is about 46-50 s old when the book is read; the log shows its age.
- **Signal:** model chance minus the ask on one side at least 4 points (PLAN15's EDGE). YES ask = $1 - the best NO
  bid; NO ask = $1 - the best YES bid.
- **Paper fill:** one contract at that ask, immediately, only if the book shows at least one contract there.
  Otherwise "no fill", logged. At most one bet per window, asset and decision minute (three a window at most).
- **Fee:** PLAN15's (quadratic, the series' multiplier). P&L at settlement: $1 if the side won, minus price and fee;
  a scalar or void result follows the project's rule (strategy.payout: scalar pays its value once final, void counts
  as minus the fee).
- A run that starts late, a laptop that sleeps, a missing price or a window that cannot be set up records that
  decision as missed, with the reason. Nothing is made up afterwards. A run stopped by its 14-minute limit (for example
  a request that stalls) leaves its remaining decisions without a row; the log shows the run did not finish.
- The project's kill switch (a KILL file in the tradebot folder) stops these paper bets too, checked before each
  decision; results of earlier bets are still recorded.

## 2. What it reports (descriptive; nothing passes or fails)
Bets, fills, wins, net P&L after fees, P&L per bet with its standard error over UTC days (each day counts once),
counts and net P&L split by asset and by decision minute, and decisions with no signal, no fill or missed. The time
the book was read is stored with each decision. The dashboard shows it as "15-minute paper bets (live)". It says in plain words that a few days of
results are noise.

## 3. Its end
- Reviewed at PLAN15's score (from 2027-01-01). If PLAN15 shows no edge, PLAN15F stops.
- If PLAN15 shows a lead, PLAN15F's record from 2027-01-01 on becomes the forward test, with a verdict rule written
  before that date.
- **It never places real orders.** Real money on these markets would need a separate live.py change that only the
  user can approve, and only after a forward test passes (CLAUDE.md sections 3 and 11a).

## 4. Running
research/live15.py, started every 15 minutes by a Windows Task Scheduler job that the user installs himself
(tasks\install_live15.cmd; it runs with no window, only while the user is signed in). Each run settles finished paper bets, then follows the current window to minute 10 and
exits, within 14 minutes. Data: research/data/live15.db (its own ledger) and logs\live15.log. Requests: Kalshi's
public API and Coinbase's public market data (approved for PLAN15, 2026-11-12), User-Agent
tradebot-paper-research/1.0, no personal data.
