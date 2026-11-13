"""Real-money (Kalshi) section of the dashboard. Presentation only (added 2026-11-13 at the user's request: "the
dashboard has not been updated to show real money orders").

dashboard.py reads live.db read-only and passes its rows here; this module never opens a file, a database or the
network, never places or changes an order, and never reads the Kalshi settings file. The value, peak, daily stop and
25% end rule are worked out exactly as live.py does (value_track, day_pnl, local_at_risk), from the same ledger, so
the page and the bot cannot disagree; a test checks that.

What it shows: the account's state (locked / unlocked / trial ended / kill switch), the bot's value with the room left
before the daily stop and the 25% end rule, a value chart with a marker at every real order (hover or tap: what was
bought, at what price, and how it settled), a calendar of market days, the order list (with skipped copies and why),
and paper vs real on the same markets."""
import html
import json
from datetime import datetime, timedelta, timezone

STAKE = 25.0          # live.STAKE: the user's own money, the base of the value, the daily stop and the end rule
MAX_AT_RISK = 50.0    # live.MAX_AT_RISK
DAILY_STOP = 2.5      # live.DAILY_STOP (10% of $25)
DRAWDOWN = 0.25       # live.DRAWDOWN_PAUSE
TZ = timezone(timedelta(hours=-4))   # tbcommon.clock: the one zone for shown times (La Paz, UTC-4)
NOT_SENT = ("skipped", "rejected", "not placed")
CITY = {"ABQ": "Albuquerque", "ATL": "Atlanta", "AUS": "Austin", "BOS": "Boston", "CHI": "Chicago", "CLL": "College Station",
        "CMH": "Columbus", "DAL": "Dallas", "DC": "Washington", "DEN": "Denver", "DTW": "Detroit", "EWR": "Newark",
        "HOU": "Houston", "IND": "Indianapolis", "LAX": "Los Angeles", "LEX": "Lexington", "LV": "Las Vegas", "MIA": "Miami",
        "MIN": "Minneapolis", "MKE": "Milwaukee", "NOLA": "New Orleans", "NYC": "New York", "OKC": "Oklahoma City",
        "PHIL": "Philadelphia", "PHX": "Phoenix", "PIT": "Pittsburgh", "PVD": "Providence", "SATX": "San Antonio",
        "SEA": "Seattle", "SFO": "San Francisco", "SGF": "Springfield", "STL": "St. Louis", "TPA": "Tampa", "TTN": "Trenton",
        "WPB": "West Palm Beach"}   # weather.RAIN's codes (the tickers' last part); checked by tests/test_real_view.py
MON = dict(JAN=1, FEB=2, MAR=3, APR=4, MAY=5, JUN=6, JUL=7, AUG=8, SEP=9, OCT=10, NOV=11, DEC=12)

CSS = """
.real .rstate{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12.5px;font-weight:600;margin-left:6px;vertical-align:middle;background:var(--chip,rgba(127,127,127,.15))}
.real .rstate.on{background:rgba(220,60,60,.15);color:var(--neg,#c33)}
.real .rstate.off{background:rgba(127,127,127,.15)}
.real .rtiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}
.real .rtiles>div{border:1px solid var(--line,rgba(127,127,127,.25));border-radius:10px;padding:10px 12px}
.real .rtiles dt{font-size:12px;opacity:.75}.real .rtiles dd{margin:2px 0 0;font-size:20px;font-weight:650}
.real .rtiles p{margin:4px 0 0;font-size:12px;opacity:.8}
.real .rbar{display:block;height:6px;border-radius:3px;background:rgba(127,127,127,.18);margin-top:6px;overflow:hidden}
.real .rbar i{display:block;min-width:2px;height:100%;background:var(--acc,#2a7)}.real .rbar i.warn{background:#d90}.real .rbar i.bad{background:var(--neg,#c33)}
.real .rv-top{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:baseline}
.real .rv-top h2{margin:0}
.real .mk{cursor:pointer;outline:none}.real .mk circle{stroke:var(--surface,#fff);stroke-width:2}
.real .mk:focus circle,.real .mk:hover circle{stroke:var(--ink,#000);stroke-width:2}
.real .mk.buy circle{fill:#3b7ddd}.real .mk.won circle{fill:var(--good,#0ca30c)}.real .mk.lost circle{fill:var(--bad,#d03b3b)}
.real .rleg{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12.5px;color:var(--ink2);margin:2px 0 4px}
.real .rleg i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}
.real .rrng{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}.real .rrng[hidden],.real .rv-js[hidden]{display:none}
.real .rrng button{font:600 13px/1 var(--text,system-ui);border:0;cursor:pointer;background:transparent;border-radius:99px;padding:8px 12px;min-height:32px;min-width:48px;color:var(--tonet,var(--ink2))}
.real .rrng button[aria-pressed=true]{background:var(--tonet,var(--ink2));color:var(--surface,#fff)}
.real .rrng button:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.real .rv-static svg{width:100%;height:100%}
.real .rcal{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:4px;margin:8px 0;max-width:560px}
.real .rcal .h{font-size:11px;opacity:.6;text-align:center}
.real .rcal .d{border-radius:6px;padding:4px;min-height:44px;font-size:11px;background:rgba(127,127,127,.08);outline:none}
.real .rcal .d b{display:block;font-size:12px}.real .rcal .d.won{background:rgba(40,160,90,.18)}.real .rcal .d.lost{background:rgba(220,60,60,.16)}
.real .rcal .d.open{background:rgba(59,125,221,.16)}.real .rcal .d.none{opacity:.45}
"""


