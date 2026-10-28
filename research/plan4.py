"""PLAN4: following other traders (research only; never touches paper.db or live.db; places no orders).
Follows research/PLAN4.md. Python 3.8+, needs requests. Each test is scored once: a scorer refuses to run if its result
file exists, and the selection files are frozen once written. Wallets are public addresses only (names, bios and images
are dropped on ingest).

Polymarket (P1 persistence, P2 late copies, P2c consensus):
  python research/plan4.py pmarkets    formation markets (Gamma) -> data/pm/formation_markets.json
  python research/plan4.py ppool       formation fills >= $500 -> data/pm/fills/, the 2,000-wallet pool -> data/pm/pool.json
  python research/plan4.py ppositions  every pool wallet's closed and redeemable positions -> data/pm/positions/
  python research/plan4.py pselect     format checks, eligibility, selection, coverage checks (frozen) -> results/plan4_selected.json
  python research/plan4.py pcopies     selected and placebo wallets' buys, market details, resolutions, trade lists -> data/pm/
  python research/plan4.py scoreP      P1, P2 and P2c, scored once -> results/plan4_P.md and .json
Kalshi (K1 large trades):
  python research/plan4.py kseries     the 40 series and the sampled markets (metadata only; frozen) -> results/plan4_series.json
  python research/plan4.py ktrades     the sampled markets' trade lists -> data/k1/trades/
  python research/plan4.py scoreK      K1, scored once -> results/plan4_K.md and .json
  python research/plan4.py kquotes     descriptive standing-ask check on 300 sampled copies (after scoring)
Polite: one request at a time, pauses, honours Retry-After; resumable (finished files are skipped, failures are retried)."""
import os, sys, json, time, math, random, re, calendar
from datetime import datetime, timezone
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
for p in (HERE,ROOT):
    if p not in sys.path: sys.path.insert(0,p)
DATA=os.path.join(HERE,"data"); OUT=os.path.join(HERE,"results")
PM="https://data-api.polymarket.com"; GAMMA="https://gamma-api.polymarket.com"; KALSHI="https://api.elections.kalshi.com/trade-api/v2"
UA={"User-Agent":"tradebot-paper-research/1.0"}
SEED=4; CAP=0.97; DELAY=300; WINDOW=3600; MAXPAGES=200
POSCAP=10000   # a wallet with more than this many rows in its CLOSED or REDEEMABLE walk is not eligible (PLAN4, 16:20 revision)
def ts(s): return calendar.timegm(datetime.strptime(s,"%Y-%m-%d").timetuple())
F0,F1=ts("2026-01-01"),ts("2026-07-01")          # formation: end dates Jan 1..Jun 30, first entry before Jul 1
E0,E1=ts("2026-07-01"),ts("2026-10-01")          # evaluation: first entry Jul 1..Sep 30
EEND0,EEND1=ts("2026-07-01"),ts("2026-10-08")    # evaluation end dates Jul 1..Oct 7
RESOLVED_BY=ts("2026-10-15")                     # resolved by Oct 14 (inclusive)
K0,K1END=ts("2026-07-15"),ts("2026-10-14")       # K1 scheduled close Jul 15..Oct 13
DROP=("name","pseudonym","bio","profile_image","profile_image_optimized","x_username","user_name","icon")

# ---------------- network and files ----------------
def http(url,params,pause=0.3,tries=8):
    import requests
    for k in range(tries):
        try: r=requests.get(url,params=params,headers=UA,timeout=60)
        except requests.RequestException as ex: print("  retry (%s)"%ex); time.sleep(min(120,5*2**k)); continue
        if r.status_code==200:
            try: j=r.json()
            except ValueError: print("  not JSON, retrying"); time.sleep(min(120,5*2**k)); continue
            time.sleep(pause); return j
        if r.status_code==429 or r.status_code>=500:
            try: wait=float(r.headers.get("Retry-After") or 0)
            except ValueError: wait=0
            wait=wait or min(120,5*2**k); print("  HTTP %d, waiting %.0fs"%(r.status_code,wait)); time.sleep(wait); continue
        raise RuntimeError("HTTP %d (not retried) %s %s"%(r.status_code,url,str(params)[:120]))
    raise RuntimeError("giving up on %s"%url)
def strip(row): return {k:v for k,v in row.items() if k not in DROP}
def pm_pages(path,params,maxpages=None,maxrows=None):
    """Every row of a Data API v2 walk (identical filters re-sent with each cursor). Returns (rows, complete); with
    maxpages or maxrows the walk stops early and complete is False."""
    out=[]; cur=None; n=0
    while True:
        p=dict(params); p.update(cursor=cur) if cur else None
        j=http(PM+path,p); out+=[strip(r) for r in (j.get("data") or [])]; n+=1
        if n%50==0: print("    %s: %d pages, %d rows"%(path,n,len(out)))
        pg=j.get("pagination") or {}; cur=pg.get("next_cursor")
        if not cur or pg.get("has_more") is False or not (j.get("data") or []): return out,True   # has_more missing + a cursor: more
        if (maxpages and n>=maxpages) or (maxrows and len(out)>maxrows): return out,False
def k_pages(path,params,key,reduce=lambda r:r):
    """Every row of a Kalshi cursor walk, reduced to the fields needed as each page arrives (keeps memory small)."""
    out=[]; cur=None; n=0; seen=0
    while True:
        p=dict(params); p.update(cursor=cur) if cur else None
        j=http(KALSHI+path,p,pause=0.12); page=j.get(key) or []; seen+=len(page); out+=[x for x in (reduce(r) for r in page) if x]; cur=j.get("cursor"); n+=1
        if n%100==0: print("  %s: %d pages, %d rows read, %d kept"%(path,n,seen,len(out)))
        if not cur or not (j.get(key) or []): return out
def save(path,obj):
    os.makedirs(os.path.dirname(path),exist_ok=True); tmp=path+".tmp"
    with open(tmp,"w",encoding="utf-8") as f: json.dump(obj,f)
    for k in range(5):   # an antivirus scan can hold the file for a moment on Windows
        try: os.replace(tmp,path); return
        except PermissionError:
            if k==4: raise
            time.sleep(1+k)
def load(path,default=None):
    return json.load(open(path,encoding="utf-8")) if os.path.exists(path) else default
def once(name):
    p=os.path.join(OUT,name)
    if os.path.exists(p): sys.exit("%s already exists: PLAN4 scores each test once. A re-score after a bug fix must be logged in CHANGELOG and written under a new name."%p)
    return p
def short(w): return (w or "")[:6]
def now(): return datetime.now().isoformat(timespec="minutes")
def rts(s):
    """Epoch seconds from an ISO time ('2026-04-09T00:28:21Z', '2026-04-09 00:28:21+00', '...+00:00', with or without
    fractions); a time without an offset is read as UTC. None if it cannot be read."""
    if isinstance(s,bool): return None
    if isinstance(s,(int,float)) or re.fullmatch(r"\d{9,13}(\.\d+)?",str(s or "").strip()):   # epoch seconds (or ms)
        v=float(s); return int(v/1000) if v>1e11 else int(v)
    s=str(s or "").strip()
    if not s: return None
    s=s.replace(" ","T").replace("Z","+00:00")
    if re.search(r"\d\d:\d\d(:\d\d)?(\.\d+)?[+-]\d\d$",s): s+=":00"   # '+00' after a time (not a date's '-09')
    s=re.sub(r"\.(\d{1,6})\d*",lambda m:"."+m.group(1).ljust(6,"0"),s)   # 3.8-3.10 read only 3 or 6 digits
    try: d=datetime.fromisoformat(s)
    except ValueError: return None
    if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
    return int(d.timestamp())
def cn(c):
    """A condition ID in one form: lower case with 0x (a bare hex ID gets the prefix)."""
    c=str(c or "").strip().lower()
    if c and not c.startswith("0x") and re.fullmatch(r"[0-9a-f]{62,64}",c): c="0x"+c
    return c
def num(v):
    try: return None if v in (None,"") else float(v)
    except (TypeError,ValueError): return None
def count(d,k): d[k]=d.get(k,0)+1

# ---------------- statistics (PLAN4 "Common statistics") ----------------
def mean(x): return sum(x)/len(x) if x else None
def cl_se(units):
    """units: [(value, null variance, end-date cluster[, weight])], one per event (or market date). The (weighted) mean
    of values, and its SE = the largest of the SE over units, the SE clustered by end date, and the null SE
    sqrt(sum w^2 var)/sum w. With weights the SEs are the usual linearized ones; all weights 1 gives the plain formulas."""
    n=len(units)
    if n<2: return (units[0][0] if units else None),None
    w=[(u[3] if len(u)>3 else 1.0) for u in units]; W=sum(w)
    m=sum(wi*u[0] for wi,u in zip(w,units))/W
    z=[wi*(u[0]-m) for wi,u in zip(w,units)]
    se_u=((n/(n-1))*sum(x*x for x in z))**0.5/W
    g={}
    for zi,u in zip(z,units): g[u[2]]=g.get(u[2],0)+zi
    C=len(g); se_c=((C/(C-1))*sum(v*v for v in g.values()))**0.5/W if C>1 else float("inf")
    se_0=(sum(wi*wi*u[1] for wi,u in zip(w,units)))**0.5/W
    return m,max(se_u,se_c,se_0)
