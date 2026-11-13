"""real_view.py (the dashboard's real-money section): its numbers equal live.py's on the same ledger, its markers group,
and the page builds and stays read-only. Fake data only. python test_real_view.py WORK OUT"""
import os, sys, json, time, sqlite3, hashlib
WORK, OUT = sys.argv[1], sys.argv[2]; os.makedirs(OUT, exist_ok=True); os.chdir(OUT)
os.environ["PAPER_DB"] = os.path.join(OUT, "paper.db"); os.environ["LIVE_DB"] = os.path.join(OUT, "live.db")
os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(OUT, "offsite")
assert not os.path.abspath(os.environ["LIVE_DB"]).startswith(os.path.abspath(WORK)), "tests must never use the real live.db"
sys.path.insert(0, WORK)
import live, real_view as RV
from datetime import date

T0 = 1794400000.0
c = live.ldb()
def order(i, ts, env, t, side, n, lc, status="executed", result=None, pnl=None, sts=None, paper=None):
    cost = n * lc / 100.0
    c.execute("insert into orders(id,ts,env,paper_id,ticker,side,count,limit_cents,client_order_id,status,fill_count,cost,fees,note,result,pnl,settled_ts)"
              " values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (i, ts, env, paper, t, side, n, lc, "c%d" % i, status, n if status == "executed" else 0, cost if status == "executed" else 0,
               live.fee(lc / 100.0, n) if status == "executed" else 0, "note %d" % i, result, pnl, sts))
order(1, T0, "prod", "KXRAIN-26NOV12-STL", "yes", 5, 7, result="no", pnl=-0.37, sts=T0 + 50000, paper=45)
order(2, T0 + 5, "prod", "KXRAIN-26NOV12-MKE", "yes", 1, 42, result="yes", pnl=0.56, sts=T0 + 50060, paper=46)
order(3, T0 + 9, "prod", "KXRAIN-26NOV12-TPA", "yes", 3, 14, paper=47)                  # still open
order(4, T0 + 12, "prod", "KXRAIN-26NOV12-DC", "no", 1, 29, status="skipped", paper=48)  # not copied
order(5, T0 + 90000, "prod", "KXRAIN-26NOV14-SEA", "no", 2, 60, result="yes", pnl=-1.25, sts=T0 + 140000, paper=49)
order(6, T0 + 20, "demo", "KXRAIN-26NOV12-MIA", "no", 1, 46, result="no", pnl=0.5, sts=T0 + 50000, paper=44)
c.execute("insert into events(ts,env,kind,detail) values(?,?,?,?)", (T0 - 100, "prod", "unlock", "gate NOT passed"))
c.commit()
orders = [dict(zip([d[0] for d in c.execute("select * from orders").description], r)) for r in c.execute("select * from orders")]
events = [dict(id=r[0], ts=r[1], env=r[2], kind=r[3], detail=r[4]) for r in c.execute("select id,ts,env,kind,detail from events")]

# the same numbers as live.py
for when in (T0 + 60000, T0 + 141000, T0 + 300000):
    live.now = lambda w=when: w
    for env in ("prod", "demo"):
        assert abs(RV.value_track(orders, events, env)[0] - live.value_track(c, env)[0]) < 1e-9
        assert abs(RV.value_track(orders, events, env)[1] - live.value_track(c, env)[1]) < 1e-9
        assert RV.value_track(orders, events, env)[2] == live.value_track(c, env)[2]
        assert abs(RV.day_pnl(orders, when, env) - live.day_pnl(c, env)) < 1e-9, (env, when)
        assert abs(RV.at_risk(orders, env) - live.local_at_risk(c, env)) < 1e-9
for c_ in range(1, 100):          # every whole-cent price and many counts: the page's fee is the bot's
    for n in (1, 2, 3, 4, 5, 7, 11, 25, 40):
        assert RV.fee(c_ / 100.0, n) == live.fee(c_ / 100.0, n), (c_, n)
assert RV.STAKE == live.STAKE and RV.MAX_AT_RISK == live.MAX_AT_RISK and RV.DAILY_STOP == live.DAILY_STOP and RV.DRAWDOWN == live.DRAWDOWN_PAUSE
# after a resume the peak restarts, as in live.py
c.execute("insert into events(ts,env,kind,detail) values(?,?,?,?)", (T0 + 100000, "prod", "resume", ""))
c.commit(); events.append(dict(id=99, ts=T0 + 100000, env="prod", kind="resume", detail=""))
assert RV.value_track(orders, events)[:2] == live.value_track(c, "prod")[:2]
print("parity ok")

# lock states
d = date(2026, 11, 13); stop = date(2026, 11, 11)
assert RV.state([], True, d, stop)[0] == "Halted"
assert RV.state([], False, date(2026, 11, 10), stop)[0] == "Locked"
assert RV.state([dict(id=1, ts=1, env="prod", kind="unlock")], False, d, stop)[0] == "Unlocked"
assert RV.state([dict(id=1, ts=1, env="prod", kind="unlock"), dict(id=2, ts=2, env="prod", kind="lock")], False, d, stop)[0] == "Locked"
assert RV.state([dict(id=1, ts=1, env="prod", kind="unlock"), dict(id=2, ts=2, env="prod", kind="trial_end")], False, d, stop)[0] == "Trial ended"
assert RV.state([dict(id=1, ts=1, env="prod", kind="trial_end"), dict(id=2, ts=2, env="prod", kind="resume"),
                 dict(id=3, ts=3, env="prod", kind="unlock")], False, d, stop)[0] == "Unlocked"