def e(s):
    return html.escape(str(s), quote=True)


def usd(v):
    return ("\u2212$%.2f" % -v) if v < -0.004 else "$%.2f" % abs(v)


def plus(v):
    return ("+$%.2f" % v) if v > 0.004 else (("\u2212$%.2f" % -v) if v < -0.004 else "$0.00")


def when(ts):
    d = datetime.fromtimestamp(ts, TZ)
    return d.strftime("%b %d, %I:%M %p").replace(" 0", " ")


def market(ticker):
    """KXRAIN-26NOV12-STL -> (date(2026,11,12), 'St. Louis', 'rain'). Unknown shapes give (None, ticker, '')."""
    try:
        s, d, c = ticker.split("-")[:3]
        day = datetime(2000 + int(d[:2]), MON[d[2:5]], int(d[5:7])).date()
        kind = "rain" if s.startswith("KXRAIN") else ("high temperature" if s.startswith("KXHIGH") else s)
        return day, CITY.get(c, c), kind
    except (ValueError, KeyError, IndexError):
        return None, ticker, ""


def bet_words(o):
    _, city, kind = market(o["ticker"])
    side = (("YES (%s)" % kind) if kind else "YES") if o["side"] == "yes" else ("NO (no %s)" % kind) if kind == "rain" else o["side"].upper()
    return city, side


# ---------- the numbers, as live.py works them out ----------
def last_event(events, env, kinds):
    for ev in sorted(events, key=lambda x: x["id"], reverse=True):   # as live.last_event: the latest by id
        if ev["env"] == env and ev["kind"] in kinds:
            return ev
    return None


def value_track(orders, events, env="prod"):
    """live.value_track: (value, peak since the last resume, paused). Value = $25 + settled net."""
    r = last_event(events, env, ("resume",))
    since = r["ts"] if r else 0
    cum, peak = 0.0, None
    for o in sorted((o for o in orders if o["env"] == env and o.get("settled_ts") is not None),
                    key=lambda o: (o["settled_ts"], o["id"])):
        if o["settled_ts"] >= since and peak is None:
            peak = STAKE + cum
        cum += o.get("pnl") or 0
        if o["settled_ts"] >= since:
            peak = max(peak, STAKE + cum)
    if peak is None:
        peak = STAKE + cum if since else max(STAKE, STAKE + cum)
    v = STAKE + cum
    return v, peak, v < (1 - DRAWDOWN) * peak


def day_pnl(orders, now, env="prod"):
    """live.day_pnl: net of orders settled in the last 24 hours."""
    return sum(o.get("pnl") or 0 for o in orders if o["env"] == env and (o.get("settled_ts") or -1) >= now - 86400)


def at_risk(orders, env="prod"):
    """live.local_at_risk: filled and unsettled cost + fees, plus orders still being sent or unknown."""
    a = sum((o.get("cost") or 0) + (o.get("fees") or 0) for o in orders
            if o["env"] == env and (o.get("fill_count") or 0) > 0 and o.get("result") is None)
    for o in orders:
        if o["env"] == env and o["status"] in ("sending", "unknown"):
            p = o["limit_cents"] / 100.0
            a += o["count"] * p + fee(p, o["count"])
    return a


try:
    from core import fee   # the bot's own fee rule, so the page's at-risk figure is live.py's to the cent
except Exception:   # only if core cannot load; live.py cannot run then either
    def fee(p, n):
        import math
        return math.ceil(0.07 * n * p * (1 - p) * 100 - 1e-9) / 100.0


