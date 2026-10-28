"""Immutable decision audit ledger (added 2026-10-22, platform upgrade phase 2).

Every market a strategy evaluates gets one decision row: what it saw (quote, model inputs and their age, market rules
hash), what it concluded (TRADE_YES, TRADE_NO or ABSTAIN with a reason code) and, for a trade, the paper trade it
opened. Rows are never changed: SQLite triggers refuse UPDATE and DELETE on every audit table. Anything learned later
(a fill, a settlement, a price mark, a post-mortem) is a new row in decision_events. So "why did Tradebot enter this
trade?" can be answered from the exact snapshot that made the decision, months later.

Additive only: new tables next to the old ones (obs and trades are unchanged). strategy_log (registry.py) lives here
too, so it is created with the same backup. Creating the tables the first time backs
up the database first, like core.db's migrations. If the tables cannot be created, ensure() returns False and the
callers fail closed: markets are still logged as before, but no paper trade is opened without its decision row. The
same happens if an existing table's columns differ from the definitions below. The scan then prints TRADES BLOCKED and
the dashboard shows it.
Known edge case: a ticker listed twice in one scan gets one decision row; its second listing cannot be recorded, so it
cannot trade a second time (the old code could).
Python 3.8+, no dependencies."""
import os, sys, json, time, uuid, hashlib, subprocess
HERE=os.path.dirname(os.path.abspath(__file__))
SCHEMA=1
ACTIONS=("TRADE_YES","TRADE_NO","ABSTAIN")
# Reason codes: what each one means in plain words (shown on the dashboard).
REASONS={
 "TRADE":"All checks passed; a paper trade was opened.",
 "CLOSE_TIME_UNREADABLE":"The market's close time could not be read, so the day window is unknown (fails closed).",
 "MARKET_STARTED":"The market's Kalshi day has already begun; the bot only trades before it starts.",
 "NO_QUOTE":"No usable bid or ask.",
 "WIDE_SPREAD":"The bid-ask spread is wider than the strategy allows.",
 "MODEL_UNAVAILABLE":"The forecast model gave no estimate (missing data, unknown station or city).",
 "DAILY_LOSS_STOP":"The daily loss stop is on: markets are logged, no new trades.",
 "ALREADY_HELD":"An open trade on this market already exists.",
 "STRATEGY_DISABLED":"This market type is logged but not traded (temperature since 2026-10-14).",
 "INSUFFICIENT_EDGE":"The blended forecast is not far enough from the price (needs 8 points).",
 "LOW_WIN_PROBABILITY":"The chance that the chosen side wins is below the experiment's floor.",
 "NEGATIVE_NET_EV":"Expected value after fees is not positive.",
 "SIZE_BELOW_ONE":"The stake rule sizes the trade below one contract.",
 "CASH_LIMIT":"Not enough paper cash for this trade.",
 "EXPOSURE_CAP":"The 15% open-exposure cap would be exceeded.",
 "CORRELATION_LIMIT":"The risk cluster's cap would be exceeded.",
 "STALE_DATA":"An input is older than its allowed age.",
 "RULES_UNCERTAIN":"The settlement rule or station could not be confirmed.",
 "SOURCE_MISMATCH":"The data source does not match the market's settlement source.",
 "ANOMALOUS_MODEL_MARKET_GAP":"Model and market disagree by more than the anomaly bound: investigate, do not trade.",
 "FEE_TOO_HIGH":"Fees remove the edge.",
 "LOW_LIQUIDITY":"Not enough displayed size or trading.",
 "INSUFFICIENT_HISTORY":"Not enough settled history to calibrate this kind of trade.",
 "RESEARCH_ONLY":"Research strategy: recorded, never traded.",
 "FORWARD_TEST_ONLY":"Forward-test strategy: paper only.",
 "EXCHANGE_STATE_UNSAFE":"The market or exchange state is not normal (closed, halted, settled).",
 "LIMIT_PRICE_INVALID":"The limit price would be outside 1-99 cents.",
 "AUDIT_UNAVAILABLE":"The audit ledger could not be written, so no trade was opened (fail closed).",
 "GATE_NOT_PASSED":"A market day from the stop date (2026-11-11) on: v3 rain trades it only after the gate's single look has passed (pre-committed 2026-10-28).",
}
TABLES={
 "audit_meta":"create table audit_meta(key text primary key,value text)",
 "scans":"create table scans(scan_id text primary key,started_ts real not null,kind text not null,code_hash text,config text,host text)",
 "scan_ends":"create table scan_ends(scan_id text primary key,ended_ts real not null,summary text)",
 "decisions":("create table decisions(decision_id text primary key,scan_id text not null,ts real not null,strategy_id text not null,"
   "strategy_version text,model_version text,mode text not null,ticker text not null,event_ticker text,market_type text,"
   "action text not null,side text,reason text not null,close_ts real,day_start_ts real,bid real,ask real,mid real,spread real,"
   "p_model real,p_fair real,p_win real,price real,edge real,fee real,net_ev real,n integer,cost real,capital real,"
   "trade_ref text,rules_hash text,station text,inputs text,detail text)"),
 "decision_events":"create table decision_events(event_id integer primary key,decision_id text not null,ts real not null,kind text not null,detail text)",
 "market_results":"create table market_results(ticker text primary key,result text not null,recorded_ts real not null)",
 "strategy_log":"create table strategy_log(ts real,strategy_id text,version text,state text,mode text,detail text)",
}
INDEXES=["create unique index if not exists decisions_once on decisions(scan_id,strategy_id,ticker)",
         "create index if not exists decisions_ticker on decisions(ticker)",
         "create index if not exists decisions_trade on decisions(trade_ref)",
         "create index if not exists events_decision on decision_events(decision_id)"]
