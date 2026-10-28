"""Station rain forecast, the "v4 candidate" (research only; the live bot still trades v3).
NBM station guidance (NBS) for the airport named in the market's rules, from the Iowa Environmental Mesonet: the evening
run (18 or 19 UTC) of the day before the market day, issued hours before the 8:55 PM scan. Four 6-hour rain chances
(P06) and amounts (Q06) ending 12Z and 18Z on the day and 00Z and 06Z the next day, combined with v3's rule and then
calibrated by a logistic regression fitted on 2025-07-01..2026-06-30 (research/backtest.py writes the coefficients to
research/results/rain_model.json). The formulas match research/backtest.py exactly. Python 3.8+, requests only."""
import os, csv, io, json, math, time
from datetime import timedelta
import requests
IEM="https://mesonet.agron.iastate.edu"; UA={"User-Agent":"tradebot-paper-research/1.0"}
MODEL=os.path.join(os.path.dirname(os.path.abspath(__file__)),"research","results","rain_model.json")
def sig(z): return 1/(1+math.exp(-max(-30,min(30,z))))
def logit(p): p=min(max(p,0.005),0.995); return math.log(p/(1-p))
def num(v):
    try: return None if v in (None,"","M","T") else float(v)
    except (TypeError,ValueError): return None
def evening_run(station,run_date):
    """({ftime 'YYYY-MM-DD HH:MM': (p06, q06)}, runtime) for the latest 18/19 UTC NBS run on run_date, or None."""
    for wait in (5,15,45,None):   # IEM answers 429 when asked too fast; back off politely
        r=requests.get(IEM+"/cgi-bin/request/mos.py",params=dict(station=station,model="NBS",sts="%sT18:00Z"%run_date,ets="%sT19:00Z"%run_date,format="csv"),headers=UA,timeout=60)
        if r.status_code==200 or wait is None or (r.status_code!=429 and r.status_code<500): break
        time.sleep(wait)
    r.raise_for_status()
    rows=[x for x in csv.DictReader(io.StringIO(r.text)) if (x.get("runtime") or "")[11:16] in ("18:00","19:00")]
    if not rows: return None
    rt=max(x["runtime"] for x in rows)
    return {x["ftime"][:16]:(num(x.get("p06")),num(x.get("q06"))) for x in rows if x["runtime"]==rt},rt
def features(run,day):
    """Same as research/backtest.py: None if any of the four periods is missing."""
    nx=day+timedelta(days=1)
    v=[run.get(k) for k in ("%s 12:00"%day,"%s 18:00"%day,"%s 00:00"%nx,"%s 06:00"%nx)]
    if any(x is None or x[0] is None or x[1] is None for x in v): return None
    p=[x[0]/100 for x in v]; q=sum(x[1] for x in v)
    pmax=max(p); pind=1-math.prod(1-x for x in p)
    return dict(R=(pmax+pind)/2,pmax=pmax,pind=pind,q=q/100)
def predict(coef,f): return min(max(sig(coef[0]+coef[1]*logit(f["R"])+coef[2]*math.log1p(100*f["q"])),0.01),0.99)
def load_coef():
    try: return json.load(open(MODEL,encoding="utf-8"))["coef"]
    except (OSError,ValueError,KeyError): return None
