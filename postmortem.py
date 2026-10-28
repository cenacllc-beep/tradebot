"""Post-mortem of settled trades (added 2026-10-22, platform upgrade phase 26). Read-only classification, never a
reason to change a strategy by itself. Strategies change only on aggregated evidence, through a plan written first.

Every settled trade gets one or more cause codes, the most specific first:
- TIMING_ERROR: opened at or after its market's Kalshi day began (the guard added 2026-10-14 now prevents this).
- STALE_DATA: the forecast data was older than 3 hours at the decision.
- WRONG_SETTLEMENT_SOURCE: the station the model used is not the one the market settles on (when both are known).
- MODEL_CALIBRATION_ERROR: the chance the model gave the side is above the top of the 95% range of how often that
  side actually won in settled history for this probability range. Needs 30 settled markets in the range.
- LOW_PROBABILITY_BET: the side was bought with less than a 30% chance by the model's own numbers. A loss is the
  expected outcome then, and a value-only rule allowed it.
- NORMAL_VARIANCE: none of the above. The side lost a bet the numbers said it could lose.
- UNKNOWN: no decision record (trades opened before the audit ledger) and too little to tell.
Wins get WON. A won trade can still carry TIMING_ERROR or LOW_PROBABILITY_BET: luck is not evidence. Python 3.8+."""
from datetime import datetime, timedelta, timezone

# Hours behind UTC of each city's standard time (Kalshi's day runs from local standard-time midnight). Unknown: Eastern.
STD_OFFSET={**{c:6 for c in ("CHI","MKE","MIN","STL","SGF","DAL","HOU","AUS","SATX","OKC","CLL","NOLA")},
            **{c:7 for c in ("DEN","PHX","ABQ")},**{c:8 for c in ("LAX","SFO","SEA","SAN","LV")}}
def day_start(ticker):
    """Kalshi day start for daily weather markets: local standard-time midnight on the date in the ticker. Without the
    close time it is approximate, so it is used only when no decision record exists."""
    try: d=datetime.strptime(ticker.split("-")[1],"%y%b%d").replace(tzinfo=timezone.utc)
    except (IndexError,ValueError): return None
    import risk
    return (d+timedelta(hours=STD_OFFSET.get(risk.city_of(ticker),5))).timestamp()
def classify(trade,decision=None,calib=None,station_expected=None,max_age_s=3*3600):
    if trade.get("status")!="settled": return []
    won=trade.get("result")==trade.get("side"); codes=[]
    ds=(decision or {}).get("day_start_ts") or day_start(trade.get("ticker") or "")
    if ds and (trade.get("ts") or 0)>=ds: codes.append("TIMING_ERROR")
    inp=(decision or {}).get("inputs_obj") or {}
    g=inp.get("grid") or {}
    if decision and g.get("fetched") and decision.get("ts") and decision["ts"]-g["fetched"]>max_age_s: codes.append("STALE_DATA")
    st=(decision or {}).get("station")
    if station_expected and st and st!=station_expected: codes.append("WRONG_SETTLEMENT_SOURCE")
    p=(decision or {}).get("p_win") if decision else trade.get("fair")
    if p is not None and p<0.30: codes.append("LOW_PROBABILITY_BET")
    if not won and calib is not None and p is not None and decision and decision.get("p_fair") is not None:
        lo,hi,n=calib.interval(decision["p_fair"],trade.get("side"))
        if hi is not None and p>hi: codes.append("MODEL_CALIBRATION_ERROR")
    if won: return ["WON"]+codes
    if codes: return codes
    return ["NORMAL_VARIANCE"] if (decision or p is not None) else ["UNKNOWN"]
TEXT={"WON":"won","TIMING_ERROR":"opened after the market's day had begun","STALE_DATA":"forecast data was stale",
      "WRONG_SETTLEMENT_SOURCE":"model station differs from the settlement station","MODEL_CALIBRATION_ERROR":"the model is overconfident in this range",
      "LOW_PROBABILITY_BET":"bought a side the model gave under 30%","NORMAL_VARIANCE":"an ordinary loss the numbers allowed","UNKNOWN":"not enough recorded to tell"}
def summary(rows):
    """rows: [codes] -> {code: count}."""
    out={}
    for codes in rows:
        for c in codes: out[c]=out.get(c,0)+1
    return out
