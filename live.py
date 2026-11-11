"""Kalshi account connection and order placing (added 2026-10-14 at the user's request; see CLAUDE.md section 3a).
The ONLY file in this project that can place an order. It copies the paper bot: after each scan it places the same
rain trades on your Kalshi account, at the paper price or better, never more contracts, never more than $50 at risk (the cap; $25 until 2026-11-11).

  .\\run live setup        connect an account (you type the key ID and the key file location; run it yourself)
  .\\run live test         signed read-only check: balance and open positions
  .\\run live status       settings, locks, account, this ledger and the paper gate verdict
  .\\run live demo-order [no] [TICKER]   demo exchange only: buy 1 YES (or NO) contract at the ask (fake money)
  .\\run live mirror       place this scan's paper rain trades (run.bat scan runs this after main.py scan)
  .\\run live sync         record fills and settlements (run.bat settle runs this)
  .\\run live use demo     (or: use prod) switch exchange
  .\\run live unlock       real money, Nov 11 or later only: shows the gate verdict, then you type the phrase
  .\\run live lock         stop real-money orders again (always allowed)
  .\\run live resume       restart after a 25% drawdown pause (you type it; on real money, unlock again too)

Locks: a KILL file stops everything. The demo exchange (fake money) works any time. The real exchange places orders only
when ALL hold: today is on or after the stop date (Nov 11, 2026), the exchange is set to prod, and you ran `unlock`
yourself in a terminal (not a script); the unlock is recorded both in live.db and in your settings file, so restoring an
old live.db cannot undo a later `lock`. Limits on every order: rain markets only, version v3, the market's day has not
begun, buy only, limit price no higher than the paper price (immediate-or-cancel, so nothing rests on the book), count
no more than the paper count, one bot order per market (checked on Kalshi too, so a lost or restored live.db cannot
cause a second order), at most $50 at risk across the whole account (Kalshi's own position figures; missing figures stop
the run), enough cash, a daily loss stop of $2.50, and a pause after a 25% drawdown from the bot's peak. Since
2026-11-06 (your rule): no "no rain" copy when v3 itself says rain 50% or more (SKIP_NO_FROM; fails closed).
Since 2026-11-07 (your rules): on real money the 25% drawdown ends the trial: real money locks again, and starting again
needs both your resume and your unlock (END_ON_DRAWDOWN). A 6-hour check (AGREE_6H) is built but off, by your choice.

Your key never goes in this folder: settings live in %USERPROFILE%\\.kalshi\\settings.json (or the KALSHI_ENV,
KALSHI_KEY_ID, KALSHI_KEY_FILE environment variables) and the key file must sit outside this folder. Nothing here prints,
copies or uploads the key. Kalshi's changelog (June 30, 2026) describes a write::trade key scope (orders, no transfers):
use it for the real account if offered; otherwise treat the key as full access to the account. Keep the file private. Python 3.8+, needs `cryptography` (pip install cryptography).
Revised 2026-10-14 after an independent code review (see CHANGELOG.md)."""
import os, sys, json, time, math, re, base64, sqlite3, io, contextlib, subprocess
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
import requests
HERE=os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path: sys.path.insert(0,HERE)
from config import DB, DAILY_LOSS_LIMIT, BLEND, MIN_EDGE   # BLEND and MIN_EDGE: the paper bot's own rule, for the 6-hour filter
import kalshi
from core import fee, killed   # Kalshi taker fee (rounded up to the cent); the kill switch (one rule for every file)
from strategy import STOP_DATE, started, close_time, payout, settled_pnl, STRATEGY_RAIN, VETO_MAX_GAP   # payout/settled_pnl: yes, no, scalar and void (2026-11-06); VETO_MAX_GAP: the bot's 30-point veto, for the 6-hour filter

BASES={"demo":"https://external-api.demo.kalshi.co/trade-api/v2",     # Kalshi demo exchange, fake money
       "prod":"https://api.elections.kalshi.com/trade-api/v2"}        # real exchange (the bot already reads prices here)
MAX_AT_RISK=50.0          # dollars at risk across the account at once. $25 by the user's decision of 2026-10-14; raised to $50
                          # on 2026-11-11 at his explicit instruction ("we need to use the $25 promotional credit given, so raise
                          # it to $50 for placing orders"). Only this cap moved: the loss stops below stay on his own $25.
STAKE=25.0                # the user's own money: the base of the daily loss stop, the bot's value and the doubling reminder
DAILY_STOP=DAILY_LOSS_LIMIT*STAKE   # $2.50 of settled losses in 24 hours stops new orders (unchanged)
DRAWDOWN_PAUSE=0.25       # pause after the bot's value falls 25% from its peak (CLAUDE.md 11a)
MIRROR_HOURS=12           # only paper trades opened in the last 12 hours are copied
# The user's rule of 2026-11-06 ("yes" to the no-rain filter, with real money from Nov 12): a NO ("no rain") paper trade
# is not copied when v3's own forecast for that market says rain is SKIP_NO_FROM or more likely. In the paper record
# those bets won 1 of 22 (a screen found after looking, not a tested edge). Paper keeps making them, so whether skipping
# was right stays measurable. It applies on every exchange, so the demo rehearses the real setup, and it only ever
# removes orders. It fails closed: a NO trade whose forecast cannot be read is not copied.
SKIP_NO_FROM=0.50
# The user's rules of 2026-11-07 ("implement your recommendations"), both live-only; paper, v3 and the gate are unchanged.
# AGREE_6H: a paper trade is copied only when v3's own 24 hourly chances, combined in 6-hour blocks (PLAN9's "v3-6h",
# research/PLAN9.md section 3), would have made the same bet by the paper bot's own rule (strategy.scan): blend 50/50
# with the mid, then 8+ points of edge on the same side against the price the paper trade paid, and v3-6h within the
# bot's 30-point veto of the mid (strategy.VETO_MAX_GAP; added after the review, it only removes orders). The inputs are those the
# trade was decided on (its decision row; without the decision ledger, the scan's log). v3-6h is never below v3, so it
# mostly removes "no rain" bets. It was picked after looking at the same days, so it is untested (PLAN9 tests v3-6h on
# new markets). It fails closed (unreadable inputs: no copy), applies on every exchange, and only ever removes orders.
# OFF since the user's answer of 2026-11-07 22:11, before it was deployed ("we don't need fewer bets... we need more
# successful winning bets"): it would have cut real bets to about 3 in 36. Built, reviewed and tested; switching it on
# needs his word.
AGREE_6H=False
# END_ON_DRAWDOWN: on real money, the first time the 25% drawdown pause is on (since the last resume), real money locks
# again exactly as `.\run live lock` does: the trial ends. Starting again needs both of the user's typed commands,
# resume and unlock (unchanged). It only ever locks; the demo exchange keeps the plain pause.
END_ON_DRAWDOWN=True
GIVE_UP=1800             # an order still not found on Kalshi after 30 minutes counts as never placed
UNLOCK_PHRASE="UNLOCK REAL MONEY"
def _abs(p): return p if os.path.isabs(p) else os.path.join(HERE,p)   # paths never depend on the current folder
PAPER=_abs(DB)
LIVE_DB=_abs(os.getenv("LIVE_DB") or os.path.join(os.path.dirname(PAPER),"live.db"))
KDIR=os.getenv("TRADEBOT_KALSHI_DIR",os.path.join(os.path.expanduser("~"),".kalshi"))
SETTINGS=os.path.join(KDIR,"settings.json")
HTTP=requests             # tests replace this with a fake exchange
def today(): return date.today()
def now(): return time.time()
def interactive(): return sys.stdin.isatty() and sys.stdout.isatty()
def windows(): return os.name=="nt"
def open_setup_window():
    """Setup asks questions, which PowerShell ISE (and scripts) cannot answer. On Windows, open a normal console window
    that runs setup, so the user can type there. Only setup does this; unlock and resume never open windows by themselves."""
    subprocess.Popen([sys.executable,os.path.join(HERE,"live.py"),"setup","--window"],cwd=HERE,
                     creationflags=getattr(subprocess,"CREATE_NEW_CONSOLE",0x10))
    print("A new black window opened for Kalshi setup. Type your answers there (it may be behind this one).")
