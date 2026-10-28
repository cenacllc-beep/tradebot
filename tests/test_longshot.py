"""research/longshot.py on a synthetic record: a planted longshot overpricing shows up in the right group, and the
report refuses to run before K1 is scored. python test_longshot.py WORK OUT"""
import os, sys, shutil, random
WORK,OUT=sys.argv[1],sys.argv[2]; shutil.rmtree(OUT,ignore_errors=True); os.makedirs(OUT)
sys.path.insert(0,os.path.join(WORK,"research")); import longshot as L
assert L.category("KXBTCD")=="crypto" and L.category("KXMLBGAME")=="sports" and L.category("KXHIGHNY")=="weather" and L.category("KXGOLD15M")=="markets"
rnd=random.Random(3); ms={}; tr={}
for i in range(3000):
    t="KXMLBGAME-26AUG%02d-M%d"%(1+i%28,i); y="yes" if rnd.random()<0.10 else "no"   # a 10% event
    ms[t]=dict(series="KXMLBGAME",event=t.rsplit("-",1)[0],result=y)
    tr[t]=[dict(side="yes",yes=0.15,no=0.85,block=False),dict(side="no",yes=0.15,no=0.85,block=False)]   # YES priced 15c, worth 10c
S=L.summarize(L.rows(ms,lambda t:tr[t]))
g={(r["category"],r["side"],r["tenth"]):r for r in S}
y=g[("sports","yes",1)]; n=g[("sports","no",8)]
assert y["fills"]==3000 and y["excess"]<-0.03 and y["se"] and y["excess"]/y["se"]<-3, y   # cheap YES overpriced
assert n["excess"]>0.03 and abs(y["excess"]+n["excess"])<1e-9, n   # the mirror image on the NO side
assert ("all","yes",1) in g
L.OUT=os.path.join(OUT,"results"); L.D_K=os.path.join(OUT,"k1"); os.makedirs(L.OUT)
try: L.report(); raise SystemExit("ran before K1 was scored")
except SystemExit as e: assert "after PLAN4 test K1" in str(e), e
print("longshot.py: all checks passed")