def stops(orders, events, now):
    """live.stops and the unknown-order hold, as far as live.db shows them: [plain reasons new orders are held]."""
    out = []
    m = last_event(events, "prod", ("mismatch", "reconciled", "resume"))
    if m and m["kind"] == "mismatch":
        out.append("a position on Kalshi differs from the ledger (%s); the next sync clears it if they agree" % (m.get("detail") or ""))
    if day_pnl(orders, now) <= -DAILY_STOP + 1e-9:
        out.append("the daily loss stop: %s of settled losses in 24 hours" % usd(DAILY_STOP))
    v, p, paused = value_track(orders, events)
    if paused:
        out.append("the 25%% drawdown: value %s, peak %s" % (usd(v), usd(p)))
    if any(o["env"] == "prod" and o["status"] in ("sending", "unknown") for o in orders):
        out.append("an order's outcome is unknown until the next sync")
    return out


def state(events, killed, today, stop_date, orders=(), now=None):
    """(short label, css class, sentence) for the account's lock state, from live.db only. The settings file's half
    of the unlock is not read here (live.py checks both), so an unlock is described as what live.db records, and
    `.\\run live status` is named as the full answer."""
    if killed:
        return "Halted", "on", "The kill switch is on: no orders go out on any exchange."
    if today < stop_date:
        return "Locked", "off", "Real money is locked until %s." % stop_date.strftime("%b %d, %Y").replace(" 0", " ")
    t = last_event(events, "prod", ("resume", "trial_end"))
    if t and t["kind"] == "trial_end":
        return "Trial ended", "off", ("The real-money trial ended at the 25% drawdown (your rule of Nov 7). Starting again "
                                      "needs you to type .\\run live resume and .\\run live unlock.")
    u = last_event(events, "prod", ("unlock", "lock"))
    if u and u["kind"] == "unlock":
        held = stops(list(orders), events, now) if now is not None else []
        if held:
            return "Unlocked, paused", "off", ("live.db records an unlock (since %s), but new orders are held: %s. "
                                               ".\\run live status shows the full state." % (when(u["ts"]), "; ".join(held)))
        return "Unlocked", "on", ("live.db records a real-money unlock (since %s). Orders go out after each evening scan "
                                  "while the exchange is set to prod; .\\run live status confirms it. Stop at any time: "
                                  ".\\run live lock." % when(u["ts"]))
    return "Locked", "off", "Real money is locked. Only you can unlock it (.\\run live unlock)."


# ---------- the section ----------
def tiles(orders, events, now):
    real = [o for o in orders if o["env"] == "prod" and o["status"] not in NOT_SENT and (o.get("fill_count") or 0) > 0]
    settled = [o for o in real if o.get("settled_ts") is not None]
    nopen = sum(1 for o in real if o.get("result") is None) + sum(1 for o in orders if o["env"] == "prod" and o["status"] in ("sending", "unknown") and not (o.get("fill_count") or 0))
    won = [o for o in settled if (o.get("pnl") or 0) > 0]
    v, peak, paused = value_track(orders, events)
    risk = at_risk(orders)
    dp = day_pnl(orders, now)
    floor = (1 - DRAWDOWN) * peak
    net = sum(o.get("pnl") or 0 for o in settled)
    fees = sum(o.get("fees") or 0 for o in real)

    def bar(used, room, warn=0.6):
        f = 0 if room <= 0 else max(0.0, min(1.0, used / room))
        return '<span class=rbar><i class="%s" style="width:%.0f%%"></i></span>' % ("bad" if f >= 1 else "warn" if f >= warn else "", 100 * f)

    out = [
        ("Open bets", usd(risk), "%d bet%s waiting for Kalshi's result. At most %s at risk at once." % (
            nopen, "" if nopen == 1 else "s", usd(MAX_AT_RISK)) + bar(risk, MAX_AT_RISK), ""),
        ("Settled bets", "%d won, %d lost" % (len(won), len(settled) - len(won)),
         "Net %s, fees included. Fees paid on all bets so far: %s." % (plus(net), usd(fees)), ""),
        ("Daily loss stop", usd(max(0.0, -dp)) + " of " + usd(DAILY_STOP),
         ("Net loss of bets settled in the last 24 hours. At %s, no new orders for the day." % usd(DAILY_STOP)) + bar(max(0.0, -dp), DAILY_STOP), "neg" if dp <= -DAILY_STOP + 1e-9 else ""),
        ("25% end rule", usd(max(0.0, v - floor)) + " to go",
         ("The real-money trial ends if the value falls below %s (25%% under its peak)." % usd(floor)) + bar(peak - v, peak - floor), "neg" if paused else ""),
    ]
    return '<dl class=rtiles>%s</dl>' % "".join(
        '<div><dt>%s</dt><dd class="%s">%s</dd><p>%s</p></div>' % (e(a), c, e(b), p) for a, b, p, c in out)