def need_terminal(cmd,what):
    """PowerShell ISE, Claude and other scripts cannot answer typed questions; say exactly what to do instead."""
    sys.exit("%s must be typed by you in a normal PowerShell window. PowerShell ISE and scripts can't answer its questions.\n"
             "Open Start, type PowerShell, choose \"Windows PowerShell\" (not ISE), then run:\n  cd \"%s\"\n  .\\run live %s"%(what,HERE,cmd))
def safe(x): return str(x).encode("ascii","replace").decode("ascii")   # Kalshi's text, printable on any Windows console

class ExchangeError(Exception): pass
class Unknown(Exception): pass    # the request may or may not have reached Kalshi

# ---------- settings and key ----------
def read_settings():
    if not os.path.exists(SETTINGS): return {}
    with open(SETTINGS,encoding="utf-8") as f: return json.load(f)
def load_settings():
    s=read_settings()
    env=(os.getenv("KALSHI_ENV") or s.get("env") or "demo").lower()
    if env not in BASES: raise SystemExit("Unknown exchange %r (use demo or prod)."%env)
    k=dict((s.get("keys") or {}).get(env) or {})
    if os.getenv("KALSHI_KEY_ID"): k["key_id"]=os.getenv("KALSHI_KEY_ID")
    if os.getenv("KALSHI_KEY_FILE"): k["key_file"]=os.getenv("KALSHI_KEY_FILE")
    return s,env,k
def save_settings(s):
    os.makedirs(KDIR,exist_ok=True); tmp=SETTINGS+".tmp"
    with open(tmp,"w",encoding="utf-8") as f: json.dump(s,f,indent=1)
    os.replace(tmp,SETTINGS)
def inside_project(path):
    a,b=os.path.normcase(os.path.realpath(path)),os.path.normcase(os.path.realpath(HERE))
    try: return os.path.commonpath([a,b])==b
    except ValueError: return False   # different drives
def load_key(path):
    """Messages never include the path or the file's contents (scan output may be summarised elsewhere)."""
    if not path or not os.path.isfile(path): raise ExchangeError("the key file was not found (see .\\run live status)")
    if inside_project(path): raise ExchangeError("the key file is inside the project folder; move it to %USERPROFILE%\\.kalshi and run setup again")
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa, ed25519
    except ImportError: raise ExchangeError("the cryptography package is missing: %USERPROFILE%\\Python313\\python.exe -m pip install cryptography")
    with open(path,"rb") as f: data=f.read()
    data=data.lstrip(b"\xef\xbb\xbf").strip()+b"\n"
    try: k=serialization.load_pem_private_key(data,password=None)
    except Exception: raise ExchangeError("the key file is not a Kalshi private key (it should start with -----BEGIN ... PRIVATE KEY-----)")
    if not isinstance(k,(rsa.RSAPrivateKey,ed25519.Ed25519PrivateKey)): raise ExchangeError("unsupported key type (Kalshi keys are Ed25519 or RSA)")
    return k
def sign(key,msg):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, ed25519
    if isinstance(key,ed25519.Ed25519PrivateKey): sig=key.sign(msg)
    else: sig=key.sign(msg,padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=padding.PSS.DIGEST_LENGTH),hashes.SHA256())
    return base64.b64encode(sig).decode("ascii")
