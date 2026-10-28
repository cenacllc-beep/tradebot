"""Market discovery (research only; added 2026-10-22, platform upgrade phase 29). A separate path from the frozen
weather scan, which it never touches. It keeps a catalogue of Kalshi's open markets in its own database
(research/data/discovery.db), never paper.db or live.db, and places no orders.

  python research/discover.py refresh [--every SECONDS] [--singles]   update the catalogue (skipped if the last run is
      too recent; --singles leaves out combos, which number in the tens of thousands: the hourly job uses it)
  python research/discover.py summary                     -> research/results/discovery.md

How it avoids fetching the whole universe too often:
- **Series:** the list (with category and fee type) is re-read at most once a day.
- **Open markets:** one paginated pass of status=open (1,000 a page, cursor), single markets and combos
  (multivariate) separately. Combos are flagged.
- **Changes only:** markets are upserted by ticker, so a ticker is stored once however often it is seen.
- **Lifecycle:** a market that was open last time but is missing now is looked up in batches of 50 tickers, then one
  at a time for any the batch leaves out (at most 300 a run; the rest wait for the next). Its new status (closed,
  settled and so on) is added to the append-only lifecycle table. A ticker Kalshi no longer knows is marked not_found.
- **Memory and crashes:** each page is written to the database as it arrives, and a run is logged when it starts, so a
  crash does not make the next hourly run repeat the whole download.
- **Rate limit:** at most 8 requests a second.
- **Retries:** 429 and 5xx answers back off (Retry-After when given, else 3, 6, 12 ... seconds up to 60).
- **Cache:** with --every N, a refresh within N seconds of the last one does nothing.
Read-only Kalshi public GETs, same domain and User-Agent as kalshi.py. Python 3.8+, needs requests."""
import os, sys, time, sqlite3
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
if ROOT not in sys.path: sys.path.insert(0,ROOT)
from tbcommon.httpclient import JsonClient, KALSHI_PUBLIC
from tbcommon.parse import num, px, rts
from tbcommon import clock   # report times in the bot's zone, named (2026-10-23)
DATA=os.path.join(HERE,"data"); OUT=os.path.join(HERE,"results")
DB=os.path.join(DATA,"discovery.db")
MIN_GAP=0.125   # seconds between requests: at most 8 a second
CLIENT=JsonClient(KALSHI_PUBLIC,tries=6,timeout=30,min_gap=MIN_GAP,backoff_base=3.0,backoff_cap=60.0)
def http(path,params=None,tries=6): return CLIENT.get(path,params,tries=tries)
SCHEMA=["create table if not exists series(ticker text primary key,category text,title text,fee_type text,fee_multiplier real,first_seen real,last_seen real)",
        "create table if not exists markets(ticker text primary key,event_ticker text,series text,mve integer,status text,close_ts real,"
        "yes_bid real,yes_ask real,volume real,open_interest real,first_seen real,last_seen real,status_ts real)",
        "create table if not exists lifecycle(ticker text,ts real,old text,new text)",
        "create table if not exists runs(ts real,seconds real,requests integer,open_seen integer,new integer,closed integer,series integer,note text)",
        "create trigger if not exists lifecycle_no_update before update on lifecycle begin select raise(abort,'lifecycle is append-only'); end",
        "create trigger if not exists lifecycle_no_delete before delete on lifecycle begin select raise(abort,'lifecycle is append-only'); end",
        "create index if not exists markets_status on markets(status)","create index if not exists markets_series on markets(series)"]
def connect(path=None):
    os.makedirs(os.path.dirname(path or DB),exist_ok=True); c=sqlite3.connect(path or DB)
    for s in SCHEMA: c.execute(s)
    c.commit(); return c
def series_of(t): return (t or "").split("-")[0]
def refresh_series(c,now):
    last=c.execute("select max(last_seen) from series").fetchone()[0]
    if last and now-last<86400: return 0
    rows=(http("/series").get("series") or [])
    for s in rows:
        t=s.get("ticker")
        if not t: continue
        c.execute("insert into series(ticker,category,title,fee_type,fee_multiplier,first_seen,last_seen) values(?,?,?,?,?,?,?) "
                  "on conflict(ticker) do update set category=excluded.category,title=excluded.title,fee_type=excluded.fee_type,"
                  "fee_multiplier=excluded.fee_multiplier,last_seen=excluded.last_seen",
                  (t,s.get("category"),s.get("title"),s.get("fee_type"),num(s.get("fee_multiplier")),now,now))
    return len(rows)
def open_pass(mve_filter,max_pages=400):
    """Yields the open listing one page at a time."""
    cur=None
    for _ in range(max_pages):
        p=dict(status="open",limit=1000,mve_filter=mve_filter)
        if cur: p["cursor"]=cur
        j=http("/markets",p); page=j.get("markets") or []; cur=j.get("cursor")
        yield page
        if not cur or not page: return
    raise RuntimeError("open listing did not end after %d pages"%max_pages)
