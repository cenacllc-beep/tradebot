"""Market research: what trades on Kalshi, and how Kalshi's prices compare with Polymarket's on the same questions.
Research only (CLAUDE.md section 7, approved by the user 2026-10-14). Read-only public data; places no orders; never
touches paper.db or live.db. Python 3.8+, needs requests.

  python research/markets.py kalshi      snapshot of every open Kalshi market (combos excluded) -> data/snap/kalshi_*.jsonl
  python research/markets.py poly        snapshot of active Polymarket markets -> data/snap/poly_*.jsonl
  python research/markets.py inventory   results/inventory.md: Kalshi series ranked by trading, with a note on public data
  python research/markets.py match       results/gap_candidates.md: possible same-question pairs for a person to check
  python research/markets.py gaps        results/gaps.md: price gaps for the pairs listed in data/pairs.json (checked by hand)

A price gap is not an arbitrage unless both markets settle on exactly the same thing. Kalshi and Polymarket often use
different sources (for example different weather stations), different cut-off times or different wording, so every
pair is checked by hand against both rule texts before it goes into data/pairs.json. Fees: Kalshi taker fee =
0.07 x p x (1-p) per contract (rounded up to the cent); Polymarket taker fee = rate x p x (1-p) per share, with the rate
from the market's own fee schedule (0 when fees are off). Trading on Polymarket depends on where you live; this file
only reads public prices."""
import os, sys, json, time, re, glob, math
from datetime import datetime, timezone
import requests
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
sys.path.insert(0,ROOT)
from config import KALSHI_BASE
DATA=os.path.join(HERE,"data"); SNAP=os.path.join(DATA,"snap"); OUT=os.path.join(HERE,"results")
UA={"User-Agent":"tradebot-paper-research/1.0"}
GAMMA="https://gamma-api.polymarket.com"
def stamp(): return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
def fnum(v):
    try: return None if v in (None,"") else float(v)
    except (TypeError,ValueError): return None
def get(url,params=None,tries=4):
    """GET with retries for rate limits (429), server errors and dropped connections. Other 4xx answers (404, 422) are
    raised at once: asking again would not change them."""
    for i in range(tries):
        try: r=requests.get(url,params=params,headers=UA,timeout=30)
        except requests.RequestException:
            if i==tries-1: raise
            time.sleep(2*(i+1)); continue
        if r.status_code==429 or r.status_code>=500:
            if i==tries-1: r.raise_for_status()
            time.sleep(3*(i+1)); continue
        r.raise_for_status(); return r.json()
def latest(prefix):
    fs=sorted(glob.glob(os.path.join(SNAP,prefix+"_*.jsonl")))
    if not fs: sys.exit("No %s snapshot yet: run python research/markets.py %s"%(prefix,prefix))
    return fs[-1],[json.loads(l) for l in open(fs[-1],encoding="utf-8")]
def save(prefix,rows):
    os.makedirs(SNAP,exist_ok=True); p=os.path.join(SNAP,"%s_%s.jsonl"%(prefix,stamp()))
    with open(p,"w",encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r)+"\n")
    print("%d rows -> %s"%(len(rows),p)); return p

# ---------- Kalshi ----------
def kalshi():
    """Every open market (combos excluded) plus its event's title, in two paged passes."""
    ms,cur=[],None
    for _ in range(400):
        p={"status":"open","limit":1000,"mve_filter":"exclude"}
        if cur: p["cursor"]=cur
        j=get(KALSHI_BASE+"/markets",p); ms+=j.get("markets") or []; cur=j.get("cursor")
        if not cur: break
        time.sleep(0.12)
    ev,cur={},None
    for _ in range(400):
        p={"status":"open","limit":200}
        if cur: p["cursor"]=cur
        j=get(KALSHI_BASE+"/events",p)
        for e in j.get("events") or []: ev[e.get("event_ticker")]=e
        cur=j.get("cursor")
        if not cur: break
        time.sleep(0.12)
    rows=[]
    for m in ms:
        e=ev.get(m.get("event_ticker")) or {}
        rows.append(dict(ticker=m.get("ticker"),event=m.get("event_ticker"),series=e.get("series_ticker") or (m.get("event_ticker") or "").split("-")[0],
            event_title=e.get("title"),category=e.get("category"),title=m.get("title"),yes_sub=m.get("yes_sub_title"),
            close=m.get("close_time"),bid=fnum(m.get("yes_bid_dollars")),ask=fnum(m.get("yes_ask_dollars")),last=fnum(m.get("last_price_dollars")),
            bid_size=fnum(m.get("yes_bid_size_fp")),ask_size=fnum(m.get("yes_ask_size_fp")),
            vol24=fnum(m.get("volume_24h_fp")),vol=fnum(m.get("volume_fp")),oi=fnum(m.get("open_interest_fp")),
            rules=(m.get("rules_primary") or "")[:600]))
    save("kalshi",rows)