def tstat(m,se): return (m/se) if (m is not None and se) else None
def rank_corr(x,y):
    """Spearman rank correlation (average ranks for ties)."""
    def ranks(v):
        o=sorted(range(len(v)),key=lambda i:v[i]); r=[0.0]*len(v); i=0
        while i<len(o):
            j=i
            while j+1<len(o) and v[o[j+1]]==v[o[i]]: j+=1
            for k in range(i,j+1): r[o[k]]=(i+j)/2
            i=j+1
        return r
    if len(x)<3: return None
    a,b=ranks(x),ranks(y); ma,mb=mean(a),mean(b)
    num_=sum((p-ma)*(q-mb) for p,q in zip(a,b)); den=(sum((p-ma)**2 for p in a)*sum((q-mb)**2 for q in b))**0.5
    return num_/den if den else None

# ================= Polymarket =================
D_PM=os.path.join(DATA,"pm")
def is_combo(m):
    """A combo (parlay) market: 'create your own' (cyom), or a 31-byte combo condition ID (0x + 62 hex digits instead of
    64). Gamma's comboStatus only says whether a normal market may be a combo leg ('enabled'/'disabled'), so it is not used."""
    if isinstance(m,dict):
        if m.get("cyom"): return True
        m=m.get("conditionId") or m.get("condition_id") or ""
    return len(cn(m)[2:])==62
def pmarkets():
    """The 300 highest-volume closed markets with end dates in the formation window (combos excluded)."""
    out=[]; off=0
    while len(out)<300 and off<5000:
        j=http(GAMMA+"/markets",dict(closed="true",end_date_min="2026-01-01T00:00:00Z",end_date_max="2026-06-30T23:59:59Z",order="volumeNum",ascending="false",limit=100,offset=off))
        if not j: break
        for m in j:
            if not m.get("conditionId") or is_combo(m): continue
            out.append(dict(condition_id=cn(m["conditionId"]),end=(m.get("endDate") or "")[:10],volume=num(m.get("volumeNum"))))
        off+=len(j)
    out=out[:300]; save(os.path.join(D_PM,"formation_markets.json"),dict(fetched=now(),markets=out)); print("formation markets:",len(out))
def ppool():
    F=load(os.path.join(D_PM,"formation_markets.json")) or sys.exit("run pmarkets first")
    ms=F["markets"]; failed=[]
    for i,m in enumerate(ms):
        p=os.path.join(D_PM,"fills",m["condition_id"]+".json")
        if os.path.exists(p): continue
        try: rows,ok=pm_pages("/v2/trades",dict(condition=m["condition_id"],taker_only="false",filter_type="CASH",filter_amount=500,limit=1000))
        except RuntimeError as ex: print("  fills failed for",m["condition_id"][:10],ex); failed.append(m["condition_id"]); continue
        save(p,[dict(w=(r.get("proxy_wallet") or "").lower(),cash=(r.get("size") or 0)*(r.get("price") or 0)) for r in rows])
        if i%20==0: print("  fills",i,"/",len(ms))
    if failed: sys.exit("ppool incomplete: %d markets failed; run again"%len(failed))
    cnt={}; cash={}
    for m in ms:
        seen=set()
        for r in load(os.path.join(D_PM,"fills",m["condition_id"]+".json"),[]):
            w=r["w"]
            if not w: continue
            cash[w]=cash.get(w,0)+r["cash"]
            if w not in seen: seen.add(w); cnt[w]=cnt.get(w,0)+1
    pool=sorted(cnt,key=lambda w:(-cnt[w],-cash[w],w))[:2000]
    save(os.path.join(D_PM,"pool.json"),pool); print("pool:",len(pool),"wallets")
POSF=("condition_id","token_id","outcome_index","event_id","end_date","first_entry_at","avg_price","total_size","entry_fees_usdc","entry_cost_usdc","total_pnl","current_price","realized_pnl","status","negative_risk")
def fetch_positions(w,statuses,name):
    """Positions of one wallet, deduplicated by token. A failed walk is not saved (it is retried on the next run). A walk
    longer than POSCAP rows is stopped and saved as truncated with no rows (the wallet is then not eligible)."""
    p=os.path.join(D_PM,name,w+".json")
    if os.path.exists(p): return load(p)
    rows=[]
    for st,extra in statuses:
        r,c=pm_pages("/v2/positions",dict(user=w,status=st,limit=1000,**extra),maxrows=POSCAP)
        if not c:
            obj=dict(fetched=now(),rows=[],truncated=st); save(p,obj); return obj
        rows+=r
    seen=set(); uniq=[]
    for r in rows:
        k=r.get("token_id") or (cn(r.get("condition_id")),r.get("outcome_index"),r.get("status"))
        if k in seen: continue
        seen.add(k); x={k2:r.get(k2) for k2 in POSF}; x["condition_id"]=cn(x.get("condition_id")); uniq.append(x)
    obj=dict(fetched=now(),rows=uniq); save(p,obj); return obj
def positions_of(w,folder="positions"): return fetch_positions(w,(("CLOSED",{}),("REDEEMABLE",{"include_archived":"true"})),folder)
def open_positions_of(w,folder="open_positions"): return fetch_positions(w,(("OPEN",{"include_archived":"true"}),),folder)
def lost_positions_of(w,folder="lost_positions"): return fetch_positions(w,(("REDEEMABLE_LOST",{"include_archived":"true"}),),folder)
def ppositions():
    pool=load(os.path.join(D_PM,"pool.json")) or sys.exit("run ppool first")
    fails=[]
    for i,w in enumerate(pool):
        try: positions_of(w)
        except RuntimeError as ex: print("  positions failed for",short(w),ex); fails.append(w)
        if i%50==0: print("  positions",i,"/",len(pool))
    old=load(os.path.join(D_PM,"positions_failed.json"),{})
    for w in fails: old[w]=old.get(w,0)+1
    for w in list(old):
        if os.path.exists(os.path.join(D_PM,"positions",w+".json")): old.pop(w)
    save(os.path.join(D_PM,"positions_failed.json"),old)
    print("ppositions done; failed this run:",len(fails),"(run again to retry; a wallet failing 3 runs is left out and counted)")
def endts(r):
    try: return ts(str(r.get("end_date") or "")[:10])
    except ValueError: return None
def cost(r): return (r.get("total_size") or 0)*(r.get("avg_price") or 0)+(r.get("entry_fees_usdc") or 0)
def wallet_events(rows,window,fee_adjust=0.0,skip=None):
    """Wallet-events in a window: {event_id: dict(ret, var, end, cost, positions, conds, avg)} (PLAN4 P1 rules).
    Profit = total_pnl - fee_adjust x entry fees (fee_adjust 1 when total_pnl excludes fees). The null variance is
    (sum of each position's payout SD)^2 / cost^2: conservative for correlated holdings."""
    ev={}; skip=skip if skip is not None else {}
    for r in rows:
        e=endts(r); fe=r.get("first_entry_at") or 0; p=r.get("avg_price")
        fe_in=(0<fe<F1) if window=="formation" else (E0<=fe<E1)
        e_ok=e is not None and e>86400
        e_in=e_ok and ((F0<=e<F1) if window=="formation" else (EEND0<=e<EEND1))
        if not e_in:
            if fe_in: count(skip,"end date outside the window" if e_ok else "no end date (1970)")
            continue
        if not (r.get("total_size") and p): count(skip,"no buys (split, merge, conversion or transfer)"); continue
        if not fe: count(skip,"no first entry time"); continue
        if not fe_in: continue
        if not r.get("event_id"): count(skip,"no event"); continue
        if is_combo(r.get("condition_id") or ""): count(skip,"combo position"); continue
        if p>=CAP: count(skip,"avg_price 0.97 or more"); continue
        x=ev.setdefault(str(r["event_id"]),dict(profit=0.0,cost=0.0,sd=0.0,end=e,positions=0,conds=set(),pc=0.0))
        x["profit"]+=(r.get("total_pnl") or 0)-fee_adjust*(r.get("entry_fees_usdc") or 0); x["cost"]+=cost(r)
        x["sd"]+=(r.get("total_size") or 0)*(p*(1-p))**0.5; x["end"]=min(x["end"],e); x["positions"]+=1; x["conds"].add(r.get("condition_id")); x["pc"]+=p*cost(r)
    out={}
    for k,v in ev.items():
        if v["cost"]<10: count(skip,"wallet-event under $10"); continue
        out[k]=dict(ret=v["profit"]/v["cost"],var=(v["sd"]/v["cost"])**2,end=v["end"],cost=v["cost"],profit=v["profit"],positions=v["positions"],conds=v["conds"],avg=v["pc"]/v["cost"])
    return out