def groups(items, key):
    """Markers closer than 45 minutes to a group's first item are one marker (bets placed in one scan, results
    recorded in one settle); otherwise they would sit on top of each other and only one could be read."""
    out = []
    for it in sorted(items, key=key):
        if out and key(it) - key(out[-1][0]) <= 2700:
            out[-1].append(it)
        else:
            out.append([it])
    return out


def chart_data(orders, events, now):
    """What the chart draws: dict(t0, now, start, steps=[[settled_ts, change]], markers=[{t, kind, tip}]), or None
    without real orders. The value at t is $25 plus the net of orders settled at or before t, as live.py counts it
    (fees are part of a settled order's P&L, so the line moves only when a bet settles)."""
    real = [o for o in orders if o["env"] == "prod" and o["status"] not in NOT_SENT and (o.get("fill_count") or 0) > 0]
    if not real:
        return None
    u = last_event(events, "prod", ("unlock",))
    t0 = min([min(o["ts"] for o in real)] + ([u["ts"]] if u else [])) - 3600
    steps = [[o["settled_ts"], round(o.get("pnl") or 0, 6)]
             for o in sorted((o for o in real if o.get("settled_ts") is not None), key=lambda o: (o["settled_ts"], o["id"]))]

    def bought(o):
        city, side = bet_words(o)
        return "%s %s, %d contract%s at %d\u00a2 (cost %s + fee %s)%s" % (
            city, side, o["fill_count"], "" if o["fill_count"] == 1 else "s", o["limit_cents"],
            usd(o.get("cost") or 0), usd(o.get("fees") or 0),
            ", waiting for Kalshi's result" if o.get("result") is None else ", settled %s: %s" % (o["result"].upper(), plus(o.get("pnl") or 0)))

    marks = []
    for grp in groups(real, lambda o: o["ts"]):
        t = grp[0]["ts"]
        marks.append(dict(t=t, kind="buy", tip="%s: %s placed. %s." % (
            when(t), "1 bet" if len(grp) == 1 else "%d bets" % len(grp), "; ".join(bought(o) for o in grp))))
    for grp in groups([o for o in real if o.get("settled_ts") is not None], lambda o: o["settled_ts"]):
        t = grp[-1]["settled_ts"]
        net = sum(o.get("pnl") or 0 for o in grp)
        parts = []
        for o in grp:
            city, side = bet_words(o)
            p = o.get("pnl") or 0
            parts.append("%s %s %s %s (paid %s + fee %s)" % (city, side, "void, fee kept" if o.get("result") == "void" else
                                                             "won" if p > 0 else "lost", plus(p), usd(o.get("cost") or 0), usd(o.get("fees") or 0)))
        marks.append(dict(t=t, kind="won" if net > 0 else "lost", tip="%s: %s settled, net %s. %s." % (
            when(t), "1 bet" if len(grp) == 1 else "%d bets" % len(grp), plus(net), "; ".join(parts))))
    return dict(t0=t0, first=min(o["ts"] for o in real), now=now, start=STAKE, steps=steps, markers=sorted(marks, key=lambda m: m["t"]))


def value_at(d, t):
    return d["start"] + sum(c for ts, c in d["steps"] if ts <= t)


def static_svg(d):
    """The chart without JavaScript (all time, markers with their text), replaced by the interactive one."""
    W, H, PT, PB, PR = 720, 220, 22, 26, 10
    start, now = d["t0"], d["now"]
    pts = [[start, value_at(d, start)]] + [[t, value_at(d, t)] for t, _ in d["steps"] if start < t <= now] + [[now, value_at(d, now)]]
    lo = min(p[1] for p in pts); hi = max(p[1] for p in pts)
    pad = max((hi - lo) * 0.15, 0.25); lo -= pad; hi += pad
    X = lambda t: (t - start) / max(1.0, now - start) * (W - PR)
    Y = lambda v: PT + (hi - v) / (hi - lo) * (H - PT - PB)
    path = "M%.1f %.1f" % (X(pts[0][0]), Y(pts[0][1])) + "".join(" H%.1f V%.1f" % (X(t), Y(v)) for t, v in pts[1:])
    ch = pts[-1][1] - pts[0][1]
    tone = "up" if ch > 0.004 else "down" if ch < -0.004 else "flat"
    g = ['<line class=bl x1=0 x2=%d y1=%.1f y2=%.1f />' % (W, Y(pts[0][1]), Y(pts[0][1])), '<path class=ln d="%s" />' % path]
    for m in d["markers"]:
        if start <= m["t"] <= now:
            g.append('<g class="mk %s" tabindex=0 data-tip="%s"><title>%s</title><circle cx=%.1f cy=%.1f r=6 /></g>' % (
                m["kind"], e(m["tip"]), e(m["tip"]), X(m["t"]), Y(value_at(d, m["t"]))))
    return '<svg viewBox="0 0 %d %d" class=%s role=img aria-label="The bot\'s real-money value since the first order">%s</svg>' % (W, H, tone, "".join(g))