LOOKUP_CAP=300
def upsert(c,m,now,mve):
    t=m.get("ticker")
    old=c.execute("select status from markets where ticker=?",(t,)).fetchone()
    st=(m.get("status") or "").lower()
    if old and old[0]!=st: c.execute("insert into lifecycle values(?,?,?,?)",(t,now,old[0],st))
    vals=(m.get("event_ticker"),series_of(m.get("event_ticker") or t),1 if mve else 0,st,rts(m.get("close_time")),px(m,"yes_bid"),px(m,"yes_ask"),
          num(m.get("volume_fp")) if m.get("volume_fp") is not None else num(m.get("volume")),
          num(m.get("open_interest_fp")) if m.get("open_interest_fp") is not None else num(m.get("open_interest")))
    if old and st=="not_found":   # Kalshi no longer knows it: keep what was seen, change only the status
        c.execute("update markets set status=?,status_ts=?,last_seen=? where ticker=?",(st,now,now,t)); return False
    if old:
        c.execute("update markets set event_ticker=?,series=?,mve=?,status=?,close_ts=?,yes_bid=?,yes_ask=?,volume=?,open_interest=?,last_seen=?,"
                  "status_ts=case when status=? then status_ts else ? end where ticker=?",vals+(now,st,now,t))
        return False
    c.execute("insert into markets(event_ticker,series,mve,status,close_ts,yes_bid,yes_ask,volume,open_interest,first_seen,last_seen,status_ts,ticker) "
              "values(?,?,?,?,?,?,?,?,?,?,?,?,?)",vals+(now,now,now,t))
    c.execute("insert into lifecycle values(?,?,?,?)",(t,now,None,st)); return True
def refresh(now=None,path=None,every=None,singles=False):
    c=connect(path); now=now or time.time()
    last=c.execute("select max(ts) from runs").fetchone()[0]
    if every and last and now-last<every:
        print("discover: last refresh %.1f hours ago; next after %.1f hours"%((now-last)/3600,every/3600)); return None
    c.execute("insert into runs values(?,?,?,?,?,?,?,?)",(now,None,None,None,None,None,None,"started")); c.commit()   # --every holds even if this run crashes
    t0=time.time(); r0=CLIENT.requests
    ns=refresh_series(c,now); c.commit()
    seen=set(); new=0
    for mve,flt in ((False,"exclude"),)+(() if singles else ((True,"only"),)):
        for page in open_pass(flt):
            for m in page:
                t=m.get("ticker")
                if not t or t in seen: continue
                seen.add(t); new+=upsert(c,m,now,mve)
            c.commit()
    q="select ticker from markets where status in ('open','active')"+(" and mve=0" if singles else "")
    gone=[t for (t,) in c.execute(q) if t not in seen]
    closed=lookups=0
    for i in range(0,len(gone),50):
        got={m.get("ticker"):m for m in (http("/markets",dict(tickers=",".join(gone[i:i+50]),limit=1000)).get("markets") or [])}
        for t in gone[i:i+50]:
            m=got.get(t)
            if m is None:
                if lookups>=LOOKUP_CAP: continue   # the rest wait for the next run
                lookups+=1
                try: m=http("/markets/"+t).get("market") or None
                except RuntimeError as ex:
                    m=dict(ticker=t,status="not_found") if "HTTP 404" in str(ex) else None
            if m is None: continue   # a temporary failure: tried again next run
            upsert(c,dict(m,event_ticker=m.get("event_ticker") or c.execute("select event_ticker from markets where ticker=?",(t,)).fetchone()[0]),
                   now,bool(c.execute("select mve from markets where ticker=?",(t,)).fetchone()[0])); closed+=1
        c.commit()
    c.execute("insert into runs values(?,?,?,?,?,?,?,?)",(now,time.time()-t0,CLIENT.requests-r0,len(seen),new,closed,ns,None)); c.commit()
    print("discover: %d open markets seen (%d new), %d no longer open, %d series re-read, %d requests"%(len(seen),new,closed,ns,CLIENT.requests-r0))
    return dict(open=len(seen),new=new,closed=closed)
def summary(path=None):
    c=connect(path); L=["# Market discovery (research)",""]
    r=c.execute("select ts,open_seen,new,closed,requests from runs where note is null order by ts desc limit 1").fetchone()
    if not r: print("discover: no refresh yet"); return None
    L.append("Last refresh %s: %d open markets (%d new, %d closed since the previous refresh), %d requests."%("%s, %s"%(clock.label(r[0]),clock.ZONE_NOTE),r[1],r[2],r[3],r[4]))
    rows=c.execute("select coalesce(s.category,'(unknown)'),m.mve,count(*),sum(case when m.yes_bid>0 and m.yes_ask<1 then 1 else 0 end) from markets m left join series s on s.ticker=m.series "
                   "where m.status in ('open','active') group by 1,2 order by 3 desc").fetchall()
    L+=["","| Category | Kind | Open markets | With a two-sided quote |","|---|---|---:|---:|"]
    L+=["| %s | %s | %d | %d |"%(cat,"combo" if mv else "single",n,q or 0) for cat,mv,n,q in rows]
    ft=c.execute("select coalesce(s.fee_type,'(unknown)'),count(*) from markets m left join series s on s.ticker=m.series where m.status in ('open','active') group by 1 order by 2 desc").fetchall()
    L+=["","Fee types of open markets: "+", ".join("%s %d"%x for x in ft)+".","",
        "A catalogue only: nothing here is a strategy or a recommendation, and nothing is traded."]
    os.makedirs(OUT,exist_ok=True); open(os.path.join(OUT,"discovery.md"),"w",encoding="utf-8").write("\n".join(L)+"\n"); print("\n".join(L))
    return rows
if __name__=="__main__":
    try: sys.stdout.reconfigure(errors="replace")
    except AttributeError: pass
    a=sys.argv[1:]
    if a[:1]==["refresh"]:
        ev=float(a[a.index("--every")+1]) if "--every" in a else None
        refresh(every=ev,singles="--singles" in a)
    elif a[:1]==["summary"]: summary()
    else: sys.exit(__doc__)
