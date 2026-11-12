"""Static CSS and JavaScript of the dashboard page (moved out of dashboard.py 2026-10-23, refactor stage 2; the text
is unchanged). Presentation only: no data, no network, no file access. 2026-11-11: a redesign layer at the end of CSS
and JS (section menu, animations, back-to-top), added at the user's request; it changes no text or number."""
CSS="""
/* Layout: a forecast-desk briefing. The plain-language verdict and the test calendar lead, then the next actions,
   then the evidence (charts), then the records. Left-aligned, one column on phones.
   Type: DIN for the verdict, headings and figures (Bahnschrift on Windows, DIN Alternate on iPhone, Roboto Condensed
   on Android), the system UI sans for text. No web fonts, so the page never calls out to the network. */
:root{color-scheme:light;
 --page:#eef1f4;--surface:#fbfcfd;--sunk:#e7ebef;--ink:#14212e;--ink2:#465566;--mut:#5f6b78;--grid:#e1e6eb;--rule:#cfd6de;--ring:rgba(20,33,46,.12);
 --fc:#2a78d6;--fcsoft:#9ec5f4;--mk:#eb6834;--acc:#1c5cab;--good:#0ca30c;--goodt:#006300;--bad:#d03b3b;--badt:#b4302f;--warn:#fab219;--warnt:#8a5a00;
 --display:"Bahnschrift","DIN Alternate","Roboto Condensed","sans-serif-condensed","Segoe UI",system-ui,sans-serif;
 --text:"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,Roboto,"Helvetica Neue",Arial,sans-serif}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;
 --page:#0d1116;--surface:#151a21;--sunk:#1b222b;--ink:#edf1f5;--ink2:#b5bfca;--mut:#8b95a1;--grid:#242c35;--rule:#323b46;--ring:rgba(255,255,255,.10);
 --fc:#3987e5;--fcsoft:#1c5cab;--mk:#d95926;--acc:#6da7ec;--good:#0ca30c;--goodt:#3ec23e;--bad:#d03b3b;--badt:#f07c7c;--warn:#fab219;--warnt:#fab219}}
:root[data-theme="dark"]{color-scheme:dark;
 --page:#0d1116;--surface:#151a21;--sunk:#1b222b;--ink:#edf1f5;--ink2:#b5bfca;--mut:#8b95a1;--grid:#242c35;--rule:#323b46;--ring:rgba(255,255,255,.10);
 --fc:#3987e5;--fcsoft:#1c5cab;--mk:#d95926;--acc:#6da7ec;--good:#0ca30c;--goodt:#3ec23e;--bad:#d03b3b;--badt:#f07c7c;--warn:#fab219;--warnt:#fab219}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.5 var(--text);-webkit-text-size-adjust:100%}
.wrap{max-width:1040px;margin:0 auto;padding-inline:16px;padding-block:18px 56px;display:grid;gap:16px}
@media(min-width:720px){.wrap{padding-inline:28px;padding-block:28px 64px;gap:20px}}
h1,h2,.answer,.sv,.gv,.facts dd{font-family:var(--display);font-stretch:semi-condensed}
h1{font-size:22px;font-weight:600;margin:0;letter-spacing:.01em}
h2{font-size:19px;font-weight:600;margin:0 0 10px;text-wrap:balance}
h2 span{font-family:var(--text);font-stretch:normal;font-size:13px;font-weight:400;color:var(--mut);margin-left:6px}
p{margin:0}small{font-size:12.5px;color:var(--mut)}
code{font:13px/1 Consolas,"SF Mono",Menlo,monospace;background:var(--sunk);color:var(--ink2);padding:5px 8px;border-radius:6px;white-space:nowrap}
.top{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:baseline;justify-content:space-between}
.top p{color:var(--ink2);font-size:13.5px;margin-top:2px}
.meta{display:flex;flex-wrap:wrap;gap:8px;align-items:center;color:var(--mut);font-size:13px}
.chip{display:inline-flex;gap:6px;align-items:center;padding:3px 10px;border-radius:99px;font-size:12.5px;font-weight:600}
.chip.halt{background:var(--bad);color:#fff}.chip.warn{background:var(--warn);color:#14212e}
.chip.live{background:var(--sunk);color:var(--ink2);box-shadow:inset 0 0 0 1px var(--rule)}
a.chip{text-decoration:none}
.hero{display:grid;gap:14px;padding-block:6px 4px}
.q{color:var(--ink2);font-size:15px}
.answer{font-size:30px;line-height:1.12;font-weight:600;max-width:30ch;text-wrap:balance;letter-spacing:-.005em}
@media(min-width:720px){.answer{font-size:40px}}
.gatehead{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline;justify-content:space-between;padding-top:12px;border-top:1px solid var(--rule);font-size:13.5px;color:var(--ink2)}
.gatehead b{color:var(--ink)}
.gate{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,160px),1fr));gap:10px}
.gate li{display:grid;grid-template-columns:20px 1fr;gap:2px 10px;align-items:baseline;background:var(--surface);border-radius:12px;padding:12px 14px;box-shadow:0 0 0 1px var(--ring)}
.gate li>*:not(.ic){grid-column:2;min-width:0}
.gate .ic{grid-row:1/span 2;width:20px;height:20px;border-radius:50%;display:grid;place-items:center;font-size:12px;font-weight:700;color:var(--mut);box-shadow:inset 0 0 0 1.5px var(--rule)}
.gate li.ok .ic{background:var(--good);color:#fff;box-shadow:none}
.gl{font-size:13px;color:var(--ink2)}.gv{font-size:22px;font-weight:600;line-height:1.2}.gv small{font-family:var(--text);font-size:13px;font-weight:400}
.gate .meter{margin-top:6px}.gate li>small{display:block;margin-top:4px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}
.meter{height:5px;border-radius:3px;background:var(--sunk);overflow:hidden}.meter i{display:block;height:100%;background:var(--fc);border-radius:3px}.meter i.over{background:var(--bad)}
.cal{display:grid;gap:8px}
.calhead{display:flex;flex-wrap:wrap;gap:2px 12px;align-items:baseline;font-size:13.5px;color:var(--ink2)}.calhead b{font-family:var(--display);font-stretch:semi-condensed;font-size:17px;color:var(--ink)}
.days{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(var(--n),minmax(0,1fr));gap:4px}
.days li{display:grid;gap:4px;justify-items:center;font-size:12px;color:var(--mut);font-variant-numeric:tabular-nums;border-radius:6px;padding:2px 0;outline-offset:2px}
.days li i,.calkey i{display:block;width:100%;height:14px;border-radius:4px;background:var(--grid)}
.calkey i{width:14px;height:10px;display:inline-block;margin-right:6px;vertical-align:-1px}
.days .settled i,.calkey .settled{background:var(--fc)}
.days .logged i,.calkey .logged{background:var(--fcsoft)}
.days .missed i,.calkey .missed{background:transparent;box-shadow:inset 0 0 0 1.5px var(--bad)}
.days .next i,.calkey .next{box-shadow:0 0 0 2px var(--page),0 0 0 3.5px var(--acc)}
.days .next span{color:var(--acc);font-weight:700}
.days li b.amt{font:600 11px/1.25 var(--text);font-variant-numeric:tabular-nums;min-height:1.25em;white-space:nowrap;color:var(--mut);letter-spacing:-.01em}
.days li b.amt.pos{color:var(--goodt)}.days li b.amt.neg{color:var(--badt)}
@media(max-width:820px){.days{grid-template-columns:repeat(7,minmax(0,1fr));row-gap:8px}}
.calkey{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12.5px;color:var(--mut)}
.two{display:grid;gap:16px}@media(min-width:760px){.two{grid-template-columns:1fr 1fr;gap:20px}}
.two>*{min-width:0}
.panel{background:var(--surface);border-radius:14px;padding:18px;box-shadow:0 0 0 1px var(--ring);min-width:0}
@media(min-width:720px){.panel{padding:22px}}
.todo{list-style:none;margin:0;padding:0;display:grid;gap:10px}
.todo li{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;justify-content:space-between;padding:10px 12px;border-radius:10px;background:var(--sunk)}
.todo li div{display:grid;min-width:0}.todo li span{font-size:13.5px;color:var(--ink2)}
.todo li.due{box-shadow:inset 3px 0 0 var(--warn)}
.foot{margin-top:12px;font-size:13px;color:var(--mut)}
.facts{margin:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px 20px}
.facts div{min-width:0}.facts dt{font-size:13px;color:var(--ink2)}.facts dd{margin:2px 0 6px;font-size:22px;font-weight:600;display:flex;gap:8px;align-items:baseline}
.facts dd small{font-family:var(--text);font-stretch:normal;font-weight:400;font-size:13px}.facts p{font-size:12.5px;color:var(--mut)}
.facts .ic{font-family:var(--text);font-size:13px;font-weight:700;width:20px;height:20px;border-radius:50%;display:inline-grid;place-items:center;align-self:center}
.facts .ok .ic{background:var(--good);color:#fff}.facts .warn{color:var(--warnt)}.facts .warn .ic{background:var(--warn);color:#14212e}
.pos{color:var(--goodt)}.neg{color:var(--badt)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:14px 20px;margin-bottom:12px}
.stats div{display:grid;gap:2px;min-width:0;align-content:start}.sl{font-size:13px;color:var(--ink2)}.sv{font-size:32px;font-weight:600;line-height:1.1}
.note{font-size:13.5px;color:var(--ink2);margin-top:10px;max-width:75ch}
.empty{color:var(--mut);font-size:14px}
.legend{display:flex;flex-wrap:wrap;gap:4px 18px;font-size:13px;color:var(--ink2);margin:0 0 6px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:7px;vertical-align:0}.legend .fc{background:var(--fc)}.legend .mk{background:var(--mk)}
.chart{overflow-x:auto;margin-inline:-4px}.chart svg{min-width:600px}.swipe{display:none;font-size:12.5px;color:var(--mut);margin:0 0 4px}@media(max-width:640px){.swipe{display:block}h2 span{display:block;margin:2px 0 0}.gate li{padding:10px 12px}.gv{font-size:20px}}
svg{width:100%;height:auto;display:block;overflow:visible}
svg text{font-family:var(--text)}
.grid{stroke:var(--grid);stroke-width:1}.base{stroke:var(--rule);stroke-width:1}.ref{stroke:var(--mut);stroke-width:1}
.ax{fill:var(--mut);font-size:11.5px;font-variant-numeric:tabular-nums}.lb{fill:var(--ink2);font-size:12.5px}.val{fill:var(--ink);font-size:12.5px;font-weight:600;font-variant-numeric:tabular-nums}
.hit{fill:transparent}.row:hover .hit{fill:var(--sunk)}
.link{stroke:var(--mut);stroke-width:2;stroke-linecap:round;opacity:.45}
circle.fc,path.fc{fill:var(--fc)}circle.mk,path.mk{fill:var(--mk)}circle.fc,circle.mk{stroke:var(--surface);stroke-width:2}
.gap{fill:var(--mut);font-size:12.5px;font-variant-numeric:tabular-nums}.gap.cand{fill:var(--ink);font-weight:700}.gap.warn{fill:var(--warnt);font-weight:700}
.res{fill:var(--ink);font-size:11.5px;font-weight:700}.res.p{fill:var(--mut);font-weight:400}
.bars{display:grid;gap:10px;margin-top:4px}.bar{display:grid;grid-template-columns:100px 1fr 48px;gap:12px;align-items:center}.bl{font-size:13.5px;color:var(--ink2)}.track{position:relative;height:16px;background:var(--sunk);border-radius:4px}.track i{position:absolute;left:0;top:0;bottom:0;border-radius:0 4px 4px 0}.track i.fc{background:var(--fc)}.track i.mk{background:var(--mk)}.refm{position:absolute;top:-5px;bottom:-5px;width:1.5px;background:var(--ink2)}.bv{text-align:right;font-weight:600;font-variant-numeric:tabular-nums}
details{margin-top:12px}summary{cursor:pointer;color:var(--acc);font-size:13.5px;font-weight:600;width:max-content;max-width:100%}
.records h2:not(:first-child){margin-top:24px}
h3{font-family:var(--display);font-stretch:semi-condensed;font-size:16.5px;font-weight:600;margin:0 0 10px}
.shadow .sub+.sub{margin-top:24px;padding-top:20px;border-top:1px solid var(--grid)}.shadow .sv{font-size:28px}
@media(max-width:640px){.shadow th,.shadow td,.bt th,.bt td{padding-inline:6px}}
.sv small{font-family:var(--text);font-stretch:normal;font-size:13px;font-weight:400;color:var(--mut)}td small{color:var(--mut);margin-left:4px}
.tag.filled{color:var(--acc)}.tag.rest{color:var(--ink2)}
.lead{font-size:16px;line-height:1.45;max-width:65ch;margin:0 0 14px;color:var(--ink)}
.p2{margin-top:22px;padding-top:4px;border-top:1px solid var(--grid)}.p2 .note{margin:0 0 14px}
.fwh{margin:20px 0 10px}.fwh span{font-family:var(--text);font-stretch:normal;font-size:13px;font-weight:400;color:var(--mut);margin-left:6px}
.scroll{overflow-x:auto;margin-top:8px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--grid);white-space:nowrap}
th{color:var(--ink2);font-weight:600;font-size:12.5px;border-bottom-color:var(--rule)}
.n{text-align:right;font-variant-numeric:tabular-nums}
td.empty{color:var(--mut);white-space:normal}
.tag{font-size:12px;font-weight:700;padding:2px 8px;border-radius:99px;background:var(--sunk);color:var(--ink2)}
.tag.won{color:var(--goodt)}.tag.lost{color:var(--badt)}.tag.gate{color:var(--acc)}.tag.exploratory{color:var(--warnt)}.tag.excluded{color:var(--mut)}
.fine{font-size:12.5px;color:var(--mut);max-width:80ch}
#tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--page);padding:7px 10px;border-radius:8px;font-size:12.5px;line-height:1.4;max-width:290px;opacity:0;transition:opacity .1s;z-index:9}
:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
@media(prefers-reduced-motion:reduce){#tip{transition:none}}

/* ---- 2026-11-11 redesign layer (user: "a better modern, animated, user friendly design"). Presentation only: it adds a
   sticky section menu, entrance and meter animations, hover feedback and a back-to-top button. No text or number on
   the page changes, nothing is hidden without JavaScript, and "reduce motion" turns every animation off. ---- */
body{background:radial-gradient(1200px 520px at 12% -8%,color-mix(in srgb,var(--fc) 13%,transparent),transparent 62%),
 radial-gradient(900px 480px at 96% -4%,color-mix(in srgb,var(--mk) 9%,transparent),transparent 60%),var(--page);background-attachment:fixed}
.top h1{font-size:26px}
@supports((-webkit-background-clip:text) or (background-clip:text)){.top h1{display:inline-block;background:linear-gradient(92deg,var(--ink) 0%,var(--acc) 85%);-webkit-background-clip:text;background-clip:text;color:transparent}}
.panel{border-radius:18px;box-shadow:0 0 0 1px var(--ring),0 1px 2px rgba(16,24,40,.04),0 10px 28px -18px rgba(16,24,40,.28);transition:box-shadow .25s ease,transform .25s ease}
.panel:hover{box-shadow:0 0 0 1px var(--ring),0 2px 4px rgba(16,24,40,.05),0 18px 40px -20px rgba(16,24,40,.36)}
.gate li{transition:transform .2s ease,box-shadow .2s ease}
.gate li:hover{transform:translateY(-2px);box-shadow:0 0 0 1px var(--ring),0 10px 22px -14px rgba(16,24,40,.35)}
.chip{transition:transform .15s ease,filter .15s ease}a.chip:hover{transform:translateY(-1px);filter:brightness(1.05)}
.chip.live::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--good);box-shadow:0 0 0 0 color-mix(in srgb,var(--good) 60%,transparent);animation:tbpulse 2.2s ease-out infinite}
@keyframes tbpulse{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--good) 55%,transparent)}70%,100%{box-shadow:0 0 0 9px transparent}}
.meter i{transform-origin:left center;animation:tbgrow .9s cubic-bezier(.2,.7,.2,1) both}
@keyframes tbgrow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.tbnav{position:sticky;top:0;z-index:20;margin-inline:-16px;padding:8px 16px;display:flex;gap:6px;overflow-x:auto;scrollbar-width:none;
 background:var(--page);background:color-mix(in srgb,var(--page) 93%,transparent);backdrop-filter:saturate(1.4) blur(10px);-webkit-backdrop-filter:saturate(1.4) blur(10px);border-bottom:1px solid var(--ring)}
.tbnav::-webkit-scrollbar{display:none}
@media(min-width:720px){.tbnav{margin-inline:-28px;padding-inline:28px}}
.tbnav a{flex:none;font-size:13px;font-weight:600;color:var(--ink2);text-decoration:none;padding:8px 13px;border-radius:99px;min-height:36px;display:inline-flex;align-items:center;transition:background .2s ease,color .2s ease}
.tbnav a:hover{background:var(--sunk);color:var(--ink)}
.tbnav a.on{background:var(--ink);color:var(--page)}
.tbnav a:focus-visible,.tbtop:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
html{scroll-padding-top:64px}
#tip{z-index:30}
.tbrv{opacity:0;transform:translateY(14px)}
.tbrv.tbin{opacity:1;transform:none;transition:opacity .55s ease,transform .55s cubic-bezier(.2,.7,.2,1)}
.tbtop{position:fixed;right:16px;bottom:16px;z-index:21;width:44px;height:44px;border-radius:50%;border:0;cursor:pointer;font-size:18px;line-height:1;
 background:var(--ink);color:var(--page);box-shadow:0 8px 22px -8px rgba(16,24,40,.5);opacity:0;visibility:hidden;pointer-events:none;transform:translateY(8px);transition:opacity .25s ease,transform .25s ease,visibility 0s .25s}
.tbtop.on{opacity:1;visibility:visible;pointer-events:auto;transform:none;transition:opacity .25s ease,transform .25s ease,visibility 0s}
@media(prefers-reduced-motion:reduce){.tbrv,.tbrv.tbin{opacity:1;transform:none;transition:none}
 .meter i,.chip.live::before{animation:none}.panel,.gate li,.chip,.tbnav a,.tbtop{transition:none}.gate li:hover,a.chip:hover{transform:none}}
@media print{.tbnav,.tbtop{display:none}.tbrv{opacity:1;transform:none}.top h1{background:none;color:var(--ink)}}
"""
JS="""
if(document.body.getAttribute('data-live')&&location.protocol==='file:'){   // run watch rebuilds dashboard_live.html every 5 minutes
  setTimeout(function(){location.reload()},300000);
  try{var D0=JSON.parse(document.getElementById('acct-data').textContent).now,ch=document.getElementById('pricechip');
    if(ch&&Date.now()/1000-D0>900){ch.textContent='Not updating: run watch is closed';ch.className='chip warn'}}catch(e){}}
(function(){var t=document.getElementById('tip');
function show(n,x,y){t.textContent=n.getAttribute('data-tip');t.style.opacity=1;t.style.left=Math.max(8,Math.min(x+14,innerWidth-300))+'px';t.style.top=Math.max(8,Math.min(y+14,innerHeight-80))+'px'}
document.addEventListener('mousemove',function(ev){var n=ev.target.closest&&ev.target.closest('[data-tip]');if(!n){t.style.opacity=0;return}show(n,ev.clientX,ev.clientY)});
document.addEventListener('focusin',function(ev){var n=ev.target.closest&&ev.target.closest('[data-tip]');if(!n){t.style.opacity=0;return}var r=n.getBoundingClientRect();show(n,r.left,r.bottom)});
document.addEventListener('focusout',function(){t.style.opacity=0});
document.addEventListener('scroll',function(){t.style.opacity=0},true);})();

/* 2026-11-11 redesign layer: section menu, entrance animation, back-to-top. Presentation only; fails quiet. */
(function(){try{
var wrap=document.querySelector('.wrap'); if(!wrap)return;
var still=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
var secs=[].slice.call(wrap.querySelectorAll('section')).filter(function(s){return s.querySelector('h2')||s.classList.contains('hero')});
var pin=null;   // the section whose menu link was last clicked: it wins when two sections sit side by side
var nav=document.createElement('nav'); nav.className='tbnav'; nav.setAttribute('aria-label','Sections'); var links=[];
secs.forEach(function(s,i){
  var h=s.querySelector('h2'),name='';
  if(h){for(var n=h.firstChild;n;n=n.nextSibling){if(n.nodeType===3)name+=n.textContent}name=name.trim()||h.textContent.trim()}
  if(s.classList.contains('hero'))name='Verdict';
  if(!name)return;
  if(!s.id)s.id='tbsec'+i; s.setAttribute('data-tbsec','1');
  var a=document.createElement('a'); a.href='#'+s.id; a.textContent=name.length>26?name.slice(0,24).trim()+'\u2026':name; a.addEventListener('click',function(ev){ev.preventDefault();pin=s;s.classList.add('tbin');try{s.tabIndex=-1;s.focus({preventScroll:true})}catch(e){}s.scrollIntoView({behavior:still?'auto':'smooth',block:'start'});if(history.replaceState)history.replaceState(null,'','#'+s.id)});
  nav.appendChild(a); links.push([s,a]);
});
var top=wrap.querySelector('.top'); if(links.length>2){if(top&&top.nextSibling)wrap.insertBefore(nav,top.nextSibling);else wrap.insertBefore(nav,wrap.firstChild)}
var btn=document.createElement('button'); btn.className='tbtop'; btn.type='button'; btn.setAttribute('aria-label','Back to top'); btn.textContent='\u2191';
btn.addEventListener('click',function(){pin=null;window.scrollTo({top:0,behavior:still?'auto':'smooth'});try{if(links.length)links[0][1].focus({preventScroll:true})}catch(e){}}); document.body.appendChild(btn);
function mark(){var y=window.scrollY||0,cur=null; btn.classList.toggle('on',y>900);
  var ct=0; links.forEach(function(p){var t=p[0].getBoundingClientRect().top; if(t<=90&&(!cur||t>ct+2)){cur=p;ct=t}});   // side by side: the first one
  if(cur&&pin)links.forEach(function(p){var r=p[0].getBoundingClientRect(); if(p[0]===pin&&(Math.abs(r.top-ct)<=2||(r.top>=-2&&r.top<innerHeight*.6&&innerHeight+y>=document.documentElement.scrollHeight-2)))cur=p});   // a last section too short to reach the top: the clicked link stays marked
  [].slice.call(document.querySelectorAll('.tbrv:not(.tbin)')).forEach(function(el){var r=el.getBoundingClientRect(); if(r.top<innerHeight&&r.bottom>0)el.classList.add('tbin')});   // backstop: nothing on screen stays hidden
  links.forEach(function(p){var on=p===cur; if(p[1].classList.contains('on')!==on){p[1].classList.toggle('on',on); if(on)p[1].setAttribute('aria-current','true');else p[1].removeAttribute('aria-current'); if(on)nav.scrollLeft=Math.max(0,p[1].offsetLeft-40)   /* instant: a gliding menu would keep firing scroll events, which hide the page's tooltips */}})}
['wheel','touchstart','keydown'].forEach(function(t){window.addEventListener(t,function(ev){if(t!=='keydown'||!ev.target.closest||!ev.target.closest('.tbnav'))pin=null},{passive:true})});   // the viewer scrolls by hand: the clicked link no longer wins
var tick=false; window.addEventListener('scroll',function(){if(!tick){tick=true;requestAnimationFrame(function(){tick=false;mark()})}},{passive:true}); mark();
if(!still&&'IntersectionObserver' in window){
  var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){e.target.classList.add('tbin');io.unobserve(e.target)}})},{rootMargin:'0px 0px -6% 0px',threshold:0});
  [].slice.call(wrap.children).forEach(function(el){
    if(el===nav||el.tagName==='SCRIPT'||el.classList.contains('top'))return;
    if(el.getBoundingClientRect().top<innerHeight)return;   // what is already on screen never flashes
    el.classList.add('tbrv'); io.observe(el)});
  setTimeout(function(){[].slice.call(document.querySelectorAll('.tbrv')).forEach(function(el){if(el.getBoundingClientRect().top<innerHeight)el.classList.add('tbin')})},1200);
}
}catch(e){}})();
"""
