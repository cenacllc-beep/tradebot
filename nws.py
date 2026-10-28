import requests, time, re
from datetime import datetime, timedelta
# api.weather.gov, approved for the KXRAIN estimator only. No personal data in the User-Agent.
UA={"User-Agent":"tradebot-paper-research/1.0","Accept":"application/geo+json"}
_pts={}; _fc={}; _gr={}
GRID_META={}   # (lat, lon) -> fetch time and NWS updateTime of the grid used (audit only, 2026-10-22; values unchanged)
def _get(url):
    r=requests.get(url,headers=UA,timeout=20); r.raise_for_status(); return r.json()
def _point(lat,lon):
    k=(lat,lon)
    if k not in _pts: _pts[k]=_get("https://api.weather.gov/points/%s,%s"%(lat,lon))["properties"]
    return _pts[k]
def periods(lat,lon):
    k=(lat,lon)
    if k not in _fc or time.time()-_fc[k][0]>1800:
        _fc[k]=(time.time(),_get(_point(lat,lon)["forecast"])["properties"]["periods"])
    return _fc[k][1]
def pop(p):
    v=p["probabilityOfPrecipitation"]["value"]; return 0.0 if v is None else v/100.0   # NWS reports null for 0%
def rain_raw(lat,lon,date,prev_date):
    """v2 raw 12h-period PoPs, logging only: day (6am-6pm), night (6pm-6am) on `date`; prev = night starting prev_date."""
    out={"day":None,"night":None,"prev":None}
    for p in periods(lat,lon):
        d=p["startTime"][:10]
        if d==date: out["day" if p["isDaytime"] else "night"]=pop(p)
        elif d==prev_date and not p["isDaytime"]: out["prev"]=pop(p)
    return out
_D=re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$")
def grid_slices(lat,lon):
    """gridpoint probabilityOfPrecipitation as [(start_utc, end_utc, value_percent_or_None)] (aware datetimes)."""
    k=(lat,lon)
    if k not in _gr or time.time()-_gr[k][0]>1800:
        props=_get(_point(lat,lon)["forecastGridData"])["properties"]; vals=props["probabilityOfPrecipitation"]["values"]
        GRID_META[k]=dict(fetched=time.time(),update_time=props.get("updateTime"))
        out=[]
        for v in vals:
            st,du=v["validTime"].split("/"); m=_D.match(du)
            s=datetime.fromisoformat(st)
            out.append((s,s+timedelta(days=int(m.group(1) or 0),hours=int(m.group(2) or 0),minutes=int(m.group(3) or 0)),v["value"]))
        _gr[k]=(time.time(),out)
    return _gr[k][1]
