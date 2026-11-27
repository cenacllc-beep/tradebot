# PLAN21: a walk-forward learning engine (monthly refit, freeze, single score)

Written 2026-11-26 (La Paz) at the user's request for a system that "learns from wins and losses" and detects winning
patterns, before any of its numbers were computed and before any outcome was read for it. Draft: it is statistics-
reviewed (agents/statistician.md) and frozen before the first freeze date; its SHA-256 then goes into CHANGELOG.md.
Research and paper only. Not financial advice.

## 0. The question, what "learning" means here, and the honest prior
- Question: if we keep proposing models, fit each one only on the past, freeze it, and judge it once on the next
  month's markets, does any of them beat Kalshi's price by more than luck allows?
- **Learning here means:** (1) every candidate is re-fitted each month on the newest data, so it adapts; (2) every
  settled bet and market is broken down into wins and losses in a monthly report, which may suggest new candidates;
  (3) a new idea is written down in full before it is tested on new markets, and a candidate that keeps failing is
  retired. It never means tuning a model after a loss, re-scoring a month, or changing v3, the gate, live.py or a limit.
- Prior: PLAN2-4 and PLAN16-18 lost about the fee; Kalshi's prices are well calibrated; v3 runs low on rain (section
  12 of CLAUDE.md). **Expected result: most months, for most candidates, "no edge shown" or "not testable".** Searching
  many ideas makes a lucky pass likely unless the error budget is shared; section 5 shares it.

## 1. The monthly cycle (La Paz time, UTC-4)
- **Month M** runs from the 1st 00:00 to the last day 23:59:59 La Paz.
- **Freeze (once per candidate and month):** the nominal freeze time is M's 1st at 00:00. The job runs from 00:10 and
  retries hourly until the 2nd 23:59. Fit data = rows logged and settled strictly before the nominal freeze time, inside
  the candidate's fit window. The fitted model (coefficients, scaling, fit rows' count and hash, code hash) is
  written to research/results/plan21/models/YYYY-MM/<id>.json and its SHA-256 appended to research/results/plan21/freezes.jsonl.
  A freeze not done by the 2nd 23:59 means that candidate sits out M ("missed freeze", counted).
- **Scored markets:** those whose first decision moment (section 2) is after the nominal freeze time and whose close
  time falls inside M. Nothing settled before the freeze is ever scored; nothing from M is ever fitted on for M.
- **Score (once):** from the 8th of M+1 at 00:00 (time for settlements to arrive), with the model frozen for M.
  Markets still without a result are left out and counted; over 5% of them makes the test "not testable". The score is
  written once to research/results/plan21/scores/YYYY-MM.json and never recomputed.
- **First month:** December 2026 (freeze 2026-12-01). **Last month:** November 2028 (24 months; section 5). Continuing
  after that needs a new plan.

## 2. Data (already collected automatically; no new source, no new domain)
All read-only. Anything read before a freeze may be used for that freeze's fit only.
- **15-minute series:** research/live20.py's files in research/data/live20/ (GitHub, cloud/workflows/live20.yml):
  results.json ({ticker: result, yes_pay, no_pay, status, close, settled_ts}); Kalshi's one-minute candles in
  candles/SERIES/YYYY-MM-DD.json.gz (yes bid, yes ask, last price, volume, open interest per candle), parsed with
  research/plan20.py's parse_candles; the minute snapshots snap-*.jsonl.gz (ts, minute, ticker, series, event, open,
  close, yes_bid, yes_ask, no_bid, no_ask, last, volume, oi) only to count gaps (as in live20, they are a raw record).
  Asset groups from research/results/plan20_series.json. Scalar and void results are left out, as in PLAN20.