JS = r"""
(function(){var el=document.getElementById('rv-data');if(!el)return;
var D=JSON.parse(el.textContent),rng='ALL';
var RANGES={'1D':86400,'1W':7*86400,'1M':30*86400,'ALL':0};
var PER={'1D':'Past 24 hours','1W':'Past week','1M':'Past month','ALL':'Since the first real order'};
var TZ='America/La_Paz';
function $(i){return document.getElementById(i)}
function money(x){return (x<-0.004?'−$':'$')+Math.abs(x).toFixed(2)}
function signed(x){return (x>0.004?'+':(x<-0.004?'−':''))+'$'+Math.abs(x).toFixed(2)}
function dt(ts){var d=new Date(ts*1000);return d.toLocaleDateString(undefined,{month:'short',day:'numeric',timeZone:TZ})+', '+d.toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit',timeZone:TZ})}
function valueAt(t){var v=D.start;D.steps.forEach(function(s){if(s[0]<=t)v+=s[1]});return v}
var NS='http://www.w3.org/2000/svg';
function sv(tag,a){var n=document.createElementNS(NS,tag);for(var k in a)n.setAttribute(k,a[k]);return n}
function tone(ch){return ch>0.004?'up':(ch<-0.004?'down':'flat')}
function headline(v,base,label){var ch=v-base,d=$('rv-d');
  $('rv-v').textContent=money(v);
  d.className='acct-d '+(ch>0.004?'pos':(ch<-0.004?'neg':''));
  d.querySelector('.arr').textContent=ch>0.004?'▲':(ch<-0.004?'▼':'');
  $('rv-dv').textContent='$'+Math.abs(ch).toFixed(2)+' ('+(base?Math.abs(ch/base*100):0).toFixed(2)+'%)';
  $('rv-sg').textContent=ch>0.004?'up ':(ch<-0.004?'down ':'no change ');
  $('rv-per').textContent=label}
var view=null;
function draw(){
  var now=D.now,span=RANGES[rng],start=span?Math.max(D.t0,now-span):D.t0;
  var base=valueAt(start),cur=valueAt(now),pts=[[start,base]];
  D.steps.forEach(function(s){if(s[0]>start&&s[0]<=now)pts.push([s[0],valueAt(s[0])])});
  pts.push([now,cur]);
  var box=$('rv-chart'),W=Math.max(280,box.clientWidth),H=box.clientHeight||220,PT=22,PB=26,PR=10;
  var lo=Math.min.apply(null,pts.map(function(p){return p[1]})),hi=Math.max.apply(null,pts.map(function(p){return p[1]}));
  var pad=Math.max((hi-lo)*0.15,0.25);lo-=pad;hi+=pad;
  var X=function(t){return now>start?(t-start)/(now-start)*(W-PR):0},Y=function(v){return PT+(hi-v)/(hi-lo)*(H-PT-PB)};
  var d='M'+X(pts[0][0]).toFixed(1)+' '+Y(pts[0][1]).toFixed(1);
  for(var j=1;j<pts.length;j++){d+=' H'+X(pts[j][0]).toFixed(1)+' V'+Y(pts[j][1]).toFixed(1)}
  var cls=tone(cur-base);
  var s=sv('svg',{viewBox:'0 0 '+W+' '+H,role:'img',tabindex:'0','class':cls,
    'aria-label':"The bot's real-money value: "+money(cur)+' now, '+signed(cur-base)+' '+PER[rng].toLowerCase()+'. Drag or use the arrow keys to read past values; the markers are the bets.'});
  s.appendChild(sv('line',{'class':'bl',x1:0,x2:W,y1:Y(base),y2:Y(base)}));
  s.appendChild(sv('path',{'class':'ln',d:d}));
  var xh=sv('line',{'class':'xh',x1:0,x2:0,y1:4,y2:H-PB+6,visibility:'hidden'});s.appendChild(xh);
  var tl=sv('text',{'class':'tl',x:0,y:H-6,'text-anchor':'middle',visibility:'hidden'});s.appendChild(tl);
  var dot=sv('circle',{'class':'dot',cx:X(now),cy:Y(cur),r:4.5});s.appendChild(dot);
  var shown=0;
  D.markers.forEach(function(m){if(m.t<start||m.t>now)return;shown++;
    var g=sv('g',{'class':'mk '+m.kind,tabindex:'0','data-tip':m.tip,role:'img','aria-label':m.tip});
    g.appendChild(sv('circle',{cx:X(m.t),cy:Y(valueAt(m.t)),r:6}));s.appendChild(g)});
  if(!D.steps.length){var m=sv('text',{'class':'emptyc',x:W/2,y:Math.min(Y(base)+28,H-PB-4),'text-anchor':'middle'});
    m.textContent=shown?'No bets settled yet: the line moves when Kalshi settles them':'No bets in this period';s.appendChild(m)}
  box.innerHTML='';box.appendChild(s);box.className='acct-chart '+cls;
  $('rv-rng').className='rrng '+cls;
  view={start:start,now:now,X:X,Y:Y,W:W,base:base,cur:cur,xh:xh,tl:tl,dot:dot,svg:s,k:-1,pts:pts,label:PER[rng]+' · from '+money(base)};
  headline(cur,base,view.label);
  s.addEventListener('pointermove',scrub);s.addEventListener('pointerdown',scrub);
  s.addEventListener('pointerleave',reset);s.addEventListener('pointerup',function(ev){if(ev.pointerType!=='mouse')reset()});
  s.addEventListener('keydown',keys);s.addEventListener('blur',reset)}
function show(t){var v=valueAt(t),x=view.X(t);
  view.xh.setAttribute('x1',x);view.xh.setAttribute('x2',x);view.xh.setAttribute('visibility','visible');
  view.tl.textContent=dt(t);view.tl.setAttribute('x',Math.min(Math.max(x,48),view.W-48));view.tl.setAttribute('visibility','visible');
  view.dot.setAttribute('cx',x);view.dot.setAttribute('cy',view.Y(v));headline(v,view.base,dt(t))}
function scrub(ev){if(!view)return;if(ev.target.closest&&ev.target.closest('.mk')){reset();return}
  var r=view.svg.getBoundingClientRect(),f=Math.min(Math.max((ev.clientX-r.left)/r.width,0),1);show(view.start+f*(view.now-view.start))}
function keys(ev){if(!view)return;var n=view.pts.length;
  if(ev.key==='ArrowLeft'||ev.key==='ArrowRight'){ev.preventDefault();view.k=(view.k<0?n-1:view.k)+(ev.key==='ArrowLeft'?-1:1);view.k=Math.min(Math.max(view.k,0),n-1);show(view.pts[view.k][0])}
  else if(ev.key==='Escape'){reset()}}
function reset(){if(!view)return;view.k=-1;view.xh.setAttribute('visibility','hidden');view.tl.setAttribute('visibility','hidden');
  view.dot.setAttribute('cx',view.X(view.now));view.dot.setAttribute('cy',view.Y(view.cur));headline(view.cur,view.base,view.label)}
$('rv-rng').hidden=false;Array.prototype.forEach.call(document.querySelectorAll('#real .rv-js'),function(n){n.hidden=false});
Array.prototype.forEach.call(document.querySelectorAll('#rv-rng button'),function(b){b.addEventListener('click',function(){rng=b.getAttribute('data-r');
  Array.prototype.forEach.call(document.querySelectorAll('#rv-rng button'),function(x){x.setAttribute('aria-pressed',x===b?'true':'false')});draw()})});
try{draw()}catch(err){}
var rt;window.addEventListener('resize',function(){clearTimeout(rt);rt=setTimeout(function(){try{draw()}catch(err){}},150)});
})();
"""


