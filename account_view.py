"""Account view for the dashboard (presentation only; added 2026-10-14 at the user's request).
A brokerage-style paper account: value over time with 1D/1W/1M/3M/ALL ranges, an activity list, monthly statements and a
yearly gains-and-losses report, for the main bot and for the limit-order test. dashboard.py passes rows it already read
(read-only); this module never opens paper.db, the network or any file. Downloads (CSV and a printable HTML copy) are
built in the page: on the phone page through the artifact's downloads capability, on the PC as a normal browser download.
Value model: open trades count at what they cost; a fee counts when paid; a settled trade adds its payout minus cost.
Live prices (2026-10-15, user request): when dashboard.py passes price snapshots from marks.py, the chart, the headline
and "In open trades" count each open trade at its latest Kalshi bid instead of its cost (marked to market). The monthly
statements and the gains report stay on settled results.
Paper trading only: nothing here is a tax document. Python 3.8+, no dependencies."""
import json, html, math
from datetime import datetime, timezone, timedelta
e=html.escape
# Times are shown in the bot's zone, La Paz (UTC-4 all year), on the PC and in the page's own script, whatever zone
# the viewing device uses (2026-10-23). The same zone as tbcommon/clock.py; kept here so this module needs nothing else.
BOT_TZ=timezone(timedelta(hours=-4))
NAMES={"ABQ":"Albuquerque","ATL":"Atlanta","AUS":"Austin","BOS":"Boston","CHI":"Chicago","CLL":"College Station","CMH":"Columbus",
 "DAL":"Dallas","DC":"Washington","DEN":"Denver","DET":"Detroit","EWR":"Newark","HOU":"Houston","IND":"Indianapolis","LAX":"Los Angeles",
 "LEX":"Lexington","LV":"Las Vegas","MIA":"Miami","MIN":"Minneapolis","MKE":"Milwaukee","NOLA":"New Orleans","NYC":"New York",
 "NY":"New York","OKC":"Oklahoma City","PHIL":"Philadelphia","PHX":"Phoenix","PIT":"Pittsburgh","PVD":"Providence",
 "SATX":"San Antonio","SEA":"Seattle","SFO":"San Francisco","SGF":"Springfield","STL":"St. Louis","TPA":"Tampa","TTN":"Trenton",
 "SAN":"San Diego","SDF":"Louisville","DTW":"Detroit","WPB":"West Palm Beach"}
def label(t):
    """'KXRAIN-26OCT14-PHIL' -> 'Philadelphia rain, Oct 14'; 'KXHIGHDEN-26OCT14-T48' -> 'Denver high temperature, Oct 14 (48° line)'."""
    p=(t or "").split("-")
    try: d=datetime.strptime(p[1],"%y%b%d"); ds=d.strftime("%b ")+str(d.day)
    except (IndexError,ValueError): return t or ""
    if p[0]=="KXRAIN": return "%s rain, %s"%(NAMES.get(p[2],p[2]),ds) if len(p)>2 else "Rain, %s"%ds
    if p[0].startswith("KXHIGH"):
        c=p[0][6:]; c=c[1:] if c.startswith("T") and c[1:] in NAMES else c
        line=p[2][1:] if len(p)>2 and p[2][:1] in "TB" else ""
        return "%s high temperature, %s%s"%(NAMES.get(c,c),ds," (%s° line)"%line if line else "")
    return t
def _r(x,k=4):
    if x is None: return None
    x=float(x); return round(x,k) if math.isfinite(x) else None
def main_ledger(tr,bank,t0):
    trades=[]; ev=[]
    for r in sorted(tr,key=lambda r:r.get("ts") or 0):
        cost=float(r.get("cost") or 0); fee=float(r.get("fee") or 0); n=int(r.get("n") or 0); ts=r.get("ts") or t0
        st,payout,closed="open",None,None
        if r.get("status")=="settled" and r.get("result") in ("yes","no"):
            payout=float(n if r.get("result")==r.get("side") else 0); closed=r.get("settled_ts") or ts; st="won" if payout>0 else "lost"
        trades.append(dict(id=r.get("id"),ts=ts,label=label(r.get("ticker")),ticker=r.get("ticker"),side=(r.get("side") or "").upper(),n=n,
                           price=_r(r.get("price")),cost=_r(cost),fee=_r(fee),status=st,payout=payout,closed=closed,ver=r.get("version") or "",
                           nodate=bool(closed is not None and not r.get("settled_ts"))))
        if fee: ev.append([ts,-fee])
        if closed is not None: ev.append([closed,payout-cost])
    ev.sort(key=lambda x:x[0]); return dict(name="Main bot",start=bank,t0=t0,events=[[a,_r(b,6)] for a,b in ev],trades=trades)
def maker_ledger(so,bank,t0):
    """The limit-order test's own hypothetical account. A resting order changes nothing; a fill pays its (zero) fee; a
    settled fill adds payout minus cost."""
    trades=[]; ev=[]
    for r in sorted(so,key=lambda r:r.get("ts") or 0):
        cost=float(r.get("cost") or 0); fee=float(r.get("fee") or 0); n=int(r.get("n") or 0); ts=r.get("ts") or t0
        s=r.get("status") or "pending"; payout=closed=None
        st={"pending":"resting","unfilled":"unfilled","filled":"open"}.get(s,"open")
        if s=="settled" and r.get("result") in ("yes","no"):
            payout=float(n if r.get("result")==r.get("side") else 0); closed=r.get("settle_ts") or ts; st="won" if payout>0 else "lost"
        trades.append(dict(id=r.get("id"),ts=ts,label=label(r.get("ticker")),ticker=r.get("ticker"),side=(r.get("side") or "").upper(),n=n,
                           price=_r(r.get("price")),cost=_r(cost),fee=_r(fee),status=st,payout=payout,closed=closed,filled=r.get("fill_ts"),
                           cancel=r.get("cancel_ts"),improved=bool(r.get("improved")),nodate=bool(closed is not None and not r.get("settle_ts"))))
        if fee and r.get("fill_ts"): ev.append([r["fill_ts"],-fee])
        if closed is not None: ev.append([closed,payout-cost])
    ev.sort(key=lambda x:x[0]); return dict(name="Limit-order test",start=bank,t0=t0,events=[[a,_r(b,6)] for a,b in ev],trades=trades)