def _triggers(t):
    return ["create trigger if not exists %s_no_update before update on %s begin select raise(abort,'%s is append-only'); end"%(t,t,t),
            "create trigger if not exists %s_no_delete before delete on %s begin select raise(abort,'%s is append-only'); end"%(t,t,t)]
def _have(c): return {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
def _cols(sql):
    """Column names from one of the CREATE TABLE statements above."""
    body=sql[sql.index("(")+1:sql.rindex(")")]
    return [p.strip().split()[0] for p in body.split(",") if p.strip() and not p.strip().startswith(("primary","unique"))]
def schema_problems(c):
    """Tables whose columns differ from this file's definition (an older or foreign ledger). Empty when all match."""
    out=[]
    for t,sql in TABLES.items():
        have=[r[1] for r in c.execute("pragma table_info(%s)"%t)]
        if have and have!=_cols(sql): out.append(t)
    return out
def ensure(c,backup=True):
    """Create the audit tables if missing (backing up the database first). True when the ledger is ready."""
    try:
        bad=schema_problems(c)
        if bad:
            print("AUDIT: ledger unavailable: the columns of %s differ from audit.py (schema %s). Nothing was changed."%(", ".join(bad),SCHEMA)); return False
        missing=[t for t in TABLES if t not in _have(c)]
        if missing:
            if backup and os.path.exists(os.path.join(HERE,"backup.py")):
                rc=None
                for k in range(2):   # backup names have one-second resolution and are never overwritten: a clash is retried once
                    rc=subprocess.run([sys.executable,os.path.join(HERE,"backup.py"),"preaudit"]).returncode
                    if rc in (0,3): break
                    time.sleep(1.2)
                if rc not in (0,3): print("AUDIT: backup failed, so the audit tables were not created"); return False
            for t in missing: c.execute(TABLES[t])
            c.execute("insert or ignore into audit_meta(key,value) values('schema',?)",(str(SCHEMA),))
            c.execute("insert or ignore into audit_meta(key,value) values('created',?)",(str(time.time()),))
        for s in INDEXES: c.execute(s)
        for t in TABLES:
            if t!="audit_meta":
                for s in _triggers(t): c.execute(s)
        c.commit(); return True
    except Exception as ex:   # sqlite errors, a backup that could not start, anything: fail closed, never crash the scan
        print("AUDIT: ledger unavailable (%s)"%ex); return False
def code_hash(files):
    h=hashlib.sha256()
    for f in files:
        try: h.update(open(os.path.join(HERE,f),"rb").read())
        except OSError: h.update(b"missing:"+f.encode())
    return h.hexdigest()[:12]
def rules_hash(m):
    s=(m.get("rules_primary") or "")+"\n"+(m.get("rules_secondary") or "")
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16] if s.strip() else None
def _j(x): return json.dumps(x,separators=(",",":"),default=str,allow_nan=False) if x is not None else None
def _clean(x):
    if isinstance(x,float) and x!=x: return None
    return x
def start_scan(c,kind,config=None):
    sid=uuid.uuid4().hex
    c.execute("insert into scans(scan_id,started_ts,kind,code_hash,config,host) values(?,?,?,?,?,?)",
              (sid,time.time(),kind,code_hash(("strategy.py","weather.py","nws.py","core.py","config.py","shadow.py","audit.py","selector.py")),_j(config),os.name))
    return sid
def end_scan(c,sid,summary):
    if sid: c.execute("insert or ignore into scan_ends(scan_id,ended_ts,summary) values(?,?,?)",(sid,time.time(),_j(summary)))