- **Rain (GitHub's trial copy, trial/paper.db, opened read-only through tbcommon/db.py; never the PC's paper.db):**
  table obs, rows with version "v3" and market_type rain: ticker, ts (log time), fc (v3's chance), mid (Kalshi's mid at
  the scan), result; table v4_obs: ticker, ts, fc (the airport forecast), mid, bid, ask, result, start_ts, with only
  rows logged 00:50-01:30 UTC counted (PLAN.md amendment's window). Day = the market day (tbcommon market_day).
- **PLAN19's samples** (research/data/plan19/samples-*.jsonl, fills-*.jsonl): not used. PLAN19 shows no interim figures
  before its score, and its sampling ends 2026-12-27, so it has no data forward of any PLAN21 freeze. Using it would
  need the user's decision to keep sampling and a new candidate.
- **Kept clean:** KXBTC15M/KXETH15M rows from Nov 2026 on are PLAN15's check period; no candidate fits on or scores
  them until PLAN15's score is recorded in CHANGELOG.md. PLAN7, PLAN8 and PLAN9 keep their own data and verdicts;
  PLAN21 never changes them and its results never stand in for theirs.
- **Missed data:** a 15-minute window without candles or a result, or a night the trial scan did not log, simply has
  no rows (counted by reason each month). A test with more than 20% of its month's windows (or 20% of its market days)
  missing is "not testable" for that month; its share of the error budget is lost, never carried forward.

## 3. Starting candidates (fixed now; each test id counts once toward section 5's cap)
- **S1 `P20R-ALT`:** PLAN20's chances, features, fill, $1 bet and whole-cent fee (PLAN20 section 2) and its ridge
  procedure (section 4: standardisation, unpenalised intercept, 13 strengths, 5-fold day-grouped CV), re-fitted on the
  two whole calendar months before the freeze, on every 15-minute series except KXBTC15M/KXETH15M; at least 20 fit days,
  else it sits out. Rule: p >= ask + fee per contract + 0.01, one bet per window per series. One pooled test.
- **S2 `P20R-BTCETH`:** the same on KXBTC15M and KXETH15M only, first freeze no earlier than the 1st of the month after
  PLAN15's score is recorded. One pooled test.
- **S3 `RAIN-CAL`:** logit(q) = a + b logit(v3 fc), fitted by plain logistic regression (Newton, chances clipped to
  1%-99%) on the two months of obs before the freeze; at least 300 markets and 20 market days, else it sits out.
- **S4 `RAIN-MIX`:** logit(q) = a + b_m logit(mid) + b_s logit(airport fc), same fit and floors, on v4_obs.
- S3 and S4 are accuracy tests only (obs keeps the mid, not the ask): a pass can only lead to a new trading plan.

## 4. Adding candidates from wins and losses
- Each monthly report (section 8) breaks every scored bet and market into wins and losses by ask band, minutes left,
  last-3-minute move, hour band, group, city and forecast-price gap. It is descriptive: nothing in it can pass.
- Any idea from it (or from the user) becomes a candidate only by an entry appended to
  **research/plan21_candidates.json** with: id (never reused), registered (La Paz timestamp), origin, first month,
  data and fields, fit window and procedure, rule, statistic, floors, placebo, and the SHA-256 of the definition text.
  It must be registered by the 25th of the month before its first scored month, statistics-reviewed, and recorded in
  CHANGELOG.md with the file's new SHA-256. Since month k's report appears on the 8th of k+1, an idea from it is first
  scored in month k+2 at the earliest.
- Entries are append-only: never edited. A candidate is changed only by **retiring** it and registering a new id that
  says it **supersedes** the old one. A candidate is retired automatically after 3 scored months in a row with a mean
  at or below zero, or 6 scored months without a pass; retiring never frees error budget.
- At most **6 tests** are scored in a month (section 5). When more are active, those registered first are scored; the
  rest wait (counted), in registry order.

## 5. Error budget across all candidates and months
- Family: every test of every candidate in every month, December 2026 to November 2028. Total family-wise error 2.5%
  one-sided (the project's usual level).
- Spending: equal over the 24 months, 2.5% / 24 = 0.104% per month, split equally over the 6 test slots: **each test
  at 0.0174% one-sided** (z about 3.58; Student-t about 4.05 at 29 degrees of freedom). Unused slots are lost (no
  carry-over, no re-allocation after seeing results), so the family error stays at most 2.5% whatever is tried.
- Why not 2.5% x 2^-k: it gives month 6 only 0.039% and month 10 0.0024%, so later ideas, made with more data and more
  learning, would be nearly untestable. A fixed horizon with equal spending keeps every month equally able to find a
  real edge, at the price of an end date.
- **A test passes** at its level only if every check clears it:
  1. the day-clustered t reading (La Paz day; day means of profit per contract, or of Brier(q) - Brier(mid) below 0);
  2. a 2-day block bootstrap, 100,000 draws (share at or below zero at most the level);
  3. 15-minute tests only: PLAN20's matched placebo (same bets per day from the same ask band x minute cells), 20,000
     draws, p = (k+1)/(N+1), and PLAN20's exact Poisson-binomial bound on wins at break-even;
  4. floors: 300 bets (rain: 300 markets) and 20 days with a bet in the month, else "not testable".
- Reported with every verdict: the bet-weighted figure, the centicent-fee version, calibration by decile.

## 6. Promotion (never directly to real money)
- A pass in month k earns a **confirmation month**: the first whole month whose freeze comes after the pass is
  recorded (normally k+2), with the candidate's own procedure, scored once by section 5's checks at 2.5% one-sided
  (Holm if several confirm in the same month). It is a separate family that only passed candidates enter.
- A confirmed 15-minute candidate enters a forward paper ledger (research/data/plan21/ledger.jsonl, live20's paper
  path, rows marked by candidate id). A confirmed rain candidate only earns a new trading plan.
- Real money stays the user's explicit decision, through a new, code-reviewed live.py path ($1 bets, its own caps
  inside live.MAX_AT_RISK, every existing lock and the kill switch). Nothing in PLAN21 asks for it automatically.

## 7. Power (stated before the data)
At 0.0174% with 80% power a test needs about 4.4 standard errors (normal) to 4.9 (t, 30 day means). Ignoring
clustering, the smallest edge reliably seen in one month:
- cheap sides (1-10c; one bet's SD about 17c): 300 bets 4.3c, 1,000 bets 2.4c, 3,000 bets 1.4c a contract;
- 50c contracts (SD about 50c): 300 bets 12.8c, 1,000 bets 7.0c, 3,000 bets 4.0c;
- rain accuracy: about 0.9 day-level SDs of Brier(q) - Brier(mid) over 30 market days.
Day clustering and requiring every check raise these. Read plainly: only large edges can pass in any single month;
the 50c fee is about 1.75c and cheap-side long-shot bias is documented, so a pass is unlikely and must be confirmed.

## 8. Reporting
- research/results/plan21/report-YYYY-MM.md in plain English, written at each score: each test's verdict, bets, days,
  wins against what prices implied, mean profit per contract with its interval, what was left out and why, the win and
  loss breakdown (section 4), the registry's state, and the budget used so far. A dashboard section "Learning engine
  (PLAN21)" shows the same, read-only. Before a month's score only counts appear (rows, gaps, freezes), no profit.

## 9. Operations
- GitHub Actions (cloud/workflows/plan21.yml; public repository: no keys, no PC data). It reads live20's and the
  trial's files; any candle fetch goes through live20's own public Kalshi GETs. No order endpoint, no live.py import,
  never writes paper.db, live.db or trial/paper.db. The KILL file lives on the PC only; this is paper research.
- Pure Python (Python 3.8 syntax). numpy is approved for PLAN20's fit and score only: PLAN21 uses it only if the user
  approves it for PLAN21; otherwise the ridge fit is plain Python (about 30 features, Newton's method).
- research/plan21.py is written after this plan's freeze, code-reviewed, and frozen before the first freeze; its hash
  and the registry's are checked at every freeze and score, and a difference stops the cycle until an amendment.

## 10. Freeze
Where code and text differ, the text wins, by a dated amendment before any number is computed.