def value_at(L,t):
    return L["start"]+sum(d for ts,d in L["events"] if ts<=t)
def mark_points(L,snaps,prefix,now):
    """Unrealized gain of the open trades over time: [[ts, sum of (latest marked value - cost)]], one point at each price
    snapshot and at each ledger event after the first snapshot (so a trade that settles drops out at once and never
    counts twice). A trade without a price yet stays at cost. Returns (points, time of the last snapshot)."""
    tr={"%s:%s"%(prefix,t["id"]):t for t in L["trades"] if t.get("id") is not None}
    sn=sorted((x for x in snaps or [] if L["t0"]<=x.get("ts",0)<=now and any(k in tr for k in (x.get("marks") or {}))),key=lambda x:x["ts"])
    if not sn: return [],None
    times=sorted({x["ts"] for x in sn}|{ev[0] for ev in L["events"] if sn[0]["ts"]<ev[0]<=now})
    latest={}; out=[]; i=0
    for t in times:
        while i<len(sn) and sn[i]["ts"]<=t:
            for k,v in sn[i]["marks"].items():
                if k in tr and v is not None: latest[k]=float(v)
            i+=1
        u=0.0
        for k,v in latest.items():
            x=tr[k]
            if x.get("closed") is not None and x["closed"]<=t: continue
            u+=v-(x.get("cost") or 0)
        out.append([t,_r(u,4)])
    return out,sn[-1]["ts"]
def note(m,now,live):
    """The line under the chart: how open trades are valued and how fresh the prices are."""
    refresh=(" While <code>run watch</code> is open, prices and this page refresh every 5 minutes." if live else
             " For prices every 5 minutes, run <code>.\\run watch</code> on the PC.")
    if m.get("marked") and m.get("marks") and any(t["status"]=="open" for t in m["trades"]):
        age=now-m["marked"]; d=datetime.fromtimestamp(m["marked"],BOT_TZ); when="%s %d, %d:%02d %s"%(d.strftime("%b"),d.day,(d.hour%12) or 12,d.minute,"AM" if d.hour<12 else "PM")
        stale=" These prices are %s old."%("%.0f hours"%(age/3600) if age>=7200 else "over an hour") if age>3600 else ""
        return ("Paper money, no real dollars. Open trades count at their Kalshi bid, what they could be sold for (prices from %s);"
                " fees count when paid, and a trade counts at its payout once it settles. A trade with no price yet keeps its last price (or its"
                " cost). Statements and the P&amp;L tile count settled trades only.%s%s")%(e(when),stale,refresh)
    return ("Paper money, no real dollars. Open trades count at what they cost and fees count when paid, so the line moves when"
            " a trade opens (its fee) and when it settles.%s")%refresh
def section(tr,so,bank,t0,now,marks=None,live=False):
    """The two panels (account chart, then activity and documents) plus the embedded data. Works without JavaScript
    for the headline numbers; the chart, lists and downloads are drawn by ACCT_JS. marks: price snapshots from marks.py
    ([{ts, marks: {"main:<id>"|"maker:<id>": value}}]); live: the page refreshes itself (run watch)."""
    m=main_ledger(tr,bank,t0); k=maker_ledger(so,bank,t0)
    for L,pre in ((m,"main"),(k,"maker")): L["marks"],L["marked"]=mark_points(L,marks,pre,now)
    data=dict(now=now,bank=bank,ledgers=dict(main=m,maker=k))
    def un(L,t):
        u=0.0
        for p in L["marks"]:
            if p[0]<=t: u=p[1]
        return u
    v=value_at(m,now)+un(m,now); b0=max(t0,now-86400); base=value_at(m,b0)+un(m,b0); ch=v-base
    cls="pos" if ch>0.004 else ("neg" if ch<-0.004 else "")
    arrow="▲" if ch>0.004 else ("▼" if ch<-0.004 else "")
    js=json.dumps(data,separators=(",",":"),allow_nan=False).replace("&","\\u0026").replace("<","\\u003c").replace(">","\\u003e")   # nothing in the data can end or comment out the script block
    acct=('<section class="panel acct" id=acct aria-labelledby=acct-h>'
          '<div class=acct-top><h2 id=acct-h>Paper account</h2>'
          '<div class=seg role=group aria-label="Which paper account"><button type=button data-led=main aria-pressed=true>Main bot</button>'
          '<button type=button data-led=maker aria-pressed=false>Limit-order test</button></div></div>'
          '<p class=acct-v id=acct-v>$%.2f</p>'
          '<p class="acct-d %s" id=acct-d><span class=arr aria-hidden=true>%s</span><span class=sr id=acct-sg>%s </span><span id=acct-dv>$%.2f (%.2f%%)</span> <span class=per id=acct-per>Past 24 hours \u00b7 from $%.2f</span></p>'
          '<div class=acct-chart id=acct-chart></div>'
          '<div class=rng role=group aria-label="Time range">%s</div>'
          '<dl class=acct-facts id=acct-facts></dl>'
          '<p class=note id=acct-note>%s</p>'
          '</section>')%(v,cls,arrow,"up" if ch>0.004 else ("down" if ch<-0.004 else "no change"),abs(ch),abs(ch)/base*100 if base else 0.0,base,
          "".join('<button type=button data-r="%s" aria-pressed=%s>%s</button>'%(r,"true" if r=="1D" else "false",r) for r in ("1D","1W","1M","3M","ALL")),note(m,now,live))
    docs=('<section class="panel docs" id=docs aria-label="Activity and documents">'
          '<div class=tabs role=tablist aria-label="Account records"><button type=button role=tab id=tb-act aria-controls=tp-act aria-selected=true>Activity</button>'
          '<button type=button role=tab id=tb-stm aria-controls=tp-stm aria-selected=false tabindex=-1>Statements</button>'
          '<button type=button role=tab id=tb-tax aria-controls=tp-tax aria-selected=false tabindex=-1>Tax report</button></div>'
          '<div class=tabp role=tabpanel id=tp-act aria-labelledby=tb-act><div class=chips role=group aria-label="Show">'
          '<button type=button data-f=all aria-pressed=true>All</button><button type=button data-f=open aria-pressed=false>Open</button><button type=button data-f=closed aria-pressed=false>Closed</button></div>'
          '<ul class=act id=act-list><li class=empty>No paper trades yet.</li></ul></div>'
          '<div class=tabp role=tabpanel id=tp-stm aria-labelledby=tb-stm hidden><div id=stm-list></div></div>'
          '<div class=tabp role=tabpanel id=tp-tax aria-labelledby=tb-tax hidden><p class=paperbanner><b>Paper trading – not a tax document.</b> These are simulated trades: no real money changed hands and there is nothing to report or file.</p><div id=tax-list></div></div>'
          '<p class=dlnote id=dl-note hidden></p>'
          '</section>')
    return acct+docs+'<script type="application/json" id=acct-data>'+js+'</script>'

