import requests, re, time, math
from datetime import datetime, timedelta, timezone
from config import WEATHER_SIGMA_F
import nws
RAW={}   # ticker -> raw values from the last estimate, logged to obs (never used by the live formula except p_a/p_b)
# Temperature (unchanged since v1): approximate airport coordinates, Open-Meteo. Station per rules text where known.
CITY={"NYC":(40.78,-73.97),"CHI":(41.79,-87.75),"PHX":(33.43,-112.01),"SEA":(47.45,-122.31),"BOS":(42.36,-71.01),
"LAX":(33.94,-118.41),"DEN":(39.86,-104.67),"STL":(38.75,-90.37),"MIA":(25.79,-80.29),"HOU":(29.65,-95.28),
"MKE":(42.95,-87.90),"PVD":(41.72,-71.43),"IND":(39.72,-86.29),"MIN":(44.88,-93.22)}
TEMP_STATION={"CHI":"CLIMDW","DEN":"CLIDEN","LAX":"CLILAX","MIA":"CLIMIA"}   # from KXHIGH rules_primary, audited 2026-10-13
# Rain (v3): key = KXRAIN ticker suffix -> (station named in the market's rules_primary, lat, lon from NWS station metadata;
# DTW and WPB, added 2026-10-28, from the Iowa Environmental Mesonet's station records)
RAIN={"ABQ":("CLIABQ",35.0417,-106.6147),
 "ATL":("CLIATL",33.6403,-84.4269),
 "AUS":("CLIAUS",30.183,-97.6799),
 "BOS":("CLIBOS",42.3606,-71.0106),
 "CHI":("CLIORD",41.9797,-87.9044),
 "CLL":("CLICLL",30.5822,-96.3617),
 "CMH":("CLICMH",39.9907,-82.8769),
 "DAL":("CLIDFW",32.8974,-97.022),
 "DC":("CLIDCA",38.8483,-77.0342),
 "DEN":("CLIDEN",39.8466,-104.6562),
 "DTW":("CLIDTW",42.23,-83.33),   # added 2026-10-28 (user): Detroit Metro; IEM station DTW (api.weather.gov blocked from Claude's tools)
 "EWR":("CLIEWR",40.6825,-74.1694),
 "HOU":("CLIHOU",29.6375,-95.2825),
 "IND":("CLIIND",39.7252,-86.2816),
 "LAX":("CLILAX",33.9381,-118.3889),
 "LEX":("CLILEX",38.0339,-84.6115),
 "LV":("CLILAS",36.0719,-115.1634),
 "MIA":("CLIMIA",25.7906,-80.3164),
 "MIN":("CLIMSP",44.8831,-93.2289),
 "MKE":("CLIMKE",42.955,-87.9044),
 "NOLA":("CLIMSY",29.9928,-90.2508),
 "NYC":("CLINYC",40.7833,-73.9667),
 "OKC":("CLIOKC",35.3886,-97.6003),
 "PHIL":("CLIPHL",39.8733,-75.2268),
 "PHX":("CLIPHX",33.4278,-112.0035),
 "PIT":("CLIPIT",40.4846,-80.2145),
 "PVD":("CLIPVD",41.7223,-71.4277),
 "SATX":("CLISAT",29.5328,-98.4636),
 "SEA":("CLISEA",47.4447,-122.3136),
 "SFO":("CLISFO",37.6196,-122.3656),
 "SGF":("CLISGF",37.2397,-93.3897),
 "STL":("CLISTL",38.7525,-90.3736),
 "TPA":("CLITPA",27.9614,-82.5403),
 "TTN":("CLITTN",40.2764,-74.8164),
 "WPB":("CLIDJT",26.6847,-80.0994)}   # added 2026-10-28 (user): West Palm Beach, the airport re-coded PBI -> DJT in July 2026; IEM station DJT
_c={}
def _daily(city):
    if city not in _c or time.time()-_c[city][0]>1800:
        lat,lon=CITY[city]
        j=requests.get("https://api.open-meteo.com/v1/forecast",params={"latitude":lat,"longitude":lon,
          "daily":"precipitation_probability_max,temperature_2m_max","temperature_unit":"fahrenheit",
          "timezone":"auto","forecast_days":4},headers={"User-Agent":"tradebot-paper-research/1.0"},timeout=20).json()   # User-Agent rule (2026-10-14); forecast logic unchanged
        _c[city]=(time.time(),j["daily"])
    return _c[city][1]
def _cdf(z): return 0.5*(1+math.erf(z/math.sqrt(2)))
def _rain_v3(m,key):
    """v3 (frozen). Kalshi day W = [close_time-24h, close_time) (close_time is local standard-time midnight).
    NWS gridpoint PoP hourly slices (the official 12h PoP equals the max of the slices inside it). A slice that
    overlaps a 12h half of W at all counts toward that half. p_a=max over the first half, p_b=max over the second.
    P=(max(p_a,p_b)+1-(1-p_a)(1-p_b))/2. Any missing/null slice, or a scan at/after W's start -> skip (no fallback).
    No Open-Meteo anywhere in this path."""
    code,lat,lon=RAIN[key]
    close=datetime.strptime(m["close_time"],"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    w0=close-timedelta(hours=24)
    if datetime.now(timezone.utc)>=w0: return None
    sl=nws.grid_slices(lat,lon); hours=[]
    for h in range(24):
        a=w0+timedelta(hours=h); b=a+timedelta(hours=1)
        v=[x[2] for x in sl if x[0]<b and x[1]>a]
        if not v or any(y is None for y in v): return None
        hours.append(max(v))
    pa=max(hours[:12])/100.0; pb=max(hours[12:])/100.0
    r={"type":"rain","station":code,"p_a":pa,"p_b":pb,"slices":hours}
    try:   # v2 raw period values, logging only
        d=datetime.strptime(m["ticker"].split("-")[1],"%y%b%d")
        r.update(nws.rain_raw(lat,lon,d.strftime("%Y-%m-%d"),(d-timedelta(days=1)).strftime("%Y-%m-%d")))
    except Exception: pass
    RAW[m["ticker"]]=r
    return (max(pa,pb)+1-(1-pa)*(1-pb))/2
def estimator(m):
    p=m["ticker"].split("-")
    if len(p)<3: return None
    try: date=datetime.strptime(p[1],"%y%b%d").strftime("%Y-%m-%d")
    except ValueError: return None
    rain=p[0]=="KXRAIN"; high=p[0].startswith("KXHIGH")
    if rain: return _rain_v3(m,p[2]) if p[2] in RAIN else None
    city=p[0][6:]
    if not high or city not in CITY: return None
    d=_daily(city)
    if date not in d["time"]: return None
    i=d["time"].index(date)
    mt=re.match(r"T(\d+)$",p[2]); mu=d["temperature_2m_max"][i]
    if not mt or mu is None: return None
    RAW[m["ticker"]]={"type":"temp","mu":mu,"station":TEMP_STATION.get(city)}   # logging only
    thr=int(mt.group(1)); st=m.get("strike_type")
    if st=="greater": return 1-_cdf((thr+0.5-mu)/WEATHER_SIGMA_F)
    if st=="less": return _cdf((thr-0.5-mu)/WEATHER_SIGMA_F)
    return None