def wallet_t(we):
    m,se=cl_se([(x["ret"],x["var"],x["end"]) for x in we.values()]); return m,se,tstat(m,se)
def flags(rows):
    """Market-maker / arbitrage signs in formation positions: share of conditions with both outcomes, share of
    neg-risk events with 3+ outcomes held, number of formation positions."""
    byc={}; byneg={}; n=0
    for r in rows:
        e=endts(r)
        if e is None or not (F0<=e<F1): continue
        n+=1; byc.setdefault(r.get("condition_id"),set()).add(r.get("outcome_index"))
        if r.get("negative_risk"): byneg.setdefault(r.get("event_id"),set()).add(r.get("condition_id"))
    both=sum(1 for v in byc.values() if len(v)>1)/max(1,len(byc))
    multi=(sum(1 for v in byneg.values() if len(v)>=3)/len(byneg)) if byneg else 0.0
    return both,multi,n
def user_buys(w):
    """All BUY fills of a wallet (maker and taker), a year before formation to the end of evaluation."""
    p=os.path.join(D_PM,"buys",w+".json")
    if os.path.exists(p): return load(p)
    rows,ok=pm_pages("/v2/trades",dict(user=w,taker_only="false",side="BUY",start=F0-365*86400,end=E1,limit=1000))
    keep=[{k:r.get(k) for k in ("condition_id","token_id","outcome_index","price","size","timestamp","transaction_hash")} for r in rows]
    for b in keep: b["condition_id"]=cn(b.get("condition_id"))
    obj=dict(fetched=now(),rows=keep); save(p,obj); return obj
def user_taker_keys(w):
    p=os.path.join(D_PM,"taker",w+".json")
    if os.path.exists(p): return set(load(p))
    rows,ok=pm_pages("/v2/trades",dict(user=w,side="BUY",start=E0,end=E1,limit=1000))
    ks=sorted({"%s:%s"%(r.get("transaction_hash"),r.get("token_id")) for r in rows}); save(p,ks); return set(ks)
def splitmerge_cash(w):
    p=os.path.join(D_PM,"activity",w+".json")
    if os.path.exists(p): return load(p)
    rows,ok=pm_pages("/v2/activity",dict(user=w,type="SPLIT,MERGE,CONVERSION",start=F0-180*86400,end=F1,limit=1000))
    v=sum(num(r.get("usdc_size")) or 0 for r in rows if str(r.get("type") or "").upper() in ("SPLIT","MERGE","CONVERSION")); save(p,v); return v
def coverage(w,window):
    """Share of the wallet's BUY cash in the window (by fill time) that its scored rows (CLOSED and REDEEMABLE) account for,
    by (condition, outcome). From a fresh snapshot: the OPEN walk first, then the scored walks, so a holding that settles
    between the two is seen as still open or as scored, never as missing. Buys of an outcome that is still open (an OPEN
    row with status OPEN) leave the denominator; a resolved holding seen in the OPEN walk but missing from the scored
    rows counts as missing (survivorship). No formation buys at all means a broken walk (every pool wallet has fills of
    $500 or more), so it counts as 0."""
    opn=open_positions_of(w,"cov_open")["rows"]; pos=positions_of(w,"cov_positions")["rows"]
    scored={(r["condition_id"],r.get("outcome_index")) for r in pos}
    still_open=set(); missing=set()
    for r in opn:
        k=(r["condition_id"],r.get("outcome_index"))
        if r.get("status")=="OPEN": still_open.add(k)
        elif k not in scored: missing.add(k)
    lo,hi=(F0-365*86400,F1) if window=="formation" else (E0,E1)
    tot=cov=0.0; n=0
    for b in user_buys(w)["rows"]:
        if not (lo<=(b.get("timestamp") or 0)<hi): continue
        k=(b["condition_id"],b.get("outcome_index")); n+=1
        if k in still_open and k not in scored: continue
        v=(b.get("price") or 0)*(b.get("size") or 0); tot+=v
        if k in scored and k not in missing: cov+=v
    if window=="formation" and n==0: return 0.0
    return (cov/tot) if tot else 1.0
def format_check(wallets):
    """PLAN4 format check on 20 wallets, from a fresh snapshot: REDEEMABLE_LOST first, then CLOSED and REDEEMABLE, so a loss
    settling between the walks cannot break the subset test. Rows with no buys (total_size or avg_price 0: tokens from
    splits, merges, conversions or transfers) are counted and left out, as they are left out of the scores.
    - REDEEMABLE rows with no sells: total_size x avg_price = entry_cost_usdc within 1%, current_price 0 or 1;
    - CLOSED rows: total_size x avg_price > 0 and total_pnl = realized_pnl (within 1% of cost or 1c);
    - losers present; every REDEEMABLE_LOST (condition, outcome) in the CLOSED or REDEEMABLE walks, and at most 2% of
      them only as CLOSED rows (whose P&L would miss the unsold remainder's loss);
    - fields: first_entry_at in epoch seconds, a readable end_date and an event_id on 95% of rows with buys;
    - whether total_pnl includes entry fees (read off winners). At most 2% of rows may differ in each check.
    Rows sharing a (condition, outcome) are counted for information only (v1 and v2 tokens of one outcome are legitimate)."""
    rows=bad=zeros=lost_extra=lost_closed=lost_total=dup=nobuy=closed=closed_bad=buyrows=plaus=0; inc=exc=0
    for w in wallets:
        lost=lost_positions_of(w,"fmt_lost")["rows"]; pos=positions_of(w,"fmt_positions")["rows"]
        red={(r["condition_id"],r.get("outcome_index")) for r in pos}   # CLOSED or REDEEMABLE: one token can be in both walks and is kept once (2026-10-22)
        closed_keys={(r["condition_id"],r.get("outcome_index")) for r in pos if r.get("status")=="CLOSED"}
        keys={}
        for r in pos: k=(r["condition_id"],r.get("outcome_index")); keys[k]=keys.get(k,0)+1
        dup+=sum(v-1 for v in keys.values() if v>1)
        for r in pos:
            size=r.get("total_size") or 0; p=r.get("avg_price") or 0
            if not size or not p: nobuy+=1; continue
            buyrows+=1; fe=r.get("first_entry_at") or 0
            if 1.4e9<fe<2.1e9 and endts(r) is not None and r.get("event_id"): plaus+=1
            if r.get("status")=="CLOSED":
                closed+=1; c=size*p
                if not (c>0 and abs((r.get("total_pnl") or 0)-(r.get("realized_pnl") or 0))<=max(0.01,0.01*c)): closed_bad+=1
                continue
            if r.get("status")!="REDEEMABLE" or r.get("realized_pnl"): continue
            rows+=1; a=size*p; b=r.get("entry_cost_usdc")
            if not b or abs(a-b)/b>0.01 or r.get("current_price") not in (0,1): bad+=1; continue
            if r.get("current_price")==0: zeros+=1
            else:
                f=r.get("entry_fees_usdc") or 0; pnl=r.get("total_pnl") or 0
                if f>0.01:
                    if abs(pnl-(size-b-f))<abs(pnl-(size-b)): inc+=1
                    else: exc+=1
        lk={(r["condition_id"],r.get("outcome_index")) for r in lost}
        lost_extra+=len(lk-red); lost_closed+=len(lk&closed_keys); lost_total+=len(lk)
    fee_adjust=1.0 if exc>inc else 0.0   # total_pnl excludes entry fees: subtract them (cost includes them)
    # A lost token kept as its CLOSED row loses the unsold remainder's cost (CLOSED total_pnl = realized_pnl), which would
    # flatter the scores: more than 2% of lost positions listed that way fails the check (code review 2026-10-22).
    ok=(rows>0 and bad<=0.02*rows and zeros>0 and lost_extra==0 and lost_closed<=0.02*max(1,lost_total) and closed_bad<=0.02*max(1,closed) and buyrows>0 and plaus>=0.95*buyrows)
    return ok,dict(rows=rows,bad=bad,losers_seen=zeros,lost_not_in_redeemable=lost_extra,lost_listed_as_closed=lost_closed,lost_positions=lost_total,closed_rows=closed,closed_bad=closed_bad,
                   rows_without_buys=nobuy,rows_with_buys=buyrows,plausible_fields=plaus,same_outcome_rows=dup,
                   pnl_includes_fees=inc,pnl_excludes_fees=exc,fee_adjust=fee_adjust)
