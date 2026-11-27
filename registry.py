"""Strategy registry and lifecycle (added 2026-10-22, platform upgrade phases 22-23).

Every strategy has a durable id, a version, a lifecycle state and a mode. Results of different strategies are never
mixed: decisions, trades and reports carry the strategy id.

Lifecycle: IDEA -> BACKTEST -> FORWARD_TEST -> CONFIRMED -> PAPER_ONLY -> LIVE_ELIGIBLE, plus FAILED, SUSPENDED and
RETIRED. BACKTEST never goes straight to LIVE_ELIGIBLE. Failed strategies stay listed with their evidence.

Mode decides what a strategy may do:
- research: recorded only;
- paper: paper trades;
- live: may be mirrored by live.py.
Only the user can make a strategy live-eligible, after its forward test. Today none is. live.py copies v3 rain paper
trades by its own fixed filter, and nothing here can widen it.

The registry is code (reviewed, versioned). paper.db keeps an append-only log of each state the dashboard saw, so a
change of state is visible in history. Python 3.8+."""
import json, time
STATES=("IDEA","BACKTEST","FORWARD_TEST","FAILED","CONFIRMED","PAPER_ONLY","LIVE_ELIGIBLE","SUSPENDED","RETIRED")
ALLOWED={"IDEA":("BACKTEST","FORWARD_TEST","RETIRED"),"BACKTEST":("FORWARD_TEST","FAILED","RETIRED"),
         "FORWARD_TEST":("CONFIRMED","FAILED","SUSPENDED"),"CONFIRMED":("PAPER_ONLY","SUSPENDED","RETIRED"),
         "PAPER_ONLY":("LIVE_ELIGIBLE","SUSPENDED","RETIRED"),"LIVE_ELIGIBLE":("SUSPENDED","RETIRED"),
         "SUSPENDED":("FORWARD_TEST","PAPER_ONLY","RETIRED"),"FAILED":("RETIRED",),"RETIRED":()}
def S(sid,version,family,state,mode,plan,started,rule,horizon,why="",live=False,notes=""):
    return dict(id=sid,version=version,family=family,state=state,mode=mode,plan=plan,started=started,rule=rule,horizon=horizon,
                why=why,live_eligible=live,notes=notes)
