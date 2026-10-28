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
   "2026-11-11",notes="Frozen forecast. Since 2026-10-28 (user): Detroit and West Palm Beach added, and no trade when forecast and market are more than 30 points apart. The only strategy live.py can copy: to Kalshi's demo exchange (fake money) any time, and to real money only on or after 2026-11-11 after the user's own typed unlock. The gate verdict is shown at unlock, not enforced."),
 S("forecast_alpha.temp.v3","v3","forecast_alpha","FAILED","research","research/PLAN2.md","2026-10-13",
   "Past data: market Brier 0.102 beat the forecast's 0.122; the rule lost 4.4c (taker) and 2.7c (maker) a contract","2026-10-14",
   why="Market prices beat the forecast on 10,885 past markets; logged, not traded, since 2026-10-14"),
 S("maker_spread.rain.v3","v3","maker_spread","FORWARD_TEST","paper","CLAUDE.md section 5a","2026-10-14",
   "Shadow limit-order ledger on the v3 signal; research only, never part of the gate","open-ended",notes="Fills assume full size and ignore the queue (optimistic)."),
 S("forecast_alpha.rain.v4","v4","forecast_alpha","FORWARD_TEST","research","research/PLAN.md amendment 2026-10-14","2026-10-14",
   "Airport-forecast lead: futility at 60 market days (mean limit-order profit per day not above 0 drops it); verdict at 110 market days (weekly block bootstrap 95% interval above 0)",
   "110 market days"),
 S("settlement_certainty.temp.plan3a","plan3","settlement_certainty","FAILED","research","research/PLAN3.md test A","2026-10-15",
   "Late-day temperature: 0 trades; all 2,727 decided markets already cost $1.00","2026-10-15",why="Nothing to buy: the market had priced every decided outcome"),
 S("maker_spread.lowtemp.plan3b","plan3","maker_spread","FAILED","research","research/PLAN3.md test B","2026-10-15",
   "Low-temperature limit orders: -3.6c a contract (t -3.75)","2026-10-15",why="Lost money; market Brier beat the forecast"),
 S("copy_trading.polymarket.plan4","plan4","external_leadlag","BACKTEST","research","research/PLAN4.md (P1, P2, P2c)","2026-10-15",
   "Scored once each at 2.5 SE (plus 2 SE vs rest / placebo)","once data is complete"),
 S("copy_trading.kalshi_large.plan4","plan4","microstructure","BACKTEST","research","research/PLAN4.md (K1)","2026-10-15",
   "Copying large Kalshi trades: scored once at 2.5 SE with 300 copies over 40 dates","once data is complete"),
 S("maker_incentive.weather.plan5","plan5","maker_spread","IDEA","research","research/PLAN5.md test L","",
   "Forward paper study of resting quotes: spread-only verdict applies; rewards count only with dated eligibility evidence","samples 2026-10-24..2026-11-20, scored once from 2026-11-25"),
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
