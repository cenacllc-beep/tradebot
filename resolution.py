"""Resolution-certainty states for daily temperature markets (research only; added 2026-10-22, platform upgrade
phase 11). Separate from forecasting: it asks what the settlement source has ALREADY recorded, not what will happen.

A daily high can only rise during its measurement window, and a daily low can only fall. So once the official station
has recorded a value past a strike by a safety margin, the outcome is decided. States:
- UNCERTAIN: nothing is decided yet.
- HIGH_CONFIDENCE: past the strike, but within the safety margin. Rounding, a sensor fix or a report revision could
  still change it.
- MATHEMATICALLY_DETERMINED: past the strike by at least the margin. The rules fix the outcome unless the official
  value is revised.
- OFFICIAL_SOURCE_PUBLISHED: the climate report for the day is out.
- SETTLED: Kalshi has settled the market.
Determined states are reached only from observations at the market's OWN settlement station (the CLI station in the
rules). A nearby airport does not count: station_match must be True, or the state stays UNCERTAIN with a
SOURCE_MISMATCH note. Revision risk is explicit: a determined state carries revision_risk="report revisions and
sensor corrections". PLAN3 test A found the market already prices determined outcomes at $1.00, so this engine is for
risk checks (never buying a side that is already lost), not for profit. Python 3.8+."""
STATES=("UNCERTAIN","HIGH_CONFIDENCE","NEAR_DETERMINISTIC","MATHEMATICALLY_DETERMINED","OFFICIAL_SOURCE_PUBLISHED","SETTLED")
def classify(kind,strike_type,floor,cap,observed,station_match,margin=1.0,published=None,settled=None):
    """kind: 'high' (the day's maximum, can only rise) or 'low' (minimum, can only fall).
    strike_type: 'greater' (YES if value > floor), 'less' (YES if value < cap), 'between' (floor <= value <= cap).
    observed: the official station's running extreme so far (None if unknown). published: the climate report's value.
    settled: 'yes'/'no' once Kalshi settled. Returns dict(state, outcome or None, reason, revision_risk)."""
    if settled in ("yes","no"): return dict(state="SETTLED",outcome=settled,reason="settled by Kalshi",revision_risk=None)
    def yes_of(v):
        if strike_type=="greater": return v>floor
        if strike_type=="less": return v<cap
        if strike_type=="between": return floor<=v<=cap
        return None
    if published is not None and station_match:
        return dict(state="OFFICIAL_SOURCE_PUBLISHED",outcome="yes" if yes_of(published) else "no",reason="climate report published",revision_risk="report revisions")
    if observed is None: return dict(state="UNCERTAIN",outcome=None,reason="no observation",revision_risk=None)
    if not station_match: return dict(state="UNCERTAIN",outcome=None,reason="SOURCE_MISMATCH: not the settlement station",revision_risk=None)
    rr="report revisions and sensor corrections"
    # what the running extreme already rules out
    if kind=="high":
        if strike_type=="greater" and observed>floor: dec,dist="yes",observed-floor
        elif strike_type=="less" and observed>=cap: dec,dist="no",observed-cap+1
        elif strike_type=="between" and observed>cap: dec,dist="no",observed-cap
        else: return dict(state="UNCERTAIN",outcome=None,reason="the high can still rise past the strike",revision_risk=None)
    elif kind=="low":
        if strike_type=="less" and observed<cap: dec,dist="yes",cap-observed
        elif strike_type=="greater" and observed<=floor: dec,dist="no",floor-observed+1
        elif strike_type=="between" and observed<floor: dec,dist="no",floor-observed
        else: return dict(state="UNCERTAIN",outcome=None,reason="the low can still fall past the strike",revision_risk=None)
    else: raise ValueError(kind)
    if dist>=margin+1: return dict(state="MATHEMATICALLY_DETERMINED",outcome=dec,reason="past the strike by %g, at least the margin"%dist,revision_risk=rr)
    return dict(state="HIGH_CONFIDENCE",outcome=dec,reason="past the strike by %g, within the margin of %g"%(dist,margin),revision_risk=rr)