def pselect():
    out=os.path.join(OUT,"plan4_selected.json")
    if os.path.exists(out): sys.exit("plan4_selected.json is frozen (%s); PLAN4 never reselects."%load(out).get("created"))
    pool=load(os.path.join(D_PM,"pool.json")) or sys.exit("run ppool first")
    failed=load(os.path.join(D_PM,"positions_failed.json"),{})
    have=[w for w in pool if os.path.exists(os.path.join(D_PM,"positions",w+".json"))]
    waiting=[w for w in pool if w not in set(have) and failed.get(w,0)<3]
    if waiting: sys.exit("positions missing for %d wallets (failed fewer than 3 runs): run ppositions again"%len(waiting))
    def too_big(w):   # the POSCAP rule; wallets fetched in full before the cap existed are judged by the same row counts
        o=positions_of(w); n={}
        for r in o["rows"]: n[r.get("status")]=n.get(r.get("status"),0)+1
        return bool(o.get("truncated")) or any(v>POSCAP for v in n.values())
    big={w for w in have if too_big(w)}
    fmt_w=random.Random(SEED).sample(sorted(w for w in have if w not in big),min(20,len(have)-len(big)))
    ok,fmt=format_check(fmt_w)
    if not ok: sys.exit("Not selected: the position format check failed %s; the cost or coverage definition must be fixed first (PLAN4)."%fmt)
    fa=fmt["fee_adjust"]
    stats={}; skipped=dict(positions_failed=len(pool)-len(have),too_many_to_fetch=len(big),too_few=0,too_many=0,both_outcomes=0,neg_risk_multi=0,split_merge=0); excl={}
    for w in have:
        if w in big: continue
        rows=positions_of(w)["rows"]
        we=wallet_events(rows,"formation",fa,excl); both,multi,npos=flags(rows)
        if len(we)<10 or sum(x["positions"] for x in we.values())<20: skipped["too_few"]+=1; continue
        if npos>3000: skipped["too_many"]+=1; continue
        if both>0.20: skipped["both_outcomes"]+=1; continue
        if multi>0.20: skipped["neg_risk_multi"]+=1; continue
        m,se,t=wallet_t(we); stats[w]=dict(mean=m,se=se,t=t,events=len(we),cost=sum(x["cost"] for x in we.values()))
    for i,w in enumerate(sorted(stats)):   # split/merge/conversion activity: every remaining wallet (one request or so each)
        if splitmerge_cash(w)>0.20*stats[w]["cost"]: stats.pop(w); skipped["split_merge"]+=1
        if i%100==0: print("  activity",i)
    elig=sorted(stats)
    if len(elig)<250: sys.exit("Not frozen: only %d eligible wallets (50 selected and 200 placebo need 250); skipped %s, positions left out %s. Check the data before changing anything (PLAN4)."%(len(elig),skipped,excl))
    ranked=[w for w in sorted(elig,key=lambda w:(-(stats[w]["t"] if stats[w]["t"] is not None else -1e9),w)) if stats[w]["mean"] and stats[w]["mean"]>0]
    sel=ranked[:50]; rest=[w for w in elig if w not in set(sel)]
    placebo=random.Random(SEED).sample(rest,min(200,len(rest)))
    check=sel+random.Random(SEED).sample(rest,min(50,len(rest)))
    cov={w:(coverage(w,"formation"),coverage(w,"evaluation")) for w in check}
    fails=[w for w,(a,b) in cov.items() if a<0.98 or b<0.98]
    obj=dict(created=now(),selected=sel,placebo=placebo,eligible=elig,skipped=skipped,excluded_positions=excl,format_check=fmt,fee_adjust=fa,
             coverage_checked=len(check),coverage_failed=fails,coverage=[dict(wallet=short(w),formation=a,evaluation=b) for w,(a,b) in cov.items()],
             formation=[dict(wallet=short(w),**stats[w]) for w in sel],formation_all={w:stats[w] for w in elig})
    os.makedirs(OUT,exist_ok=True); save(out,obj)
    print("eligible %d, selected %d, placebo %d, coverage failures %d of %d, skipped %s, format %s"%(len(elig),len(sel),len(placebo),len(fails),len(check),skipped,fmt))
def resolutions(conds,refresh=False):
    """condition -> resolved time (epoch) or None, from /v2/resolutions (20 per request). A record with status "resolved"
    gives its last_update_timestamp (resolved_at if the API ever sends one); with several resolved records, the earliest.
    With refresh, conditions cached as unresolved are asked again (a transient empty answer must not become permanent)."""
    p=os.path.join(D_PM,"resolutions.json"); info=load(p,{})
    todo=[c for c in sorted({cn(c) for c in conds}) if c and (c not in info or (refresh and info[c] is None))]
    for i in range(0,len(todo),20):
        part=todo[i:i+20]; got={}
        rows,_=pm_pages("/v2/resolutions",dict(condition=",".join(part)))
        for r in rows:
            if str(r.get("status") or "").lower()!="resolved": continue
            t=rts(r.get("resolved_at") or r.get("last_update_timestamp")); c=cn(r.get("condition_id"))
            if t is not None and (c not in got or t<got[c]): got[c]=t
        for c in part: info[c]=got.get(c)
        if i%200==0: save(p,info); print("  resolutions",i,"/",len(todo))
    save(p,info); return info
def payouts(conds,refresh=False):
    """(condition, outcome_index) -> payout per share, from /v2/tokens final_price (10 conditions per request). Two token
    families of one outcome (v1 and polymarket-v2) must agree; a disagreement is recorded as None."""
    p=os.path.join(D_PM,"payouts.json"); info=load(p,{})
    todo=[c for c in sorted({cn(c) for c in conds}) if c and (c not in info or (refresh and not info[c]))]
    for i in range(0,len(todo),10):
        part=todo[i:i+10]
        toks,_=pm_pages("/v2/tokens",dict(condition=",".join(part)))
        for c in part:
            d={}
            for t in toks:
                if cn(t.get("condition_id"))!=c or t.get("final_price") is None: continue
                k=str(t.get("outcome_index")); v=num(t.get("final_price"))
                d[k]=v if (k not in d or d[k]==v) else None
            info[c]=d
        if i%100==0: save(p,info)
    save(p,info); return info
def gamma_meta(conds,refresh=False):
    """condition -> end date, event id, close time and fee schedule, from Gamma (20 per request, repeated parameter).
    With refresh, conditions Gamma did not return before are asked again."""
    p=os.path.join(D_PM,"gamma_meta.json"); tab=load(p,{})
    todo=[c for c in sorted({cn(c) for c in conds}) if c and (c not in tab or (refresh and tab[c] is None))]
    for i in range(0,len(todo),20):
        part=todo[i:i+20]
        for closed in ("true","false"):
            for m in (http(GAMMA+"/markets",dict(condition_ids=part,closed=closed,limit=100)) or []):
                fs=m.get("feeSchedule") if isinstance(m.get("feeSchedule"),dict) else {}
                on=bool(m.get("feesEnabled")); rate=num(fs.get("rate")); ev=(m.get("events") or [{}])[0] or {}
                tab[cn(m.get("conditionId"))]=dict(end=(m.get("endDate") or "")[:10],event=str(ev.get("id") or ""),closed_at=rts(m.get("closedTime")),
                                              rate=((rate if rate is not None else 0.07) if on else 0.0),exp=(num(fs.get("exponent")) or 1.0),combo=is_combo(m))
        for c in part:
            if c not in tab: tab[c]=None
        if i%200==0: save(p,tab); print("  market details",i,"/",len(todo))
    save(p,tab); return tab
def tape(cond,since,until):
    """Taker buys of one market covering [since, until], in the order they happened: [(ts, outcome_index, price)].
    At most MAXPAGES pages; lo/hi record how far the walk reached, so each copy can check its own window. The walk
    direction is read from the pages (newest-first is expected)."""
    p=os.path.join(D_PM,"tapes",cond+".json"); have=load(p)
    if have and have["since"]<=since and have["until"]>=until: return have
    pages=[]; cur=None; n=0; natural=False; lo=hi=None
    while n<MAXPAGES:
        prm=dict(condition=cond,side="BUY",limit=1000); prm.update(cursor=cur) if cur else None
        j=http(PM+"/v2/trades",prm); rows=[(r.get("timestamp"),r.get("outcome_index"),num(r.get("price"))) for r in (j.get("data") or []) if r.get("timestamp") is not None]; n+=1
        pages.append(rows)
        for t,_,_ in rows: lo=t if lo is None else min(lo,t); hi=t if hi is None else max(hi,t)
        pg=j.get("pagination") or {}; cur=pg.get("next_cursor")
        if not cur or pg.get("has_more") is False or not rows: natural=True; break
        allr=[x for pgs in pages for x in pgs]
        desc=allr[0][0]>=allr[-1][0] if allr else True
        if (desc and lo is not None and lo<since) or (not desc and hi is not None and hi>until): break
    allr=[x for pgs in pages for x in pgs]
    desc=(allr[0][0]>=allr[-1][0]) if allr else True
    seq=list(reversed(allr)) if desc else allr   # oldest first, keeping the API's order within a second
    seq=[x for x in seq if x[1] is not None and x[2] is not None]
    # a newest-first walk saw everything after lo; an oldest-first walk saw everything before hi
    obj=dict(since=since,until=until,complete=natural,lo=lo,hi=hi,from_newest=desc,from_oldest=not desc,
             rows=[list(x) for x in seq if since<=x[0]<=until+WINDOW])
    save(p,obj); return obj