MARKET_FIELDS=("ticker","event_ticker","title","subtitle","status","close_time","strike_type","floor_strike","cap_strike","yes_bid_dollars","yes_ask_dollars",
               "last_price_dollars","volume_fp","open_interest_fp","yes_bid_size_fp","yes_ask_size_fp","liquidity_dollars")
def market_snapshot(m): return {k:m.get(k) for k in MARKET_FIELDS if m.get(k) not in (None,"")}
def decide(c,sid,strategy_id,m,action,reason,mode="paper",strategy_version=None,model_version=None,market_type=None,
           close_ts=None,day_start_ts=None,bid=None,ask=None,side=None,p_model=None,p_fair=None,p_win=None,price=None,
           fee=None,n=None,cost=None,trade_ref=None,station=None,inputs=None,detail=None):
    """Insert one decision row and return its id. Raises on any failure (callers decide whether to fail closed)."""
    if action not in ACTIONS: raise ValueError("unknown action %r"%action)
    if reason not in REASONS: raise ValueError("unknown reason %r"%reason)
    mid=(bid+ask)/2 if (bid is not None and ask is not None) else None
    spread=(ask-bid) if (bid is not None and ask is not None) else None
    edge=(p_win-price) if (p_win is not None and price is not None) else None
    fee_pc=(fee/n) if (fee is not None and n) else None
    net_ev=(p_win-price-(fee_pc or 0)) if (p_win is not None and price is not None) else None
    capital=(cost or 0)+(fee or 0) if cost is not None else None
    did=uuid.uuid4().hex
    det=dict(detail or {}); det["market"]=market_snapshot(m)
    c.execute("insert into decisions(decision_id,scan_id,ts,strategy_id,strategy_version,model_version,mode,ticker,event_ticker,market_type,action,side,reason,"
              "close_ts,day_start_ts,bid,ask,mid,spread,p_model,p_fair,p_win,price,edge,fee,net_ev,n,cost,capital,trade_ref,rules_hash,station,inputs,detail) "
              "values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (did,sid,time.time(),strategy_id,strategy_version,model_version,mode,m.get("ticker"),m.get("event_ticker"),market_type,action,side,reason,
               close_ts,day_start_ts,_clean(bid),_clean(ask),mid,spread,_clean(p_model),_clean(p_fair),_clean(p_win),_clean(price),edge,fee,net_ev,n,cost,capital,
               trade_ref,rules_hash(m),station,_j(inputs),_j(det)))
    return did
def event(c,decision_id,kind,detail=None,ts=None):
    c.execute("insert into decision_events(decision_id,ts,kind,detail) values(?,?,?,?)",(decision_id,ts or time.time(),kind,_j(detail)))
def decision_for(c,trade_ref):
    r=c.execute("select decision_id from decisions where trade_ref=? order by ts desc limit 1",(trade_ref,)).fetchone()
    return r[0] if r else None
def record_result(c,ticker,result):
    """The market's settlement (first recorded value wins; later disagreements are logged as events, never overwritten)."""
    if result not in ("yes","no"): return
    old=c.execute("select result from market_results where ticker=?",(ticker,)).fetchone()
    if old is None: c.execute("insert into market_results(ticker,result,recorded_ts) values(?,?,?)",(ticker,result,time.time()))
    elif old[0]!=result: print("AUDIT WARNING: %s result changed from %s to %s (kept the first; check Kalshi)"%(ticker,old[0],result))
class Recorder:
    """Records one market's evaluation for one strategy. abstain() never raises (a logging failure is counted and the scan
    goes on); trade() raises, so the caller can roll the paper trade back (fail closed)."""
    def __init__(self,c,sid,strategy_id,strategy_version,model_version,mode,stats):
        self.c=c; self.sid=sid; self.sid_ok=sid is not None; self.k=dict(strategy_id=strategy_id,strategy_version=strategy_version,model_version=model_version,mode=mode); self.stats=stats
    def abstain(self,m,reason,**kw):
        self.stats[reason]=self.stats.get(reason,0)+1
        if not self.sid_ok: self.stats["_unlogged"]=self.stats.get("_unlogged",0)+1; return None
        try: return decide(self.c,self.sid,m=m,action="ABSTAIN",reason=reason,**self.k,**kw)
        except Exception as ex:
            self.stats["_failed"]=self.stats.get("_failed",0)+1
            if self.stats["_failed"]<=3: print("AUDIT: could not record %s (%s)"%(m.get("ticker"),ex))
            return None
    def trade(self,m,side,**kw):
        if not self.sid_ok: raise RuntimeError("audit ledger unavailable")
        did=decide(self.c,self.sid,m=m,action="TRADE_YES" if side=="yes" else "TRADE_NO",reason="TRADE",side=side,**self.k,**kw)
        self.stats["TRADE"]=self.stats.get("TRADE",0)+1   # counted only once its row is written
        return did