assert RV.state([dict(id=1, ts=1, env="demo", kind="unlock")], False, d, stop)[0] == "Locked"   # demo events never unlock prod
# an unlock with a stop in force reads "Unlocked, paused", never plain "Unlocked"
ue = [dict(id=1, ts=1, env="prod", kind="unlock")]
big_loss = [dict(id=1, ts=T0, env="prod", ticker="KXRAIN-26NOV12-STL", side="yes", count=10, limit_cents=40, status="executed",
                 fill_count=10, cost=4.0, fees=0.17, result="no", pnl=-4.17, settled_ts=T0 + 10, paper_id=1)]
assert RV.state(ue, False, d, stop, big_loss, T0 + 100)[0] == "Unlocked, paused"          # daily stop (and the drawdown is not hit)
assert RV.state(ue, False, d, stop, big_loss, T0 + 200000)[0] == "Unlocked"               # a day later: only the stop has lapsed
huge = [dict(big_loss[0], cost=8.0, fees=0.1, pnl=-8.1)]
assert RV.state(ue, False, d, stop, huge, T0 + 200000)[0] == "Unlocked, paused"           # the 25% drawdown, before any trial_end
unk = [dict(big_loss[0], status="unknown", fill_count=0, cost=0, fees=0, result=None, pnl=None, settled_ts=None)]
assert RV.state(ue, False, d, stop, unk, T0)[0] == "Unlocked, paused"
mm = ue + [dict(id=2, ts=2, env="prod", kind="mismatch", detail="x")]
assert RV.state(mm, False, d, stop, [], T0)[0] == "Unlocked, paused"
assert RV.state(mm + [dict(id=3, ts=3, env="prod", kind="reconciled", detail="")], False, d, stop, [], T0)[0] == "Unlocked"
assert "live status" in RV.state(ue, False, d, stop, [], T0)[2]
print("states ok")

# markets, grouping and the rendered section
assert RV.market("KXRAIN-26NOV12-STL") == (date(2026, 11, 12), "St. Louis", "rain") and RV.market("odd")[0] is None
import weather
assert set(weather.RAIN) <= set(RV.CITY), sorted(set(weather.RAIN) - set(RV.CITY))   # every rain city has a name
assert RV.bet_words(dict(ticker="odd", side="yes"))[1] == "YES"
# grouping compares with a group's first order: 15 orders 40 minutes apart are not one marker
chain = [dict(id=i, ts=T0 + 2400 * i, env="prod", ticker="KXRAIN-26NOV12-STL", side="yes", count=1, limit_cents=10, status="executed",
              fill_count=1, cost=0.1, fees=0.01, result=None, pnl=None, settled_ts=None, paper_id=None) for i in range(15)]
assert RV.chart(chain, [], T0 + 2400 * 15).count('class="mk buy"') == 8
tab = lambda h, rows, empty, num=(): "<table>%s</table>" % "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % x for x in r) for r in rows) if rows else empty
unknown_o = dict(id=7, ts=T0 + 30, env="prod", paper_id=50, ticker="KXRAIN-26NOV12-PIT", side="yes", count=2, limit_cents=30,
                 client_order_id="c7", order_id=None, status="unknown", fill_count=0, cost=0, fees=0, note="", result=None, pnl=None, settled_ts=None)
html_u = RV.section(orders + [unknown_o], events, [], T0 + 300000, False, stop, lambda h, rows, empty, num=(): "".join("|".join(r) for r in rows))
assert "Orders with an unknown outcome" in html_u and "Pittsburgh" in html_u.split("Paper bets not copied")[0]
html_ = RV.section(orders, events, [dict(id=45, n=5, status="settled", pnl=-0.37), dict(id=46, n=1, status="open")], T0 + 300000, False, stop, tab)
assert html_.count('class="mk buy"') == 2, html_.count('class="mk buy"')       # orders 1-3 within 45 minutes: one marker; order 5: another
assert html_.count('class="mk won"') + html_.count('class="mk lost"') == 2      # orders 1-2 settled together; order 5 alone
assert "3 bets placed" in html_ and "2 bets settled" in html_ and "Washington" in html_
assert "Paper bets not copied with real money (1)" in html_ and "Demo exchange (fake money): 1 filled order;" in html_
assert "Unlocked" in html_ and "1 won, 2 lost" in html_
empty = RV.section([], [], [], T0, False, stop, tab)
assert "No real orders yet" in empty
print("section ok")

# the dashboard builds with the section and opens live.db read-only
import dashboard as D
D.DB = os.environ["PAPER_DB"]
import core; core.DB = D.DB
cc = sqlite3.connect(D.DB); cc.close()
h0 = hashlib.sha256(open(os.environ["LIVE_DB"], "rb").read()).hexdigest()
page = D.build_page(D.read_db(), False)
assert 'id=real' in page and "Real money on Kalshi" in page and "real-money view failed" not in page
assert hashlib.sha256(open(os.environ["LIVE_DB"], "rb").read()).hexdigest() == h0, "live.db changed"
o2, e2 = D.read_live(); assert len(o2) == 6
print("real_view: all checks passed")