def candidate_copies(w,meta,why):
    """A wallet's copyable buys (PLAN4 P2 rules), before the copy price is looked up."""
    buys=sorted(user_buys(w)["rows"],key=lambda b:b.get("timestamp") or 0)
    taker=user_taker_keys(w)
    out=[]; hist={}; seen=set()
    for b in buys:
        t=b.get("timestamp") or 0; c=b["condition_id"]; oi=b.get("outcome_index")
        prev=hist.setdefault(c,[]); before=[(x,o) for x,o in prev if t-7*86400<=x<t]; prev.append((t,oi))
        if not (E0<=t<E1): continue
        m=meta.get(c)
        if not m: count(why,"no market details"); continue
        if m.get("combo"): count(why,"combo market"); continue
        try: e=ts(m["end"])
        except (ValueError,KeyError): count(why,"no end date"); continue
        if not (EEND0<=e<EEND1): count(why,"end date outside the window"); continue
        if (b.get("price") or 1)>=CAP: count(why,"bought at 0.97 or more"); continue
        if any(o!=oi for x,o in before): count(why,"hedge (other outcome in the 7 days before)"); continue
        k=(c,oi,datetime.fromtimestamp(t,timezone.utc).date().isoformat())
        if k in seen: count(why,"not the first buy that day"); continue
        seen.add(k)
        out.append(dict(w=w,cond=c,oi=oi,t=t,own_price=b.get("price"),event=m["event"] or c,end=e,
                        maker="%s:%s"%(b.get("transaction_hash"),b.get("token_id")) not in taker))
    return out
def pcopies():
    S=load(os.path.join(OUT,"plan4_selected.json")) or sys.exit("run pselect first")
    ws=S["selected"]+S["placebo"]; conds=set(); nbuys=0
    for i,w in enumerate(ws):
        for b in user_buys(w)["rows"]:
            if E0<=(b.get("timestamp") or 0)<E1: conds.add(b["condition_id"]); nbuys+=1
        user_taker_keys(w)
        if i%25==0: print("  buys",i,"/",len(ws))
    meta=gamma_meta(conds,refresh=True); why={}; copies=[]
    for grp in ("selected","placebo"):
        for w in S[grp]:
            for c in candidate_copies(w,meta,why): c["group"]=grp; copies.append(c)
    resolutions([c["cond"] for c in copies]); payouts([c["cond"] for c in copies])
    need={}
    for c in copies:
        lo,hi=need.get(c["cond"],(1e18,0)); need[c["cond"]]=(min(lo,c["t"]+DELAY),max(hi,c["t"]+7200+WINDOW))
    fails=0; fp=os.path.join(D_PM,"tapes_failed.json"); failed=load(fp,{})
    for i,(cond,(lo,hi)) in enumerate(sorted(need.items())):
        if failed.get(cond,0)>=3: continue   # failed 3 runs: its copies count as "no trade list"
        try: tape(cond,lo,hi); failed.pop(cond,None)
        except RuntimeError as ex: fails+=1; failed[cond]=failed.get(cond,0)+1; print("  trade list failed for",cond[:10],ex)
        if i%50==0: print("  trade lists",i,"/",len(need)); save(fp,failed)
    save(fp,failed)
    save(os.path.join(D_PM,"copies.json"),dict(fetched=now(),copies=copies,skipped=why,evaluation_buys=nbuys,evaluation_markets=len(conds),
                                               markets_without_details=sum(1 for c in conds if not meta.get(c))))
    print("pcopies done:",len(copies),"candidate copies in",len(need),"markets; skipped",why,"; trade lists failed",fails,"(run again to retry)")
def covered(tp,t0):
    """Does the trade list reach the copy's window [t0, t0+WINDOW]?"""
    if tp["complete"]: return True
    low=tp.get("from_oldest") or (tp.get("lo") is not None and tp["lo"]<=t0)
    high=tp.get("from_newest") or (tp.get("hi") is not None and tp["hi"]>=t0+WINDOW)
    return bool(low and high)
def copy_price(c,delay,res,meta):
    """The first taker buy of the same outcome at or after the buy + delay and within the hour, before close or
    resolution; when several fills of that outcome share that second (one order sweeping prices), the highest."""
    tp=load(os.path.join(D_PM,"tapes",c["cond"]+".json"))
    if not tp: return None,"no trade list"
    t0=c["t"]+delay
    if not covered(tp,t0): return None,"trade list too long"
    end_at=min(x for x in (res.get(c["cond"]),(meta.get(c["cond"]) or {}).get("closed_at"),1e18) if x)
    first=None; best=None
    for t,oi,p in tp["rows"]:
        if t<t0 or oi!=c["oi"]: continue
        if first is None:
            if t>t0+WINDOW: return None,"no buy within the hour"
            if t>=end_at: return None,"after close or resolution"
            first=t
        if t!=first: break
        best=p if best is None else max(best,p)
    if best is None: return None,"no buy within the hour"
    if best>=CAP: return None,"price 0.97 or more"
    return best,None
def score_copies(copies,res,pay,meta,delay=DELAY):
    rows=[]; why={}
    for c in copies:
        ra=res.get(c["cond"])
        if not ra or ra>=RESOLVED_BY: count(why,"not resolved by Oct 14"); continue
        p,reason=copy_price(c,delay,res,meta)
        if p is None: count(why,reason); continue
        po=(pay.get(c["cond"]) or {}).get(str(c["oi"]))
        if po is None: count(why,"no payout"); continue
        m=meta.get(c["cond"]) or {}; f=(m.get("rate") or 0)*(p*(1-p))**(m.get("exp") or 1.0)
        price=p+f
        rows.append(dict(c,price=p,fee=f,profit=po/price-1,var=(p*(1-p))/price**2,pay=po))
    return rows,why
def event_units(rows,key="profit",weight=None):
    """One unit per event: (mean value, conservative null variance (mean SD)^2, end-date cluster). With a per-copy
    weight the means are weighted and the unit carries its total weight, so cl_se weights events by it."""
    g={}
    for r in rows: g.setdefault(r["event"],[]).append(r)
    out=[]
    for e,v in g.items():
        w=[(weight(x) if weight else 1.0) for x in v]; W=sum(w)
        if W<=0: continue
        sd=sum(wi*x["var"]**0.5 for wi,x in zip(w,v))/W
        u=(sum(wi*x[key] for wi,x in zip(w,v))/W,sd*sd,min(x["end"] for x in v)); out.append(u+(W,) if weight else u)
    return out
def consensus(copies):
    """One copy per outcome when 3 different wallets bought it within 24 hours: at the 3rd buy."""
    byo={}
    for c in copies: byo.setdefault((c["cond"],c["oi"]),[]).append(c)
    out=[]
    for k,v in sorted(byo.items()):
        v=sorted(v,key=lambda c:(c["t"],c["w"]))
        for j in range(len(v)):
            if len({c["w"] for c in v[:j+1] if v[j]["t"]-c["t"]<=86400})>=3: out.append(dict(v[j])); break
    return out
def tenth(p): return min(9,int(p*10))
def reweighted(sel_rows,pl_rows):
    """The placebo reweighted to the selected copies' mix of copy-price tenths: each placebo copy gets the weight
    share_selected[b] / share_placebo[b] (copy shares), so the mean is sum over tenths of share_selected[b] x the
    placebo's mean in b. A tenth with fewer than 5 placebo events is pooled with its nearest neighbour. Returns (mean,
    SE from ONE weighted cl_se over the placebo's events, the pooling map)."""
    if not sel_rows or not pl_rows: return None,None,{}
    bins={b:b for b in range(10)}
    def events_in(b): return len({r["event"] for r in pl_rows if bins[tenth(r["price"])]==b})
    for b in range(10):
        if any(tenth(r["price"])==b for r in sel_rows+pl_rows) and events_in(bins[b])<5:
            cands=sorted((x for x in range(10) if x!=b and events_in(bins[x])>=5),key=lambda x:(abs(x-b),x))
            if cands:
                old=bins[b]
                for k in bins:
                    if bins[k]==old: bins[k]=bins[cands[0]]
    share_s={}; share_p={}
    for r in sel_rows: share_s[bins[tenth(r["price"])]]=share_s.get(bins[tenth(r["price"])],0)+1/len(sel_rows)
    for r in pl_rows: share_p[bins[tenth(r["price"])]]=share_p.get(bins[tenth(r["price"])],0)+1/len(pl_rows)
    wt=lambda r:share_s.get(bins[tenth(r["price"])],0)/share_p[bins[tenth(r["price"])]]
    m,se=cl_se(event_units(pl_rows,weight=wt))
    return m,se,{b:bins[b] for b in range(10) if bins[b]!=b}