def chart(orders, events, now):
    """The value panel: headline, chart (interactive with JavaScript, a static drawing without), ranges, legend."""
    d = chart_data(orders, events, now)
    if d is None:
        return '<p class=note>No real orders yet. The first ones appear here after an evening scan copies a paper trade.</p>'
    v0, v1 = value_at(d, d["t0"]), value_at(d, now)
    ch = v1 - v0
    js = json.dumps(d, separators=(",", ":"), allow_nan=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    tone = "up" if ch > 0.004 else "down" if ch < -0.004 else "flat"
    first = datetime.fromtimestamp(d["first"], TZ).strftime("%b %d").replace(" 0", " ")
    return ('<p class=acct-v id=rv-v>%s</p>'
            '<p class="acct-d %s" id=rv-d><span class=arr aria-hidden=true>%s</span><span class=sr id=rv-sg>%s </span>'
            '<span id=rv-dv>$%.2f (%.2f%%)</span> <span class=per id=rv-per>Since the first real order (%s) \u00b7 from %s</span></p>'
            '<div class="acct-chart rv-static %s" id=rv-chart>%s</div>'
            '<div class="rrng %s" id=rv-rng role=group aria-label="Time range for the real-money chart" hidden>%s</div>'
            '<p class=rleg><span><i style="background:#3b7ddd"></i>Bets placed</span><span><i style="background:var(--good,#0ca30c)"></i>Settled, net won</span>'
            '<span><i style="background:var(--bad,#d03b3b)"></i>Settled, net lost</span></p>'
            '<p class=note>The bot&#8217;s value: your $25 plus the net of settled bets, as live.py counts it for its stops. It moves only when '
            'Kalshi settles a bet.<span class=rv-js hidden> Drag across the chart (or use the arrow keys) to read past values; hover over or tap a marker to see the bets.</span></p>'
            '<script type="application/json" id=rv-data>%s</script>') % (
        usd(v1), "pos" if ch > 0.004 else "neg" if ch < -0.004 else "", "\u25b2" if ch > 0.004 else "\u25bc" if ch < -0.004 else "",
        "up" if ch > 0.004 else "down" if ch < -0.004 else "no change", abs(ch), abs(ch) / v0 * 100 if v0 else 0.0, first, usd(v0),
        tone, static_svg(d), tone,
        "".join('<button type=button data-r="%s" aria-pressed=%s>%s</button>' % (r, "true" if r == "ALL" else "false", r)
                for r in ("1D", "1W", "1M", "ALL")), js)


def calendar(orders, now):
    real = [o for o in orders if o["env"] == "prod" and o["status"] not in NOT_SENT and (o.get("fill_count") or 0) > 0]
    by = {}
    for o in real:
        d = market(o["ticker"])[0]
        if d:
            by.setdefault(d, []).append(o)
    if not by:
        return ""
    first = min(by)
    last = max(max(by), datetime.fromtimestamp(now, TZ).date())
    start = first - timedelta(days=first.weekday())
    cells = ['<div class=h>%s</div>' % d for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")]
    d = start
    while d <= last:
        os_ = by.get(d, [])
        lab = d.strftime("%b %d").replace(" 0", " ")
        if not os_:
            cells.append('<div class="d none"><b>%s</b>%s</div>' % (lab, "" if d < first else "no bets"))
        else:
            done = [o for o in os_ if o.get("result") is not None]
            net = sum(o.get("pnl") or 0 for o in done)
            cls = "open" if len(done) < len(os_) else ("won" if net > 0 else "lost")
            lines = []
            for o in os_:
                city, side = bet_words(o)
                lines.append("%s %s x%d at %d¢: %s" % (city, side, o["fill_count"], o["limit_cents"],
                                                            "open" if o.get("result") is None else plus(o.get("pnl") or 0)))
            tip = "Market day %s. %s" % (lab, "; ".join(lines))
            cells.append('<div class="d %s" tabindex=0 data-tip="%s"><b>%s</b>%d bet%s<br>%s</div>' % (
                cls, e(tip), lab, len(os_), "" if len(os_) == 1 else "s", "open" if cls == "open" else plus(net)))
        d += timedelta(days=1)
    return '<h3>Calendar <span class=note>by market day; hover or tap a day</span></h3><div class=rcal>%s</div>' % "".join(cells)


def order_rows(orders):
    rows, skipped, unknown = [], [], []
    for o in sorted((o for o in orders if o["env"] == "prod"), key=lambda o: o["ts"], reverse=True):
        city, side = bet_words(o)
        day = market(o["ticker"])[0]
        dl = day.strftime("%b %d").replace(" 0", " ") if day else ""
        if o["status"] in ("sending", "unknown"):
            unknown.append([e(dl), e(city), e(side), "%d" % o["count"], "%d\u00a2" % o["limit_cents"],
                            "outcome unknown: no new orders until the next sync looks it up"])
            continue
        if o["status"] in NOT_SENT or not (o.get("fill_count") or 0):
            skipped.append([e(dl), e(city), e(side), "%d" % o["count"], "%d¢" % o["limit_cents"], e(o["status"]), e(o.get("note") or "")])
            continue
        res = ("open" if o.get("result") is None else "void (fee kept)" if o["result"] == "void"
               else "won" if (o.get("pnl") or 0) > 0 else "lost")
        rows.append([e(dl), e(city), e(side), "%d" % o["fill_count"], "%d¢" % o["limit_cents"],
                     usd((o.get("cost") or 0) + (o.get("fees") or 0)), res, "" if o.get("result") is None else plus(o.get("pnl") or 0)])
    return rows, skipped, unknown


def paper_vs_real(orders, paper):
    """For every market a real order was copied on: the paper trade's result next to the real one's."""
    pid = {t.get("id"): t for t in paper}
    rows, pt, rt = [], 0.0, 0.0
    for o in sorted((o for o in orders if o["env"] == "prod" and o["status"] not in NOT_SENT and (o.get("fill_count") or 0) > 0),
                    key=lambda o: o["ts"]):
        t = pid.get(o.get("paper_id"))
        city, side = bet_words(o)
        pp = None if not t or t.get("status") != "settled" else (t.get("pnl") or 0)
        rp = None if o.get("result") is None else (o.get("pnl") or 0)
        if pp is not None and rp is not None:   # totals only where both sides have settled
            pt += pp
            rt += rp
        d = market(o["ticker"])[0]
        rows.append([e(d.strftime("%b %d").replace(" 0", " ") if d else ""), e(city), e(side), "%s" % (t.get("n") if t else "?"), "%d" % o["fill_count"],
                     "open" if pp is None else plus(pp), "open" if rp is None else plus(rp)])
    return rows, pt, rt


def section(orders, events, paper, now, killed, stop_date, table):
    """The whole real-money panel. table(headers, rows, empty, num=...) is dashboard.table."""
    today = datetime.fromtimestamp(now, TZ).date()
    lab, cls, sent = state(events, killed, today, stop_date, orders, now)
    demo = [o for o in orders if o["env"] == "demo" and o["status"] not in NOT_SENT and (o.get("fill_count") or 0) > 0]
    rows, skipped, unknown = order_rows(orders)
    pv, pt, rt = paper_vs_real(orders, paper)
    head = ('<section class="panel real acct" id=real aria-labelledby=real-h><div class=rv-top><h2 id=real-h>Real money on Kalshi</h2>'
            '<span class="rstate %s">%s</span></div>') % (cls, e(lab))
    body = [head, chart(orders, events, now), tiles(orders, events, now),
            '<p class=note>%s Orders come only from live.py, which copies the paper bot&#8217;s rain bets after each evening scan, '
            'within your limits. This page only reads the bot&#8217;s ledger (live.db); <code>.\\run live status</code> also shows '
            'Kalshi&#8217;s own balance.</p>' % e(sent), calendar(orders, now),
            '<h3>Real orders</h3>',
            table(["Market day", "City", "Bet", "Contracts", "Limit price", "Cost incl. fee", "Result", "P&amp;L"], rows,
                  "No real orders yet.", num=(3, 4, 5, 7)),
            '<h3>Paper vs real <span class=note>the same markets</span></h3>',
            table(["Market day", "City", "Bet", "Paper contracts", "Real contracts", "Paper P&amp;L", "Real P&amp;L"], pv,
                  "Nothing to compare yet.", num=(3, 4, 5, 6)),
            '<p class=note>Where both have settled: paper %s, real %s (contract counts can differ: a real copy can be smaller, if '
            'the price moved or a limit cut it). Some paper bets are not copied at all (below).</p>' % (plus(pt), plus(rt))]
    if unknown:
        body.append('<h3>Orders with an unknown outcome</h3><p class=note>The bot sent these but did not hear back. It never re-sends '
                    'them; the next sync looks them up on Kalshi, and no new orders go out until it has.</p>%s' % table(
                        ["Market day", "City", "Bet", "Contracts", "Limit price", "Status"], unknown, "", num=(3, 4)))
    if skipped:
        body.append('<details><summary>Paper bets not copied with real money (%d)</summary>%s</details>' % (
            len(skipped), table(["Market day", "City", "Bet", "Contracts", "Price", "Status", "Why"], skipped, "", num=(3, 4))))
    if demo:
        body.append('<p class=note>Demo exchange (fake money): %d filled order%s; not counted here.</p>' % (len(demo), "" if len(demo) == 1 else "s"))
    body.append('<p class=fine>Real money. Results depend on Kalshi&#8217;s settlement; fees are the bot&#8217;s whole-cent estimate. Not financial advice.</p></section>')
    return "".join(body)