REGISTRY=[
 S("forecast_alpha.rain.v3","v3","forecast_alpha","FORWARD_TEST","paper","CLAUDE.md sections 5 and 11","2026-10-13",
   "Gate, judged once on 2026-11-11: at least 100 resolved v3 rain markets, forecast Brier below market Brier by a clear margin, at least 50 settled trades, net P&L above 0",
   "2026-11-11",notes="Frozen forecast. Since 2026-10-28 (user): Detroit and West Palm Beach added, and no trade when forecast and market are more than 30 points apart. The only strategy live.py can copy: to Kalshi's demo exchange (fake money) any time, and to real money only on or after 2026-11-11 after the user's own typed unlock. From 2026-11-11: the gate's single look is stored in paper.db (pre-committed 2026-10-28). Since the user's decision of 2026-11-06, v3 keeps paper-trading market days from Nov 11 on whatever the look says, so live.py can copy them to a real account the user funds and unlocks himself; test-day markets still unsettled on 2026-11-18 are left out of the look. Gate look stored 2026-11-11: NOT PASSED (576 markets, forecast Brier 0.0722 vs market 0.0616, 39 trades, -$3.40); v3 keeps trading on paper by the user's decision of 2026-11-06, judged only through PLAN7/8/9 (audit 2026-11-26)."),
 S("forecast_alpha.temp.v3","v3","forecast_alpha","FAILED","research","research/PLAN2.md","2026-10-13",
   "Past data: market Brier 0.102 beat the forecast's 0.122; the rule lost 4.4c (taker) and 2.7c (maker) a contract","2026-10-14",
   why="Market prices beat the forecast on 10,885 past markets; logged, not traded, since 2026-10-14"),
 S("maker_spread.rain.v3","v3","maker_spread","FORWARD_TEST","paper","CLAUDE.md section 5a","2026-10-14",
   "Shadow limit-order ledger on the v3 signal; research only, never part of the gate","keeps placing its paper orders after the gate's single look (user, 2026-11-09: paper research continues); until then the Oct 28 rule stopped it after a failed look",notes="Fills assume full size and ignore the queue (optimistic)."),
 S("forecast_alpha.rain.v4","v4","forecast_alpha","FORWARD_TEST","research","research/PLAN.md amendment 2026-10-14","2026-10-14",
   "Airport-forecast lead: futility at 60 market days (mean limit-order profit per day not above 0 drops it); verdict at 110 market days (weekly block bootstrap 95% interval above 0)",
   "110 market days"),
 S("settlement_certainty.temp.plan3a","plan3","settlement_certainty","FAILED","research","research/PLAN3.md test A","2026-10-15",
   "Late-day temperature: 0 trades; all 2,727 decided markets already cost $1.00","2026-10-15",why="Nothing to buy: the market had priced every decided outcome"),
 S("maker_spread.lowtemp.plan3b","plan3","maker_spread","FAILED","research","research/PLAN3.md test B","2026-10-15",
   "Low-temperature limit orders: -3.6c a contract (t -3.75)","2026-10-15",why="Lost money; market Brier beat the forecast"),
 S("copy_trading.polymarket.plan4","plan4","external_leadlag","RETIRED","research","research/PLAN4.md (P1, P2, P2c)","2026-10-15",
   "Scored once each at 2.5 SE (plus 2 SE vs rest / placebo)","2026-10-30",
   why="Not scored (2026-10-30): 11 of 100 checked wallets failed the pre-set 98% position-coverage check (the rule allows 10), so by the plan P1 and P2 are not scored; P2c, which copies the same selected wallets, is left unscored with them. Says nothing either way; no re-run or relaxed threshold."),
 S("copy_trading.kalshi_large.plan4","plan4","microstructure","FAILED","research","research/PLAN4.md (K1)","2026-10-15",
   "Copying large Kalshi trades: scored once at 2.5 SE with 300 copies over 40 dates","2026-10-29",
   why="FAIL (scored 2026-10-29 04:17): -2.2c a contract after fees over 37,669 copies on 92 market dates (t -0.49; 95% interval about -11c to +7c). No edge shown: rules out an average edge above about 7c on these sports and 15-minute crypto series, cannot tell a small gain from a small loss."),
 S("maker_incentive.weather.plan5","plan5","maker_spread","RETIRED","research","research/PLAN5.md test L","",
   "Forward paper study of resting quotes: spread-only verdict applies; rewards count only with dated eligibility evidence","samples 2026-10-24..2026-11-20, scored once from 2026-11-25",
   why="Scored once 2026-11-25: NOT TESTABLE (Kalshi listed no liquidity program on daily weather markets after Nov 5; too few qualifying days). Generalised to every rewarded market as PLAN19.",
   notes="Sampled on the PC until 2026-10-28, then hourly by GitHub Actions in the public repository (data in research/data/lip/ there)."),
 S("station_gap.temp.plan5","plan5","external_leadlag","IDEA","research","research/PLAN5.md test S","",
   "Polymarket airport price shifted by the station difference vs Kalshi","not started"),
 S("cross_strike.structure.v1","v1","cross_strike_relative_value","FORWARD_TEST","research","docs/RESEARCH_ENGINES.md","2026-10-22",
   "Records monotonicity and bucket-sum violations at executable prices; descriptive until a plan is written","open-ended"),
 S("meta_selector.accuracy_first.v1","v1","meta_selector","FORWARD_TEST","research","selector.py EXPERIMENTS","2026-10-22",
   "Shadow verdict beside every v3 candidate: trade only with a conservative win chance and positive conservative EV; never trades","open-ended"),
 S("orderflow.micro.v1","v1","microstructure","IDEA","research","research/micro.py","2026-10-22",
   "Exploratory: book imbalance vs later mid, join/improve/cross with a queue model, toxic fills, lead-lag within events; a pattern earns only a written plan","on demand"),
 S("combo.copula.v1","v1","multivariate","IDEA","research","research/combo.py","2026-10-22",
   "Exploratory: combo mid vs independence price vs one-factor copula at an earlier-fitted correlation, by Brier on settled combos","on demand"),
 S("forecast_alpha.rain.plan7","plan7","forecast_alpha","FORWARD_TEST","research","research/PLAN7.md","2026-11-11",
   "v3 with its rain lean corrected (frozen logistic fit) vs the market: day-mean Brier, maker and taker; futility at 60 forward market days, final at 110","60 / 110 forward market days (backstop 2027-06-30)"),
 S("forecast_alpha.rain.plan8","plan8","forecast_alpha","FORWARD_TEST","research","research/PLAN8.md","2026-11-07",
   "Kalshi price mixed with the airport forecast (frozen fit) vs the price alone: accuracy only","60 / 110 forward market days (backstop 2027-06-30)"),
 S("forecast_alpha.rain.plan9","plan9","forecast_alpha","FORWARD_TEST","research","research/PLAN9.md","2026-11-08",
   "v3's hourly chances combined in 6-hour blocks: B vs v3, then A vs the price","60 / 110 counted market days (backstop 2027-06-30)"),
 S("forecast_alpha.rain.plan10","plan10","forecast_alpha","BACKTEST","research","research/PLAN10.md","2026-11-11",
   "NOAA HRRR forecast vs the evening price on PLAN.md's past markets; scored once","single score on the PC (waits for disk space)"),
 S("intraday.rain.plan11","plan11","external_leadlag","IDEA","research","research/PLAN11.md","",
   "Gauge and radar rules once the rain day has begun; replay on Jul 15 - Nov 10","plan frozen 2026-11-12; code not written yet"),
 S("skill_vs_luck.sports_crypto.plan14","plan14","microstructure","IDEA","research","research/PLAN14.md","",
   "Large/early trades, reaction speed, NBA Elo vs price; screened Oct 14 - Nov 10, scored once on Nov 11 - Jan 10","plan frozen 2026-11-13; code not written yet"),
 S("crypto15.random_walk.plan15","plan15","forecast_alpha","FORWARD_TEST","research","research/PLAN15.md","2026-11-13",
   "Coinbase random-walk model and frozen logistic per asset and minute vs Kalshi's 15-minute price; 12 tests under Holm","scored once on Nov-Dec windows, from 2027-01-01"),
 S("crypto15.live_paper.plan15f","plan15f","forecast_alpha","FORWARD_TEST","paper","research/PLAN15F.md","2026-11-13",
   "Live paper bets with PLAN15's frozen model on the 15-minute BTC/ETH markets (research/live15.py); descriptive","reviewed at PLAN15's score; stops if PLAN15 shows no edge",
   notes="Audit 2026-11-26: 3,256 settled paper bets, -1.95c a bet (-$63.54 on one-contract bets), 38% won at an average 38c."),
 S("crypto15.rules.plan16","plan16","forecast_alpha","FAILED","research","research/PLAN16.md","2026-11-13",
   "Four rules (volatility, choosier edge, trend, order flow) on 15-minute BTC/ETH; 8 tests under Holm","2026-11-19",why="NO EDGE SHOWN for all 8 tests (each lost about the fee, 0.4-5.9c a contract)."),
 S("crypto15.longshot.plan17","plan17","forecast_alpha","RETIRED","research","research/PLAN17.md","2026-11-18",
   "Cheap (1-5c) reversals on 15-minute BTC/ETH, frozen ridge model","2026-11-19",why="NOT TESTABLE (65 and 71 bets, under the 100-bet floor); cannot be rescued. Generalised as PLAN20."),
 S("crypto15.garch.plan18","plan18","forecast_alpha","FAILED","research","research/PLAN18.md","2026-11-18",
   "Five-exchange composite, GARCH(1,1) and PELT shift detector on 15-minute BTC/ETH","2026-11-20",why="NO EDGE SHOWN for G (about -1.5c and -2.0c a contract over ~10,000 bets); M and R not testable."),
 S("maker_incentive.all.plan19","plan19","maker_spread","FORWARD_TEST","research","research/PLAN19.md","2026-11-28",
   "Resting bids at the reference price on every rewarded market: spread-alone and with-rewards verdicts","samples 2026-11-28..2026-12-27, scored once from 2026-12-29"),
 S("crypto15.longshot_all.plan20","plan20","forecast_alpha","BACKTEST","research","research/PLAN20.md","2026-11-26",
   "Cheap (1-10c) sides on every 15-minute series: map (Jun-Jul), frozen ridge model scored once on Aug-Oct, then a 42-day paper test for a passing group","score once after the Aug-Oct download",
   notes="Model frozen 2026-11-26 (SHA-256 8e351ab1...). The map: cheap sides won 3.3% where their asks averaged 4.7%. research/live20.py logs every 15-minute market and writes descriptive paper bets with the frozen model."),
]
BY_ID={s["id"]:s for s in REGISTRY}
def get(sid): return BY_ID.get(sid)
def mode(sid):
    s=BY_ID.get(sid); return s["mode"] if s else "research"
