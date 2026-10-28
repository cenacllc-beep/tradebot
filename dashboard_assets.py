"""Static CSS and JavaScript of the dashboard page (moved out of dashboard.py 2026-10-23, refactor stage 2; the text
is unchanged). Presentation only: no data, no network, no file access."""
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
"""