ACCT_CSS="""
.acct{display:grid;gap:6px}
.acct-top{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;justify-content:space-between}
.acct-top h2{margin:0}
.seg{display:inline-flex;background:var(--sunk);border-radius:99px;padding:3px;gap:2px}
.seg button,.chips button,.rng button,.tabs button,.dl button{font:600 13px/1 var(--text);border:0;cursor:pointer;color:var(--ink2);background:transparent;border-radius:99px;padding:8px 12px;min-height:32px}
.seg button[aria-pressed=true]{background:var(--surface);color:var(--ink);box-shadow:0 0 0 1px var(--ring)}
.acct-v{font:600 44px/1.05 var(--text);letter-spacing:-.01em;margin-top:6px}
@media(min-width:720px){.acct-v{font-size:52px}}
.acct-d{font-size:15px;font-weight:600;color:var(--ink2);font-variant-numeric:tabular-nums}.acct-d .per{font-weight:400;color:var(--ink2)}
.acct-d.pos{color:var(--goodt)}.acct-d.neg{color:var(--badt)}.acct-d .arr{margin-right:4px;font-size:12px}
.acct-chart{position:relative;margin-top:6px;height:220px;touch-action:pan-y;user-select:none;-webkit-user-select:none}
@media(min-width:720px){.acct-chart{height:260px}}
.acct-chart svg{width:100%;height:100%;overflow:visible}
.acct-chart svg:focus-visible{outline:2px solid var(--acc);outline-offset:4px;border-radius:6px}
.acct-chart .ln{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.acct-chart .bl{stroke:var(--mut);stroke-width:1.5;stroke-dasharray:1 5;stroke-linecap:round}
.acct-chart .xh{stroke:var(--rule);stroke-width:1}
.acct-chart .dot{stroke:var(--surface);stroke-width:2}
.acct-chart .tl{fill:var(--ink2);font-size:12px;font-variant-numeric:tabular-nums}
.acct-chart .emptyc{fill:var(--mut);font-size:13px}
.up{--tone:var(--good);--tonet:var(--goodt)}.down{--tone:var(--bad);--tonet:var(--badt)}.flat{--tone:var(--fc);--tonet:var(--ink2)}
.acct-chart .ln,.acct-chart .dot{stroke:var(--tone)}.acct-chart .dot{fill:var(--tone);stroke:var(--surface)}
.rng{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}
.rng button{color:var(--tonet);min-width:48px}
.rng button[aria-pressed=true]{background:var(--tonet);color:var(--surface)}
.acct-facts{margin:8px 0 0;display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px 20px;padding-top:12px;border-top:1px solid var(--grid)}
.acct-facts div{min-width:0}.acct-facts dt{font-size:12.5px;color:var(--ink2)}.acct-facts dd{margin:2px 0 0;font-size:17px;font-weight:600;font-variant-numeric:tabular-nums}
.acct-facts dd.pos{color:var(--goodt)}.acct-facts dd.neg{color:var(--badt)}
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--rule);margin:-4px 0 14px;overflow-x:auto}
.tabs button{border-radius:8px 8px 0 0;padding:10px 12px;color:var(--ink2);position:relative}
.tabs button[aria-selected=true]{color:var(--ink)}
.tabs button[aria-selected=true]::after{content:"";position:absolute;left:8px;right:8px;bottom:-1px;height:3px;border-radius:3px 3px 0 0;background:var(--acc)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
.chips button{background:var(--sunk);padding:7px 12px}
.chips button[aria-pressed=true]{background:var(--ink);color:var(--surface)}
.act{list-style:none;margin:0;padding:0}
.act li{display:grid;grid-template-columns:1fr auto;gap:2px 12px;padding:12px 2px;border-bottom:1px solid var(--grid)}
.act li.empty{display:block;color:var(--mut);border:0}
.act li.more{display:block;border:0;padding-top:10px}.act li.more button{font:600 13.5px/1 var(--text);color:var(--acc);background:var(--sunk);border:0;border-radius:8px;padding:10px 14px;cursor:pointer}
.act .t1{font-weight:600;min-width:0;overflow-wrap:anywhere}.act .t2{font-size:13px;color:var(--ink2);grid-column:1}
.act .amt{font-weight:600;text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.act .st{grid-column:2;justify-self:end;font-size:12px}
.act .when{font-size:12.5px;color:var(--mut);grid-column:1}
.tag.open,.tag.resting{color:var(--acc)}.tag.unfilled{color:var(--mut)}
.stm{border:1px solid var(--grid);border-radius:12px;padding:14px 16px;margin-bottom:12px}
.stm h3{margin:0}.stm .sub2{font-size:13px;color:var(--ink2);margin:2px 0 10px}
.stm dl{margin:0;display:grid;grid-template-columns:1fr auto;gap:6px 16px;font-size:14px}
.stm dt{color:var(--ink2)}.stm dd{margin:0;text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
.stm dt.tot,.stm dd.tot{border-top:1px solid var(--rule);padding-top:6px;color:var(--ink)}
.stm .cnt{font-size:13px;color:var(--ink2);margin-top:10px}
.dl{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.dl button{background:var(--sunk);color:var(--acc);border-radius:8px;padding:9px 12px}
.dl button:hover{background:var(--grid)}
.paperbanner{background:var(--sunk);border-left:3px solid var(--warn);border-radius:8px;padding:10px 12px;font-size:13.5px;color:var(--ink2);margin-bottom:12px}
.paperbanner b{color:var(--ink)}
.taxsum{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:10px 16px;margin:4px 0 8px}
.docs th,.docs td{padding:8px 6px}.docs td.tm{white-space:normal;min-width:0;width:60%}.docs .scroll{overflow-x:visible}.showall{font:600 13px/1 var(--text);color:var(--acc);background:var(--sunk);border:0;border-radius:8px;padding:9px 12px;margin-top:10px;cursor:pointer}
.taxsum div{display:grid}.taxsum span{font-size:12.5px;color:var(--ink2)}.taxsum b{font-size:18px;font-variant-numeric:tabular-nums}
.dlnote{font-size:12.5px;color:var(--mut);margin-top:10px}
"""