def may_paper_trade(sid):
    s=BY_ID.get(sid); return bool(s) and s["mode"] in ("paper","live") and s["state"] not in ("FAILED","SUSPENDED","RETIRED","IDEA")
def may_trade_live(sid):
    """Nothing in the registry can enable real orders: live.py has its own fixed filter (v3 rain). This exists so new code
    can ask and always be told no unless the user has explicitly made a strategy live-eligible here."""
    s=BY_ID.get(sid); return bool(s) and s["state"]=="LIVE_ELIGIBLE" and bool(s["live_eligible"])
def check():
    """Sanity rules on the registry itself (tests call this)."""
    ids=[s["id"] for s in REGISTRY]; assert len(ids)==len(set(ids)), "duplicate strategy ids"
    for s in REGISTRY:
        assert s["state"] in STATES, s
        assert s["mode"] in ("research","paper","live"), s
        if s["live_eligible"]: assert s["state"]=="LIVE_ELIGIBLE", s
        if s["state"] in ("FAILED","RETIRED","IDEA","BACKTEST"): assert s["mode"]!="live" and not s["live_eligible"], s
    return True
def transition_ok(a,b): return b in ALLOWED.get(a,())
def log_states(c):
    """Append the current registry to paper.db's strategy_log when a state differs from the last one logged (append-only).
    The table is created by audit.ensure(), after a backup; without it nothing is written."""
    if not c.execute("select 1 from sqlite_master where type='table' and name='strategy_log'").fetchone(): return
    for s in REGISTRY:
        last=c.execute("select state,mode,version from strategy_log where strategy_id=? order by ts desc limit 1",(s["id"],)).fetchone()
        if last!=(s["state"],s["mode"],s["version"]):
            c.execute("insert into strategy_log(ts,strategy_id,version,state,mode,detail) values(?,?,?,?,?,?)",(time.time(),s["id"],s["version"],s["state"],s["mode"],json.dumps(s)))
