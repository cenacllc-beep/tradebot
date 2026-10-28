import sqlite3, os, sys, math, time, subprocess
from config import *
def db():
    c=sqlite3.connect(DB)
    cols=[r[1] for r in c.execute("pragma table_info(trades)")]
    if cols and "settled_ts" not in cols:   # one-time migration (2026-10-14): settle time, used by the daily loss stop
        here=os.path.dirname(os.path.abspath(__file__))
        if subprocess.run([sys.executable,os.path.join(here,"backup.py"),"premigration"]).returncode not in (0,3):   # 3 = only live.db failed
            raise SystemExit("Backup failed, so paper.db was not changed.")
        c.execute("alter table trades add column settled_ts real")
    c.execute("create table if not exists trades(id integer primary key,ts real,ticker text,side text,price real,fair real,n integer,cost real,fee real,status text default 'open',result text,pnl real,version text default 'v1',settled_ts real)")
    c.execute('create table if not exists obs(ticker text,version text,ts real,fc real,mid real,result text,nws_prev real,nws_day real,nws_night real,market_type text,p_a real,p_b real,slices text,mu real,station text,primary key(ticker,version))')
    c.commit()
    return c
HERE=os.path.dirname(os.path.abspath(__file__))
def kill_names(d):
    """Kill files in folder d: named KILL in any letter case, with any ending (KILL, KILL.txt, kill.txt.txt), files or
    folders. Raises OSError if d cannot be listed."""
    return [os.path.join(d,n) for n in sorted(os.listdir(d)) if n.lower()=="kill" or n.lower().startswith("kill.")]
def kill_file():
    """The kill switch (fixed 2026-10-15): a kill file in the tradebot folder, wherever the bot is started from (a kill
    file in the current folder counts too). Windows hides file endings, and Explorer's New > Text Document makes
    'KILL.txt', so any ending counts. Returns the file's path, or None when the switch is off. If the tradebot folder
    cannot be read, the switch counts as ON (fail closed)."""
    try: found=kill_names(HERE)
    except OSError: return os.path.join(HERE,"KILL (the tradebot folder could not be read, so the switch counts as on)")
    if found: return found[0]
    try:
        cwd=os.getcwd()
        if os.path.normcase(os.path.abspath(cwd))!=os.path.normcase(HERE): found=kill_names(cwd)
    except OSError: pass
    return found[0] if found else None
def killed(): return kill_file() is not None   # halts scans: no paper trades, no shadow orders, no Kalshi orders
def fee(p,n): return math.ceil(0.07*n*p*(1-p)*100)/100   # approximation: verify Kalshi's fee schedule
def kelly_stake(fair,price,cash):
    if fair<=price: return 0.0
    f=(fair-price)/(1-price)*KELLY_FRACTION
    return cash*min(f,MAX_POS_PCT)
def state(c):
    pnl=c.execute("select coalesce(sum(pnl),0) from trades where status='settled'").fetchone()[0]
    opn=c.execute("select coalesce(sum(cost+fee),0) from trades where status='open'").fetchone()[0]
    # daily loss stop: net P&L of trades SETTLED in the last 24 hours (fixed 2026-10-14: it used trades opened since
    # 00:00 UTC, which have never settled by scan time, so the stop could not trigger)
    today=c.execute("select coalesce(sum(pnl),0) from trades where status='settled' and settled_ts>=?",(time.time()-86400,)).fetchone()[0]
    return BANKROLL+pnl-opn, today