def valid_key_id(s): return bool(re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",s or ""))   # Kalshi Key IDs are UUIDs
def drain():
    """Throw away anything still waiting in the console (the rest of a pasted key), so it is never run or saved by
    PowerShell after setup exits. Windows only; elsewhere it does nothing."""
    try:
        import msvcrt
        time.sleep(0.5)
        while msvcrt.kbhit(): msvcrt.getwch()
    except Exception: pass
def looks_like_key_text(s):
    """True when the input is (part of) a pasted key rather than a file location. Never echo such input."""
    s=s or ""; u=s.upper()
    if "BEGIN" in u or "PRIVATE" in u or "-----" in s or len(s)>300: return True
    return len(s)>=24 and re.fullmatch(r"[A-Za-z0-9+/=]+",s) is not None and "\\" not in s and "/" not in s[:3]

# ---------- exchange client ----------
class Client:
    def __init__(self,env,key_id,key):
        self.env,self.base,self.key_id,self.key=env,BASES[env],key_id,key
    def call(self,method,ep,params=None,body=None,auth=True):
        url=self.base+ep; h=dict(kalshi.UA)
        if auth:
            ts=str(int(now()*1000))
            h.update({"KALSHI-ACCESS-KEY":self.key_id,"KALSHI-ACCESS-TIMESTAMP":ts,
                      "KALSHI-ACCESS-SIGNATURE":sign(self.key,(ts+method+urlparse(url).path).encode("ascii"))})
        if body is not None: h["Content-Type"]="application/json"
        try: r=HTTP.request(method,url,headers=h,params=params,json=body,timeout=20)
        except Exception as e:
            if method=="GET": raise ExchangeError("Kalshi did not answer (%s)"%type(e).__name__)
            raise Unknown("no answer from Kalshi (%s)"%type(e).__name__)
        if r.status_code>=500 and method!="GET": raise Unknown("Kalshi error %d"%r.status_code)
        if r.status_code>=400:
            try: msg=json.dumps(r.json())[:300]
            except Exception: msg=(r.text or "")[:300]
            raise ExchangeError("Kalshi refused %s %s: HTTP %d %s"%(method,ep,r.status_code,safe(msg)))
        try: return r.json()
        except Exception:
            if method=="GET": raise ExchangeError("Kalshi sent an unreadable answer")
            raise Unknown("unreadable answer from Kalshi")
    def get(self,ep,params=None,auth=True): return self.call("GET",ep,params=params,auth=auth)
def client():
    s,env,k=load_settings()
    if not ready(k): return None,env
    return Client(env,k["key_id"],load_key(k["key_file"])),env
def ready(k): return bool(k.get("key_id") and k.get("key_file"))

def _has(o,k): return o.get(k+"_dollars") not in (None,"") or o.get(k) not in (None,"")
def _usd(o,k):
    v=o.get(k+"_dollars")
    if v not in (None,""): return float(v)
    v=o.get(k)
    return 0.0 if v in (None,"") else float(v)/100
def _need(o,k,what):
    """Like _usd, but a missing field stops the run (fail closed: never read a missing exposure or balance as $0)."""
    if not _has(o,k): raise ExchangeError("Kalshi's %s data has no %s field (the API may have changed)"%(what,k))
    return _usd(o,k)
def _count(o,k):
    v=o.get(k)
    if v in (None,""): v=o.get(k+"_fp")
    return 0 if v in (None,"") else int(round(float(v)))
def _has_count(o,k): return o.get(k) not in (None,"") or o.get(k+"_fp") not in (None,"")
def _qty(o,k):
    """Contract counts can be fractional fixed-point strings ("3.00", "1.37"), so keep them as numbers, not whole ints."""
    v=o.get(k)
    if v in (None,""): v=o.get(k+"_fp")
    return 0.0 if v in (None,"") else float(v)
def balance(cl): return _need(cl.get("/portfolio/balance"),"balance","balance")
def at_risk(cl):
    """Dollars at risk on the whole account: Kalshi's market exposure for every unsettled position plus what any resting
    order could cost (the bot never leaves one, but the user might), counting sells as able to open the other side."""
    tot,cur=0.0,None
    for _ in range(20):
        p={"limit":1000,"settlement_status":"unsettled"}
        if cur: p["cursor"]=cur
        j=cl.get("/portfolio/positions",p)
        if "market_positions" not in j: raise ExchangeError("Kalshi's positions answer has no market_positions")
        for m in j["market_positions"] or []: tot+=abs(_need(m,"market_exposure","position"))
        cur=j.get("cursor")
        if not cur: break
    else: raise ExchangeError("too many pages of positions")
    cur=None
    for _ in range(20):
        p={"status":"resting","limit":1000}
        if cur: p["cursor"]=cur
        j=cl.get("/portfolio/orders",p)
        for o in j.get("orders") or []:
            if not _has_count(o,"remaining_count"): raise ExchangeError("Kalshi's resting order has no remaining_count")
            rem=_qty(o,"remaining_count"); sd=o.get("side")
            if sd in ("bid","ask"):   # V2 shape: a YES price; an ask (sell YES) can open NO at 1 - price
                p=_need(o,"price","resting order"); tot+=rem*(p if sd=="bid" else 1-p)
            else:                     # older shape: side yes/no with action buy/sell; a sell can open the other side
                p=_need(o,"yes_price" if sd=="yes" else "no_price","resting order"); tot+=rem*(1-p if o.get("action")=="sell" else p)
        cur=j.get("cursor")
        if not cur: break
    else: raise ExchangeError("too many pages of orders")
    return tot
def market(cl,t):
    try: return cl.get("/markets/"+t,auth=False).get("market") or {}
    except ExchangeError as e:
        if "HTTP 404" in str(e): return None
        raise
def bot_orders(cl,t,since=None):
    p={"ticker":t,"limit":1000}
    if since: p["min_ts"]=int(since)
    return [o for o in cl.get("/portfolio/orders",p).get("orders") or [] if str(o.get("client_order_id") or "").startswith("tb-")]
def holding(cl,t,settled="all"):
    """Kalshi's position in one market, or None. Fails closed: an answer without the expected fields stops the run,
    because a NO copy is a YES sell, and this check is what keeps it from selling YES the account already holds."""
    j=cl.get("/portfolio/positions",{"ticker":t,"limit":100,"settlement_status":settled})
    if not isinstance(j,dict) or "market_positions" not in j: raise ExchangeError("Kalshi's positions answer has no market_positions")
    for m in j["market_positions"] or []:
        if "ticker" not in m or not (_has_count(m,"position") or _has(m,"market_exposure")):
            raise ExchangeError("Kalshi's position data is missing the ticker or position fields (the API may have changed)")
        if m["ticker"]==t and (abs(_qty(m,"position"))>0 or abs(_usd(m,"market_exposure"))>0): return m
    return None
def already_on_kalshi(cl,t):
    """One bot order per market, checked on Kalshi itself, so a lost or restored live.db cannot cause a second order."""
    if bot_orders(cl,t): return "Kalshi already has a bot order on this market"
    if holding(cl,t): return "the account already holds this market"
    return None

# ---------- ledger (live.db; never paper.db) ----------
def ldb():
    c=sqlite3.connect(LIVE_DB)
    c.execute("""create table if not exists orders(id integer primary key,ts real,env text,paper_id integer,ticker text,side text,
        count integer,limit_cents integer,client_order_id text unique,order_id text,status text,fill_count integer default 0,
        cost real default 0,fees real default 0,note text,result text,pnl real,settled_ts real)""")
    c.execute("create unique index if not exists one_per_paper on orders(env,paper_id) where paper_id is not null")
    c.execute("create table if not exists events(id integer primary key,ts real,env text,kind text,detail text)")
    c.commit(); return c
def event(c,env,kind,detail=""):
    t=now(); c.execute("insert into events(ts,env,kind,detail) values(?,?,?,?)",(t,env,kind,detail)); c.commit(); return t
def last_event(c,env,kinds):
    return c.execute("select ts,kind,detail from events where env=? and kind in (%s) order by id desc limit 1"%",".join("?"*len(kinds)),(env,)+tuple(kinds)).fetchone()
def unlocked(c,s=None):
    """The real-money unlock counts only if live.db's latest unlock/lock event is an unlock AND the settings file records
    the same unlock (lock clears it), so restoring an old live.db cannot bring back an unlock that was later locked."""
    e=last_event(c,"prod",("unlock","lock"))
    if not e or e[1]!="unlock": return None
    mark=(read_settings() if s is None else s).get("prod_unlock")
    return e if mark is not None and abs(float(mark)-e[0])<1 else None
def local_at_risk(c,env):
    a=c.execute("select coalesce(sum(cost+fees),0) from orders where env=? and fill_count>0 and result is null",(env,)).fetchone()[0]
    for n,lc in c.execute("select count,limit_cents from orders where env=? and status in ('sending','unknown')",(env,)).fetchall():
        a+=n*lc/100+fee(lc/100,n)
    return a
def day_pnl(c,env):
    return c.execute("select coalesce(sum(pnl),0) from orders where env=? and settled_ts>=?",(env,now()-86400)).fetchone()[0]
def value_track(c,env):
    """The bot's value on this exchange = $25 + net profit of settled orders. Returns (value, peak since the last
    resume, paused). Paused when value < 75% of that peak (CLAUDE.md 11a)."""
    r=last_event(c,env,("resume",)); since=r[0] if r else 0
    cum,peak=0.0,None
    for ts,p in c.execute("select settled_ts,pnl from orders where env=? and settled_ts is not null order by settled_ts,id",(env,)).fetchall():
        if ts>=since and peak is None: peak=STAKE+cum
        cum+=p or 0
        if ts>=since: peak=max(peak,STAKE+cum)
    if peak is None: peak=STAKE+cum if since else max(STAKE,STAKE+cum)
    v=STAKE+cum; return v,peak,v<(1-DRAWDOWN_PAUSE)*peak

# ---------- locks ----------
def lock_reason(c,env,s=None):
    if killed(): return "KILL file present"
    if env=="prod":
        if today()<STOP_DATE: return "real money is locked until %s (then your call: .\\run live unlock)"%STOP_DATE
        if END_ON_DRAWDOWN and trial_ended(c):   # review 2026-11-07: the pause can lift by itself when open bets settle as wins
            return "the real-money trial ended at the 25% drawdown (your rule of 2026-11-07): type .\\run live resume and .\\run live unlock yourself to start again"
        if not unlocked(c,s): return "real money is locked: run .\\run live unlock yourself (it shows the gate verdict first)"
    return None
def stops(c,env):
    m=last_event(c,env,("mismatch","reconciled","resume"))
    if m and m[1]=="mismatch": return "position mismatch (%s); check on Kalshi. The next sync clears it if they agree, or type .\\run live resume"%m[2]
    if day_pnl(c,env)<=-DAILY_STOP+1e-9: return "daily loss stop: settled losses in the last 24 hours reached $%.2f"%DAILY_STOP
    v,p,paused=value_track(c,env)
    if paused:
        if env=="prod" and END_ON_DRAWDOWN:
            return "drawdown pause: the bot's value $%.2f is more than 25%% below its peak $%.2f. Your rule of 2026-11-07: this ends the real-money trial; starting again needs .\\run live resume and .\\run live unlock, both typed by you"%(v,p)
        return "drawdown pause: the bot's value $%.2f is more than 25%% below its peak $%.2f (review, then .\\run live resume)"%(v,p)
    return None
def trial_ended(c):
    """The real-money trial's end (live.db's trial_end event since the last prod resume), or None."""
    e=last_event(c,"prod",("resume","trial_end"))
    return e if e and e[1]=="trial_end" else None
def end_trial(c,env):
    """END_ON_DRAWDOWN: lock real money the first time the drawdown pause is on (once per pause, until the next resume),
    as `.\\run live lock` does. The settings mark and live.db's lock event are two separate tries, because either one
    alone locks (review 2026-11-07); trial_end is written with the lock event, and while it stands lock_reason() keeps
    real money locked until a resume, even if the pause lifts by itself. Returns a line to print, or None. While neither
    could be written, the drawdown pause still stops every order and the next run tries again."""
    if env!="prod" or not END_ON_DRAWDOWN: return None
    v,p,paused=value_track(c,env)
    if not paused or trial_ended(c): return None
    done,failed=[],[]
    try:
        if os.path.exists(SETTINGS): s=read_settings(); s["prod_unlock"]=None; save_settings(s)
        done.append("settings file")
    except (OSError,ValueError) as e: failed.append("settings file (%s)"%type(e).__name__)
    try: event(c,"prod","lock","drawdown: the real-money trial ended (your rule of 2026-11-07)"); done.append("live.db")
    except sqlite3.Error as e: failed.append("live.db lock (%s)"%type(e).__name__)
    else:
        try: event(c,"prod","trial_end","value $%.2f, peak $%.2f"%(v,p))
        except sqlite3.Error as e: failed.append("live.db trial_end record (%s; the next run tries again)"%type(e).__name__)
    if not done:
        return "WARNING: could not lock real money after the drawdown (%s); the drawdown pause still stops every order, and the next run tries again"%"; ".join(failed)
    note=""
    if failed:
        note="; could not write the %s, the other lock holds"%", ".join(failed)
        if "settings file" not in done: note+="; run .\\run live lock to clear the settings file's unlock too"
    return ("REAL-MONEY TRIAL ENDED: the bot's value $%.2f is more than 25%% below its peak $%.2f, so real money is locked again "
            "(your rule of 2026-11-07%s). Paper and the forward tests go on. Starting again needs .\\run live resume and .\\run live unlock, both typed by you."
            %(v,p,note))
def end_trial_line(c,env):
    try: return end_trial(c,env)
    except (OSError,ValueError,sqlite3.Error) as e:   # reading live.db failed: the pause (or the read error) still stops orders
        return "WARNING: could not check the end rule (%s)"%type(e).__name__

# ---------- orders ----------
def paper_ro():
    if not os.path.exists(PAPER): return None
    return sqlite3.connect(Path(PAPER).resolve().as_uri()+"?mode=ro",uri=True)
def paper_trade(pid):
    p=paper_ro()
    if p is None: return None
    try: return p.execute("select id,ts,ticker,side,price,n,version,status from trades where id=?",(pid,)).fetchone()
    finally: p.close()
def v3_forecast(t,paper_id=None):
    """v3's own rain chance for market t, read-only from paper.db, or None when it cannot be read.
    For a paper trade, the forecast it was decided on: the decision ledger's row for it, written in the same savepoint
    as the trade. While that ledger exists, a missing row or an empty value counts as unreadable (fail closed); the scan's
    log (obs) is used only without the ledger or without a paper trade, because obs keeps the first snapshot of each
    market, which can be from an earlier scan than the trade (review 2026-11-06)."""
    p=paper_ro()
    if p is None: return None
    try:
        if paper_id is not None and p.execute("select 1 from sqlite_master where type='table' and name='decisions'").fetchone():
            r=p.execute("select p_model from decisions where trade_ref=? and strategy_id=? order by ts desc limit 1",
                        ("trades:%d"%paper_id,STRATEGY_RAIN)).fetchone()
        else:
            r=p.execute("select fc from obs where ticker=? and version='v3'",(t,)).fetchone()
        fc=float(r[0]) if r and r[0] is not None else None
        return fc if fc is not None and 0.0<=fc<=1.0 else None   # NaN or out of range: unreadable
    except (sqlite3.Error,TypeError,ValueError): return None
    finally: p.close()
def _num(x,lo,hi):
    """x as a float when it is a real number from lo to hi (not a bool, NaN or infinity), else None."""
    if isinstance(x,bool) or not isinstance(x,(int,float)): return None
    try: x=float(x)
    except OverflowError: return None   # an integer too large for a float (review 2026-11-07)
    return x if lo<=x<=hi else None
def six_hour(slices):
    """PLAN9's v3-6h (research/PLAN9.md section 3) from v3's 24 hourly chances in percent (a list or its JSON text):
    1 - (1 - b1)(1 - b2)(1 - b3)(1 - b4), b = the highest chance in hours 0-5, 6-11, 12-17 and 18-23, clipped to
    [0.01, 0.99] like v3. None unless there are exactly 24 numbers from 0 to 100."""
    try: v=json.loads(slices) if isinstance(slices,str) else slices
    except ValueError: return None
    if not isinstance(v,list) or len(v)!=24: return None
    h=[_num(x,0.0,100.0) for x in v]
    if any(x is None for x in h): return None
    q=1.0
    for i in range(0,24,6): q*=1.0-max(h[i:i+6])/100.0
    return min(max(1.0-q,0.01),0.99)
def trade_inputs(t,side,paper_id):
    """(mid, price paid, v3's 24 hourly chances) that paper trade paper_id was decided on, read-only from paper.db, or
    None when they cannot be read. While the decision ledger exists, only the trade's own decision row counts (written in
    the same savepoint as the trade; it must name this market and side). Without the ledger, the scan's log (obs) gives
    the mid and the chances and the paper trade its price, as v3_forecast() does."""
    if paper_id is None: return None
    p=paper_ro()
    if p is None: return None
    try:
        if p.execute("select 1 from sqlite_master where type='table' and name='decisions'").fetchone():
            r=p.execute("select ticker,side,mid,price,inputs from decisions where trade_ref=? and strategy_id=? order by ts desc limit 1",
                        ("trades:%d"%paper_id,STRATEGY_RAIN)).fetchone()
            if not r or r[0]!=t or r[1]!=side: return None
            mid,price=r[2],r[3]
            inp=json.loads(r[4]) if isinstance(r[4],str) else None
            sl=inp.get("slices") if isinstance(inp,dict) else None
        else:
            o=p.execute("select mid,slices from obs where ticker=? and version='v3'",(t,)).fetchone()
            pt=p.execute("select ticker,side,price from trades where id=?",(paper_id,)).fetchone()
            if not o or not pt or pt[0]!=t or pt[1]!=side: return None
            mid,sl,price=o[0],o[1],pt[2]
        mid,price=_num(mid,0.0,1.0),_num(price,0.0,1.0)
        if mid is None or price is None or sl is None: return None
        return mid,price,sl
    except (sqlite3.Error,TypeError,ValueError,AttributeError): return None
    finally: p.close()
def agree_reason(t,side,paper_id):
    """Why the 6-hour filter (AGREE_6H) keeps this copy from being placed, or None to go ahead."""
    x=trade_inputs(t,side,paper_id) if side in ("yes","no") else None
    if x is None: return "6-hour filter: the inputs this trade was decided on could not be read (not copied, to be safe)"
    mid,price,sl=x; p6=six_hour(sl)
    if p6 is None: return "6-hour filter: v3's hourly chances for this market could not be read (not copied, to be safe)"
    fair=BLEND*p6+(1-BLEND)*mid
    q=fair if side=="yes" else 1-fair
    if q-price<MIN_EDGE:   # the paper bot's own tests (strategy.scan), with v3-6h in place of v3
        return "6-hour filter: v3's hours in 6-hour blocks say rain %d%%, an edge of %+.1f points on %s at %dc, not the %d needed (your rule of 2026-11-07)"%(
            round(p6*100),(q-price)*100,side.upper(),round(price*100),round(MIN_EDGE*100))
    if abs(p6-mid)>VETO_MAX_GAP+1e-9:
        return "6-hour filter: v3's hours in 6-hour blocks say rain %d%%, more than %d points from the market's %d%% (the bot's veto; your rule of 2026-11-07)"%(
            round(p6*100),round(VETO_MAX_GAP*100),round(mid*100))
    return None
def filter_reason(t,side,paper_id=None):
    """Why one of the user's filters keeps this copy from being placed, or None to go ahead: the no-rain filter
    (SKIP_NO_FROM, 2026-11-06), then the 6-hour filter (AGREE_6H, 2026-11-07)."""
    if side=="no":
        fc=v3_forecast(t,paper_id)
        if fc is None: return "no-rain filter: v3's forecast for this market could not be read (not copied, to be safe)"
        if fc>=SKIP_NO_FROM-1e-12:
            return "no-rain filter: v3 itself says rain %d%% (your rule of 2026-11-06: no 'no rain' copies from %d%%)"%(round(fc*100),round(SKIP_NO_FROM*100))
    if not AGREE_6H: return None
    try: return agree_reason(t,side,paper_id)
    except Exception as e:   # anything unexpected in the stored inputs: fail closed, and never stop the other copies
        return "6-hour filter: could not be checked (%s); not copied, to be safe"%type(e).__name__
def cents_for(price): return int(math.floor(price*100+1e-6))   # never above the paper price (0.427 -> 42c)
def record(c,row_id,o,note=None,v2=False):
    """Store Kalshi's answer and return the money used (cost + fees, never less than fills x limit price + fee formula,
    so a missing or odd price cannot hide money from the cap). v2=True only for the V2 create-order answer, whose
    average_fill_price is a YES price (verified on demo 2026-10-14: a NO buy is a YES sell, so its cost is 1 - price).
    For orders found later through GET /portfolio/orders, whose price fields have not been verified for V2 orders, the
    cost and fee are estimated at the limit (an upper bound). Prices above the limit are not believed."""
    side,lc,n=c.execute("select side,limit_cents,count from orders where id=?",(row_id,)).fetchone()
    f=_qty(o,"fill_count"); notes=[note] if note else []
    avg,fa=o.get("average_fill_price"),o.get("average_fee_paid")
    est_fee=fee(lc/100,int(math.ceil(f-1e-9))) if f else 0.0
    if not f: cost=fees=0.0
    else:
        if v2 and avg not in (None,""): px=float(avg); cost=f*(px if side=="yes" else 1-px)
        else: cost=f*lc/100; notes.append("cost estimated at the limit price")
        if cost/f>lc/100+0.005 or cost<0: cost=f*lc/100; notes.append("Kalshi's average price did not fit the limit; cost recorded at the limit")
        if v2 and fa not in (None,""): fees=max(0.0,f*float(fa))
        else: fees=est_fee; notes.append("fee estimated")
    status=o.get("status") or ("executed" if f>=n-1e-9 else ("partial" if f>0 else "canceled"))
    extra="; ".join(notes) or None
    c.execute("update orders set order_id=?,status=?,fill_count=?,cost=?,fees=?,note=case when ? is null then note else coalesce(note||'; ','')||? end where id=?",
              (o.get("order_id"),status,f,round(cost,4),round(fees,4),extra,extra,row_id))
    c.commit(); return round(max(cost+fees,f*lc/100+est_fee),4)
def place(cl,c,env,paper_id,t,side,n,cents,note):
    """Check every invariant again, write the row (status 'sending'), then send one immediate-or-cancel buy.
    A row is never sent twice. Returns the order, or None if nothing was placed or the outcome is unknown."""
    s,cur_env,_=load_settings()
    if env!=cur_env or cl.env!=env: raise ExchangeError("exchange mismatch")
    why=lock_reason(c,env,s)
    if why: raise ExchangeError("locked: "+why)
    if side not in ("yes","no") or not isinstance(n,int) or n<1 or not isinstance(cents,int) or not 1<=cents<=99: raise ExchangeError("bad order")
    if paper_id is None:
        if env!="demo" or n!=1: raise ExchangeError("only the 1-contract demo test may be placed without a paper trade")
        coid="tb-%s-x-%d"%(env,int(now()*1000))
    else:
        pt=paper_trade(paper_id)
        if not pt or pt[2]!=t or pt[3]!=side or pt[6]!="v3" or pt[7]!="open" or not t.startswith("KXRAIN") or n>pt[5] or cents/100>pt[4]+1e-9:
            raise ExchangeError("order does not match paper trade %s"%paper_id)
        f=filter_reason(t,side,paper_id)   # checked again here, so no caller can skip it
        if f: raise ExchangeError("order blocked: "+f)
        coid="tb-%s-%d-%d"%(env,paper_id,int(pt[1]))   # the same every time for this paper trade
    cur=c.execute("insert into orders(ts,env,paper_id,ticker,side,count,limit_cents,client_order_id,status,note) values(?,?,?,?,?,?,?,?,?,?)",
                  (now(),env,paper_id,t,side,n,cents,coid,"sending",note)); c.commit(); rid=cur.lastrowid
    # Kalshi's V2 order endpoint (the old POST /portfolio/orders answers HTTP 410 since 2026). Prices are YES prices:
    # buying YES at p is a bid at p; buying NO at p is an ask (sell YES) at 1 - p, which opens a NO position.
    body={"ticker":t,"side":"bid" if side=="yes" else "ask","count":"%d.00"%n,
          "price":"%.4f"%((cents if side=="yes" else 100-cents)/100),
          "time_in_force":"immediate_or_cancel","self_trade_prevention_type":"taker_at_cross","client_order_id":coid}
    try:
        j=cl.call("POST","/portfolio/events/orders",body=body)
        if not isinstance(j,dict): raise Unknown("Kalshi's answer was not an order")
        o=j.get("order") if isinstance(j.get("order"),dict) else j
    except Unknown as e:
        c.execute("update orders set status='unknown',note=? where id=?",("%s; %s"%(note,e),rid)); c.commit()
        print("  ORDER OUTCOME UNKNOWN %s: %s (sync will look it up; no new orders until then)"%(t,e)); return None
    except ExchangeError as e:
        c.execute("update orders set status='rejected',note=? where id=?",("%s; %s"%(note,e),rid)); c.commit()
        print("  REJECTED %s: %s"%(t,e)); return None
    if not o.get("order_id") or not _has_count(o,"fill_count"):
        c.execute("update orders set status='unknown',note=? where id=?",("%s; Kalshi's answer had no order id or fill count"%note,rid)); c.commit()
        print("  ORDER OUTCOME UNKNOWN %s: Kalshi's answer was incomplete (sync will look it up; no new orders until then)"%t); return None
    o=dict(o); o["_spent"]=record(c,rid,o,v2=True)
    st,fc,cost,fees=c.execute("select status,fill_count,cost,fees from orders where id=?",(rid,)).fetchone()
    print("  %s ORDER %s buy %s x%d limit %dc: %s, filled %g, cost $%.2f, fees $%.2f"%(env.upper(),t,side.upper(),n,cents,st,fc,cost,fees))
    return o
def resolve_unknown(cl,c,env):
    """Look up orders whose outcome is unknown by their client order id. Returns how many stay unknown."""
    left=0
    for rid,t,ts,coid,lc in c.execute("select id,ticker,ts,client_order_id,limit_cents from orders where env=? and status in ('sending','unknown')",(env,)).fetchall():
        try: hit=[o for o in bot_orders(cl,t,ts-3600) if o.get("client_order_id")==coid]
        except ExchangeError as e: print("  could not look up %s: %s"%(coid,e)); left+=1; continue
        if hit and not _has_count(hit[0],"fill_count"): print("  found %s, but Kalshi's answer has no fill count; still unknown"%coid); left+=1; continue
        if hit: record(c,rid,hit[0],"found by sync"); print("  found %s: %s, filled %g"%(coid,safe(hit[0].get("status")),_qty(hit[0],"fill_count"))); continue
        if now()-ts<=GIVE_UP: left+=1; continue
        try: pos=holding(cl,t)
        except ExchangeError as e: print("  could not check positions for %s: %s"%(t,e)); left+=1; continue
        other=c.execute("select 1 from orders where env=? and ticker=? and id<>? and fill_count>0",(env,t,rid)).fetchone()
        if pos and not other:
            n=abs(_qty(pos,"position")); cost=abs(_usd(pos,"market_exposure")) if _has(pos,"market_exposure") else n*lc/100
            c.execute("update orders set status='filled (from position)',fill_count=?,cost=?,fees=?,note=coalesce(note,'')||'; order not listed by Kalshi, position found (fee estimated)' where id=?",
                      (n,round(cost,4),fee(lc/100,int(math.ceil(n-1e-9))) if n else 0,rid)); c.commit(); print("  %s: not listed, but Kalshi shows a position; recorded from the position"%coid)
        else:
            c.execute("update orders set status='not placed',note=coalesce(note,'')||'; not on Kalshi after 30 minutes' where id=?",(rid,)); c.commit(); print("  %s was never placed"%coid)
    return left

# ---------- commands ----------
def candidates(since):
    p=paper_ro()
    if p is None: return []
    try: return p.execute("select id,ts,ticker,side,price,n from trades where status='open' and version='v3' and ticker like 'KXRAIN%' and ts>=? and ts>=? order by id",
                          (since,now()-MIRROR_HOURS*3600)).fetchall()
    finally: p.close()
def mirror():
    s,env,k=load_settings()
    if not ready(k): return print("live: no Kalshi account set up (paper only)")
    c=ldb(); msg=end_trial_line(c,env)   # END_ON_DRAWDOWN (2026-11-07): before the lock check, so a drawdown locks first
    if msg: print("live (%s): %s"%(env,msg)); s=read_settings()
    why=lock_reason(c,env,s)
    if why: return print("live (%s): no orders: %s"%(env,why))
    cl,_=client()
    since=float((s.get("mirror_from") or {}).get(env) or 0)   # plus the 12-hour window in candidates()
    if env=="prod": since=max(since,unlocked(c,s)[0])
    left=resolve_unknown(cl,c,env)
    if left: return print("live (%s): no orders: %d earlier order(s) have an unknown outcome; run .\\run live sync"%(env,left))
    why=stops(c,env)
    if why: return print("live (%s): no orders: %s"%(env,why))
    todo=[r for r in candidates(since) if not c.execute("select 1 from orders where env=? and paper_id=?",(env,r[0])).fetchone()]
    if not todo: return print("live (%s): no new paper rain trades to copy"%env)
    try: cash,risk=balance(cl),max(at_risk(cl),local_at_risk(c,env))
    except ExchangeError as e: return print("live (%s): no orders: could not read the account (%s)"%(env,e))
    print("live (%s): cash $%.2f, at risk $%.2f of $%.2f"%(env,cash,risk,MAX_AT_RISK))
    for pid,ts,t,side,price,n in todo:
        cents=cents_for(price)
        def skip(why):
            c.execute("insert into orders(ts,env,paper_id,ticker,side,count,limit_cents,status,note) values(?,?,?,?,?,?,?,?,?)",(now(),env,pid,t,side,n,cents,"skipped",why)); c.commit()
            print("  skipped %s: %s"%(t,why))
        if killed(): return print("  KILL file appeared: stopping")
        if not 1<=cents<=99 or cents/100>price+1e-9 or side not in ("yes","no") or n<1: skip("bad paper row"); continue
        f=filter_reason(t,side,pid)
        if f: skip(f); continue
        try: m=market(cl,t)
        except ExchangeError as e: skip("could not read the market (%s)"%e); continue
        if not m: skip("not listed on this exchange"); continue
        if close_time(m) is None or started(m): skip("the market's day has begun"); continue
        if m.get("status") not in ("active","open"): skip("market status %s"%safe(m.get("status"))); continue
        bid,ask=kalshi.quote(m)
        live_ask=ask if side=="yes" else (None if bid is None else 1-bid)
        if live_ask is None or not 0<live_ask<1: skip("no price to buy at"); continue
        if live_ask>cents/100+1e-9: skip("price moved: %s now %dc, paper paid %dc"%(side.upper(),round(live_ask*100),cents)); continue
        try: dup=already_on_kalshi(cl,t)
        except ExchangeError as e: skip("could not check Kalshi for an earlier order (%s)"%e); continue
        if dup: skip(dup); continue
        p=cents/100; room=min(MAX_AT_RISK-risk,cash); k_=n
        while k_>=1 and k_*p+fee(p,k_)>room+1e-9: k_-=1
        if k_<1: skip("no room: $%.2f at risk of $%.2f, cash $%.2f"%(risk,MAX_AT_RISK,cash)); continue
        try: o=place(cl,c,env,pid,t,side,k_,cents,"copy of paper trade %d"%pid+("" if k_==n else " (cut from %d by the $%.0f cap or cash)"%(n,MAX_AT_RISK)))
        except ExchangeError as e: skip(str(e)); continue
        if o is None:
            if c.execute("select status from orders where env=? and paper_id=?",(env,pid)).fetchone()[0]=="unknown": return
            continue
        x=o["_spent"]; risk+=x; cash-=x
def reconcile(cl,c,env,tickers):
    """For open markets, Kalshi's position (YES positive, NO negative) must equal the ledger's fills. A difference means a
    fill the ledger missed (or a manual trade on the same market), so new orders stop until a later sync finds them
    equal again, or the user types resume after checking."""
    bad=[]
    for t in sorted(tickers):
        exp=c.execute("select coalesce(sum(case when side='yes' then fill_count else -fill_count end),0) from orders where env=? and ticker=? and fill_count>0 and result is null",(env,t)).fetchone()[0]
        try: pos=holding(cl,t,"unsettled")
        except ExchangeError as e: print("  could not check the position for %s: %s"%(t,e)); continue
        q=_qty(pos,"position") if pos else 0.0
        if abs(q-exp)>0.005: bad.append("%s: Kalshi %g, ledger %g"%(t,q,exp))
    if bad:
        event(c,env,"mismatch","; ".join(bad)); print("  WARNING position mismatch (no new orders until it clears): "+"; ".join(bad))
    elif tickers and (last_event(c,env,("mismatch","reconciled","resume")) or (0,""))[1]=="mismatch":
        event(c,env,"reconciled"); print("  positions agree with the ledger again")
def sync():
    s,env,k=load_settings()
    if not ready(k): return print("live: no Kalshi account set up (paper only)")
    c=ldb(); cl,_=client(); resolve_unknown(cl,c,env); n=0; still_open=set()
    for rid,t,side,fc,cost,fees in c.execute("select id,ticker,side,fill_count,cost,fees from orders where env=? and fill_count>0 and result is null",(env,)).fetchall():
        try: m=market(cl,t) or {}
        except ExchangeError as e: print("  could not read %s: %s"%(t,e)); continue
        o=payout(m,side)   # until 2026-11-06 only yes/no: a scalar or void order stayed open, so its loss never reached the stops
        if o:
            r=o[0]; pnl=round(settled_pnl(r,side,fc,cost,fees,o[1]),4)
            c.execute("update orders set result=?,pnl=?,settled_ts=? where id=?",(r,pnl,now(),rid)); n+=1
            print("  settled %s: %s, %s%.2f"%(t,r,"+$" if pnl>=0 else "-$",abs(pnl)))
        elif m.get("result") or str(m.get("status") or "").lower() in ("finalized","settled","determined"):
            print("  %s: Kalshi says %s with result %r and no usable settlement value; left open (check it on Kalshi)"%(t,safe(m.get("status")),safe(m.get("result"))))
        elif m.get("status") in ("active","open"): still_open.add(t)
    c.commit()
    msg=end_trial_line(c,env)   # END_ON_DRAWDOWN (2026-11-07): settlements are what move the bot's value
    if msg: print("live (%s): %s"%(env,msg))
    reconcile(cl,c,env,still_open)
    tot=c.execute("select coalesce(sum(pnl),0),count(*) from orders where env=? and settled_ts is not null",(env,)).fetchone()
    print("live (%s): %d settled now; %d settled in all, net %s$%.2f after fees"%(env,n,tot[1],"+" if tot[0]>=0 else "-",abs(tot[0])))
def gate_lines():
    p=paper_ro()
    if p is None: return ["(no paper.db yet)"]
    import strategy
    buf=io.StringIO()
    try:
        with contextlib.redirect_stdout(buf): strategy.report(p)
    except Exception as e: return ["(could not work out the gate: %s; treat it as not passed)"%type(e).__name__]
    finally: p.close()
    return [l for l in buf.getvalue().splitlines() if l.startswith(("SHADOW v3 rain","TRADES v3 rain","CLEAR MARGIN","GATE","STOP DATE"))]
def status():
    s,env,k=load_settings(); c=ldb()
    print("Exchange: %s (%s)"%(env,"fake money" if env=="demo" else "REAL MONEY"))
    print("Settings: %s"%(SETTINGS if os.path.exists(SETTINGS) else "none yet (run .\\run live setup)"))
    print("Ledger: %s"%LIVE_DB)
    if k.get("key_id"): print("Key ID: %s...  key file: %s (%s)"%(k["key_id"][:4],k.get("key_file"),"found" if os.path.isfile(k.get("key_file") or "") else "MISSING"))
    print("Orders: "+((lock_reason(c,env,s) or "allowed") if ready(k) else "none (no %s account set up yet)"%env))
    print("Filter: 'no rain' paper bets are not copied when v3 itself says rain %d%% or more (your rule of 2026-11-06)"%round(SKIP_NO_FROM*100))
    if AGREE_6H: print("Filter: a paper bet is copied only if v3's hours in 6-hour blocks also give the bot's %d-point edge on the same side, within its %d-point veto (your rule of 2026-11-07)"%(round(MIN_EDGE*100),round(VETO_MAX_GAP*100)))
    else: print("Filter: the 6-hour check is off (your choice of 2026-11-07)")
    if END_ON_DRAWDOWN: print("End rule: on real money, a 25% drawdown from the peak ends the trial and locks real money again (your rule of 2026-11-07)")
    e=trial_ended(c)
    if e: print("Real-money trial: ENDED on %s (%s). Starting again needs .\\run live resume and .\\run live unlock, both typed by you."%(time.strftime("%Y-%m-%d %H:%M",time.localtime(e[0])),e[2]))
    why=stops(c,env)
    if why: print("Paused: "+why)
    if ready(k):
        try: cl,_=client(); print("Account: cash $%.2f, at risk $%.2f (cap $%.2f)"%(balance(cl),at_risk(cl),MAX_AT_RISK))
        except ExchangeError as e: print("Account: could not connect: %s"%e)
    q=c.execute("select count(*),coalesce(sum(fill_count),0),coalesce(sum(case when settled_ts is not null then pnl end),0),coalesce(sum(case when fill_count>0 and result is null then cost+fees end),0) from orders where env=? and status not in ('skipped','rejected','not placed')",(env,)).fetchone()
    print("This bot on %s: %d orders, %d contracts filled, open cost $%.2f, settled net %s$%.2f"%(env,q[0],q[1],q[3],"+" if q[2]>=0 else "-",abs(q[2])))
    v,p,_=value_track(c,env)
    if v>=2*STAKE: print("REMINDER: the bot's value has doubled ($%.2f). The rules say: withdraw your original $%.0f now."%(v,STAKE))
    print("Paper gate (v3 rain):"); [print("  "+l) for l in gate_lines()]
def test_connection():
    cl,env=client()
    if cl is None: sys.exit("No key set up for %s yet: run .\\run live setup"%env)
    try: b,r=balance(cl),at_risk(cl)
    except ExchangeError as e: sys.exit("Connection to Kalshi %s failed: %s"%(env,e))
    print("Connected to Kalshi %s (%s). Cash $%.2f, at risk $%.2f."%(env,"fake money" if env=="demo" else "real money",b,r))
def find_key_file(d,env):
    """The default key file, the same name with a hidden extra ending (Windows hides '.txt', so renaming the download to
    'kalshi-demo-key.txt' often gives 'kalshi-demo-key.txt.txt'), or else the only key-like file in the .kalshi folder
    that is not named for the other exchange. Looks at file names only."""
    for p in (d,d+".txt",os.path.splitext(d)[0]):
        if os.path.isfile(p): return p
    other="prod" if env=="demo" else "demo"
    used=os.path.normcase(os.path.abspath(((read_settings().get("keys") or {}).get(other) or {}).get("key_file") or "-"))
    try: c=[f for f in os.listdir(KDIR) if f.lower().endswith((".txt",".pem",".key")) and other not in f.lower()
            and os.path.normcase(os.path.abspath(os.path.join(KDIR,f)))!=used and os.path.isfile(os.path.join(KDIR,f))]
    except OSError: c=[]
    return os.path.join(KDIR,c[0]) if len(c)==1 else None
def setup():
    if not interactive():
        if windows() and "--window" not in sys.argv: return open_setup_window()
        need_terminal("setup","Setup")
    s=read_settings()
    print("Connect a Kalshi account. Nothing you type here leaves this computer except to Kalshi.")
    print("Never paste the private key itself here: only its Key ID and where the key FILE is saved.")
    env=(input("Exchange, demo or prod [demo]: ").strip().lower() or "demo")
    if env not in BASES: sys.exit("Type demo or prod.")
    kid=input("Key ID (from Kalshi's API Keys page): ").strip()
    if not valid_key_id(kid): drain(); sys.exit("That is not a Key ID (it looks like a1b2c3d4-e5f6-...). It was not saved or shown.")
    os.makedirs(KDIR,exist_ok=True); d=os.path.join(KDIR,"kalshi-%s-key.txt"%env)
    for attempt in range(3):
        raw=input("Private key file [%s]: "%d).strip().strip('"')
        if looks_like_key_text(raw): drain(); print("That looks like the key itself, not a file location. It was not saved or shown. Save the key into a file and give its location."); continue
        kf=os.path.expandvars(os.path.expanduser(raw))
        if not kf:
            kf=find_key_file(d,env) or d
            if kf!=d and input("Found %s in %s. Is that your %s key? [Y/n]: "%(os.path.basename(kf),KDIR,env)).strip().lower().startswith("n"):
                print("Then drag the right key file onto this window."); continue
        try: key=load_key(kf); break
        except ExchangeError as e:
            print("Not usable: %s."%e)
            if kf==d and not os.path.isfile(d):
                print("Save the key file Kalshi gave you into this folder as %s and press Enter here,"%os.path.basename(d))
                print("or drag the key file from File Explorer onto this window and press Enter.")
                if hasattr(os,"startfile"):
                    try: os.startfile(KDIR)   # opens the folder in File Explorer
                    except OSError: pass
    else: drain(); sys.exit("Setup stopped: no usable key file. Nothing was saved.")
    if os.path.normcase(os.path.dirname(os.path.realpath(kf)))!=os.path.normcase(os.path.realpath(KDIR)):
        print("Tip: keep the key in %s rather than Downloads or the desktop."%KDIR)
    print("Testing the connection to Kalshi %s..."%env)
    try: b=balance(Client(env,kid,key))   # nothing is saved unless Kalshi accepts this key
    except ExchangeError as e:
        sys.exit("Kalshi %s did not accept this Key ID and key file (%s). Nothing was saved. Check that both come from %s."%(env,e,"demo.kalshi.co" if env=="demo" else "kalshi.com"))
    keep_demo=False
    if env=="prod" and (read_settings().get("keys") or {}).get("demo"):
        keep_demo=not input("Keep copying trades to the demo account until real money is unlocked? [Y/n]: ").strip().lower().startswith("n")
    s=read_settings()   # re-read just before saving, so nothing changed meanwhile (for example a lock) is undone
    s.setdefault("keys",{})[env]={"key_id":kid,"key_file":os.path.abspath(kf)}
    if not keep_demo: s["env"]=env; s.setdefault("mirror_from",{})[env]=now()
    save_settings(s); event(ldb(),env,"setup","key id %s..."%kid[:4])
    print("Connected to Kalshi %s (%s). Cash $%.2f. Saved to %s (outside the project folder)."%(env,"fake money" if env=="demo" else "real money",b,SETTINGS))
    if env=="prod":
        print("Real-money orders stay locked until %s, and then only after you run .\\run live unlock."%STOP_DATE)
        print("The bot keeps copying to the demo account for now." if keep_demo else "The bot now uses the real account (locked). To copy to demo meanwhile: .\\run live use demo")
def use(env):
    if env not in BASES: sys.exit("Type: .\\run live use demo   or   .\\run live use prod")
    s=read_settings()
    if not (s.get("keys") or {}).get(env): sys.exit("No %s key set up yet: run .\\run live setup"%env)
    s["env"]=env; s.setdefault("mirror_from",{})[env]=now(); save_settings(s); print("Exchange set to %s."%env)
def unlock():
    s,env,k=load_settings(); c=ldb()
    if env!="prod": sys.exit("Unlock is only for real money. Switch first: .\\run live use prod")
    if today()<STOP_DATE: sys.exit("Real money stays locked until %s (the stop date)."%STOP_DATE)
    if not interactive(): need_terminal("unlock","Unlock")
    print("Paper test result (judged once on %s):"%STOP_DATE); lines=gate_lines(); [print("  "+l) for l in lines]
    passed=any(l.startswith("GATE") and "passed (paper only)" in l for l in lines)
    if not passed: print("\nThe gate did NOT pass. By the project rules (CLAUDE.md section 11) that means no edge was demonstrated and no real money. This is still your call.")
    if trial_ended(c): print("\nThe real-money trial ENDED at the 25% drawdown (your rule of 2026-11-07). Real money also stays locked until you type .\\run live resume.")
    print("\nIf you go ahead: copies of the paper rain trades that pass your filters, at most $%.0f at risk at once, daily loss stop, and a 25%% drawdown ends the trial (real money locks again). Not financial advice; you can lose the money."%MAX_AT_RISK)
    if input('Type "%s" to allow real-money orders: '%UNLOCK_PHRASE).strip()!=UNLOCK_PHRASE: sys.exit("Not unlocked.")
    t=event(c,"prod","unlock","gate %s"%("passed" if passed else "NOT passed")); s["prod_unlock"]=t; save_settings(s)
    print("Unlocked (recorded in %s and %s). The next scan copies paper rain trades to your real account. Undo any time: .\\run live lock"%(LIVE_DB,SETTINGS))
def lock():
    """Clears the settings mark first: that alone locks real money, even if live.db cannot be written."""
    if os.path.exists(SETTINGS): s=read_settings(); s["prod_unlock"]=None; save_settings(s)
    try: event(ldb(),"prod","lock"); print("Real-money orders locked (recorded in %s and %s)."%(SETTINGS,LIVE_DB))
    except sqlite3.Error as e: print("Real-money orders locked in %s (live.db could not record it: %s)."%(SETTINGS,e))
def resume():
    s,env,k=load_settings()
    if not interactive(): need_terminal("resume","Resume")
    if input("Type RESUME to restart orders after the drawdown pause: ").strip()!="RESUME": sys.exit("Not resumed.")
    c=ldb()
    if env=="prod":   # the end rule first, so a drawdown whose lock could not be written earlier still ends the trial (review)
        msg=end_trial_line(c,env)
        if msg: print(msg)
    event(c,env,"resume"); print("Resumed on %s."%env)
    if env=="prod" and not unlocked(c): print("Real money is still locked (for example after the drawdown ended the trial): .\\run live unlock, typed by you, starts it again.")
def demo_order(*args):
    """demo-order [no] [TICKER]: 1 fake contract of YES (default) or NO, then show Kalshi's position for that market,
    so a NO test proves that a V2 ask opens a NO position (shown as a negative position)."""
    side="no" if any(x.lower()=="no" for x in args) else "yes"
    rest=[x for x in args if x.lower() not in ("yes","no")]; ticker=rest[0] if rest else None
    s,env,k=load_settings()
    if env!="demo": sys.exit("demo-order works only on the demo exchange (fake money). Switch with: .\\run live use demo")
    c=ldb(); why=lock_reason(c,env,s)
    if why: sys.exit("No order: "+why)
    cl,_=client()
    if cl is None: sys.exit("No demo key set up yet: run .\\run live setup")
    if resolve_unknown(cl,c,env): sys.exit("An earlier order's outcome is unknown; run .\\run live sync first.")
    m=None
    if ticker:
        why=already_on_kalshi(cl,ticker)   # never touch a market the bot (or you) already hold: a NO test is a YES sell
        if why: sys.exit("No order on %s: %s. Pick another market, or leave the ticker out."%(safe(ticker),why))
        m=market(cl,ticker)
    else:
        for params in ({"series_ticker":"KXRAIN","status":"open","limit":200},{"status":"open","limit":500}):
            for x in cl.get("/markets",params,auth=False).get("markets") or []:
                b,a=kalshi.quote(x); p=a if side=="yes" else (None if b is None else 1-b)
                if p is not None and 0.02<=p<=0.98 and not x.get("ticker","").startswith("KXMVE") and not already_on_kalshi(cl,x.get("ticker","")): m=x; break
            if m: break
    if not m: sys.exit("No open demo market with a price found%s."%(" for "+safe(ticker) if ticker else ""))
    b,a=kalshi.quote(m); p=a if side=="yes" else (None if b is None else 1-b); cents=int(round((p or 0)*100))
    if not 1<=cents<=99: sys.exit("That market has no %s price to buy at."%side.upper())
    risk=max(at_risk(cl),local_at_risk(c,env))
    if risk+cents/100+fee(cents/100,1)>MAX_AT_RISK: sys.exit("No order: it would put more than $%.0f at risk."%MAX_AT_RISK)
    print("Demo test order on %s: buy 1 %s at %dc (fake money)"%(safe(m["ticker"]),side.upper(),cents))
    o=place(cl,c,env,None,m["ticker"],side,1,cents,"demo test order")
    if o is None: sys.exit(1)
    if _qty(o,"fill_count")>0:
        try:
            pos=holding(cl,m["ticker"]); q=_qty(pos,"position") if pos else 0
            ok=(q>0) if side=="yes" else (q<0)
            print("Kalshi now shows position %g on %s (%s): %s"%(q,safe(m["ticker"]),"positive = YES, negative = NO",
                  "as expected" if ok else "NOT what was intended; tell Claude before any real orders"))
        except ExchangeError as e: print("Could not read the position back: %s"%e)
    else: print("Nobody sold at that price just now, so nothing filled (no cost). Try again in a minute.")
    print("Demo order works. .\\run live sync records the result after the market settles.")
def main(a):
    try: sys.stdout.reconfigure(errors="replace")
    except AttributeError: pass
    if "--window" in a:   # setup running in its own window: keep the window open so the result can be read
        a=[x for x in a if x!="--window"]; code=0
        try: main(a)
        except SystemExit as e:
            if e.code not in (None,0): print(e.code); code=1
        except ExchangeError as e: print("live: %s"%e); code=1
        try: input("\nPress Enter to close this window.")
        except EOFError: pass
        sys.exit(code)
    cmd=a[0] if a else "status"
    if cmd=="mirror": mirror()
    elif cmd=="sync": sync()
    elif cmd=="status": status()
    elif cmd=="test": test_connection()
    elif cmd=="setup": setup()
    elif cmd=="use" and len(a)>1: use(a[1].lower())
    elif cmd=="unlock": unlock()
    elif cmd=="lock": lock()
    elif cmd=="resume": resume()
    elif cmd=="demo-order": demo_order(*a[1:])
    else: sys.exit(__doc__)
if __name__=="__main__":
    try: main(sys.argv[1:])
    except ExchangeError as e: sys.exit("live: %s"%e)