def scoreP():
    res_path=once("plan4_P.json")
    S=load(os.path.join(OUT,"plan4_selected.json")) or sys.exit("run pselect first")
    C=load(os.path.join(D_PM,"copies.json")) or sys.exit("run pcopies first")
    if len(S["coverage_failed"])>0.10*max(1,S["coverage_checked"]):
        R=dict(scored=now(),verdict="NOT SCORED",reason="%d of %d checked wallets failed the position-coverage check (more than 10%%)"%(len(S["coverage_failed"]),S["coverage_checked"]))
        save(res_path,R); print(R["reason"]); return
    copies=C["copies"]; need={}; tf=load(os.path.join(D_PM,"tapes_failed.json"),{})
    for c in copies: need.setdefault(c["cond"],[]).append(c["t"])
    missing=[c for c in need if not os.path.exists(os.path.join(D_PM,"tapes",c+".json")) and tf.get(c,0)<3]
    if missing: sys.exit("Not scored: %d markets have no trade list yet. Run pcopies again."%len(missing))
    if C.get("markets_without_details",0)>0.10*max(1,C.get("evaluation_markets",0)):
        sys.exit("Not scored (nothing saved): Gamma returned no details for %d of %d evaluation markets; a data problem."%(C["markets_without_details"],C["evaluation_markets"]))
    fa=S.get("fee_adjust",0.0); bad=set(S["coverage_failed"]); sel=[w for w in S["selected"] if w not in bad]; elig=[w for w in S["eligible"] if w not in bad]
    # P1 (informational): every condition of every wallet-event must have resolved by Oct 14
    skip_eval={}
    wes={w:wallet_events(positions_of(w)["rows"],"evaluation",fa,skip_eval) for w in elig}
    allc={c for we in wes.values() for x in we.values() for c in x["conds"]}
    res=resolutions(allc,refresh=True)
    def guard(cs,what):
        cs=set(cs); r=[c for c in cs if res.get(c)]
        if cs and len(r)<0.90*len(cs): sys.exit("Not scored (nothing saved): only %d of %d %s have a resolution record; a data problem (PLAN4 checks)."%(len(r),len(cs),what))
    guard(allc,"evaluation wallet-event markets")
    def ok(x): return all(res.get(c) and res[c]<RESOLVED_BY for c in x["conds"])
    for we in wes.values():
        for x in we.values():
            if not ok(x): count(skip_eval,"a market not resolved by Oct 14")
    def units(ws):
        g={}
        for w in ws:
            for e,x in wes[w].items():
                if ok(x): g.setdefault(e,[]).append(x)
        out={}
        for e,v in g.items():
            sd=sum(x["var"]**0.5 for x in v)/len(v); out[e]=(sum(x["ret"] for x in v)/len(v),sd*sd,min(x["end"] for x in v))
        return out
    selset=set(sel)
    us=units(sel); ur=units([w for w in elig if w not in selset])
    m1,se1=cl_se(list(us.values())); t1=tstat(m1,se1)
    pairs=[(us[e][0]-ur[e][0],us[e][1]+ur[e][1],us[e][2]) for e in us if e in ur]; m2,se2=cl_se(pairs); t2=tstat(m2,se2)
    nsel=sum(1 for w in sel if any(ok(x) for x in wes[w].values()))
    p1="NOT TESTABLE" if (nsel<25 or len(us)<60) else ("PASS" if (t1 is not None and t1>=2.5 and t2 is not None and t2>=2) else "FAIL")
    # P1 descriptive
    def pooled(ws):
        pr=cs=0.0
        for w in ws:
            for x in wes[w].values():
                if ok(x): pr+=x["profit"]; cs+=x["cost"]
        return pr/cs if cs else None
    form=S.get("formation_all") or {}
    ev_ret={w:mean([x["ret"] for x in wes[w].values() if ok(x)]) for w in elig}
    tt=[(form[w]["t"],ev_ret[w]) for w in elig if w in form and form[w].get("t") is not None and ev_ret[w] is not None]
    by_tenth={}
    for grp,ws in (("selected",sel),("rest",[w for w in elig if w not in selset])):
        for w in ws:
            for x in wes[w].values():
                if ok(x): by_tenth.setdefault(grp,{}).setdefault(tenth(x["avg"]),[]).append(x["ret"])
    p1desc=dict(pooled_return_selected=pooled(sel),pooled_return_rest=pooled([w for w in elig if w not in selset]),
                rank_corr_formation_t_vs_evaluation=rank_corr([a for a,b in tt],[b for a,b in tt]) if tt else None,
                selected_without_evaluation=sum(1 for w in sel if not any(ok(x) for x in wes[w].values())),excluded=skip_eval,
                by_price_tenth={g:{str(k):dict(n=len(v),mean=mean(v)) for k,v in sorted(d.items())} for g,d in by_tenth.items()})
    # P2, placebo, P2c
    copies=[c for c in copies if c["w"] not in bad]
    res=resolutions([c["cond"] for c in copies],refresh=True); pay=payouts([c["cond"] for c in copies],refresh=True); meta=load(os.path.join(D_PM,"gamma_meta.json"),{})
    guard([c["cond"] for c in copies],"copied markets")
    rc={c["cond"] for c in copies if res.get(c["cond"]) and res[c["cond"]]<RESOLVED_BY}
    paid=[c for c in rc if pay.get(c) and all(v is not None for v in pay[c].values())]
    if rc and len(paid)<0.90*len(rc): sys.exit("Not scored (nothing saved): only %d of %d resolved copied markets have payouts; a data problem."%(len(paid),len(rc)))
    sc,why=score_copies([c for c in copies if c["group"]=="selected"],res,pay,meta)
    pl,whyp=score_copies([c for c in copies if c["group"]=="placebo"],res,pay,meta)
    mP,seP=cl_se(event_units(sc)); tP=tstat(mP,seP); nev=len({r["event"] for r in sc})
    mPl,sePl,pooling=reweighted(sc,pl)
    diff=(mP-mPl) if (mP is not None and mPl is not None) else None
    sed=(seP**2+sePl**2)**0.5 if (diff is not None and seP is not None and sePl is not None) else None; td=tstat(diff,sed)
    p2="NOT TESTABLE" if (len(sc)<300 or nev<60) else ("PASS" if (tP is not None and tP>=2.5 and td is not None and td>=2) else "FAIL")
    scc,whyc=score_copies(consensus([c for c in copies if c["group"]=="selected"]),res,pay,meta)
    mC,seC=cl_se(event_units(scc)); tC=tstat(mC,seC); nevc=len({r["event"] for r in scc})
    p2c="NOT TESTABLE" if (len(scc)<100 or nevc<40) else ("PASS" if tC is not None and tC>=2.5 else "FAIL")
    desc={}
    for d in (1800,7200):
        r_,_=score_copies([c for c in copies if c["group"]=="selected"],res,pay,meta,delay=d); m_,s_=cl_se(event_units(r_)); desc["copy %d minutes late"%(d//60)]=dict(copies=len(r_),mean=m_,se=s_)
    for role in (True,False):
        g=[r for r in sc if r["maker"]==role]; m_,s_=cl_se(event_units(g)); desc["copies of maker fills" if role else "copies of taker fills"]=dict(copies=len(g),mean=m_,se=s_)
    own=[dict(r,profit=r["pay"]/r["own_price"]-1) for r in sc if r.get("own_price")]
    m_,s_=cl_se(event_units(own)); desc["the wallets' own prices on the same buys"]=dict(copies=len(own),mean=m_,se=s_)
    m_,s_=cl_se(event_units(pl)); desc["placebo, not reweighted"]=dict(copies=len(pl),mean=m_,se=s_)
    R=dict(plan="research/PLAN4.md",scored=now(),wallets=dict(selected=len(sel),eligible=len(elig),coverage_failed=len(bad)),fee_adjust=fa,
           P1=dict(verdict=p1,selected_wallets_scored=nsel,events=len(us),mean=m1,se=se1,t=t1,vs_rest=dict(events=len(pairs),mean=m2,se=se2,t=t2),descriptive=p1desc),
           P2=dict(verdict=p2,copies=len(sc),events=nev,mean=mP,se=seP,t=tP,placebo=dict(copies=len(pl),reweighted_mean=mPl,se=sePl,pooled_tenths=pooling,not_copied=whyp),
                   vs_placebo=dict(diff=diff,se=sed,t=td),not_copied=why,skipped_before_pricing=C.get("skipped")),
           P2c=dict(verdict=p2c,copies=len(scc),events=nevc,mean=mC,se=seC,t=tC,not_copied=whyc),descriptive=desc)
    save(res_path,R)
    pc=lambda x:"n/a" if x is None else "%+.1f%%"%(100*x)
    tt_=lambda x:"n/a" if x is None else ("inf" if x==float("inf") else "%.2f"%x)
    L=["# PLAN4 Polymarket tests (scored once, %s)"%R["scored"],"","Rules: research/PLAN4.md. Wallets are public addresses; none is named here.","",
       "| Test | Verdict | Result | Needed |","|---|---|---|---|",
       "| P1 skill persists (informational) | %s | selected wallets %s per $ (t %s) over %d events; vs the rest %s (t %s) | 2.5 SE, and 2 SE vs the rest |"%(p1,pc(m1),tt_(t1),len(us),pc(m2),tt_(t2)),
       "| P2 copy 5 minutes late | %s | %s per $ (t %s), %d copies in %d events; placebo %s; difference t %s | 2.5 SE with 300 copies in 60 events, and 2 SE vs the placebo |"%(p2,pc(mP),tt_(tP),len(sc),nev,pc(mPl),tt_(td)),
       "| P2c three agree | %s | %s per $ (t %s), %d copies in %d events | 2.5 SE with 100 copies in 40 events |"%(p2c,pc(mC),tt_(tC),len(scc),nevc),"",
       "Not copied (P2): %s."%(", ".join("%s %d"%kv for kv in sorted(why.items())) or "none"),
       "P1 descriptive: pooled dollar return selected %s, rest %s; rank correlation of formation t with evaluation return %s; selected wallets with no evaluation positions %d."%(
           pc(p1desc["pooled_return_selected"]),pc(p1desc["pooled_return_rest"]),"n/a" if p1desc["rank_corr_formation_t_vs_evaluation"] is None else "%.2f"%p1desc["rank_corr_formation_t_vs_evaluation"],p1desc["selected_without_evaluation"]),
       "Descriptive: %s."%"; ".join("%s %s over %d"%(k,pc(v["mean"]),v["copies"]) for k,v in desc.items()),
       "","A FAIL usually means the test could not tell, not that there is no edge (PLAN4 power table)."]
    open(os.path.join(OUT,"plan4_P.md"),"w",encoding="utf-8").write("\n".join(L)+"\n"); print("\n".join(L))

# ================= Kalshi K1 =================
D_K=os.path.join(DATA,"k1")
def kdate(event_ticker,close_ts=None):
    m=re.search(r"-(\d{2}[A-Z]{3}\d{2})",event_ticker or "")
    if m:
        try: return datetime.strptime(m.group(1),"%y%b%d").date().isoformat()
        except ValueError: pass
    return datetime.fromtimestamp(close_ts,timezone.utc).date().isoformat() if close_ts else None
def kreduce(m):
    """A settled market in the K1 window, reduced to the fields needed (None if it does not qualify)."""
    t=m.get("ticker") or ""
    if "COMBO" in t.upper() or t.startswith("KXMVE"): return None
    ct=rts(m.get("close_time"))
    if ct is None or not (K0<=ct<K1END) or m.get("result") not in ("yes","no"): return None
    v=num(m.get("volume_fp")); v=v if v is not None else num(m.get("volume"))
    return dict(ticker=t,event=m.get("event_ticker"),series=(m.get("event_ticker") or t).split("-")[0],result=m.get("result"),volume=v,close=ct)
def kseries():
    """Rank series by the volume of settled markets with a scheduled close in the window, from Kalshi's live listing
    (which can be filtered by close time); then read the archive (which cannot) series by series for the 40 chosen."""
    out=os.path.join(OUT,"plan4_series.json")
    if os.path.exists(out): sys.exit("plan4_series.json is frozen; PLAN4 never reselects.")
    q=dict(status="settled",min_close_ts=K0,max_close_ts=K1END,mve_filter="exclude",limit=1000)
    lp=os.path.join(D_K,"live_volume.json"); agg=load(lp); fresh=agg is None
    if fresh:   # pass 1: volume per series only (millions of markets; nothing per market is kept)
        agg={}
        def tally(m):
            r=kreduce(m)
            if r:
                a=agg.setdefault(r["series"],[0.0,0,0]); a[1]+=1
                if r["volume"] is None: a[2]+=1
                else: a[0]+=r["volume"]
            return None
        k_pages("/markets",q,"markets",tally)
    nm=sum(a[1] for a in agg.values()); novol=sum(a[2] for a in agg.values())
    if not nm or novol>0.05*nm or sum(a[0] for a in agg.values())<=0:
        sys.exit("Not frozen: %d of %d listed markets have no volume field; the ranking would be meaningless (nothing saved)."%(novol,nm))
    if fresh: save(lp,agg)   # cached only once it passes the volume check
    vol={x:a[0] for x,a in agg.items()}
    top=[x for x in sorted(vol,key=lambda x:(-vol[x],x)) if "COMBO" not in x.upper()][:40]
    allm={}; fee={}; ftype={}; counts={}; live={}
    for x in top:   # pass 2: the chosen series' markets, from the live listing filtered by series, then the archive
        sp=os.path.join(D_K,"live",x+".json"); lv=load(sp)
        if lv is None: lv=k_pages("/markets",dict(q,series_ticker=x),"markets",kreduce); save(sp,lv)
        if abs(len(lv)-agg[x][1])>max(2,0.01*agg[x][1]): sys.exit("Not frozen: series %s listed %d markets in pass 1 but %d by series; check before freezing."%(x,agg[x][1],len(lv)))
        for m in lv: allm[m["ticker"]]=m; live[m["ticker"]]=m
        ap=os.path.join(D_K,"archive",x+".json"); arch=load(ap)
        if arch is None: arch=k_pages("/historical/markets",dict(series_ticker=x,limit=1000),"markets",kreduce); save(ap,arch)
        for m in arch: allm.setdefault(m["ticker"],m)
        j=http(KALSHI+"/series/"+x,{}).get("series") or {}
        fee[x]=num(j.get("fee_multiplier")); ftype[x]=j.get("fee_type")
        counts[x]=dict(live=sum(1 for m in live.values() if m["series"]==x),archive=len(arch))
    bad=[x for x,v in fee.items() if v is None or not (v==0 or 0.25<=v<=2)]
    print("fee multipliers:",fee); print("fee types:",ftype); print("markets per series (live, archive):",counts)
    if bad: sys.exit("Not frozen: fee multipliers missing or not on the relative scale for %s; check before freezing (PLAN4 fee rule)."%bad)
    odd=[x for x,v in ftype.items() if v not in QUADRATIC]
    if odd: sys.exit("Not frozen: fee type not quadratic for %s (%s); the taker fee rule would not apply."%(odd,[ftype[x] for x in odd]))
    pick={}
    for x in top:
        tick=sorted(t for t,m in allm.items() if m["series"]==x)
        pick[x]=random.Random(SEED).sample(tick,min(300,len(tick)))
    save(os.path.join(D_K,"markets.json"),{t:allm[t] for x in top for t in pick[x]})
    os.makedirs(OUT,exist_ok=True)
    save(out,dict(created=now(),series=top,ranking_volume={x:vol[x] for x in top},fee_multiplier=fee,fee_type=ftype,counts=counts,
                  markets_in_window={x:sum(1 for m in allm.values() if m["series"]==x) for x in top},markets_per_series={x:len(pick[x]) for x in top}))
    print("K1 series:",top)
QUADRATIC=("quadratic","quadratic_with_maker_fees")   # the taker fee is round up(0.07 x multiplier x C x P x (1-P)) for both
TRADES="trades2"   # trade lists from both endpoints, merged by trade_id (the first code read one endpoint only)
def kprice(r,side):
    v=num(r.get(side+"_price_dollars"))
    if v is None:
        c=num(r.get(side+"_price")); v=c/100 if c is not None else None
    return v
def ktrades():
    """Each sampled market's trades from BOTH the archive (/historical/trades, trades before Kalshi's cutoff) and the
    live endpoint, merged by trade_id, so a market whose trades straddle the cutoff keeps all of them. Both walks must
    succeed; a failure is not saved and is retried on the next run."""
    ms=load(os.path.join(D_K,"markets.json")) or sys.exit("run kseries first")
    fails=[]
    for i,t in enumerate(sorted(ms)):
        p=os.path.join(D_K,TRADES,t+".json")
        if os.path.exists(p): continue
        rows={}; err=None
        for path in ("/historical/trades","/markets/trades"):
            try: got=k_pages(path,dict(ticker=t,limit=1000),"trades")
            except RuntimeError as ex: err=ex; break
            for r in got: rows[r.get("trade_id") or (r.get("created_time"),r.get("taker_side"),r.get("count_fp"),r.get("yes_price_dollars"))]=r
        if err is not None: fails.append(t); print("  trades failed for",t,err); continue   # not saved: retried next run
        save(p,[dict(id=r.get("trade_id"),ts=rts(r.get("created_time")),ct=r.get("created_time"),side=r.get("taker_side"),
                     n=num(r.get("count_fp")) if num(r.get("count_fp")) is not None else (num(r.get("count")) or 0),
                     yes=kprice(r,"yes"),no=kprice(r,"no"),block=bool(r.get("is_block_trade"))) for r in rows.values()])
        if i%200==0: print("  trade lists",i,"/",len(ms))
    print("ktrades done; failed",len(fails),"(run again to retry)")
def korders(rows):
    """Taker orders: fills of one market with the same created_time and taker side. Orders with no contracts or no
    price are dropped."""
    g={}
    for r in rows:
        if r["ts"] is None or r["side"] not in ("yes","no"): continue
        p=r["yes"] if r["side"]=="yes" else r["no"]
        if p is None or p<=0 or not r["n"]: continue
        k=(r["ct"],r["side"]); x=g.setdefault(k,dict(ts=r["ts"],ct=r["ct"],side=r["side"],notional=0.0,max_price=0.0,n=0.0,block=False))
        x["notional"]+=r["n"]*p; x["max_price"]=max(x["max_price"],p); x["n"]+=r["n"]; x["block"]=x["block"] or r["block"]
    return sorted((o for o in g.values() if o["n"]>0 and o["max_price"]>0),key=lambda o:(o["ts"],o["ct"]))
def kfee(p,mult): return math.ceil(mult*0.07*p*(1-p)*100-1e-9)/100   # Kalshi: round up(0.07 x multiplier x C x P x (1-P)), C = 1
def kcopies(od,y,mult,lo,hi,why):
    """K1 copies from one market's orders: orders with notional in [lo, hi) and not block trades, copied at the next
    other non-block order on that side 60 s to 60 min later; at most one copy per side within 60 minutes of a copy."""
    out=[]; last={}
    for i,o in enumerate(od):
        if not (lo<=o["notional"]<hi) or o["block"]: continue
        won=1 if o["side"]==y else 0
        q=None
        for j in range(i+1,len(od)):   # orders are in time order: stop once past the hour
            x=od[j]
            if x["ts"]-o["ts"]>3600: break
            if x["side"]==o["side"] and not x["block"] and x["ts"]-o["ts"]>=60: q=x; break
        if q is None: count(why,"no later order"); continue
        p=q["max_price"]
        if p>=CAP: count(why,"price 97c or more"); continue
        if q["ts"]-last.get(o["side"],-1e18)<3600: count(why,"copied within the hour"); continue
        last[o["side"]]=q["ts"]; f=kfee(p,mult)
        out.append(dict(t=o["ts"],side=o["side"],price=p,fee=f,profit=won-p-f,var=p*(1-p),own_excess=won-o["max_price"]))
    return out
def kunits(copies):
    g={}
    for c in copies: g.setdefault(c["date"],[]).append(c)
    return g,[(sum(x["profit"] for x in v)/len(v),(sum(x["var"]**0.5 for x in v)/len(v))**2,dd) for dd,v in g.items()]
def scoreK():
    res=once("plan4_K.json")
    S=load(os.path.join(OUT,"plan4_series.json")) or sys.exit("run kseries first"); ms=load(os.path.join(D_K,"markets.json"))
    miss=[t for t in ms if not os.path.exists(os.path.join(D_K,TRADES,t+".json"))]
    if miss: sys.exit("Not scored: %d markets have no trade list yet. Run ktrades again."%len(miss))
    ftype=S.get("fee_type") or {x:(http(KALSHI+"/series/"+x,{}).get("series") or {}).get("fee_type") for x in S["series"]}
    odd=[x for x in S["series"] if ftype.get(x) not in QUADRATIC or S["fee_multiplier"].get(x) is None]
    if odd: sys.exit("Not scored (nothing saved): fee type or multiplier unusable for %s."%odd)
    tl=lambda t:load(os.path.join(D_K,TRADES,t+".json"))
    nrow=noprice=0
    for t in ms:   # first pass: a data check only (files are read twice to keep memory small)
        v=tl(t); nrow+=len(v); noprice+=sum(1 for r in v if (r["yes"] if r["side"]=="yes" else r["no"]) is None)
    if nrow==0 or noprice>0.05*nrow: sys.exit("Not scored (nothing saved): %d of %d trade rows have no price for the taker's side; a data problem."%(noprice,nrow))
    copies=[]; small=[]; why={}; whys={}; large=[]; fell_back=0
    for t,m in sorted(ms.items()):
        od=korders(tl(t)); y=m["result"]; mult=S["fee_multiplier"].get(m["series"])
        d=kdate(m["event"]);
        if d is None: d=kdate("",m.get("close")); fell_back+=1
        for o in od:
            if o["notional"]>=1000 and not o["block"]: large.append((1 if o["side"]==y else 0)-o["max_price"])
        for c in kcopies(od,y,mult,1000,1e18,why): c.update(ticker=t,series=m["series"],date=d); copies.append(c)
        for c in kcopies(od,y,mult,0,50,whys): c.update(ticker=t,series=m["series"],date=d); small.append(c)
    g,units=kunits(copies); mK,seK=cl_se(units); tK=tstat(mK,seK)
    gs,units_s=kunits(small); mS,seS=cl_se(units_s)
    verdict="NOT TESTABLE" if (len(copies)<300 or len(g)<40) else ("PASS" if tK is not None and tK>=2.5 else "FAIL")
    nolater=why.get("no later order",0)
    R=dict(plan="research/PLAN4.md K1",scored=now(),verdict=verdict,copies=len(copies),dates=len(g),mean=mK,se=seK,t=tK,large_orders=len(large),
           markets=len(ms),trade_rows=nrow,rows_without_price=noprice,fee_type=ftype,
           no_later_order_share=(nolater/len(large)) if large else None,not_copied=why,large_own_excess=mean(large),dates_from_close_time=fell_back,
           small_orders=dict(copies=len(small),dates=len(gs),mean=mS,se=seS,not_copied=whys),
           by_series={s:dict(copies=len(v),mean=mean([x["profit"] for x in v])) for s in S["series"] for v in [[c for c in copies if c["series"]==s]] if v})
    R["sample_for_quote_check"]=[dict(ticker=x["ticker"],t=x["t"],side=x["side"],price=x["price"]) for x in random.Random(SEED).sample(copies,min(300,len(copies)))]
    save(res,R)
    c=lambda x:"n/a" if x is None else "%+.1fc"%(100*x)
    L=["# PLAN4 test K1: large trades on Kalshi (scored once, %s)"%R["scored"],"","**Verdict: %s.** %d copies over %d market dates: %s per contract after fees (t %s). Needed: 2.5 SE, 300 copies, 40 dates."%(
        verdict,len(copies),len(g),c(mK),"%.2f"%tK if tK is not None else "n/a"),"",
        "Large orders: %d; with no later order on their side within the hour: %s. The large orders' own excess win rate: %s. Copying orders under $50 the same way: %s per contract over %d copies."%(
        len(large),"%.0f%%"%(100*R["no_later_order_share"]) if R["no_later_order_share"] is not None else "n/a",c(R["large_own_excess"]),c(mS),len(small)),
        "Not copied: %s. Market dates read from the close time (no date in the ticker): %d markets."%(", ".join("%s %d"%kv for kv in sorted(why.items())) or "none",fell_back)]
    open(os.path.join(OUT,"plan4_K.md"),"w",encoding="utf-8").write("\n".join(L)+"\n"); print("\n".join(L))
def kquotes():
    """Descriptive check after scoring: the standing ask at the first minute candle ending at least 60 s after each sampled
    large order, against the copy price (a real copier buys at the ask, whether or not another taker shows up)."""
    R=load(os.path.join(OUT,"plan4_K.json")) or sys.exit("score K1 first")
    if R.get("quote_check"): sys.exit("quote check already done")
    import plan3
    F=plan3.fx(); gaps=[]
    for x in R.get("sample_for_quote_check",[]):
        cs=plan3.fetch_candles(F,[(x["ticker"],False,x["t"],x["t"]+3600)]).get(x["ticker"]) or []
        k=[c for c in sorted(cs,key=lambda c:c["end_period_ts"]) if c["end_period_ts"]>=x["t"]+60]
        if not k: continue
        ya,yb=F._v(k[0].get("yes_ask"),"close"),F._v(k[0].get("yes_bid"),"close")
        ask=ya if x["side"]=="yes" else ((1-yb) if yb is not None else None)
        if ask is not None and 0<ask<1: gaps.append(ask-x["price"])
    gaps.sort(); R["quote_check"]=dict(n=len(gaps),median_ask_minus_copy_price=gaps[len(gaps)//2] if gaps else None)
    save(os.path.join(OUT,"plan4_K.json"),R); print(R["quote_check"])

if __name__=="__main__":
    try: sys.stdout.reconfigure(errors="replace")
    except AttributeError: pass
    cmds=dict(pmarkets=pmarkets,ppool=ppool,ppositions=ppositions,pselect=pselect,pcopies=pcopies,scoreP=scoreP,kseries=kseries,ktrades=ktrades,scoreK=scoreK,kquotes=kquotes)
    cmd=sys.argv[1] if len(sys.argv)>1 else ""
    if cmd not in cmds: sys.exit(__doc__)
    cmds[cmd]()