# ---------- Polymarket ----------
def poly_row(m):
    """One Polymarket market (gamma API object) as a snapshot row."""
    try: outs=json.loads(m.get("outcomes") or "[]"); px=json.loads(m.get("outcomePrices") or "[]")
    except (ValueError,TypeError): outs,px=[],[]
    fs=m.get("feeSchedule") if isinstance(m.get("feeSchedule"),dict) else {}
    e=(m.get("events") or [{}])[0] or {}
    on=bool(m.get("feesEnabled")); rate=fnum(fs.get("rate"))
    return dict(id=m.get("id"),slug=m.get("slug"),question=m.get("question"),group_item=m.get("groupItemTitle"),
        event_title=e.get("title"),event_slug=e.get("slug"),end=m.get("endDate"),outcomes=outs,prices=px,
        bid=fnum(m.get("bestBid")),ask=fnum(m.get("bestAsk")),last=fnum(m.get("lastTradePrice")),vol24=fnum(m.get("volume24hr")),
        liq=fnum(m.get("liquidityNum")),fees=on,
        fee_rate=(rate if rate is not None else 0.07) if on else 0.0,   # fees on but no rate published: assume a high 7% (conservative)
        fee_exp=fnum(fs.get("exponent")) or 1.0,
        source=m.get("resolutionSource"),description=(m.get("description") or "")[:600],restricted=m.get("restricted"),fetched=stamp())
def poly(max_rows=20000,min_vol=50.0):
    """Active Polymarket markets, busiest first, until daily volume falls below min_vol dollars."""
    rows,off=[],0
    while off<max_rows:
        try: j=get(GAMMA+"/markets",{"closed":"false","active":"true","limit":500,"offset":off,"order":"volume24hr","ascending":"false"})
        except requests.HTTPError as e:   # the API refuses deep offsets (HTTP 422 past about 2,000 rows): keep what we have
            print("stopped paging at offset %d: %s"%(off,e.response.status_code if e.response is not None else e)); break
        if not j: break
        stop=False
        for m in j:
            v=fnum(m.get("volume24hr"))
            if v is not None and v<min_vol: stop=True; break   # busiest first: the rest are quieter (a missing volume does not stop paging)
            rows.append(poly_row(m))
        if stop: break
        off+=len(j); time.sleep(0.25)   # the API may return fewer rows per page than asked for (100)
    save("poly",rows)

# ---------- inventory ----------
PUBLIC={"KXHIGH":"daily high temperature: NWS forecasts, airport observations (METAR), NWS climate reports",
        "KXLOWT":"daily low temperature: NWS forecasts and observations","KXRAIN":"daily rain: NWS/NBM precipitation forecasts",
        "KXSNOW":"snowfall: NWS/NBM snow forecasts","KXHURR":"hurricanes: NHC advisories","KXTEMP":"temperature: NWS",
        "KXFED":"Fed decision: futures-implied odds (CME FedWatch), Fed communications","KXCPI":"CPI: Cleveland Fed nowcast, consensus",
        "KXGDP":"GDP: Atlanta Fed GDPNow, consensus","KXPAYROLLS":"jobs report: consensus, ADP","KXU3":"unemployment: consensus",
        "KXINX":"S&P 500 level: index futures and options","KXNASDAQ":"Nasdaq level: futures and options","KXBTC":"bitcoin price: spot and options markets",
        "KXETH":"ether price: spot and options markets","KXGAS":"gas prices: AAA, EIA weekly data","KXEIA":"energy data: EIA releases"}
def public_note(series):
    for k,v in PUBLIC.items():
        if series.startswith(k): return v
    return ""