ACCT_JS=r"""
(function(){
var el=document.getElementById('acct-data'); if(!el) return;
var D=JSON.parse(el.textContent), led='main', rng='1D', filt='all', more=false, SHOW=8;
var RANGES={'1D':86400,'1W':7*86400,'1M':30*86400,'3M':90*86400,'ALL':0};
var PER={'1D':'Past 24 hours','1W':'Past week','1M':'Past month','3M':'Past 3 months','ALL':'Since the test started'};
var $=function(id){return document.getElementById(id)};
function L(){return D.ledgers[led]}
function money(x){var s=Math.abs(x).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g,',');return (x<-0.004?'−$':'$')+s}
function signed(x){return (x>0.004?'+':(x<-0.004?'−':''))+'$'+Math.abs(x).toFixed(2)}
function cents(p){return Math.round(p*100)+'¢'}
var TZ='America/La_Paz',OFF=-4*3600;   // the bot's zone, whatever the viewing device uses
function bd(ts){return new Date((ts+OFF)*1000)}   // read with getUTC*: the calendar date and time in the bot's zone
function dt(ts){var d=new Date(ts*1000);return d.toLocaleDateString(undefined,{month:'short',day:'numeric',timeZone:TZ})+', '+d.toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit',timeZone:TZ})}
function dday(ts){return new Date(ts*1000).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric',timeZone:TZ})}
function valueAt(l,t){var v=l.start;for(var i=0;i<l.events.length;i++){if(l.events[i][0]<=t)v+=l.events[i][1];}return v}
function unreal(l,t){var m=l.marks||[],u=0;for(var i=0;i<m.length&&m[i][0]<=t;i++)u=m[i][1];return u}   // open trades at Kalshi prices minus cost
function markedAt(l,t){return valueAt(l,t)+unreal(l,t)}   // the chart and headline; statements stay on settled results (valueAt)
function txt(tag,cls,s){var n=document.createElement(tag);if(cls)n.className=cls;if(s!=null)n.textContent=s;return n}
var SVGNS='http://www.w3.org/2000/svg';
function sv(tag,attrs){var n=document.createElementNS(SVGNS,tag);for(var k in attrs)n.setAttribute(k,attrs[k]);return n}
// ---------- headline + chart ----------
var view=null;
function tone(ch){return ch>0.004?'up':(ch<-0.004?'down':'flat')}
function headline(v,base,label){
  var ch=v-base, d=$('acct-d');
  $('acct-v').textContent=money(v);
  d.className='acct-d '+(ch>0.004?'pos':(ch<-0.004?'neg':''));
  d.querySelector('.arr').textContent=ch>0.004?'▲':(ch<-0.004?'▼':'');
  $('acct-dv').textContent='$'+Math.abs(ch).toFixed(2)+' ('+(base?Math.abs(ch/base*100):0).toFixed(2)+'%)';   // the arrow carries the sign
  $('acct-sg').textContent=ch>0.004?'up ':(ch<-0.004?'down ':'no change ');
  $('acct-per').textContent=label;
}
function draw(){
  var l=L(), now=D.now, span=RANGES[rng], t0=l.t0, start=span?Math.max(t0,now-span):t0;
  var base=markedAt(l,start), cur=markedAt(l,now);
  var pts=[[start,base]], ts=[];
  l.events.forEach(function(e){if(e[0]>start&&e[0]<=now)ts.push(e[0])});
  (l.marks||[]).forEach(function(p){if(p[0]>start&&p[0]<=now)ts.push(p[0])});
  ts.sort(function(a,b){return a-b}).forEach(function(t){pts.push([t,markedAt(l,t)])});
  pts.push([now,cur]);
  var box=$('acct-chart'), W=Math.max(280,box.clientWidth), H=box.clientHeight||220, PT=22, PB=26, PR=10;
  var lo=Math.min.apply(null,pts.map(function(p){return p[1]})), hi=Math.max.apply(null,pts.map(function(p){return p[1]}));
  var pad=Math.max((hi-lo)*0.15,0.25); lo-=pad; hi+=pad;
  var X=function(t){return (now>start)?(t-start)/(now-start)*(W-PR):0}, Y=function(v){return PT+(hi-v)/(hi-lo)*(H-PT-PB)};
  var d='M'+X(pts[0][0]).toFixed(1)+' '+Y(pts[0][1]).toFixed(1);
  for(var j=1;j<pts.length;j++){d+=' H'+X(pts[j][0]).toFixed(1)+' V'+Y(pts[j][1]).toFixed(1)}
  var cls=tone(cur-base);
  var s=sv('svg',{viewBox:'0 0 '+W+' '+H,role:'img',tabindex:'0','class':cls,
    'aria-label':l.name+' paper account: '+money(cur)+' now, '+signed(cur-base)+' '+PER[rng].toLowerCase()+'. Drag or use the arrow keys to read past values.'});
  s.appendChild(sv('line',{'class':'bl',x1:0,x2:W,y1:Y(base),y2:Y(base)}));
  s.appendChild(sv('path',{'class':'ln',d:d}));
  var xh=sv('line',{'class':'xh',x1:0,x2:0,y1:4,y2:H-PB+6,visibility:'hidden'}); s.appendChild(xh);
  var tl=sv('text',{'class':'tl',x:0,y:H-6,'text-anchor':'middle',visibility:'hidden'}); s.appendChild(tl);
  var dot=sv('circle',{'class':'dot',cx:X(now),cy:Y(cur),r:4.5}); s.appendChild(dot);
  if(l.events.length===0&&!(l.marks||[]).some(function(p){return Math.abs(p[1])>0.004})){var m=sv('text',{'class':'emptyc',x:W/2,y:Y(base)+22,'text-anchor':'middle'});m.textContent='No gains or losses yet';s.appendChild(m)}
  box.innerHTML=''; box.appendChild(s); box.className='acct-chart '+cls;
  document.querySelector('.rng').className='rng '+cls;
  view={start:start,now:now,X:X,Y:Y,W:W,H:H,PB:PB,base:base,cur:cur,xh:xh,tl:tl,dot:dot,svg:s,k:-1,pts:pts};
  view.label=PER[rng]+' \u00b7 from '+money(base);
  headline(cur,base,view.label);
  facts();
  s.addEventListener('pointermove',scrub); s.addEventListener('pointerdown',scrub);
  s.addEventListener('pointerleave',reset); s.addEventListener('pointerup',function(ev){if(ev.pointerType!=='mouse')reset()});
  s.addEventListener('keydown',keys); s.addEventListener('blur',reset);
}
function at(t){var l=L();return markedAt(l,t)}
function show(t){
  var v=at(t), x=view.X(t);
  view.xh.setAttribute('x1',x);view.xh.setAttribute('x2',x);view.xh.setAttribute('visibility','visible');
  view.tl.textContent=dt(t); view.tl.setAttribute('x',Math.min(Math.max(x,48),view.W-48)); view.tl.setAttribute('visibility','visible');
  view.dot.setAttribute('cx',x);view.dot.setAttribute('cy',view.Y(v));
  headline(v,view.base,dt(t));
}
function scrub(ev){
  if(!view)return; var r=view.svg.getBoundingClientRect(); var f=Math.min(Math.max((ev.clientX-r.left)/r.width,0),1);
  show(view.start+f*(view.now-view.start));
}
function keys(ev){
  if(!view)return; var n=view.pts.length;
  if(ev.key==='ArrowLeft'||ev.key==='ArrowRight'){ev.preventDefault();view.k=(view.k<0?n-1:view.k)+(ev.key==='ArrowLeft'?-1:1);view.k=Math.min(Math.max(view.k,0),n-1);show(view.pts[view.k][0])}
  else if(ev.key==='Escape'){reset()}
}
function reset(){
  if(!view)return; view.k=-1; view.xh.setAttribute('visibility','hidden');view.tl.setAttribute('visibility','hidden');
  view.dot.setAttribute('cx',view.X(view.now));view.dot.setAttribute('cy',view.Y(view.cur)); headline(view.cur,view.base,view.label);
}
function facts(){
  var l=L(), open=l.trades.filter(function(t){return t.status==='open'||t.status==='resting'}), inOpen=open.reduce(function(a,t){return a+t.cost},0);   // resting limit orders hold their cost, as shadow._state does
  var cash=valueAt(l,D.now)-inOpen, u=unreal(l,D.now), cur=markedAt(l,D.now), since=cur-l.start, closed=l.trades.filter(function(t){return t.status==='won'||t.status==='lost'});
  var won=closed.filter(function(t){return t.status==='won'}).length;
  var f=$('acct-facts'); f.innerHTML='';
  [['Cash',money(cash),''],[(open.length===1?'In 1 open ':'In '+open.length+' open ')+(led==='maker'?(open.length===1?'trade or order':'trades or orders'):(open.length===1?'trade':'trades'))+(l.marked&&open.length?', at Kalshi prices':''),money(inOpen+u),''],['Since the start',signed(since),since>0.004?'pos':(since<-0.004?'neg':'')],
   ['Won / lost',closed.length?won+' / '+(closed.length-won):'–','']].forEach(function(r){
     var d=document.createElement('div'); d.appendChild(txt('dt','',r[0])); d.appendChild(txt('dd',r[2],r[1])); f.appendChild(d)});
}
// ---------- activity ----------
function statusTag(t){
  var m={open:['open','Open'],resting:['resting','Waiting to fill'],unfilled:['unfilled','Not filled'],won:['won','Won'],lost:['lost','Lost']}[t.status]||['',t.status];
  var s=txt('span','tag '+m[0],m[1]); return s;
}
function activity(){
  var ul=$('act-list'), l=L(); ul.innerHTML='';
  var rows=l.trades.slice().sort(function(a,b){return (b.closed||b.ts)-(a.closed||a.ts)}).filter(function(t){
    var isOpen=(t.status==='open'||t.status==='resting'); return filt==='all'||(filt==='open'?isOpen:!isOpen)});
  if(!rows.length){ul.appendChild(txt('li','empty',filt==='open'?'No open trades.':(filt==='closed'?'Nothing closed yet.':'No paper trades yet.')));return}
  var hidden=more?0:Math.max(0,rows.length-SHOW); if(hidden) rows=rows.slice(0,SHOW);
  rows.forEach(function(t){
    var li=document.createElement('li');
    li.appendChild(txt('span','t1',t.label));
    var amt; if(t.status==='won'||t.status==='lost'){var p=t.payout-t.cost-t.fee; amt=txt('span','amt '+(p>0.004?'pos':'neg'),signed(p))}
    else if(t.status==='unfilled'||t.status==='resting'){amt=txt('span','amt','$0.00')}
    else amt=txt('span','amt',signed(-(t.cost+t.fee)));
    li.appendChild(amt);
    var verb=(led==='maker'?'Limit order: ':'Bought ')+t.n+' '+t.side+' at '+cents(t.price)+(t.fee?' + '+money(t.fee)+' fee':'');
    if(t.status==='won'||t.status==='lost') verb+=' · paid out '+money(t.payout);
    li.appendChild(txt('span','t2',verb)); li.appendChild(statusTag(t)).classList.add('st');
    li.appendChild(txt('span','when',(t.closed?(t.nodate?'Closed (date not recorded)':'Closed '+dt(t.closed))+' · opened ':'Opened ')+dt(t.ts)));
    ul.appendChild(li);
  });
  if(hidden){var li=txt('li','more'),b=txt('button','','Show '+hidden+' more');b.type='button';b.addEventListener('click',function(){more=true;activity()});li.appendChild(b);ul.appendChild(li)}
}
// ---------- statements ----------
function monthKey(ts){var d=bd(ts);return d.getUTCFullYear()*100+d.getUTCMonth()}
function monthStart(k){return Date.UTC(Math.floor(k/100),k%100,1)/1000-OFF}
function monthName(k){return new Date(Date.UTC(Math.floor(k/100),k%100,1)).toLocaleDateString(undefined,{month:'long',year:'numeric',timeZone:'UTC'})}
function statement(l,k){
  var a=Math.max(monthStart(k),l.t0), b=Math.min(monthStart(k%100===11?(Math.floor(k/100)+1)*100:k+1),D.now);
  var opened=l.trades.filter(function(t){return t.ts>=a&&t.ts<b&&t.status!=='unfilled'&&t.status!=='resting'});
  var closed=l.trades.filter(function(t){return t.closed&&t.closed>=a&&t.closed<b});
  var fees=l.trades.reduce(function(s,t){var ft=(led==='maker'?t.filled:t.ts);return s+((ft&&ft>=a&&ft<b)?t.fee:0)},0);
  var gains=0,losses=0; closed.forEach(function(t){var r=t.payout-t.cost; if(r>=0)gains+=r; else losses+=r});
  var openEnd=l.trades.filter(function(t){var start=(led==='maker'?t.filled:t.ts);return start&&start<b&&!(t.closed&&t.closed<b)&&t.status!=='unfilled'});
  return {k:k,a:a,b:b,start:valueAt(l,a-1e-6),end:valueAt(l,b),fees:fees,gains:gains,losses:losses,opened:opened,closed:closed,
          won:closed.filter(function(t){return t.status==='won'}).length,openEnd:openEnd,openCost:openEnd.reduce(function(s,t){return s+t.cost},0)};
}
function months(l){var ks={},k=monthKey(l.t0),end=monthKey(D.now);while(k<=end){ks[k]=1;k=(k%100===11)?(Math.floor(k/100)+1)*100:k+1}return Object.keys(ks).map(Number).sort(function(x,y){return y-x})}
function dlrow(btns){var d=txt('div','dl');btns.forEach(function(b){var x=txt('button','',b[0]);x.type='button';x.addEventListener('click',b[1]);d.appendChild(x)});return d}
function statements(){
  var box=$('stm-list'), l=L(); box.innerHTML='';
  months(l).forEach(function(k){
    var s=statement(l,k), c=txt('div','stm');
    c.appendChild(txt('h3','',monthName(k)+' statement'));
    var sofar=s.b>=D.now-1; c.appendChild(txt('p','sub2',l.name+' · '+dday(s.a)+' to '+dday(sofar?s.b:s.b-1)+(sofar?' (so far)':'')));
    var dl=document.createElement('dl');
    [['Starting value',money(s.start),''],['Fees paid',signed(-s.fees),''],['Gains on winning trades',signed(s.gains),''],['Losses on losing trades',signed(s.losses),''],['Ending value',money(s.end),'tot']].forEach(function(r){
      dl.appendChild(txt('dt',r[2],r[0])); dl.appendChild(txt('dd',r[2],r[1]))});
    c.appendChild(dl);
    c.appendChild(txt('p','cnt',s.opened.length+' opened · '+s.closed.length+' settled ('+s.won+' won, '+(s.closed.length-s.won)+' lost) · '+s.openEnd.length+' open at the end, '+money(s.openCost)+' at cost'));
    if(DL!==null) c.appendChild(dlrow([['Download CSV',function(){save(fname('statement',k,'csv'),stmCSV(l,s),'text/csv')}],['Printable copy',function(){save(fname('statement',k,'html'),stmHTML(l,s),'text/html')}]]));
    box.appendChild(c);
  });
}
// ---------- tax report ----------
function years(l){var y0=bd(l.t0).getUTCFullYear(),y1=bd(D.now).getUTCFullYear(),o=[];for(var y=y1;y>=y0;y--)o.push(y);return o}
function closedIn(l,y){return l.trades.filter(function(t){return t.closed&&bd(t.closed).getUTCFullYear()===y}).sort(function(a,b){return a.closed-b.closed})}
var taxAll={};
function taxes(){
  var box=$('tax-list'), l=L(); box.innerHTML='';
  years(l).forEach(function(y){
    var rows=closedIn(l,y), pr=0,cb=0; rows.forEach(function(t){pr+=t.payout;cb+=t.cost+t.fee});
    var c=txt('div','stm'); c.appendChild(txt('h3','',y+' gains and losses')); c.appendChild(txt('p','sub2',l.name+' · closed (settled) paper trades'));
    var sm=txt('div','taxsum');
    [['Closed trades',String(rows.length)],['Proceeds',money(pr)],['Cost incl. fees',money(cb)],['Net gain or loss',signed(pr-cb)]].forEach(function(r){var d=document.createElement('div');d.appendChild(txt('span','',r[0]));d.appendChild(txt('b','',r[1]));sm.appendChild(d)});
    c.appendChild(sm);
    if(!rows.length) c.appendChild(txt('p','empty','No closed trades in '+y+' yet.'));
    else{
      var sc=txt('div','scroll'), tb=document.createElement('table'), hr=document.createElement('tr'), list=rows.slice().reverse(), cut=taxAll[y]?list.length:Math.min(list.length,10);
      ['Market','Closed','Gain/loss'].forEach(function(h,i){hr.appendChild(txt('th',i===2?'n':'',h))}); tb.appendChild(hr);
      list.slice(0,cut).forEach(function(t){var tr=document.createElement('tr'), g=t.payout-t.cost-t.fee;
        tr.appendChild(txt('td','tm',t.label+' · '+t.n+' '+t.side)); tr.appendChild(txt('td','',new Date(t.closed*1000).toLocaleDateString(undefined,{month:'short',day:'numeric',timeZone:TZ}))); tr.appendChild(txt('td','n '+(g>0.004?'pos':(g<-0.004?'neg':'')),signed(g))); tb.appendChild(tr)});
      sc.appendChild(tb); c.appendChild(sc);
      if(cut<list.length){var mb=txt('button','showall','Show all '+list.length+' closed trades');mb.type='button';mb.addEventListener('click',function(){taxAll[y]=1;taxes()});c.appendChild(mb)}
      c.appendChild(txt('p','note','Newest first. The downloads list every trade with its proceeds, cost and dates.'));
    }
    if(DL!==null) c.appendChild(dlrow([['Download CSV',function(){save(fname('gains',y,'csv'),taxCSV(l,y,rows),'text/csv')}],['Printable copy',function(){save(fname('gains',y,'html'),taxHTML(l,y,rows,pr,cb),'text/html')}]]));
    box.appendChild(c);
  });
}
// ---------- files ----------
var NOTE='Paper trading - not a tax document. Simulated trades; no real money changed hands.';
function csvq(v){if(typeof v!=='number'){v=String(v==null?'':v);if(/^[=+\-@\t\r]/.test(v)&&isNaN(Number(v)))v="'"+v}else v=String(v);return /[",\n\r]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v}   // text starting with = + - @ cannot run as a spreadsheet formula
function csv(rows){return '\ufeff'+rows.map(function(r){return r.map(csvq).join(',')}).join('\r\n')+'\r\n'}   // byte-order mark so Excel reads the degree sign
function iso(ts){var d=bd(ts),p=function(n){return (n<10?'0':'')+n};return d.getUTCFullYear()+'-'+p(d.getUTCMonth()+1)+'-'+p(d.getUTCDate())+' '+p(d.getUTCHours())+':'+p(d.getUTCMinutes())}
function fname(kind,k,ext){var tag=kind==='statement'?(Math.floor(k/100)+'-'+((k%100)+1<10?'0':'')+((k%100)+1)):String(k);return 'tradebot-'+kind+'-'+tag+'-'+(led==='maker'?'limit-order-test':'main-bot')+'.'+ext}
function stmCSV(l,s){
  var r=[[NOTE],[l.name+' statement',monthName(s.k)],[],['Starting value',s.start.toFixed(2)],['Fees paid',(-s.fees).toFixed(2)],['Gains on winning trades',s.gains.toFixed(2)],['Losses on losing trades',s.losses.toFixed(2)],['Ending value',s.end.toFixed(2)],[],
    ['Opened (UTC-4)','Market','Side','Contracts','Price','Cost','Fee','Status','Closed (UTC-4)','Payout']];
  l.trades.filter(function(t){return (t.ts>=s.a&&t.ts<s.b)||(t.closed&&t.closed>=s.a&&t.closed<s.b)}).forEach(function(t){
    r.push([iso(t.ts),t.label,t.side,t.n,t.price,t.cost,t.fee,t.status,t.closed?iso(t.closed):'',t.payout==null?'':t.payout])});
  return csv(r);
}
function taxCSV(l,y,rows){
  var r=[[NOTE],[l.name+' gains and losses',String(y)],[],['Market','Contracts','Side','Opened (UTC-4)','Closed (UTC-4)','Proceeds','Cost incl. fee','Gain or loss']];
  rows.forEach(function(t){r.push([t.label,t.n,t.side,iso(t.ts),iso(t.closed),t.payout.toFixed(2),(t.cost+t.fee).toFixed(2),(t.payout-t.cost-t.fee).toFixed(2)])});
  return csv(r);
}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function page(title,inner){   // a small printable document; the tag names are split so the dashboard page never contains them literally
  var o='<', T=function(n){return o+n+'>'}, C=function(n){return o+'/'+n+'>'};
  return o+'!doctype html>'+T('html lang=en')+T('head')+T('meta charset=utf-8')+T('title')+esc(title)+C('title')+
    T('style')+'body{font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;color:#14212e;max-width:760px;margin:32px auto;padding:0 20px}h1{font-size:22px;margin:0 0 4px}p.s{color:#465566;margin:0 0 16px}.b{border-left:3px solid #fab219;background:#f3f5f7;padding:8px 12px;margin:0 0 18px}table{border-collapse:collapse;width:100%;margin-top:10px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #d9dee4}th{font-size:12px;color:#465566}.n{text-align:right;font-variant-numeric:tabular-nums}@media print{body{margin:0}}'+C('style')+C('head')+
    T('body')+inner+C('body')+C('html');
}
function trows(heads,rows,nums){var h='<table>'+(heads.join('')?'<tr>'+heads.map(function(x,i){return '<th'+(nums.indexOf(i)>=0?' class=n':'')+'>'+esc(x)+'</th>'}).join('')+'</tr>':'');
  rows.forEach(function(r){h+='<tr>'+r.map(function(x,i){return '<td'+(nums.indexOf(i)>=0?' class=n':'')+'>'+esc(x)+'</td>'}).join('')+'</tr>'});return h+'</table>'}
function stmHTML(l,s){
  var tr=l.trades.filter(function(t){return (t.ts>=s.a&&t.ts<s.b)||(t.closed&&t.closed>=s.a&&t.closed<s.b)}).map(function(t){return [dday(t.ts),t.label,t.n+' '+t.side+' at '+cents(t.price),money(t.cost+t.fee),t.status,t.closed?dday(t.closed):'',t.payout==null?'':money(t.payout)]});
  var sofar=s.b>=D.now-1;
  return page('Tradebot statement '+monthName(s.k),'<h1>'+esc(monthName(s.k))+' statement</h1><p class=s>'+esc(l.name)+' · '+esc(dday(s.a))+' to '+esc(dday(sofar?s.b:s.b-1))+(sofar?' (so far)':'')+' · generated '+esc(dt(D.now))+'</p><p class=b><b>'+esc(NOTE)+'</b></p>'+
    trows(['',''],[['Starting value',money(s.start)],['Fees paid',signed(-s.fees)],['Gains on winning trades',signed(s.gains)],['Losses on losing trades',signed(s.losses)],['Ending value',money(s.end)]],[1])+
    '<h2 style="font-size:16px;margin-top:22px">Activity</h2>'+(tr.length?trows(['Opened','Market','Order','Cost incl. fee','Status','Closed','Payout'],tr,[3,6]):'<p>No activity this month.</p>'));
}
function taxHTML(l,y,rows,pr,cb){
  return page('Tradebot gains and losses '+y,'<h1>'+y+' gains and losses</h1><p class=s>'+esc(l.name)+' · closed paper trades</p><p class=b><b>'+esc(NOTE)+'</b> Nothing to report or file.</p>'+
    trows(['',''],[['Closed trades',String(rows.length)],['Proceeds',money(pr)],['Cost incl. fees',money(cb)],['Net gain or loss',signed(pr-cb)]],[1])+
    (rows.length?trows(['Market','Opened','Closed','Proceeds','Cost incl. fee','Gain or loss'],rows.map(function(t){return [t.label+' · '+t.n+' '+t.side,dday(t.ts),dday(t.closed),money(t.payout),money(t.cost+t.fee),signed(t.payout-t.cost-t.fee)]}),[3,4,5]):'<p>No closed trades.</p>'));
}
// downloads: the phone page uses the artifact's downloads capability; a page opened from the PC uses a normal browser download
var DL=null;   // null = unknown/unavailable; 'browser' or the capability namespace once known
function note(s){var n=$('dl-note');n.textContent=s;n.hidden=!s}
function save(name,text,mime){
  if(DL==='browser'){var a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type:mime}));a.download=name;document.body.appendChild(a);a.click();setTimeout(function(){URL.revokeObjectURL(a.href);a.remove()},1000);return}
  if(DL&&DL.save){DL.save({filename:name,data:text}).then(function(){note('')},function(err){var c=err&&err.code;if(c==='declined')return;if(c==='unavailable'||c==='not_granted'||c==='capability_disabled'||c==='capability_removed'){DL=null;statements();taxes();note('Downloads are not available in this view; open the dashboard on the PC to save statements.');return}note(c==='rate_limited'?'Another save is waiting for your answer; try again in a moment.':'This view could not save the file ('+(c||'error')+'). Open the dashboard on the PC to download it.')})}
}
function all(){draw();activity();statements();taxes()}
// controls
function keep(){try{sessionStorage.setItem('tb-view',JSON.stringify({led:led,rng:rng,tab:(document.querySelector('.tabs [aria-selected=true]')||{}).id}))}catch(e){}}   // a self-refreshing page keeps the reader's place
Array.prototype.forEach.call(document.querySelectorAll('.seg button'),function(b){b.addEventListener('click',function(){led=b.getAttribute('data-led');
  Array.prototype.forEach.call(document.querySelectorAll('.seg button'),function(x){x.setAttribute('aria-pressed',x===b?'true':'false')});keep();all()})});
Array.prototype.forEach.call(document.querySelectorAll('.rng button'),function(b){b.addEventListener('click',function(){rng=b.getAttribute('data-r');
  Array.prototype.forEach.call(document.querySelectorAll('.rng button'),function(x){x.setAttribute('aria-pressed',x===b?'true':'false')});keep();draw()})});
Array.prototype.forEach.call(document.querySelectorAll('.chips button'),function(b){b.addEventListener('click',function(){filt=b.getAttribute('data-f');more=false;
  Array.prototype.forEach.call(document.querySelectorAll('.chips button'),function(x){x.setAttribute('aria-pressed',x===b?'true':'false')});activity()})});
var tabs=Array.prototype.slice.call(document.querySelectorAll('.tabs [role=tab]'));
function sel(t){tabs.forEach(function(x){var on=x===t;x.setAttribute('aria-selected',on?'true':'false');x.tabIndex=on?0:-1;$(x.getAttribute('aria-controls')).hidden=!on})}
tabs.forEach(function(t,i){t.addEventListener('click',function(){sel(t);keep()});t.addEventListener('keydown',function(ev){var j=ev.key==='ArrowRight'?i+1:(ev.key==='ArrowLeft'?i-1:-9);if(j===-9)return;j=(j+tabs.length)%tabs.length;tabs[j].focus();sel(tabs[j])})});
var rt;window.addEventListener('resize',function(){clearTimeout(rt);rt=setTimeout(draw,150)});
try{var kv=JSON.parse(sessionStorage.getItem('tb-view')||'null');
  if(kv){if(D.ledgers[kv.led]){led=kv.led;Array.prototype.forEach.call(document.querySelectorAll('.seg button'),function(x){x.setAttribute('aria-pressed',x.getAttribute('data-led')===led?'true':'false')})}
    if(RANGES.hasOwnProperty(kv.rng)){rng=kv.rng;Array.prototype.forEach.call(document.querySelectorAll('.rng button'),function(x){x.setAttribute('aria-pressed',x.getAttribute('data-r')===rng?'true':'false')})}
    if(kv.tab&&$(kv.tab))sel($(kv.tab))}}catch(e){}
if(window.claude&&window.claude.use){
  all();
  window.claude.use('downloads').then(function(d){DL=d||null;if(!d)note('Downloads are not available in this view; open the dashboard on the PC to save statements.');statements();taxes()},function(){note('Downloads are not available in this view.')});
}else{DL='browser';all()}
})();
"""