def inventory():
    path,rows=latest("kalshi")
    by={}
    for r in rows:
        s=by.setdefault(r["series"],dict(series=r["series"],markets=0,vol24=0.0,oi=0.0,spreads=[],title=r.get("event_title") or "",category=r.get("category") or ""))
        s["markets"]+=1; s["vol24"]+=r.get("vol24") or 0; s["oi"]+=r.get("oi") or 0
        if r.get("bid") is not None and r.get("ask") is not None and 0<r["ask"]<=1 and r["bid"]>0: s["spreads"].append(r["ask"]-r["bid"])
    ss=sorted(by.values(),key=lambda s:-s["vol24"])
    for s in ss[:150]:   # series titles and categories for the busiest
        try: j=get(KALSHI_BASE+"/series/"+s["series"]).get("series") or {}; s["title"]=j.get("title") or s["title"]; s["category"]=j.get("category") or s["category"]; s["frequency"]=j.get("frequency")
        except Exception: pass
        time.sleep(0.1)
    for s in ss:
        sp=sorted(s.pop("spreads")); s["median_spread"]=sp[len(sp)//2] if sp else None; s["public_data"]=public_note(s["series"])
    os.makedirs(OUT,exist_ok=True)
    json.dump(dict(snapshot=os.path.basename(path),series=ss),open(os.path.join(OUT,"inventory.json"),"w",encoding="utf-8"),indent=1)
    cats={}
    for s in ss: c=s.get("category") or "?"; cats.setdefault(c,[0,0.0]); cats[c][0]+=s["markets"]; cats[c][1]+=s["vol24"]
    L=["# Kalshi inventory (research only)","","Snapshot %s: %d open markets in %d series (combo markets excluded). Volume = contracts traded in the last 24 hours."%(os.path.basename(path),len(rows),len(ss)),"",
       "## By category","","| Category | Open markets | 24h volume |","|---|---:|---:|"]
    L+=["| %s | %d | %s |"%(c,v[0],"{:,.0f}".format(v[1])) for c,v in sorted(cats.items(),key=lambda x:-x[1][1])]
    L+=["","## Busiest 60 series","","| Series | Title | Category | Markets | 24h volume | Open interest | Median spread | Public data that could inform a forecast |","|---|---|---|---:|---:|---:|---:|---|"]
    for s in ss[:60]:
        L.append("| %s | %s | %s | %d | %s | %s | %s | %s |"%(s["series"],(s["title"] or "")[:60].replace("|","/"),s.get("category") or "",s["markets"],"{:,.0f}".format(s["vol24"]),
                 "{:,.0f}".format(s["oi"]),"%.0fc"%(100*s["median_spread"]) if s["median_spread"] is not None else "-",s["public_data"]))
    wx=[s for s in ss if (s.get("category") or "").lower().startswith(("climate","weather")) or s["series"].startswith(("KXHIGH","KXLOW","KXRAIN","KXSNOW","KXHURR","KXTEMP"))]
    L+=["","## Weather and climate series (%d)"%len(wx),"","| Series | Title | Markets | 24h volume | Median spread |","|---|---|---:|---:|---:|"]
    L+=["| %s | %s | %d | %s | %s |"%(s["series"],(s["title"] or "")[:70].replace("|","/"),s["markets"],"{:,.0f}".format(s["vol24"]),"%.0fc"%(100*s["median_spread"]) if s["median_spread"] is not None else "-") for s in wx[:80]]
    open(os.path.join(OUT,"inventory.md"),"w",encoding="utf-8").write("\n".join(L)+"\n"); print("\n".join(L[:40]))

# ---------- matching and gaps ----------
STOP=set("will the a an of in on at by to for be is are and or than more less after before 2026 2025 its with this that what which who does do".split())
def toks(s): return set(w for w in re.findall(r"[a-z]+|\d+(?:\.\d+)?",(s or "").lower()) if w not in STOP)
def nums(s): return set(re.findall(r"\d+(?:\.\d+)?",(s or "").lower()))-{"2025","2026"}
def day(s):
    try: return datetime.strptime((s or "")[:10],"%Y-%m-%d").date()
    except ValueError: return None
def match(min_score=0.34,min_vol=1000.0):
    kp,ks=latest("kalshi"); pp,ps=latest("poly")
    kidx={}
    for k in ks:
        k["_t"]=toks(" ".join(filter(None,[k.get("event_title"),k.get("title"),k.get("yes_sub")]))); k["_n"]=nums(" ".join(filter(None,[k.get("title"),k.get("yes_sub"),k.get("event_title")]))); k["_d"]=day(k.get("close"))
        for w in k["_t"]: kidx.setdefault(w,[]).append(k)
    out=[]
    for p in ps:
        if (p.get("vol24") or 0)<min_vol: continue
        text=" ".join(filter(None,[p.get("question"),p.get("event_title")])); pt=toks(text); pn=nums(text); pd=day(p.get("end"))
        cand={}
        for w in pt:
            for k in kidx.get(w,[]): cand[k["ticker"]]=k
        best=None
        for k in cand.values():
            if pn and not pn<=k["_n"]: continue   # every number in the Polymarket question must appear on the Kalshi side
            if pd and k["_d"] and abs((pd-k["_d"]).days)>7: continue
            sc=len(pt&k["_t"])/max(1,len(pt|k["_t"]))
            if best is None or sc>best[0]: best=(sc,k)
        if best and best[0]>=min_score: out.append((best[0],p,best[1]))
    out.sort(key=lambda x:(-x[0],-(x[1].get("vol24") or 0)))
    L=["# Possible same-question pairs (to check by hand)","","Kalshi %s, Polymarket %s. Score = word overlap (0-1); every number in the Polymarket question must appear on the Kalshi side; end dates within 7 days. A pair only counts after both rule texts are read: same event, same source, same cut-off."%(os.path.basename(kp),os.path.basename(pp)),"",
       "| # | Score | Polymarket question | Kalshi market | PM bid/ask | Kalshi bid/ask | PM 24h $ | Kalshi 24h |","|---:|---:|---|---|---|---|---:|---:|"]
    for i,(sc,p,k) in enumerate(out[:300],1):
        L.append("| %d | %.2f | %s (%s) | %s: %s / %s | %s/%s | %s/%s | %s | %s |"%(i,sc,(p.get("question") or "")[:80].replace("|","/"),p.get("slug","")[:40],k["ticker"],(k.get("event_title") or "")[:50].replace("|","/"),(k.get("yes_sub") or "")[:30].replace("|","/"),
                 p.get("bid"),p.get("ask"),k.get("bid"),k.get("ask"),"{:,.0f}".format(p.get("vol24") or 0),"{:,.0f}".format(k.get("vol24") or 0)))
    os.makedirs(OUT,exist_ok=True); open(os.path.join(OUT,"gap_candidates.md"),"w",encoding="utf-8").write("\n".join(L)+"\n")
    json.dump([dict(score=sc,poly_id=p["id"],poly_slug=p.get("slug"),poly_q=p.get("question"),kalshi=k["ticker"],kalshi_title=" / ".join(filter(None,[k.get("event_title"),k.get("yes_sub")])),
                    poly_source=p.get("source"),poly_rules=p.get("description"),kalshi_rules=k.get("rules")) for sc,p,k in out[:300]],
              open(os.path.join(OUT,"gap_candidates.json"),"w",encoding="utf-8"),indent=1)
    print("%d candidate pairs -> results/gap_candidates.md"%len(out))
def kfee(p): return math.ceil(0.07*p*(1-p)*100-1e-9)/100 if 0<p<1 else 0.0
def pfee(p,rate,exp=1.0): return (rate or 0)*(p*(1-p))**(exp or 1.0) if 0<p<1 else 0.0
def real(x): return x is not None and 0<x<1
def gaps():
    """For each hand-checked pair in data/pairs.json ({"kalshi": ticker, "poly_id": id, "same_side": true, "note": ...}),
    compare prices and test both ways of buying YES on one venue and NO on the other at the asks, after taker fees.
    same_side=false means Kalshi's YES is Polymarket's NO (the question is worded the other way round)."""
    pp=os.path.join(DATA,"pairs.json")
    if not os.path.exists(pp): sys.exit("No data/pairs.json yet (pairs checked by hand).")
    pairs=json.load(open(pp,encoding="utf-8-sig")); kp,ks=latest("kalshi"); qp,ps=latest("poly")
    K={k["ticker"]:k for k in ks}; P={str(p["id"]):p for p in ps}; rows=[]; fetched=0
    for pr in pairs:   # pairs whose Polymarket market fell outside the snapshot (quiet that day) are read one by one
        if str(pr["poly_id"]) not in P:
            try: P[str(pr["poly_id"])]=poly_row(get(GAMMA+"/markets/%s"%pr["poly_id"])); fetched+=1; time.sleep(0.25)
            except (requests.RequestException,ValueError) as e: print("could not read Polymarket market %s: %s"%(pr["poly_id"],e))
    for pr in pairs:
        k=K.get(pr["kalshi"]); p=P.get(str(pr["poly_id"]))
        ok=lambda b,a:b is not None and a is not None and 0<=b<a<=1
        if not k or not p or not ok(k.get("bid"),k.get("ask")) or not ok(p.get("bid"),p.get("ask")): rows.append((pr,None)); continue
        pb,pa=(p["bid"],p["ask"]) if pr.get("same_side",True) else (1-p["ask"],1-p["bid"])   # Polymarket in Kalshi-YES terms
        rate=p.get("fee_rate") or 0; ex=p.get("fee_exp") or 1.0
        # A: buy YES on Kalshi at its ask + buy the opposite on Polymarket (NO in Kalshi-YES terms costs 1 - pb)
        a=k["ask"]+kfee(k["ask"])+(1-pb)+pfee(1-pb,rate,ex) if real(k["ask"]) and real(1-pb) else None
        b=pa+pfee(pa,rate,ex)+(1-k["bid"])+kfee(1-k["bid"]) if real(pa) and real(1-k["bid"]) else None   # B: YES on Polymarket + NO on Kalshi
        if a is None and b is None: rows.append((pr,None)); continue
        rows.append((pr,dict(k_mid=(k["bid"]+k["ask"])/2,p_mid=(pb+pa)/2,gap=(pb+pa)/2-(k["bid"]+k["ask"])/2,cost_a=a,cost_b=b,best=min(x for x in (a,b) if x is not None),k=k,p=p)))
    ktime=os.path.basename(kp).split("_",1)[1].split(".")[0]; ptime=os.path.basename(qp).split("_",1)[1].split(".")[0]
    L=["# Kalshi vs Polymarket, hand-checked pairs (research only)","",
       "Snapshots (UTC): Kalshi %s, Polymarket %s%s. The two snapshots are minutes apart, so a gap can be a price that moved in between. "
       "Prices in Kalshi-YES terms, for ONE contract at the best ask (deeper orders may cost more). "
       "A locked profit needs a pair cost below $1.00 after fees AND identical settlement; pairs with a settlement difference are price comparisons only."%(
           ktime,ptime,(" (%d market(s) read separately just now)"%fetched) if fetched else ""),"",
       "| Pair | Kalshi mid | Polymarket mid | Gap (PM - K) | Cheapest pair cost after fees | Same settlement? | Note |","|---|---:|---:|---:|---:|---|---|"]
    for pr,r in rows:
        if r is None: L.append("| %s | - | - | - | - | %s | no usable prices now |"%(pr["kalshi"],"yes" if pr.get("identical") else "no")); continue
        L.append("| %s / %s | %.3f | %.3f | %+.3f | $%.3f | %s | %s |"%(pr["kalshi"],(r["p"].get("slug") or "")[:40],r["k_mid"],r["p_mid"],r["gap"],r["best"],"yes" if pr.get("identical") else "no",(pr.get("note") or "").replace("|","/")))
    os.makedirs(OUT,exist_ok=True); open(os.path.join(OUT,"gaps.md"),"w",encoding="utf-8").write("\n".join(L)+"\n")
    log=os.path.join(DATA,"gaps_log.jsonl")   # one line per pair per run, for watching whether gaps persist
    with open(log,"a",encoding="utf-8") as f:
        for pr,r in rows:
            if r: f.write(json.dumps(dict(t=stamp(),kalshi=pr["kalshi"],poly_id=pr["poly_id"],k_mid=r["k_mid"],p_mid=r["p_mid"],gap=r["gap"],best=r["best"]))+"\n")
    print("\n".join(L))
if __name__=="__main__":
    try: sys.stdout.reconfigure(errors="replace")   # market titles can hold characters the Windows console cannot show
    except AttributeError: pass
    cmd=sys.argv[1] if len(sys.argv)>1 else ""
    {"kalshi":kalshi,"poly":poly,"inventory":inventory,"match":match,"gaps":gaps}.get(cmd,lambda: sys.exit(__doc__))()
